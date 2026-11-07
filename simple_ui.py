"""Simple mode (the default screen): drop the Excel files, the meeting decks appear. Everything else happens after the deck.
One deck per customer (zip when there are several), each with that customer's own data workbook for Copilot.
No tabs, no charts, no jargon, never a traceback. Anything deeper lives in Advanced mode."""
from __future__ import annotations
import hashlib, io, os, re, shutil, tempfile, zipfile
import streamlit as st
import master_pack as mp
import providers
from decisions import Decisions

S = st.session_state
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _safe(name):
    return re.sub(r"\s+", "_", re.sub(r"[^\w\- ]", "", str(name), flags=re.UNICODE)).strip("_") or "customer"


def _sig(sources):
    h = hashlib.sha256()
    for n, b in sources:
        h.update(n.encode())
        h.update(hashlib.sha256(b).digest() if isinstance(b, (bytes, bytearray)) else str(b).encode())
    return h.hexdigest()


def _decisions() -> Decisions:
    d = S.get("decisions") or Decisions()
    S.decisions = d
    return d


def _norm(name): return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


def _match_customer(named, names):
    n = _norm(named)
    if not n: return None
    for cid, nm in names.items():
        if _norm(nm) == n: return cid
    return None


def _dver():
    d = _decisions()
    payload = repr((sorted(d.issue_actions.items()), d.exclusions, d.bands, sorted(d.mapping.items())))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _is_current(res, sig, sample):
    """A build is current only when the files, the decisions and the sample/real flag all match what it was built with."""
    bw = (res or {}).get("built_with") or {}
    return bool(bw) and bw.get("sig") == sig and bw.get("decisions") == _dver() and bw.get("sample") == bool(sample)


DECK_FAILED = "the meeting deck could not be built"
PACK_FAILED = "the data workbook could not be built"


def _failed_decks(res):
    return [(cid, c["name"], c.get("deck_error") or DECK_FAILED) for cid, c in res["customers"].items() if not c.get("deck")]


def _failed_packs(res):
    return [(cid, c["name"], c["pack_error"]) for cid, c in res["customers"].items() if c.get("pack_error")]


def _sync_decision_widgets(res):
    """Copy the radio choices into the decisions. A choice equal to the issue's default is not a decision, so its key is removed."""
    d = _decisions()
    I = res["work"]["issues"]
    for r in I[I.severity.isin(["ERROR", "WARNING"])].itertuples():
        if not r.n_rows:
            continue
        k = f"{r.check}|{r.table}"
        v = S.get(f"act_{k}")
        if v is None:
            continue
        action = "exclude" if str(v).startswith("Exclude") else "keep"
        if action == r.default_action:
            d.issue_actions.pop(k, None)
        else:
            d.issue_actions[k] = action


def _reset_choices():
    """New, unrelated files: old review choices, pasted additions and radio states must not carry over."""
    S.decisions = Decisions()
    S.pop("additions", None)
    for k in [k for k in list(S.keys()) if str(k).startswith("act_")]:
        S.pop(k, None)


def _bundle(res, cid):
    import deck_draft as dd
    w = res["work"]
    b = dd.prepare(w["T"], w["issues"], w["log"], cid, [], bands=_decisions().bands_obj(), additions=S.get("additions", {}).get(cid), synthetic=bool(res.get("sample")))
    prev = (res.get("prev_measures") or {}).get(cid)
    now = {k: (m.label, m.value, m.fmt()) for k, m in b["M"].items()}
    res.setdefault("measures", {})[cid] = now
    if prev:
        b["changes"] = [f"{now[k][0]}: {prev[k][2]} to {now[k][2]}" for k in now if k in prev and abs(now[k][1] - prev[k][1]) > 1e-9 * max(1.0, abs(prev[k][1]))]
    res.setdefault("changes", {})[cid] = list(b.get("changes", []))
    return b


def _deck(res, cid):
    import deck_draft as dd
    return dd.build(_bundle(res, cid))


def _read(paths):
    return {os.path.basename(o): open(o, "rb").read() for o in paths}


