import os, sys, re, hashlib, json
sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import providers
import pipeline as pl, data_loader as dl, metrics as mt, story as sy, export_pptx as xp, portfolio as pf, analyst as an, prep as pr
from schema import TABLES
from decisions import Decisions
from assumptions import Uncertainty, scenario_text, APP_ASSUMPTIONS, THRESH

S = st.session_state
STATUS_COL = {"CALCULATED": "#1b7f5c", "ALLOCATED": "#2b6cb0", "ESTIMATED": "#b7791f", "MEASURED": "#1b7f5c"}
SEV_ICON = {"ERROR": "🔴 ERROR", "WARNING": "🟠 WARNING", "INFO": "🔵 INFO"}
TABLE_LABEL = {t: f"{TABLES[t].label}  [{t}]" for t in TABLES}
LABEL_TABLE = {v: k for k, v in TABLE_LABEL.items()}
IGNORE = "(ignore sheet)"
TABLE_OPTIONS = [IGNORE] + list(TABLE_LABEL.values())


# =============================================================================== data source
def sig(files):
    return hashlib.md5(b"".join(n.encode() + hashlib.md5(b).digest() for n, b in files)).hexdigest()


def load_source(files, auto):
    """Read files and auto-map. For the sample demo also validate + apply defaults so the dashboard works at once."""
    S.raw, S.mapping = pl.ingest(files)
    S.decisions = S.get("pending_decisions") or Decisions()          # sidecar: mapping fixes, exclusions, bands (never the source files)
    S.mapping = S.decisions.apply_mapping(S.raw, S.mapping)
    S.ver = S.get("ver", 0) + 1
    S.confirmed, S.applied, S.V, S.actions, S.extra, S.T, S.log = False, False, None, {}, {}, None, None
    if auto:
        validate_now()
        apply_now()


def validate_now():
    S.V = pl.validate_mapping(S.raw, S.mapping)
    S.confirmed, S.applied = True, False
    S.ver = S.get("ver", 0) + 1
    S.extra = {}


def apply_now():
    d = S.get("decisions") or Decisions()
    acts = {**d.actions_for(S.V["issues"]), **S.actions}
    extra = {**d.uid_reasons(), **S.extra}
    S.T, S.log = pl.finalize(S.V, acts, extra)
    S.actions = acts
    S.excluded_ids = {r.id for r in S.V["issues"].itertuples() if S.actions.get(r.id, r.default_action) == "exclude" and r.n_rows}
    S.applied = True
    S.ver = S.get("ver", 0) + 1