def _run_build(sources, sig, sample=False):
    import portfolio as pf
    tmp = tempfile.mkdtemp(prefix="kam_")
    bar = st.progress(0.0, text="Starting…")
    try:
        old = S.get("simple_result")
        prog = lambda p, m: bar.progress(min(p * 0.6, 0.6), text=m)
        rep = mp.build([], os.path.join(tmp, "all.xlsx"), "all", decisions=_decisions(), progress=prog, sources=sources, keep_working=True)
        work = rep.pop("_working", None)
        res = dict(report=rep, sig=sig, sample=bool(sample), built_with=dict(sig=sig, decisions=_dver(), sample=bool(sample)), prev_measures=(old or {}).get("measures"))
        if rep.get("ok"):
            res["work"] = work
            CU = pf.customers(work["T"])
            names = dict(zip(CU.customer_id, CU.customer))
            res["names"] = names
            res["customers"] = {}
            for i, (cid, nm) in enumerate(names.items(), 1):
                bar.progress(0.6 + 0.4 * (i - 1) / max(len(names), 1), text=f"Deck {i} of {len(names)}: {nm}")
                pack_error = ""
                if len(names) == 1:
                    outs = rep["outputs"]
                else:
                    try:
                        r2 = mp.build([], os.path.join(tmp, f"{_safe(nm)}.xlsx"), cid, decisions=_decisions(), sources=sources)
                    except Exception:
                        r2 = {}
                    if r2.get("ok"):
                        outs = r2["outputs"]
                    else:
                        outs, pack_error = [], PACK_FAILED
                xl = _read([o for o in outs if o.endswith(".xlsx") and not o.endswith("_for_Copilot.xlsx")])
                slim = _read([o for o in outs if o.endswith("_for_Copilot.xlsx")])
                pm = [o for o in outs if o.endswith("Copilot_Prompt.md")]
                res["customers"][cid] = dict(name=nm, xlsx=xl, slim=slim, prompt=open(pm[0], encoding="utf-8").read() if pm else "")
                if pack_error:
                    res["customers"][cid]["pack_error"] = pack_error
                try:
                    res["customers"][cid]["deck"] = _deck(res, cid)
                except Exception:
                    res["customers"][cid]["deck"] = None
                    res["customers"][cid]["deck_error"] = DECK_FAILED
            res["integrity"] = rep.get("integrity")
        S.simple_result = res
    finally:
        bar.empty()
        shutil.rmtree(tmp, ignore_errors=True)         # nothing is kept on disk


def _zip(res):
    bad, badp = _failed_decks(res), _failed_packs(res)
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("READ_ME.txt", "One folder per customer.\nIn each: the draft meeting deck (PowerPoint) and that customer's data workbook for Microsoft Copilot.\n"
                                  "Attach the workbook in Copilot chat and send: Follow the instructions in the START_HERE sheet.\n"
                                  "Draft only: the KAM reviews each deck before customer use.\n")
        if bad or badp:
            lines = ["INCOMPLETE BUILD", "", "This zip does not contain everything. Rebuild before the meeting.", ""]
            if bad:
                lines += ["Meeting decks that were not built:"] + [f"- {nm}: {why}" for _, nm, why in bad] + [""]
            if badp:
                lines += ["Data workbooks that were not built:"] + [f"- {nm}: {why}" for _, nm, why in badp] + [""]
            lines.append("A customer whose deck was not built has a DECK_NOT_BUILT.txt in its folder; its data workbook is still included where it could be built.")
            z.writestr("INCOMPLETE_BUILD.txt", "\n".join(lines) + "\n")
        for cid, c in res["customers"].items():
            d = _safe(c["name"])
            if c.get("deck"):
                z.writestr(f"{d}/Meeting_plan_{d}_DRAFT.pptx", c["deck"])
            else:
                why = c.get("deck_error") or DECK_FAILED
                z.writestr(f"{d}/DECK_NOT_BUILT.txt", f"The meeting deck for {c['name']} was not built.\nReason: {why}.\n"
                                                      "This customer's data workbook is included where it could be built. Rebuild before the meeting.\n")
            for n, b in (c.get("slim") or {}).items():
                z.writestr(f"{d}/{n}", b)
            for n, b in (c.get("xlsx") or {}).items():
                z.writestr(f"{d}/full_data_pack/{n}", b)
            if c.get("prompt"):
                z.writestr(f"{d}/Copilot_Prompt.md", c["prompt"])
    return bio.getvalue()