def render_advanced():
    """Everything the app did before Simple mode existed, unchanged in behaviour. Reached from Settings -> Advanced mode."""
    st.title("Customer value review")
    st.caption("For the Lindström key account manager: the whole portfolio, one customer at a time, an analyst to think with, and a meeting pack that contains only that customer.")
    strip = st.empty()
    tab_prep, tab_data, tab_port, tab_cust, tab_brief, tab_ask, tab_method = st.tabs(
        ["Prepare the meeting", "① Data: load & check", "Portfolio", "Customer", "Meeting brief", "Analyst", "Method & data readiness"])

    # =============================================================================== DATA step 1: source (runs first so every tab sees the data)
    with tab_data:
        st.markdown("Everything starts here: **1** choose the data → **2** check how the sheets were understood → **3** review data issues and decide what to exclude. "
                    "The sample pack goes through all three steps automatically. Nothing is calculated until steps 2 and 3 are confirmed.")
        st.subheader("Step 1 · Choose the data")
        src = st.radio("Source", ["Sample pack (default demo)"] if providers.demo_mode() else ["Sample pack (default demo)", "Upload my Excel files"], key="src", horizontal=True)
        if src.startswith("Sample"):
            files = pl.sample_files()
            if S.get("sig") != "sample":
                with st.spinner("Loading the sample pack…"):
                    load_source(files, auto=True)
                S.sig = "sample"
        else:
            up = st.file_uploader("Upload one or more .xlsx files: any sheet names, column names, column order or units", type=["xlsx"], accept_multiple_files=True)
            if up:
                files = [(f.name, f.getvalue()) for f in up]
                g = sig(files)
                if S.get("sig") != g:
                    with st.spinner("Reading and auto-mapping sheets…"):
                        load_source(files, auto=False)
                    S.sig = g
            elif S.get("sig") not in (None, "sample") and not up:
                pass
            else:
                S.sig = None

    ready = S.get("raw") is not None and S.get("sig") is not None


    def data_status():
        """One line, shown above every tab: where the data stands and where to fix it."""
        if not ready:
            return "info", "**No data loaded.** Open **① Data: load & check** to use the sample pack or upload your Excel files."
        srcname = "Sample pack" if S.get("sig") == "sample" else f"{len({r.file for r in S.raw.values()})} uploaded file(s)"
        if not S.get("confirmed"):
            return "warning", f"**{srcname} read, mapping not confirmed yet.** Go to **① Data: load & check**, step 2, and confirm the mapping."
        I0 = S.V["issues"]
        e, w = int((I0.severity == "ERROR").sum()), int((I0.severity == "WARNING").sum())
        if not S.get("applied"):
            return "warning", f"**{srcname} validated: {e} error(s), {w} warning(s).** Go to **① Data: load & check**, step 3, and apply your decisions to calculate."
        n_ex = len(S.log) if S.get("log") is not None else 0
        return ("warning" if e else "success"), (f"**Data: {srcname}** · {e} error(s) and {w} warning(s) flagged, not hidden · {n_ex} row(s) excluded · "
                                               "to load other files or change a decision, open **① Data: load & check**.")


    with st.sidebar:
        st.header("Data")
        st.caption("Load, map and fix data in the first tab, **① Data: load & check**. Everything is calculated in code from the cleaned data; an LLM never produces a number.")

    # =============================================================================== shared state for the analysis tabs
    OK = bool(ready and S.get("applied") and S.T is not None and not S.T.get("sites", pd.DataFrame()).empty
              and S.T.get("service_activity") is not None and not S.T["service_activity"].empty)
    NEED = "Load data, confirm the mapping and apply the validation decisions in the first tab, **① Data: load & check**. The sample pack does this automatically."


    def fmt_n(x, d=0):
        return "n/a" if pd.isna(x) else f"{x:,.{d}f}".replace(",", " ")


    if OK:
        T, I, log = S.T, S.V["issues"], S.log
        CU = pf.customers(T)
        names, inds = CU.set_index("customer_id").customer.to_dict(), CU.set_index("customer_id").industry.to_dict()
        with st.sidebar:
            st.header("Analysis settings")
            B = T.get("baselines")
            bids = list(B.baseline_id) if B is not None and len(B) else [None]
            blab = {mt.baseline_name(T, b): b for b in bids}
            dflt = mt.baseline_name(T, mt.default_baseline(T))
            bsel = blab[st.selectbox("Comparison baseline", list(blab), index=list(blab).index(dflt) if dflt in blab else 0, key=f"base_{S.get('sig')}")]
            with st.expander("Sensitivity assumptions (editable)"):
                u = Uncertainty(baseline_pct=st.number_input("Baseline ± (%)", 0, 80, 20) / 100, allocation_pct=st.number_input("Allocation ± (%)", 0, 50, 10) / 100,
                                repair_low=st.number_input("Repair factor, Low", 0.0, 1.0, 0.5, 0.05), repair_high=st.number_input("Repair factor, High", 0.0, 1.5, 1.0, 0.05))
            st.caption("Values shown are the Base case. Every uncertain figure shows its Low–High range next to it. " + scenario_text("Base", u))

        @st.cache_data(show_spinner="Calculating the portfolio…")
        def portfolio_data(_T, ver, bsel, u):
            P, SA = pf.portfolio(_T, bsel, "Base", u)
            return P, SA, pf.repair_intensity(_T), pf.flows(_T)
        P, SA, RI, FL = portfolio_data(T, S.ver, bsel, u)
        clab = {f"{names[c]} ({inds[c]})": c for c in CU.customer_id}
        # ONE customer selector for the whole app (also shared with Simple mode). Tabs inherit it; nobody is asked twice.
        _cur = S.get("customer_id")
        if _cur not in clab.values():
            _cur = next(iter(clab.values()))
        S.customer_id = _cur
        with st.sidebar:
            if len(clab) > 1:
                st.header("Customer")
                _sel = st.selectbox("Customer (used in every tab)", list(clab), index=list(clab.values()).index(_cur), key="shared_customer_sel")
                S.customer_id = clab[_sel]
            else:
                st.caption(f"Customer: {names[_cur]}")


    def card(col, m, scen="Base"):
        with col:
            rng = "exact" if m.exact else f"{m._f(m.low, m.unit)} to {m._f(m.high, m.unit)}"
            st.markdown(f"<div style='font-size:13px;color:#555'>{m.label}</div><div style='font-size:28px;font-weight:700'>{m.fmt()}</div>"
                        f"<div style='font-size:12px;color:#555'>range {rng}</div>"
                        f"<span style='background:{STATUS_COL.get(m.status,'#555')};color:#fff;border-radius:4px;padding:1px 6px;font-size:11px'>{m.status.title()}</span> "
                        f"<span style='font-size:11px;color:#777'>input: {m.input_status.split(';')[0].lower()}</span>", unsafe_allow_html=True)
            with st.popover("How is this calculated?"):
                st.markdown(f"**Formula:** {m.formula}")
                for k, v in m.inputs.items():
                    st.write(f"- {k}: {v:,.3f}" if isinstance(v, (int, float)) else f"- {k}: {v}")
                st.markdown(f"**Status:** {m.status.title()} · **Input data:** {m.input_status}")
                st.markdown(f"**Low / Base / High:** {m._f(m.low, m.unit)} / {m._f(m.value, m.unit)} / {m._f(m.high, m.unit)}"
                            + (f"  \nVaried: {m.range_basis}" if m.range_basis else "  \nNo assumption involved."))
                st.caption("Source tables: " + ", ".join(m.sources))
                if m.note: st.caption(m.note)
                if m.caveat: st.warning(m.caveat)


    SYN = "Synthetic demo data unless your files say otherwise: figures are illustrative estimates, not audited or verified Lindström/customer claims."

    # =============================================================================== analyst helpers (also used by the Customer tab)
    BADGE = {"CALCULATED": ("Calculated", "#1b7f5c"), "ALLOCATED": ("Estimate · allocated", "#b7791f"), "ESTIMATED": ("Estimate · assumption", "#b7791f"),
             "SCENARIO": ("What-if", "#6b46c1"), "HYPOTHESIS": ("Hypothesis", "#64748b")}


    def badge(status):
        lab, col = BADGE.get(status, (str(status).title(), "#555"))
        return f"<span style='background:{col};color:#fff;border-radius:4px;padding:1px 6px;font-size:11px;white-space:nowrap'>{lab}</span>"


    def legend():
        return " ".join(badge(k) for k in ("CALCULATED", "ALLOCATED", "ESTIMATED", "SCENARIO", "HYPOTHESIS"))


    def get_ctx():
        key = (S.ver, bsel, u)
        if S.get("an_key") != key:
            with st.spinner("Preparing the analyst…"):
                S.an_ctx = an.Ctx(T, I, bsel, u, P=P.copy(), S=SA.copy())
            if S.get("an_key") is not None and S.get("chat"):
                S.chat.append(dict(q=None, answer=dict(read="Settings or data changed. Earlier answers above used the previous settings; new answers use the current ones.", notice=True)))
            S.an_key, S.snaps = key, {}
        return S.an_ctx


    def get_snap(cid):
        ctx = get_ctx()
        k = cid or "_portfolio"
        if k not in S.snaps:
            S.snaps[k] = an.snapshot(ctx, cid)
        return S.snaps[k]


    def render_snapshot(sn, key, compact=False):
        st.markdown(f"#### {sn['customer']}: where things stand")
        st.caption(sn["headline"])
        if not compact:
            for i in range(0, len(sn["kpis"]), 2):
                cols = st.columns(2)
                for col, k in zip(cols, sn["kpis"][i:i + 2]):
                    rng = f"<div style='font-size:11px;color:#666'>range {k['low']} to {k['high']}</div>" if k.get("low") else ""
                    col.markdown(f"<div style='font-size:12px;color:#555'>{k['label']}</div><div style='font-size:21px;font-weight:700'>{k['value']}</div>{rng}{badge(k['status'])}",
                                 unsafe_allow_html=True)
        if sn.get("moving"):
            st.markdown("**What is moving**" if sn.get("customer_id") else "**Accounts**")
            for m in sn["moving"]:
                arrow = {"up": "▲", "down": "▼", "flat": "▬"}.get(m.get("direction"), "•")
                colr = {"good": "#1b7f5c", "watch": "#b43b2e"}.get(m.get("tone"), "#555")
                st.markdown(f"<span style='color:{colr}'>{arrow}</span> {m['text']}", unsafe_allow_html=True)
        if sn.get("watch"):
            st.markdown("**Watch**")
            for w in sn["watch"]:
                st.markdown(f"- {w['text']}  {badge(w['status'])}", unsafe_allow_html=True)
        if sn.get("open_threads"):
            st.markdown("**Open threads for the meeting** " + badge("HYPOTHESIS"), unsafe_allow_html=True)
            for t in sn["open_threads"]:
                st.markdown(f"- {'★ ' if t['fits_priority'] else ''}{t['title']}: {t['sizing']}")
        if sn.get("industry_lens"):
            st.caption(f"Industry lens (from the data pack): {' → '.join(sn['industry_lens'])}. Customer's stated priorities: {', '.join(sn.get('priority_topics', []))}. ★ = matches a stated priority.")
        if sn.get("trend") and not compact:
            tdf = pd.DataFrame(sn["trend"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=tdf.month, y=tdf.utilisation_pct, name="Utilisation %", mode="lines+markers"))
            fig.add_trace(go.Bar(x=tdf.month, y=tdf.service_requests, name="Service requests", yaxis="y2", opacity=0.35))
            fig.update_layout(height=230, margin=dict(l=0, r=0, t=30, b=0), title="Monthly: utilisation and service requests",
                              yaxis=dict(title="%"), yaxis2=dict(overlaying="y", side="right", showgrid=False), legend=dict(orientation="h", y=-0.25))
            st.plotly_chart(fig, width="stretch", key=f"snapfig_{key}")


    def chart_fig(c, outputs):
        e = outputs.get(c["result_id"])
        if not e:
            return None
        res = e["result"]
        rows = res.get("rows") or res.get("changes") or res.get("customers")
        df = pd.DataFrame(rows)
        x, ys = c["x"], c["y"]
        if x not in df or any(y not in df for y in ys):
            return None
        lab = {y: an.LABEL.get(y, y.replace("_", " ")) for y in ys}
        lab.update({x: x.replace("_", " "), "value": an.LABEL.get(ys[0], "value") if len(ys) == 1 else "value", "variable": ""})
        kind = c.get("kind", "bar")
        if kind == "line":
            fig = px.line(df, x=x, y=ys, markers=True, labels=lab)
        elif kind == "barh":
            d = df.sort_values(ys[0])
            err = (d[ys[0] + "_high"] - d[ys[0]]) if ys[0] + "_high" in d else None
            errm = (d[ys[0]] - d[ys[0] + "_low"]) if ys[0] + "_low" in d else None
            fig = px.bar(d, y=x, x=ys[0], orientation="h", labels=lab, error_x=err, error_x_minus=errm)
            fig.update_layout(height=max(260, 24 * len(d) + 80))
        elif kind == "scatter":
            hov = next((cc for cc in ("site", "customer", "product", "country") if cc in df), None)
            fig = px.scatter(df, x=x, y=ys[0], hover_name=hov, labels=lab, text=hov if hov and len(df) <= 12 else None)
        else:
            if len(ys) == 1 and ys[0] + "_high" in df:
                fig = px.bar(df, x=x, y=ys[0], labels=lab, error_y=df[ys[0] + "_high"] - df[ys[0]], error_y_minus=df[ys[0]] - df[ys[0] + "_low"])
            else:
                fig = px.bar(df, x=x, y=ys, barmode="group", labels=lab)
        sub = BADGE.get(c.get("status"), ("", ""))[0]
        rng = " · bars show Low–High range" if any(y + "_high" in df for y in ys) and kind in ("bar", "barh") else ""
        fig.update_layout(title=dict(text=f"{c.get('title', '')}<br><sup>{sub}{rng} · drawn from {c['result_id']}</sup>"),
                          margin=dict(l=0, r=0, t=60, b=0), legend_title_text="", showlegend=len(ys) > 1)
        return fig


    def ask_pending(text):
        S.an_pending = text


    def render_answer(a, i):
        if a.get("notice"):
            st.info(a["read"])
            return
        if a.get("banner"):
            st.warning(a["banner"])
        st.markdown(a["read"])
        kn = a.get("key_numbers") or []
        if kn:
            cols = st.columns(min(len(kn), 4))
            for j, k in enumerate(kn[:8]):
                cols[j % len(cols)].markdown(f"<div style='font-size:12px;color:#555'>{k['label']}</div><div style='font-size:20px;font-weight:700'>{k['value']}</div>{badge(k['status'])}",
                                             unsafe_allow_html=True)
        for j, c in enumerate(a.get("charts") or []):
            fig = chart_fig(c, a.get("outputs", {}))
            if fig is not None:
                st.plotly_chart(fig, width="stretch", key=f"anfig_{i}_{j}")
        if a.get("hypotheses"):
            with st.container(border=True):
                st.markdown(badge("HYPOTHESIS") + " **Not shown by the data: ideas to test with the customer**", unsafe_allow_html=True)
                for h in a["hypotheses"]:
                    st.markdown(f"- {h}")
        if a.get("caveat"):
            st.caption("⚠ " + a["caveat"])
        if a.get("note"):
            st.info(a["note"])
        src = {"llm": "AI-worded; every number checked against the calculations", "rules": "Rule-based analyst (no AI key): built directly from the calculations"}.get(a.get("source"), "")
        st.caption(f"{src} · calculations used: {', '.join(t['tool'] + ' ' + t['result_id'] for t in a.get('tools', []) if t.get('result_id'))}")
        fu = a.get("follow_ups") or []
        if fu:
            cols = st.columns(len(fu))
            for j, f in enumerate(fu):
                cols[j].button(f, key=f"fu_{i}_{j}", on_click=ask_pending, args=(f,), width="stretch")
        with st.expander("Calculations behind this answer"):
            for rid, e in (a.get("outputs") or {}).items():
                st.markdown(f"**{rid} · {e['tool']}** `{json.dumps(e.get('args', {}), ensure_ascii=False, default=str)}`")
                res = e["result"]
                rows = res.get("rows")
                if isinstance(rows, list) and rows:
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
                    st.json({k: v for k, v in res.items() if k != "rows"}, expanded=False)
                else:
                    st.json(res, expanded=False)


    STARTERS = ["How are we doing with NorthStar, and what should I worry about?", "Which sites stand out at NorthStar?",
                "Show the monthly trend of service requests at NorthStar", "What if utilisation at Apex reached 90 %?",
                "What should I propose to Mediora?", "How fair is the baseline for Apex?"]

    # =============================================================================== PREPARE THE MEETING
    def _draft_public(pc, company, industry, country):
        pts, brand, mode = pr.public_brief(company, industry, country)
        S[f"pub_{pc}"] = dict(points=pts, mode=mode)
        if brand:
            S[f"c1_{pc}"], S[f"c2_{pc}"] = brand[0], brand[1]


    with tab_prep:
        if not OK:
            st.info(NEED)
        else:
            st.subheader("Prepare the meeting")
            st.caption("Company → what matters to them → who is in the room. Each step is a suggestion you can change. The result steers the meeting brief and the deck.")
            pc = S.customer_id
            st.markdown(f"**Meeting with: {names[pc]}**  (change the customer in the sidebar)")
            cname, cind = names[pc], inds[pc]
            crow = CU[CU.customer_id == pc].iloc[0]
            PS = SA[SA.customer_id == pc]
            # ---- 1 CRM
            st.markdown("#### 1 · What we know (CRM)")
            k = f"crm_{pc}"
            if k not in S:
                S[k] = (f"Industry: {cind}\nSegment: {crow.segment}\nSites: {len(PS)} in {PS.country.nunique()} countries ({', '.join(sorted(PS.country.unique()))})\n"
                        f"Priority topics (CRM): {str(crow.topics).replace('|', ', ')}")
            st.text_area("CRM notes. Edit them or paste from Dynamics. Stand-in until the CRM is connected.", key=k, height=130)
            # ---- 2 public information
            st.markdown("#### 2 · What is public about them")
            st.button("Draft from public information", key=f"draft_{pc}", on_click=_draft_public, args=(pc, cname, cind, str(crow.get("hq_country", "") if hasattr(crow, "get") else "")))
            pub = S.get(f"pub_{pc}")
            pub_pts = []
            if pub:
                if pub["mode"].startswith("sample"):
                    st.warning(f"Sample text, not real public information ({pub['mode']}). With an API key the app searches the web and cites a source for every point.")
                else:
                    st.caption("From a live web search. Every point has a source: check them before you use them. They only steer emphasis; they are never used in a calculation.")
                df = pd.DataFrame(pub["points"])
                ed = st.data_editor(df, hide_index=True, width="stretch", key=f"pubed_{pc}", num_rows="dynamic",
                                    column_config={"include": st.column_config.CheckboxColumn("use", width="small"),
                                                   "text": st.column_config.TextColumn("What we found", width="large"),
                                                   "theme": st.column_config.SelectboxColumn("topic", options=[""] + list(pr.THEME_LABEL)),
                                                   "source": st.column_config.TextColumn("source")})
                pub_pts = ed.fillna("").to_dict("records")
            # ---- 3 attendees
            st.markdown("#### 3 · Who is in the room?")
            att = st.multiselect("Attendees from the customer", list(pr.ROLES), key=f"att_{pc}")
            # ---- 4 result
            st.markdown("#### 4 · What we will lead with")
            order, why = pr.rank_themes(sy.industry_order(T, cind), S[f"crm_{pc}"], pub_pts, att)
            ov = st.text_input("Or type your own focus (this overrides the suggestion)", key=f"ov_{pc}", placeholder="e.g. water, then hygiene")
            final = sy.parse_priority(ov, T, cind) if ov.strip() else order
            st.success("Leading with:  " + "  ›  ".join(pr.THEME_LABEL[t] for t in final[:3]))
            if not ov.strip():
                for t in final[:3]:
                    if why[t]:
                        st.write(f"**{pr.THEME_LABEL[t]}**: " + "; ".join(dict.fromkeys(why[t])))
            # ---- 5 deck style
            st.markdown("#### 5 · Deck style")
            style = st.radio("Colours of the PowerPoint", ["Lindström colours", "Customer colours"], key=f"style_{pc}", horizontal=True)
            c1 = c2 = None
            if style.startswith("Customer"):
                S.setdefault(f"c1_{pc}", "#1F5F3A"); S.setdefault(f"c2_{pc}", "#E2A400")
                cc = st.columns(2)
                c1 = cc[0].color_picker("Main colour", key=f"c1_{pc}")
                c2 = cc[1].color_picker("Accent colour", key=f"c2_{pc}")
                st.caption("Colours only. No logos or fonts are copied. Text is darkened automatically if a colour is too light to read. Suggested colours come from the public information; check them.")
            S.setdefault("prep", {})[pc] = dict(themes=final, order=order, attendees=att, brand=(c1, c2) if c1 else None, focus=ov.strip())
            st.info("Next: open **Meeting brief** for this customer. It will use this order and these colours.")

    # =============================================================================== PORTFOLIO
    with tab_port:
        if not OK:
            st.info(NEED)
        else:
            st.warning(SYN)
            n_err = int((I.severity == "ERROR").sum())
            if n_err:
                st.error(f"{n_err} data error(s) in the loaded data are flagged, not hidden. First: {I[I.severity=='ERROR'].iloc[0].check} ({I[I.severity=='ERROR'].iloc[0].location}). Review or change the decision in **① Data: load & check**, step 3.")
            c = st.columns(4)
            c[0].metric("Customers", len(P)); c[1].metric("Sites", int(P.sites.sum())); c[2].metric("Countries", SA.country.nunique())
            c[3].metric("Sites needing attention", int(P.sites_attention.sum()))
            st.subheader("Customers side by side")
            show = pd.DataFrame({"Customer": P.customer, "Industry": P.industry, "Sites": P.sites, "Countries": P.countries,
                                 "Washed kg": P.kg.round(0), "% of portfolio kg": P.share_of_portfolio_kg.round(0),
                                 "Utilisation %": P.utilisation.round(1), "On-time %": P.ontime.round(1),
                                 "Requests / 1000 garments": P.requests_per_1000.round(1), "Repairs / 100 garments": P.repairs_per_100.round(1),
                                 "Sites needing attention": P.sites_attention,
                                 "Water saved, Low–High (M L)": [f"{r.water_low/1e6:.2f} – {r.water_high/1e6:.2f}" for r in P.itertuples()]})
            st.dataframe(show, hide_index=True, width="stretch")
            st.caption(f"Water saved vs {mt.baseline_name(T, bsel)}; range = baseline ±{u.baseline_pct:.0%} and allocation ±{u.allocation_pct:.0%} (Low–High). "
                       "With only a few accounts this is a side-by-side comparison, not a statistical benchmark. A site is flagged against its own customer's other sites.")
            st.subheader("How customers, countries and laundries relate")
            c1, c2 = st.columns(2)
            with c1:
                labels = list(dict.fromkeys(list(FL.customer) + list(FL.country) + list(FL.laundry)))
                ix = {l: i for i, l in enumerate(labels)}
                a = FL.groupby(["customer", "country"]).customer_washed_kg.sum().reset_index()
                b = FL.groupby(["country", "laundry"]).customer_washed_kg.sum().reset_index()
                src = [ix[x] for x in a.customer] + [ix[x] for x in b.country]
                tgt = [ix[x] for x in a.country] + [ix[x] for x in b.laundry]
                val = list(a.customer_washed_kg) + list(b.customer_washed_kg)
                fig = go.Figure(go.Sankey(node=dict(label=labels, pad=12), link=dict(source=src, target=tgt, value=val)))
                fig.update_layout(title="Washed kg: customer → site country → serving laundry", height=420, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig, width="stretch")
            with c2:
                tm = SA.dropna(subset=["pieces"]).copy()
                tm["utilisation"] = tm.utilisation.fillna(0)
                fig = px.treemap(tm, path=["customer", "country", "site"], values="pieces", color="utilisation", color_continuous_scale="RdYlGn",
                                 labels={"utilisation": "Utilisation %"})
                fig.update_layout(title="Garments allocated by site (colour = utilisation %)", height=420, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig, width="stretch")
            shared = FL.groupby("laundry").customer_id.nunique()
            shared = shared[shared > 1]
            if len(shared):
                st.caption("Laundries serving more than one of your customers (their resource figures are shared out by washed kg): " + ", ".join(f"{k} ({v})" for k, v in shared.items()) + ".")
            st.subheader("All sites across customers")
            f1, f2, f3 = st.columns(3)
            cf = f1.multiselect("Customer", sorted(SA.customer.unique()), key="pf_c")
            kf = f2.multiselect("Country", sorted(SA.country.dropna().unique()), key="pf_k")
            af = f3.checkbox("Only sites needing attention", key="pf_a")
            V = SA.copy()
            if cf: V = V[V.customer.isin(cf)]
            if kf: V = V[V.country.isin(kf)]
            if af: V = V[V.attention]
            V = V.sort_values(["attention", "requests_per_1000"], ascending=False)
            st.dataframe(V[["customer", "site", "country", "type", "pieces", "utilisation", "ontime", "requests_per_1000", "repairs", "attention", "extreme"]]
                         .rename(columns={"pieces": "garments", "utilisation": "utilisation %", "ontime": "on-time %", "requests_per_1000": "requests/1000", "attention": "needs attention", "extreme": "extreme"})
                         .round(1), hide_index=True, width="stretch", height=360)
            st.caption("Attention rule: robust outlier versus the customer's own sites (median/MAD z ≥ 1.5 on ≥ 2 indicators, with a minimum effect size, or z ≥ 3 on one). A signal to ask about, not a diagnosis.")

    # =============================================================================== CUSTOMER
    with tab_cust:
        if not OK:
            st.info(NEED)
        else:
            cid = S.customer_id
            ind = inds[cid] if isinstance(inds[cid], str) else ""
            M = mt.metrics(T, cid, bsel, "Base", u)
            St = SA[SA.customer_id == cid].reset_index(drop=True)
            Ct = mt.country_rollup(St)
            st.header(f"{names[cid]}")
            st.caption(f"{ind} · baseline: {M.baseline_name} · {len(St)} sites in {St.country.nunique()} countries")
            st.warning(SYN)
            with st.container(border=True):
                render_snapshot(get_snap(cid), key=f"cust_{cid}", compact=True)
                st.caption("Same standing summary as in the Analyst tab. Ask the Analyst to drill into any line.")
            head = [M[k] for k in ("kg", "pieces", "utilisation", "ontime") if k in M]
            for col, m in zip(st.columns(4), head): card(col, m)
            st.subheader("What the service saved, versus the selected baseline")
            for i in range(0, 8, 4):
                row = [M[k] for k in ("water_saving", "energy_saving", "co2_service", "waste", "repairs", "postponed", "avoided_cost", "avoided_co2")[i:i + 4] if k in M]
                for col, m in zip(st.columns(4), row): card(col, m)
            with st.expander("More indicators (people, service, recycling)"):
                rest = [M[k] for k in ("wearers", "requests", "cycle_hours", "recycling_pct", "water_per_kg", "energy_per_kg") if k in M]
                for i in range(0, len(rest), 4):
                    for col, m in zip(st.columns(4), rest[i:i + 4]): card(col, m)
            if M.missing:
                with st.expander("Not calculated (no valid data)"):
                    st.dataframe(pd.DataFrame([dict(metric=k, reason=v) for k, v in M.missing.items()]), hide_index=True, width="stretch")

            st.subheader("Trend by month")
            mo = pf.monthly(T, cid)
            if len(mo) > 1:
                mo["month"] = pd.to_datetime(mo.month).dt.strftime("%Y-%m")
                c1, c2, c3 = st.columns(3)
                c1.plotly_chart(px.line(mo, x="month", y="utilisation", markers=True, title="Garment utilisation %"), width="stretch")
                c2.plotly_chart(px.line(mo, x="month", y="requests", markers=True, title="Service requests"), width="stretch")
                if "repairs" in mo:
                    c3.plotly_chart(px.bar(mo, x="month", y="repairs", title="Repairs completed"), width="stretch")
                st.caption("The pack covers one year, so there is no year-on-year comparison; monthly values show seasonality and sudden changes.")
            st.subheader("Countries and sites")
            st.dataframe(Ct.rename(columns={"attention": "sites needing attention", "kg": "washed kg", "water_saving": "water saved (L)", "co2": "CO2e saved (kg)"}).round(0), hide_index=True, width="stretch")
            bad = St[St.attention]
            st.markdown(f"**{len(bad)} of {len(St)} sites stand out** against this customer's other sites.")
            if len(bad):
                st.dataframe(bad[["site", "country", "utilisation", "ontime", "requests_per_1000", "extreme"]].round(1), hide_index=True, width="stretch")
            slab = {f"{r.site} [{r.site_id}]": r.site_id for r in St.itertuples()}
            site = slab[st.selectbox("Site drill-down", list(slab), key=f"drill_{cid}_{S.ver}")]
            SM = mt.metrics(T, cid, bsel, "Base", u, sites=[site])
            keys = [k for k in ("pieces", "kg", "utilisation", "ontime", "requests", "water_saving", "repairs", "co2_service") if k in SM]
            for i in range(0, len(keys), 4):
                for col, k in zip(st.columns(4), keys[i:i + 4]): card(col, SM[k])

            st.subheader("What if? Use the customer's own numbers")
            w1, w2 = st.columns(2)
            if "water_saving" in M and "water_per_kg" in M:
                own = w1.number_input("Customer's own water use (L per kg textile)", 0.0, 100.0, float(M.get("water_saving").inputs["baseline_L_per_kg"]), 0.5, key=f"own_{cid}")
                kgm = M["water_saving"].inputs["matched_kg"]
                w1.metric("Water saved at that baseline", fmt_n(kgm * (own - M["water_per_kg"].value)) + " L",
                          help=f"matched kg {fmt_n(kgm)} × (their {own} − allocated {M['water_per_kg'].value:.2f} L/kg). Allocation ±{u.allocation_pct:.0%} not applied here.")
            if "avoided_cost" in M:
                sh = w2.slider("Share of repairs that really prevent a purchase", 0, 100, 100, 5, key=f"sh_{cid}")
                w2.metric("Purchases avoided (EUR)", fmt_n(M["avoided_cost"].inputs["gross_EUR"] * sh / 100),
                          help="Σ repairs × product purchase cost × share. 100 % is the upper bound used in the pack.")

    # =============================================================================== MEETING BRIEF
    with tab_brief:
        if not OK:
            st.info(NEED)
        else:
            bc = S.customer_id
            st.markdown(f"**Meeting with: {names[bc]}**  (change the customer in the sidebar)")
            bind = inds[bc] if isinstance(inds[bc], str) else ""
            BM = mt.metrics(T, bc, bsel, "Base", u)
            BS = SA[SA.customer_id == bc].reset_index(drop=True)
            BC = mt.country_rollup(BS)
            c1, c2 = st.columns([2, 1])
            ex = c1.selectbox("Meeting focus (examples)", ["", "Water and emissions", "Cost and garment utilisation", "Hygiene and service reliability", "Circularity and repairs"], key="ex_focus")
            prompt = c1.text_input("Meeting focus: what does this customer care about right now?", value=ex, placeholder="e.g. water, then hygiene")
            stale_days = c2.slider("Garment-control threshold (days since last delivery)", 30, 240, 90, 15, help="Illustrative: the customer defines what is acceptable.")
            themes = sy.parse_priority(prompt, T, bind)
            PRp = S.get("prep", {}).get(bc)
            if PRp and not prompt.strip():
                themes = PRp["themes"]
                st.caption("Priority order comes from **Prepare the meeting** (" + (", ".join(PRp["attendees"]) or "no attendees chosen") + "). Type a focus above to override it.")
            Ib = pf.issues_for_customer(I, T, bc)
            ordered = sy.order_metrics(BM, themes)
            recs = sy.recommendations(BM, BS, themes, BM.baseline_name, Ib, log)
            story = sy.narrative(names[bc], themes, BM, recs)
            st.success(story)
            st.caption(f"Priority order used: {' → '.join(themes[:3])}. Numbers in the text are filled in by code from the calculated figures.")
            IP = T.get("industry_priorities")
            if IP is not None and len(IP) and bind:
                ip = IP[IP.industry.astype(str).str.lower() == bind.lower()].sort_values("priority_rank")
                if len(ip):
                    with st.expander(f"Industry lens: what {bind} customers usually need emphasised (from the data pack)", expanded=False):
                        for r in ip.itertuples():
                            st.markdown(f"**{int(r.priority_rank)}. {r.priority_theme}**: {r.dashboard_emphasis}")
                        st.caption("With no meeting focus typed, the priority order follows this lens. It steers emphasis only; it is not compliance advice.")
            opps = pf.opportunities(T, bc, BM, BS, RI, u, stale_days)
            st.subheader("Where a new conversation could start")
            st.caption("Evidence-based hypotheses, ranked by fit with the customer's stated priorities. Sized in units, not invented revenue. Internal view: the deck shows only the customer-safe part.")
            for c in opps:
                with st.expander(f"{'★ ' if c['fit'] else ''}{c['title']}  ·  {c['status'].title()}", expanded=bool(c["fit"])):
                    st.write(c["hypothesis"])
                    st.markdown("**What the data shows**")
                    for e in c["evidence_internal"]: st.write(f"- {e}")
                    st.markdown(f"**Size:** {c['sizing']}")
                    st.markdown("**Assumptions:** " + " ".join(c["assumptions"]))
                    st.markdown("**Ask the customer:** " + " · ".join(c["confirm"]))
                    if c["caveat"]: st.warning(c["caveat"])
                    if c["fit"]: st.caption("Matches the customer's priority topic: " + ", ".join(c["fit"]))
            st.subheader("Be ready to be challenged")
            for c in pf.challenges(T, BM, bc, bsel, u, Ib):
                with st.expander(f"{c['q']}  ·  {c['number']}"):
                    st.write(c["answer"])
                    if c.get("table") is not None: st.dataframe(c["table"], hide_index=True, width="stretch")
                    st.caption("What would change this: " + c["changes"])
            st.subheader("Agree actions: priorities, owners and next steps")
            akey = f"actions_{S.get('sig')}_{bc}"
            if akey not in S:
                S[akey] = pd.DataFrame([dict(action=c["title"], lindstrom_owner="", customer_owner="", target_date="", status="Proposed") for c in opps[:4]]
                                       + ([dict(action="Fix the data issues that limit next year's review", lindstrom_owner="", customer_owner="", target_date="", status="Proposed")]
                                          if len(Ib[Ib.severity.isin(["ERROR", "WARNING"])]) else []))
            agreed = st.data_editor(S[akey], num_rows="dynamic", hide_index=True, width="stretch", key=f"ed_{akey}",
                                  column_config={"action": st.column_config.TextColumn("action", width="large"),
                                                 "lindstrom_owner": st.column_config.TextColumn("Lindström owner"), "customer_owner": st.column_config.TextColumn("customer owner"),
                                                 "target_date": st.column_config.TextColumn("target date"),
                                                 "status": st.column_config.SelectboxColumn("status", options=["Proposed", "Agreed", "Parked", "Done"])})
            st.caption("Pre-filled from the topics above; edit in the meeting. Blank owners and dates are exported as fill-in fields, so the deck closes with commitments, not just findings.")
            st.subheader("Meeting pack for this customer")
            st.caption(f"The PowerPoint contains only {names[bc]}: its figures, its sites and the validation notes that concern its data. No other customer's name, site or number is included.")
            ctx = dict(mapping_df=dl.mapping_table(S.raw, S.mapping), issues=Ib, log=log, excluded_ids=S.get("excluded_ids", set()),
                       assumptions=T.get("assumptions"), readiness=pl.readiness(T, S.mapping, S.raw),
                       topics=opps[:4], actions=agreed.fillna("").to_dict("records"), stale=pf.stale_assets(T, bc, stale_days),
                       brand=(PRp or {}).get("brand"))
            deck = xp.build(names[bc], bind, themes, BM.baseline_name, "Base", u, BM, ordered, recs, story, BS, BC, ctx)
            st.download_button(f"Export PowerPoint for {names[bc]} only", deck, file_name=f"{str(names[bc]).replace(' ', '_')}_annual_review.pptx",
                               mime="application/vnd.openxmlformats-officedocument.presentationml.presentation", type="primary")

    # =============================================================================== ANALYST
    with tab_ask:
        if not OK:
            st.info(NEED)
        else:
            ctx = get_ctx()
            whole = st.checkbox("Ask about the whole portfolio instead of the selected customer", value=False, key=f"an_whole_{S.get('sig')}")
            fsel = "Whole portfolio" if whole else next(k for k, v in clab.items() if v == S.customer_id)
            focus = None if whole else S.customer_id
            left, right = st.columns([3, 2], gap="large")
            with right:
                with st.container(border=True):
                    render_snapshot(get_snap(focus), key=f"an_{focus}")
            with left:
                live = bool(os.getenv("ANTHROPIC_API_KEY"))
                st.markdown("Ask anything about the data: drill down, compare, follow a thread, test a what-if, brainstorm angles for the meeting. "
                            f"{'An AI model chooses the calculations and words the answer; ' if live else 'No AI key is set, so a rule-based analyst answers; '}"
                            "**every number is produced by code and checked**. Internal KAM view: it may compare customers.")
                st.markdown(legend(), unsafe_allow_html=True)
                S.setdefault("chat", [])
                if not S.chat:
                    st.caption("Try one of these, or type your own below:")
                    cols = st.columns(2)
                    for j, q0 in enumerate(STARTERS):
                        cols[j % 2].button(q0, key=f"start_{j}", on_click=ask_pending, args=(q0,), width="stretch")
                conv = st.container()
                with conv:
                    for i, turn in enumerate(S.chat):
                        if turn.get("q"):
                            with st.chat_message("user"):
                                st.markdown(turn["q"])
                        with st.chat_message("assistant"):
                            render_answer(turn["answer"], i)
                typed = st.chat_input("Ask the analyst… e.g. 'compare on-time by country', 'drill into Gdańsk', 'what if they use home washing?'", key="an_input")
                q = typed or S.pop("an_pending", None)
                if q:
                    with conv:
                      with st.chat_message("user"):
                        st.markdown(q)
                      with st.chat_message("assistant"):
                        with st.spinner("Running the numbers…"):
                            n0 = ctx.n
                            hist = [t for t in S.chat if t.get("q")]
                            a = an.answer(q, ctx, history=hist, focus=focus)
                            a["outputs"] = {rid: e for rid, e in ctx.store.items() if int(rid[1:]) > n0}
                        render_answer(a, len(S.chat))
                    S.chat.append(dict(q=q, answer=a))
                if S.chat:
                    c1, c2 = st.columns([1, 3])
                    if c1.button("Clear conversation", key="an_clear"):
                        S.chat, ctx.state = [], {}
                        st.rerun()
                    c2.download_button("Download conversation (Markdown)", "\n\n".join(
                        (f"**Q:** {t['q']}\n\n" if t.get("q") else "") + t["answer"].get("read", "") + "\n" +
                        "".join(f"\n- {k['label']}: {k['value']} ({BADGE.get(k['status'], ('',))[0]})" for k in t["answer"].get("key_numbers", [])) +
                        "".join(f"\n- Hypothesis: {h}" for h in t["answer"].get("hypotheses", [])) for t in S.chat),
                        "analyst_conversation.md", key="an_dl")

    # =============================================================================== DATA step 2: mapping
    with tab_data:
        st.divider()
        st.subheader("Step 2 · Check how the sheets were understood")
        if not ready:
            st.info("Choose the sample pack or upload one or more Excel files in step 1 (any sheet names, column names, column order or units). "
                    "The app detects each sheet, maps its columns to the internal data model, and shows you the result to confirm before anything is calculated.")
        else:
            raw, mapping = S.raw, S.mapping
            md = dl.mapping_table(raw, mapping)
            st.caption(f"{len(md)} sheet(s) read, {int(md.used.sum())} used. Open a sheet to confirm or fix its table and column mapping. Documentation sheets (README, dictionary …) are ignored automatically. "
                       "The 'factor' converts the source unit to the internal unit (kg, L, kWh, kgCO2e, %, h).")
            with st.expander("Detected sheets (overview)", expanded=not S.get("confirmed")):
                st.dataframe(md, hide_index=True, width="stretch")
            with st.expander("Fix how a sheet was understood (change its table, remap a column, set a unit factor, or ignore it)", expanded=False):
                labs = {f"{raw[k].file} › {raw[k].sheet}": k for k in raw}
                mk = labs[st.selectbox("Sheet", list(labs), key=f"mapsheet_{S.get('sig')}")]
                sm = mapping[mk]
                cur = TABLE_LABEL[sm.table] if sm.table else IGNORE
                tsel = st.selectbox("This sheet contains…", TABLE_OPTIONS, index=TABLE_OPTIONS.index(cur), key=f"maptable_{mk}_{S.ver}")
                use = st.checkbox("Use this sheet", value=bool(sm.include and sm.table), key=f"mapuse_{mk}_{S.ver}")
                new_table = None if tsel == IGNORE else LABEL_TABLE[tsel]
                work = sm if new_table == sm.table else (dl.map_sheet(raw[mk], new_table) if new_table else None)
                new_cols, new_fac = {}, {}
                if work is not None and new_table:
                    st.caption("Required fields are marked *. The preview shows the first values of the chosen source column.")
                    srccols = ["(not provided)"] + list(raw[mk].df.columns)
                    for f in TABLES[new_table].fields:
                        c1, c2, c3 = st.columns([2, 2, 1])
                        curc = work.cols.get(f.name)
                        pick = c1.selectbox(f"{f.name}{' *' if f.required else ''}", srccols, index=srccols.index(curc) if curc in srccols else 0, key=f"mapcol_{mk}_{new_table}_{f.name}_{S.ver}")
                        new_cols[f.name] = None if pick == "(not provided)" else pick
                        c2.caption("e.g. " + (", ".join(map(str, raw[mk].df[pick].dropna().head(3))) if pick != "(not provided)" else "—"))
                        if f.kind == "num" and pick != "(not provided)":
                            new_fac[f.name] = c3.number_input("× factor", value=float(work.factor.get(f.name, 1.0)), key=f"mapfac_{mk}_{new_table}_{f.name}_{S.ver}", format="%g")
                if st.button("Save this sheet's mapping", key=f"mapsave_{mk}_{S.ver}"):
                    if new_table is None or not use:
                        sm.include = False if new_table is None or not use else sm.include
                        if new_table is None:
                            sm.table = None
                        S.decisions.set_sheet(mk, table=new_table or "", include=False)
                    else:
                        work.include = True
                        for fn, c in new_cols.items():
                            work.cols[fn], work.conf[fn] = c, (1.0 if c else 0.0)
                        for fn, fac in new_fac.items():
                            work.factor[fn] = fac
                        work.note = "mapping adjusted by user"
                        mapping[mk] = work
                        S.decisions.set_sheet(mk, table=new_table, include=True, cols=new_cols, factor=new_fac)
                    S.confirmed = False
                    S.ver += 1
                    st.rerun()
                st.caption("Changes apply to the working copy only. Your Excel file is never modified. Press 'Confirm mapping and validate' afterwards.")
            if S.confirmed:
                st.success("Mapping confirmed and validated. Review step 3 below. If you change the mapping above, confirm again.")
            if st.button("Confirm mapping and validate", type="primary"):
                with st.spinner("Validating across sheets…"):
                    validate_now()
                st.rerun()

    # =============================================================================== DATA step 3: validation
    with tab_data:
        st.divider()
        st.subheader("Step 3 · Review data issues and decide")
        if not ready or not S.get("confirmed"):
            st.info("Confirm the mapping in step 2 first. Nothing is calculated until you have reviewed the validation report.")
        else:
            I = S.V["issues"]
            c = st.columns(4)
            c[0].metric("Errors", int((I.severity == "ERROR").sum()))
            c[1].metric("Warnings", int((I.severity == "WARNING").sum()))
            c[2].metric("Notes", int((I.severity == "INFO").sum()))
            c[3].metric("Rows to exclude (default)", int(sum(r.n_rows for r in I.itertuples() if r.default_action == "exclude")))
            st.markdown("Each issue shows **where** it is, **why** it matters and a **suggested fix**. For issues that point at specific rows you choose whether to "
                        "**exclude** those rows from the calculation or **keep & flag** them. Dataset-level inconsistencies (for example a total that does not match) are kept by default, "
                        "because neither side can be proven wrong from the data alone.")
            sevs = st.multiselect("Show", ["ERROR", "WARNING", "INFO"], default=["ERROR", "WARNING", "INFO"])
            show = I[I.severity.isin(sevs)].copy()
            show["action"] = show.apply(lambda r: "Exclude rows" if (r.default_action == "exclude") else "Keep & flag", axis=1)
            view = show[["id", "severity", "check", "table", "location", "explanation", "fix", "n_rows", "action"]].copy()
            view["severity"] = view.severity.map(SEV_ICON)
            ed = st.data_editor(view, key=f"issues_{S.ver}", hide_index=True, width="stretch", height=420,
                                disabled=[c for c in view.columns if c != "action"],
                                column_config={"action": st.column_config.SelectboxColumn("your decision", options=["Exclude rows", "Keep & flag"]),
                                               "explanation": st.column_config.TextColumn(width="large"), "fix": st.column_config.TextColumn("suggested fix", width="medium"),
                                               "location": st.column_config.TextColumn(width="medium"), "n_rows": st.column_config.NumberColumn("rows")})
            acts = {r.id: ("exclude" if (r.action == "Exclude rows" and show.set_index("id").loc[r.id, "n_rows"] > 0) else "keep") for r in ed.itertuples()}
            for r in I.itertuples():
                acts.setdefault(r.id, "keep")
            with st.expander("Exclude specific source rows manually"):
                lab = {f"{S.raw[k].file} › {S.raw[k].sheet}": k for k in S.raw}
                k = lab[st.selectbox("Sheet", list(lab), key=f"msheet_{S.get('sig')}_{S.ver}")]
                txt = st.text_input("Excel row numbers (e.g. 12, 40-45)", key=f"manual_{S.ver}")
                nums = []
                for part in re.split(r"[,\s]+", txt.strip()):
                    if re.fullmatch(r"\d+", part):
                        nums.append(int(part))
                    elif re.fullmatch(r"\d+-\d+", part):
                        a, b = map(int, part.split("-")); nums += list(range(a, b + 1))
                extra = {f"{k}#{n}": f"manual exclusion by user ({S.raw[k].sheet} row {n})" for n in nums}
                if nums:
                    st.caption(f"{len(nums)} row(s) will be excluded from {S.raw[k].sheet}.")
            st.caption("To exclude a whole sheet, set it to '(ignore sheet)' or untick 'Use this sheet' in step 2, then confirm again.")
            if st.button("Apply decisions and calculate", type="primary"):
                S.actions, S.extra = acts, extra
                with st.spinner("Excluding rows and preparing the data…"):
                    apply_now()
                st.rerun()
            if S.get("applied"):
                st.success(f"Calculated from cleaned data. {len(S.log)} row(s) excluded.")
                if len(S.log):
                    st.dataframe(S.log.groupby(["table", "sheet", "reason"]).agg(rows=("row", "count"), example_rows=("row", lambda x: ", ".join(map(str, sorted(x)[:5])))).reset_index(),
                                 hide_index=True, width="stretch")
            st.download_button("Download validation report (CSV)", I.drop(columns=["uids"]).to_csv(index=False).encode(), "validation_report.csv", "text/csv")
            if S.get("applied"):
                dd = S.decisions
                for r in I.itertuples():
                    dd.set_issue_action(r.check, r.table, S.actions.get(r.id, r.default_action))
                for uid, why in S.extra.items():
                    f_, rest = uid.split("::", 1); sh_, rw_ = rest.rsplit("#", 1)
                    dd.exclude_row(f_, sh_, int(rw_), "manual", why)
                import json as _json
                st.download_button("Download my decisions (sidecar JSON: mapping fixes, exclusions)", _json.dumps(dict(mapping=dd.mapping, exclusions=dd.exclusions, issue_actions=dd.issue_actions, bands=dd.bands), indent=2).encode(),
                                   "decisions.json", "application/json", help="Reuse with the master pack CLI: --decisions decisions.json. Your source files are never changed.")

    kind, msg = data_status()
    getattr(strip, kind)(msg)

    # =============================================================================== 4 method
    with tab_method:
        if not ready:
            st.info("Load data first.")
        else:
            st.subheader("Data readiness: what was provided, what is missing, and the future source")
            T0 = S.T if S.get("T") is not None else (S.V["T"] if S.get("V") else {})
            st.dataframe(pl.readiness(T0, S.mapping, S.raw), hide_index=True, width="stretch")
            st.subheader("Assumptions introduced by this app")
            fm = dict(baseline_pct=.2, allocation_pct=.1, repair_low=.5, repair_high=1.0, **THRESH)
            st.dataframe(pd.DataFrame([dict(id=a[0], assumption=a[1], rule=a[2].format(**fm), rationale=a[3], confidence=a[4], treatment=a[5]) for a in APP_ASSUMPTIONS]), hide_index=True, width="stretch")
            for f in ("METHODOLOGY.md", "DATA_READINESS.md"):
                p = os.path.join(os.path.dirname(__file__), f)
                if os.path.exists(p):
                    with st.expander(f):
                        st.markdown(open(p, encoding="utf-8").read())