def _open_advanced():
    S["advanced"] = True


def _plain_errors(rep):
    out = []
    for e in rep.get("errors", []):
        low = e.lower()
        if "no .xlsx" in low:
            out.append("We did not find any Excel or CSV files there.")
        elif "none of the files could be read" in low:
            out.append("None of the files could be opened as an Excel workbook. Check that they are not password-protected and are real .xlsx files.")
        elif "usable sites" in low or "service-activity" in low:
            out.append("We could open the files, but could not recognise the customer, site and activity sheets. Open Advanced to show the program how the sheets should be understood.")
        else:
            out.append("Something unexpected stopped the build. Open Advanced to look at the details, or try fewer files.")
    return out


def render_simple():
    import deck_draft as dd
    demo = providers.demo_mode()
    st.markdown("## Customer meeting plan")
    st.caption("Drop your Excel files. A draft meeting deck for each customer appears. Nothing in your files is changed.")

    sources, is_sample = [], False
    if demo:
        st.info("Demo with synthetic sample data. Uploading is switched off.")
        if st.button("Use the sample data", type="primary", key="use_sample"):
            S.simple_pick = "sample"
    else:
        up = st.file_uploader("Excel or CSV files (many at once is fine)", type=["xlsx", "xlsm", "csv"], accept_multiple_files=True, key="simple_up", label_visibility="collapsed")
        if up:
            S.simple_pick = None
            sources = [(f.name, f.getvalue()) for f in up]
        if st.button("or try it with sample data", key="use_sample", type="tertiary"):
            S.simple_pick = "sample"
    if not sources and S.get("simple_pick") == "sample":
        import pipeline
        sources = list(pipeline.sample_files())
        is_sample = True

    sig = _sig(sources) if sources else None
    if not sources and S.get("had_sources"):                          # uploads cleared: the old result must not look current
        for k in ("simple_result", "additions", "simple_sig", "had_sources"):
            S.pop(k, None)
        _reset_choices()
    if sources:
        S.had_sources = True
        prev = S.get("simple_sig")
        if prev != sig:                                              # different files: old choices do not carry over
            if prev is not None:
                _reset_choices()
            else:
                S.pop("additions", None)
            S.simple_sig = sig

    res = S.get("simple_result")
    if sources and (not res or res.get("sig") != sig or (not res["report"].get("ok") and not _is_current(res, sig, is_sample))):
        try:
            _run_build(sources, sig, is_sample)
        except Exception:                                            # never a traceback in Simple mode
            S.simple_result = dict(report=dict(ok=False, errors=["unexpected"], warnings=[]), sig=sig, sample=is_sample,
                                   built_with=dict(sig=sig, decisions=_dver(), sample=bool(is_sample)))
        res = S.get("simple_result")
    if not res:
        st.caption("Your files are only read, never changed.")
        return
    if not res["report"].get("ok"):
        st.error("We could not build the meeting plan.")
        for m in _plain_errors(res["report"]) or ["Something unexpected stopped the build."]:
            st.markdown(f"- {m}")
        st.button("Open Advanced", on_click=_open_advanced, type="primary", key="adv_btn_bad")
        return

    rep, cust = res["report"], res["customers"]
    n = len(cust)
    _sync_decision_widgets(res)                                      # before the "outdated" check, so a change disables downloads at once
    current = _is_current(res, sig if sources else res.get("sig"), is_sample if sources else res.get("sample"))
    bad, badp = _failed_decks(res), _failed_packs(res)
    built = n - len(bad)

    if not current:
        st.warning("These downloads are from an earlier build. Your files or decisions changed after it was made, so they are disabled until you rebuild.")
        if st.button("Rebuild now", type="primary", key="rebuild_btn", disabled=not sources):
            with st.spinner("Rebuilding…"):
                _run_build(sources, sig, is_sample)
            st.rerun()
    else:
        if not bad and not badp:
            st.success(f"{'Your meeting deck is' if n == 1 else f'{n} meeting decks are'} ready. Draft only: the KAM reviews each deck before customer use.")
        elif bad:
            st.warning(f"{built} of {n} meeting decks built. Not built: {', '.join(nm for _, nm, _ in bad)}. "
                       "The rest can be downloaded, but this result is incomplete — rebuild before the meeting.")
        else:
            st.warning(f"{len(badp)} data workbook(s) could not be built: {', '.join(nm for _, nm, _ in badp)}. This result is incomplete — rebuild before the meeting.")
        if n == 1:
            cid, c = next(iter(cust.items()))
            if c.get("deck"):
                st.download_button(f"Download the meeting deck for {c['name']}", c["deck"], f"Meeting_plan_{_safe(c['name'])}_DRAFT.pptx", PPTX, type="primary", key="dl_deck")
        else:
            label = (f"Download all {n} decks (zip, with each customer's data for Copilot)" if not (bad or badp)
                     else (f"Download the {built} of {n} decks that were built (zip, marked incomplete)" if bad
                           else f"Download all {n} decks (zip, marked incomplete: a data workbook is missing)"))
            st.download_button(label, _zip(res), "Meeting_plans.zip", "application/zip", type="primary", key="dl_zip")
            with st.expander("Or one customer at a time"):
                for cid, c in cust.items():
                    if c.get("deck"):
                        st.download_button(c["name"], c["deck"], f"Meeting_plan_{_safe(c['name'])}_DRAFT.pptx", PPTX, key=f"dl_deck_{cid}")
                    else:
                        st.caption(f"{c['name']}: not built.")
        for w in rep.get("warnings", []):
            if "Integrity" in w:
                st.error("Some automatic number checks did not pass. Do not quote numbers until you have looked at the sheet Integrity_Check in the workbook.")

    st.divider()
    st.markdown("#### Then, to make it better")

    # ---------------------------------------------------------------- review flagged data
    I = res["work"]["issues"]
    I = I[I.severity.isin(["ERROR", "WARNING"])]
    with st.expander(f"Review the data flagged in your files ({len(I)})", expanded=False):
        st.caption("Reviewing flagged data changes which rows are counted. It does not approve the deck: the KAM still reviews every deck before customer use.")
        if not len(I):
            st.success("Nothing needs a decision.")
        else:
            d = _decisions()
            for r in I.itertuples():
                k = f"{r.check}|{r.table}"
                cur = d.issue_actions.get(k, r.default_action)
                c1, c2 = st.columns([3, 2])
                c1.markdown(f"**{r.severity.title()}** · {r.explanation[:170]}  \n<small>{r.table}, {r.location}{f' · {int(r.n_rows)} rows' if r.n_rows else ''}</small>", unsafe_allow_html=True)
                if r.n_rows:
                    c2.radio("What should happen", ["Exclude these rows", "Keep and report as exception"], index=0 if cur == "exclude" else 1, key=f"act_{k}", label_visibility="collapsed")
                else:
                    c2.caption("Listed as a note. No rows to exclude.")
        if current:
            chg = []
            for cid in cust:
                chg += [f"{cust[cid]['name']}: {x}" for x in (res.get("changes") or {}).get(cid, [])[:3]]
            if chg:
                st.info("What changed in the decks: " + "; ".join(chg[:5]) + ".")

    if current:
        # ---------------------------------------------------------------- copilot
        with st.expander("Talk to the data in Microsoft Copilot", expanded=False):
            cid = st.selectbox("Customer", list(cust), format_func=lambda k: cust[k]["name"], key="cop_customer") if n > 1 else next(iter(cust))
            c = cust[cid]
            st.markdown("1. Open Copilot and attach the workbook below.\n2. Send this message (use the copy icon):")
            st.code("Follow the instructions in the START_HERE sheet of the attached workbook.", language=None)
            st.markdown("3. Talk it through. When you are done, ask Copilot to list what the meeting deck should add, then paste its answer below.")
            st.link_button("Open Microsoft Copilot", "https://copilot.microsoft.com/")
            for nme, data in (c.get("slim") or c["xlsx"]).items():
                st.download_button(f"Download {nme}", data, nme, XLSX, type="primary", key=f"dl_s_{cid}_{nme}")
            with st.expander("Full data pack (for checking, not needed in Copilot)"):
                for nme, data in c["xlsx"].items():
                    st.download_button(f"Download {nme}", data, nme, XLSX, key=f"dl_x_{cid}_{nme}")
            st.download_button("Download Copilot_Prompt.md (fallback)", (c.get("prompt") or "").encode("utf-8"), "Copilot_Prompt.md", "text/markdown", key=f"dl_p_{cid}")

        # ---------------------------------------------------------------- paste back
        with st.expander("Bring Copilot's answer back into the deck", expanded=False):
            cid2 = st.selectbox("Customer", list(cust), format_func=lambda k: cust[k]["name"], key="add_customer") if n > 1 else next(iter(cust))
            sel_name = cust[cid2]["name"]
            txt = st.text_area("Paste Copilot's answer: its list of what to add to the deck", height=180, key="add_text", placeholder=dd.ADD_FORMAT)
            has_txt = bool(txt.strip())
            parsed = dd.parse_additions(txt) if has_txt else []
            named = dd.parse_customer(txt) if has_txt else ""
            if has_txt and not parsed:
                st.warning("We could not find a list in that text. Paste the part of the answer that has the bulleted or numbered topics.")
            blocked, confirmed = False, True
            if has_txt and named:
                names = res.get("names") or {k: v["name"] for k, v in cust.items()}
                mid = _match_customer(named, names)
                if mid is None:
                    st.error(f"We could not match the customer named in the pasted answer ({named}) to this build. Nothing will be added.")
                    blocked = True
                elif mid != cid2:
                    st.error(f"That answer is for {cust[mid]['name']}, not {sel_name}. Nothing will be added.")
                    blocked = True
                elif parsed:
                    st.caption(f"The pasted answer names {sel_name}. That matches the selected customer.")
            if parsed and not named:
                st.info(f"No customer name was found in the pasted answer. This list would be added to {sel_name} only.")
                st.markdown("\n".join(f"- {p_['title']}" for p_ in parsed))
                confirmed = st.checkbox(f"I confirm this list is for {sel_name}", key=f"add_confirm_{cid2}_{hashlib.sha256(txt.encode('utf-8')).hexdigest()[:8]}")
            if parsed and not blocked:
                st.caption(("We read your list as topics. " if parsed[0].get("loose") else "") + f"{len(parsed)} slide(s) found. All pasted text is added as written and marked as not verified. Only a named site's facts box is calculated by code.")
            if st.button("Add to the deck", disabled=(not parsed) or blocked or not confirmed, key="add_btn") and parsed and not blocked and confirmed:
                S.setdefault("additions", {})[cid2] = parsed
                try:
                    res["customers"][cid2]["deck"] = _deck(res, cid2)
                    st.success(f"Added to {sel_name}'s deck as unverified text. Nothing in the data or decisions changed.")
                except Exception:
                    st.warning("We could not add these to the deck.")
            if S.get("additions", {}).get(cid2) and res["customers"][cid2].get("deck"):
                c = res["customers"][cid2]
                st.download_button(f"Download the updated deck for {c['name']}", c["deck"], f"Meeting_plan_{_safe(c['name'])}_DRAFT.pptx", PPTX, type="primary", key="dl_deck_upd")

    st.button("Something look wrong? Open Advanced", on_click=_open_advanced, key="adv_btn_ok")
    st.divider()
    st.caption("Your Excel files are never changed. " + ("Synthetic demo data: estimates, not audited savings. " if demo else "This app processes your files in your session and does not save them. ") + "Numbers are calculated by code, never by an AI model.")
