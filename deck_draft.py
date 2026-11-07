"""Draft meeting deck: the first thing a KAM sees after upload. Built from calculated numbers only (an LLM never writes a figure).

prepare(...) computes everything for one customer (no Streamlit); build(bundle) -> .pptx bytes.
Slides: title (DRAFT banner) / the story / value delivered / utilisation vs band / discussion points / questions to expect /
last time & next steps / what I'm unsure about / appendix. Customer-safe: only this customer's data."""
from __future__ import annotations
import datetime as dt
import pandas as pd
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
import metrics as mt, portfolio as pf, prep, story as sy, measures as ms
import export_pptx as xp
import anomalies
from assumptions import Uncertainty

W, H, MX = 13.33, 7.5, 0.7
CW = W - 2 * MX
INK, MUTE, LINE, SOFT, WHITE = RGBColor(0x14, 0x1B, 0x26), RGBColor(0x5A, 0x63, 0x70), RGBColor(0xDD, 0xE3, 0xEA), RGBColor(0xF4, 0xF6, 0xF9), RGBColor(255, 255, 255)
AMBER, RED, GREEN = RGBColor(0xC9, 0x7A, 0x12), RGBColor(0xB4, 0x3B, 0x2E), RGBColor(0x1B, 0x7F, 0x5C)
FONT = "Calibri"
STATUS_PLAIN = {"CALCULATED": "Calculated from your data", "ALLOCATED": "Calculated, shared across customers by washed kg", "ESTIMATED": "Estimate, depends on an assumption",
                "MEASURED": "Measured"}


# ============================================================================================ data
_PC = None            # (T, baseline, result): the whole-portfolio site table is the same for every customer of one build, so it is computed once


def _portfolio_cached(T, bsel, u):
    global _PC
    c = _PC
    if c is not None and c[0] is T and c[1] == bsel:
        return c[2]
    val = pf.portfolio(T, bsel, "Base", u)
    _PC = (T, bsel, val)
    return val


def prepare(T, issues, log, cid, attendees=(), bands: ms.Bands | None = None, stale_days=90, brand=None, notes_by_customer=None, additions=None, synthetic: bool = False):
    u = Uncertainty()
    bsel = mt.default_baseline(T)
    CU = pf.customers(T).set_index("customer_id")
    name, industry = CU.customer[cid], CU.industry[cid]
    _, SA = _portfolio_cached(T, bsel, u)
    RI = pf.repair_intensity(T)
    M = mt.metrics(T, cid, bsel, "Base", u)
    BS = SA[SA.customer_id == cid].reset_index(drop=True)
    themes, why = prep.rank_themes(sy.industry_order(T, industry), "", [], list(attendees))
    Ib = pf.issues_for_customer(issues, T, cid)
    opps = pf.opportunities(T, cid, M, BS, RI, u, stale_days)
    chal = pf.challenges(T, M, cid, bsel, u, Ib)
    lo, hi, src, rationale = (bands or ms.Bands()).for_customer(cid, industry)
    anoms = anomalies.find(BS, RI, cid, lo, hi)
    mo = pf.monthly(T, cid)
    topics = [t.strip() for t in str(CU.topics.get(cid, '') if 'topics' in CU.columns else '').split('|') if t.strip() and t.strip().lower() != 'nan']
    ys = 1 if len(mo) >= 3 else 0
    return dict(anoms=anoms, monthly=mo, topics=topics, _ys=ys, additions=resolve_additions(additions or [], BS), cid=cid, name=name, industry=industry, M=M, S=BS, themes=themes, why=why, issues=Ib, opps=opps, chal=chal, attendees=list(attendees),
                band=(lo, hi, src, rationale), baseline=M.baseline_name, brand=brand, ordered=sy.order_metrics(M, themes), log=log, followups=(notes_by_customer or {}).get(cid, []), synthetic=bool(synthetic))


def _open_issues(b):
    I = b["issues"]
    return I[I.severity.isin(["ERROR", "WARNING"])] if len(I) else I


# ============================================================================================ drawing helpers
def _tb(s, x, y, w, h, text, size=16, bold=False, color=INK, align=None, anchor=MSO_ANCHOR.TOP):
    t = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = t.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, line in enumerate(str(text).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run(); r.text = line; f = r.font; f.size, f.bold, f.name = Pt(size), bold, FONT; f.color.rgb = color
        if align: p.alignment = align
    return t


def _box(s, x, y, w, h, fill, line=None, radius=True):
    r = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    if radius: r.adjustments[0] = 0.06
    r.fill.solid(); r.fill.fore_color.rgb = fill
    if line is None: r.line.fill.background()
    else: r.line.color.rgb = line; r.line.width = Pt(0.75)
    r.shadow.inherit = False
    return r


def _chip(s, x, y, text, fill, color=WHITE, w=None, size=10):
    w = w or (0.14 + 0.085 * len(text))
    c = _box(s, x, y, w, 0.3, fill)
    c.adjustments[0] = 0.5
    tf = c.text_frame; tf.margin_left = tf.margin_right = Inches(0.06); tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = text; r.font.size, r.font.bold, r.font.name = Pt(size), True, FONT; r.font.color.rgb = color
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    return c


def _head(prs, b, headline, kicker, n, notes=""):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _box(s, 0, 0, 0.18, H, b["_accent"], radius=False)
    _tb(s, MX, 0.45, CW, 0.3, kicker.upper(), 11, True, b["_accent"])
    _tb(s, MX, 0.8, CW, 1.1, headline, 30, True, INK)
    _tb(s, W - MX - 3.5, H - 0.42, 3.5, 0.25, f"{b['name']}  ·  {n}", 9, False, MUTE, PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = notes
    return s


def _footnote(s, b, text=None):
    open_n = len(_open_issues(b))
    t = text or (f"Draft: some figures depend on {open_n} flagged data point(s), see slide {b.get('_un', 4)}." if open_n else "")
    if t: _tb(s, MX, H - 0.42, 8, 0.25, t, 9, False, AMBER)


def _card(s, x, y, w, h, label, value, sub, chip=None, chipcol=None, accent=None):
    _box(s, x, y, w, h, SOFT)
    _box(s, x, y + 0.2, 0.07, h - 0.4, accent or MUTE, radius=False)
    _tb(s, x + 0.3, y + 0.2, w - 0.5, 0.5, label, 13, False, MUTE)
    _tb(s, x + 0.3, y + 0.62, w - 0.5, 0.9, value, 34 if len(value) <= 8 else (28 if len(value) <= 10 else 22), True, INK)
    _tb(s, x + 0.3, y + 1.55, w - 0.5, h - 1.9, sub, 11.5, False, MUTE)
    if chip: _chip(s, x + 0.3, y + h - 0.45, chip, chipcol or MUTE)


def _metric_sub(m):
    return ("Exact, no assumption applied." if m.exact else f"Plausible range: {m.fmt_range()}")


# ============================================================================================ deck
def build(b) -> bytes:
    prim, acc = (b.get("brand") or ("#0B2A4A", "#007A87"))
    b["_primary"], b["_accent"] = xp._readable(xp._rgb(prim), 0.35), xp._readable(xp._rgb(acc), 0.5)
    prs = Presentation(); prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    M, S = b["M"], b["S"]
    open_n = len(_open_issues(b))
    n_an = 1 if len(b["anoms"]) <= 1 else 2
    ys = b["_ys"]
    n_pri = 2 + ys; n_top = n_pri + 1; n_rest = n_top + 1
    n_opp = n_pri + 1 + n_an; n_dec = n_opp + 1
    UN = n_dec + len(b.get("additions") or []) + 1
    b["_un"], b["_rest"] = UN, n_rest
    lo, hi, bsrc, brat = b["band"]
    shown_themes = [prep.THEME_LABEL[t] for t in b["themes"][:2]]
    room = ", ".join(b["attendees"]) or "attendees not chosen yet"

    # ---------------------------------------------------------------- 1 executive summary (steering committee, one page)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _box(s, 0, 0, W, 1.55, b["_primary"], radius=False)
    _box(s, 0, 1.55, W, 0.07, b["_accent"], radius=False)
    _tb(s, MX, 0.28, 8.2, 0.7, b["name"], 34, True, WHITE)
    _tb(s, MX, 0.9, 8.0, 0.3, f"Steering committee summary  ·  {dt.date.today():%d %B %Y}", 14, False, RGBColor(0xC9, 0xD3, 0xDD))
    _tb(s, MX, 1.2, 8.0, 0.3, _receives(M), 13, False, RGBColor(0x9F, 0xD8, 0xDE))
    ban = _box(s, W - MX - 4.6, 0.42, 4.6, 0.62, RGBColor(0xF2, 0xB8, 0x4B)); ban.adjustments[0] = 0.3
    tf = ban.text_frame; tf.vertical_anchor = MSO_ANCHOR.MIDDLE; tf.margin_left = Inches(0.15)
    r = tf.paragraphs[0].add_run(); r.text = f"DRAFT · unreviewed data · {open_n} open check{'s' if open_n != 1 else ''}"
    r.font.size, r.font.bold, r.font.name = Pt(14), True, FONT; r.font.color.rgb = RGBColor(0x3A, 0x26, 0x00)
    _hl = _headline(b)
    _tb(s, MX, 1.85, CW, 0.6, _hl, 24 if len(_hl) <= 62 else 20, True, INK)
    heroes = _heroes(b)[:4]
    cw = (CW - 0.3 * 3) / 4
    for i, m in enumerate(heroes):
        x = MX + i * (cw + 0.3); col = {"CALCULATED": GREEN, "ALLOCATED": b["_accent"], "ESTIMATED": AMBER}.get(m.status, MUTE)
        _box(s, x, 2.6, cw, 1.7, SOFT); _box(s, x, 2.6, cw, 0.08, col, radius=False)
        v = m.fmt()
        _tb(s, x + 0.25, 2.85, cw - 0.5, 0.8, v, 36 if len(v) <= 8 else (30 if len(v) <= 10 else 24), True, INK, anchor=MSO_ANCHOR.MIDDLE)
        _tb(s, x + 0.25, 3.7, cw - 0.5, 0.5, _short_label(m), 13, False, MUTE)
    # --- garment use: track with the healthy band, marker, one dot per site
    px, pw = MX, 6.4
    _box(s, px, 4.6, pw, 2.2, SOFT)
    _tb(s, px + 0.3, 4.75, pw - 0.6, 0.3, "GARMENT USE", 11, True, b["_accent"])
    tx, tw = px + 0.3, pw - 0.6
    util = float(M["utilisation"].value) if "utilisation" in M else None
    _box(s, tx, 5.45, tw, 0.26, LINE, radius=False)
    _box(s, tx + tw * lo / 100, 5.45, tw * (hi - lo) / 100, 0.26, xp._mix(b["_accent"], (255, 255, 255), 0.55), radius=False)
    if util is not None:
        mx_ = tx + tw * max(0, min(100, util)) / 100
        _box(s, mx_ - 0.04, 5.3, 0.08, 0.56, INK, radius=False)
        _tb(s, min(max(mx_ - 0.9, tx), tx + tw - 1.8), 5.02, 1.8, 0.25, f"{util:.1f} %", 13, True, INK, PP_ALIGN.CENTER)
    _tb(s, tx, 5.78, tw, 0.25, f"Healthy range {lo:.0f} to {hi:.0f} %", 11, False, MUTE, PP_ALIGN.CENTER) if False else None
    _tb(s, tx + tw * lo / 100, 5.78, max(tw * (hi - lo) / 100, 1.2), 0.25, f"{lo:.0f} to {hi:.0f} %", 11, False, MUTE, PP_ALIGN.CENTER)
    sv = [float(v) for v in S.utilisation.dropna()]
    per = 20
    for i, v in enumerate(sv[:40]):
        d = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(tx + (i % per) * 0.285), Inches(6.18 + (i // per) * 0.3), Inches(0.21), Inches(0.21))
        d.fill.solid(); d.fill.fore_color.rgb = b["_accent"] if lo <= v <= hi else AMBER; d.line.fill.background(); d.shadow.inherit = False
    n_out = sum(1 for v in sv if not (lo <= v <= hi))
    _tb(s, tx + 3.9, 6.18 + (0.3 if len(sv) > per else 0) - (0.0), 2.0, 0.3, "", 1) if False else None
    _tb(s, px + pw - 2.55, 4.75, 2.25, 0.3, f"{n_out} of {len(sv)} sites outside", 11, True, AMBER if n_out else GREEN, PP_ALIGN.RIGHT)
    # --- discuss today
    qx = MX + pw + 0.3; qw = CW - pw - 0.3
    _box(s, qx, 4.6, qw, 2.2, SOFT)
    _tb(s, qx + 0.3, 4.75, qw - 0.6, 0.3, "START THE CONVERSATION HERE", 11, True, b["_accent"])
    disc = [{"short": a["short"], "why": _why(a)} for a in b["anoms"][:3]] or [{"short": SHORT_OPP.get(c.get("id"), " ".join(c["title"].split()[:5]))} for c in b["opps"][:3]]
    for i, c in enumerate(disc):
        y = 5.15 + i * 0.52
        dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(qx + 0.3), Inches(y), Inches(0.36), Inches(0.36))
        dot.fill.solid(); dot.fill.fore_color.rgb = b["_accent"]; dot.line.fill.background(); dot.shadow.inherit = False
        t_ = dot.text_frame; t_.margin_left = t_.margin_right = t_.margin_top = t_.margin_bottom = 0; t_.vertical_anchor = MSO_ANCHOR.MIDDLE
        rr = t_.paragraphs[0].add_run(); rr.text = str(i + 1); rr.font.size, rr.font.bold, rr.font.name = Pt(13), True, FONT; rr.font.color.rgb = WHITE
        t_.paragraphs[0].alignment = PP_ALIGN.CENTER
        _tb(s, qx + 0.85, y - 0.02, qw - 1.15, 0.28, c["short"], 13.5, True, INK)
        if c.get("why"): _tb(s, qx + 0.85, y + 0.25, qw - 1.15, 0.25, c["why"], 11, False, MUTE)
    est = sum(1 for m in M.values() if m.status == "ESTIMATED")
    tail = "  ·  Synthetic demonstration data, not audited" if b.get("synthetic") else "  ·  Draft: the KAM must review before customer use"
    _tb(s, MX, 6.98, CW, 0.3, f"{open_n} data point(s) to review (slide {UN})  ·  {est} estimate(s)" + tail, 10.5, False, AMBER if open_n else MUTE)
    s.notes_slide.notes_text_frame.text = ("One-page summary for the steering committee. Top row: the four numbers that matter most to the people in the room, in their priority order. "
                                           "Dots: one per site, amber = outside this customer's healthy utilisation range; the range is a conversation starter, not a verdict. "
                                           "Right: three topics to raise. The DRAFT banner stays until the KAM has reviewed this deck; reviewing the flagged data does not approve it for customer use. Every number is calculated by code.")

    # ---------------------------------------------------------------- 2 the year at a glance (same graphs as the web view, native and editable)
    if ys:
        mo = b["monthly"]
        s = _head(prs, b, "How the year went", "Q1 · Outcomes and how they are measured", 2, "Monthly values from the data. Utilisation = garments with scan activity / garments allocated; this customer's healthy range is shown in the panel title.")
        panels = [(f"Garment use, % (healthy range {lo:.0f} to {hi:.0f} %)", "utilisation", '0"%"'), ("Service requests", "requests", "0"), ("Repairs completed", "repairs", "0")]
        panels = [p_ for p_ in panels if p_[1] in mo and mo[p_[1]].notna().any()]
        cw = (CW - 0.3 * (len(panels) - 1)) / max(len(panels), 1)
        for i, (ttl, col, fmt_) in enumerate(panels):
            x = MX + i * (cw + 0.3)
            _box(s, x, 2.2, cw, 4.2, SOFT)
            _tb(s, x + 0.3, 2.35, cw - 0.6, 0.35, ttl, 14, True, INK)
            cd = CategoryChartData(); cd.categories = [str(m_)[5:] if len(str(m_)) >= 7 else str(m_) for m_ in mo.month]
            cd.add_series(ttl, [None if pd.isna(v) else round(float(v), 1) for v in mo[col]])
            gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS if col != "repairs" else XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(x + 0.15), Inches(2.75), Inches(cw - 0.3), Inches(3.5), cd)
            ch = gf.chart; ch.has_legend = False; ch.has_title = False; ch.font.size = Pt(10); ch.font.name = FONT
            ch.value_axis.has_major_gridlines = False; ch.value_axis.tick_labels.number_format = fmt_; ch.value_axis.tick_labels.number_format_is_linked = False
            ser = ch.plots[0].series[0]
            if col == "repairs":
                ser.format.fill.solid(); ser.format.fill.fore_color.rgb = b["_accent"]
            else:
                ser.format.line.color.rgb = b["_accent"]; ser.format.line.width = Pt(2.5); ser.smooth = False
            if col == "utilisation":
                ch.value_axis.minimum_scale = max(0, min(lo, float(mo[col].min())) - 10); ch.value_axis.maximum_scale = min(100, max(hi, float(mo[col].max())) + 10)
        _tb(s, MX, 6.5, CW, 0.5, "How measured: scan and delivery data are calculated; water, energy and emissions are shared across customers by washed kg; savings depend on a stated baseline. Showing the whole year: add your last meeting date to see change since then.", 10, False, MUTE)
        _footnote(s, b)

    # ---------------------------------------------------------------- Q2 priorities
    s = _head(prs, b, "Your priorities, and where you stand today", "Q2 · What matters to you next", n_pri, "Topics come from the customer record. A topic shows a measure only when it names that measure directly; a cost topic shows a proxy that must be confirmed; anything else is shown as having no direct measure. Confirm the list with the customer, they may have changed.")
    tp = b.get("topics") or []
    if not tp:
        _tb(s, MX, 2.4, CW, 1.0, "No priorities are recorded for this customer. Ask them in the meeting and note the answers.", 20, False, MUTE)
    for i, t_ in enumerate(tp[:4]):
        y = 2.15 + i * 1.12
        _box(s, MX, y, CW, 0.98, SOFT)
        _tb(s, MX + 0.35, y + 0.14, 4.3, 0.7, t_, 18, True, INK, anchor=MSO_ANCHOR.MIDDLE)
        m_, kind_, _why_none = _metric_for_topic(b, t_)
        if m_ is None:
            _tb(s, MX + 5.0, y + 0.14, CW - 5.3, 0.7, "No direct measure available in this data. Ask how they track it.", 14, False, MUTE, anchor=MSO_ANCHOR.MIDDLE)
        else:
            col = {"CALCULATED": GREEN, "ALLOCATED": b["_accent"], "ESTIMATED": AMBER}.get(m_.status, MUTE)
            _tb(s, MX + 5.0, y + 0.1, 2.6, 0.78, m_.fmt(), 28, True, INK, anchor=MSO_ANCHOR.MIDDLE)
            _tb(s, MX + 7.7, y + 0.14, 3.2, 0.7, _short_label(m_), 13, False, MUTE, anchor=MSO_ANCHOR.MIDDLE)
            if kind_ == "proxy":                       # a proxy is never proof
                _chip(s, MX + CW - 2.3, y + 0.34, "PROXY · CONFIRM", AMBER, w=1.9)
            else:
                _chip(s, MX + CW - 1.9, y + 0.34, {"CALCULATED": "CALCULATED", "ALLOCATED": "ALLOCATED", "ESTIMATED": "ESTIMATE"}.get(m_.status, m_.status), col, w=1.5)
    _footnote(s, b)

    # ---------------------------------------------------------------- 2 the anomaly that matters most
    anoms = b["anoms"]
    if not anoms:
        s = _head(prs, b, "No threshold was crossed in this data", "Q3 · Delivery issues and risks", n_top, "No site or product crossed a threshold in anomalies.py. That is not proof that service is healthy.")
        _tb(s, MX, 2.4, CW, 0.9, "No site or product crossed a threshold on garment use, delivery or service requests in this data.", 20, False, MUTE)
        _tb(s, MX, 3.4, CW, 1.4, "That is not proof that service is healthy: the checks only cover the measures and periods in this file. Ask what the customer is seeing.", 20, True, INK)
    else:
        top = anoms[0]
        s = _head(prs, b, top["headline"], "Q3 · Delivery issues and risks", n_top,
                  f"{top['reference_text']}. Affects about {_n0(top['pieces'])} garments. {anomalies.rule_text()} Ask: {top['question']}")
        _anomaly_chart(s, top, b, MX, 2.3, 7.4, 4.5)
        x = MX + 7.7; w = CW - 7.7
        _box(s, x, 2.3, w, 4.5, SOFT); _box(s, x, 2.3, 0.09, 4.5, AMBER, radius=False)
        _tb(s, x + 0.35, 2.5, w - 0.6, 0.3, top["metric"].upper(), 11, True, AMBER)
        _tb(s, x + 0.35, 2.85, w - 0.6, 0.9, top["fmt"].format(top["value"]), 44, True, INK)
        _tb(s, x + 0.35, 3.8, w - 0.6, 0.6, top["reference_text"], 13, False, MUTE)
        _tb(s, x + 0.35, 4.3, w - 0.6, 0.4, f"Affects about {_n0(top['pieces'])} garments", 13, True, INK)
        _tb(s, x + 0.35, 5.15, w - 0.6, 0.3, "ASK", 10, True, b["_accent"])
        _tb(s, x + 0.35, 5.42, w - 0.6, 1.2, top["question"], 15, True, INK)
        _footnote(s, b)
        # ---------------------------------------------------------------- 3 the rest, largest first
        if len(anoms) > 1:
            rest = anoms[1:9]
            s = _head(prs, b, f"{len(anoms) - 1} more worth a look, largest first", "Q3 · Delivery issues and risks", n_rest,
                      "Ranked by garments touched x distance from the reference x weight. " + anomalies.rule_text())
            mx_ = max(a["score"] for a in rest) or 1
            for i, a in enumerate(rest):
                y = 2.05 + i * 0.54
                dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(MX), Inches(y + 0.07), Inches(0.36), Inches(0.36))
                dot.fill.solid(); dot.fill.fore_color.rgb = b["_accent"]; dot.line.fill.background(); dot.shadow.inherit = False
                t_ = dot.text_frame; t_.margin_left = t_.margin_right = t_.margin_top = t_.margin_bottom = 0; t_.vertical_anchor = MSO_ANCHOR.MIDDLE
                rr = t_.paragraphs[0].add_run(); rr.text = str(a["rank"]); rr.font.size, rr.font.bold, rr.font.name = Pt(12), True, FONT; rr.font.color.rgb = WHITE
                t_.paragraphs[0].alignment = PP_ALIGN.CENTER
                _tb(s, MX + 0.6, y, 7.6, 0.5, a["headline"], 13, False, INK, anchor=MSO_ANCHOR.MIDDLE)
                bw = 3.0 * a["score"] / mx_
                _box(s, MX + 8.6, y + 0.14, max(bw, 0.08), 0.22, AMBER if a["kind"] != "utilisation" or a["direction"] == "below" else b["_accent"], radius=False)
                _tb(s, MX + 8.6 + max(bw, 0.08) + 0.12, y + 0.1, 1.5, 0.3, f"{_n0(a['pieces'])} garments", 11, False, MUTE)
            if len(anoms) - 1 > len(rest):
                _tb(s, MX, 6.4, CW, 0.3, f"{len(anoms) - 1 - len(rest)} smaller findings are in the workbook.", 11, False, MUTE)
            _footnote(s, b)

    if len(anoms) > 1:
        _tb(s, MX, 6.72, CW, 0.3, "Unresolved commitments from the last meeting: none recorded yet. Add them after the meeting.", 10.5, False, MUTE)

    # ---------------------------------------------------------------- Q4 opportunities
    s = _head(prs, b, "Three ways to add value", "Q4 · Where to improve or expand", n_opp, "Customer-safe evidence only. Each is a hypothesis to test with the customer, not a promise; sizes are in units, never invented revenue.")
    cols = (("Cost", ("cost", "circularity")), ("Sustainability", ("water", "emissions")), ("Operations", ("service",)))
    cw = (CW - 0.6) / 3
    for i, (ttl, ths) in enumerate(cols):
        x = MX + i * (cw + 0.3)
        o = next((c for c in b["opps"] if c.get("theme") in ths), None)
        _box(s, x, 2.15, cw, 4.6, SOFT); _box(s, x, 2.15, cw, 0.09, b["_accent"], radius=False)
        _tb(s, x + 0.3, 2.4, cw - 0.6, 0.3, ttl.upper(), 11, True, b["_accent"])
        if o is None:
            _tb(s, x + 0.3, 3.0, cw - 0.6, 2.0, "Nothing in the data points here. A good place to ask what they need.", 14, False, MUTE)
            continue
        _tb(s, x + 0.3, 2.8, cw - 0.6, 1.0, SHORT_OPP.get(o.get("id"), o["title"]), 18, True, INK)
        _tb(s, x + 0.3, 3.85, cw - 0.6, 1.5, (o["evidence_customer"] or [""])[0][:210], 12, False, MUTE)
        _tb(s, x + 0.3, 5.45, cw - 0.6, 0.3, "ASK", 10, True, b["_accent"])
        _tb(s, x + 0.3, 5.72, cw - 0.6, 0.9, (o["confirm"] or ["What would help most?"])[0], 13, True, INK)
    _footnote(s, b)

    # ---------------------------------------------------------------- Q5 decisions
    s = _head(prs, b, "What we need to decide today", "Q5 · Decisions, owners and dates", n_dec, "Pre-filled from the findings and opportunities. Owners and dates are blank on purpose: fill them in during the meeting.")
    acts = []
    if anoms: acts.append(f"Look into: {anoms[0]['short'].split(': ', 1)[-1]} at {anoms[0]['entity']}" if anoms[0]["kind"] != "repairs" else f"Review {anoms[0]['entity']} durability")
    for o in b["opps"][:3]:
        acts.append(SHORT_OPP.get(o.get("id"), o["title"]))
    if len(_open_issues(b)): acts.append("Agree how flagged data points are handled")
    rows = [["Decision or action", "Lindström owner", "Customer owner", "By when"]] + [[a_[:78], "", "", ""] for a_ in acts[:5]]
    while len(rows) < 5: rows.append(["", "", "", ""])
    xp._table(s, rows, MX, 2.2, CW, [6.0, 2.2, 2.2, 1.73], 14, 0.7, False)
    _footnote(s, b)

    # ---------------------------------------------------------------- added from the KAM's Copilot session
    for k, ad in enumerate(b.get("additions") or [], 1):
        s = _head(prs, b, ad["title"], "Added from your Copilot session", n_dec + k, "This slide was suggested in the Copilot conversation and pasted back. All of its text is unverified, including numbers written as words; only the site facts box is calculated by code. The pasted text did not change any data, calculation or decision.")
        _chip(s, MX, 1.98, "ADDED FROM COPILOT", MUTE, w=2.0)
        _chip(s, MX + 2.15, 1.98, "TEXT NOT VERIFIED", AMBER, w=2.1)
        if ad.get("figures"):
            _chip(s, MX + 4.4, 1.98, "FIGURES IN TEXT NOT VERIFIED", AMBER, w=3.0)
        _tb(s, MX, 6.85, CW - 3.6, 0.3, PASTE_FOOTER, 10.5, False, AMBER)
        bw_ = 7.4 if ad.get("facts") else CW
        _box(s, MX, 2.5, bw_, 4.2, SOFT)
        _tb(s, MX + 0.35, 2.7, bw_ - 0.7, 0.3, "WHY IT MATTERS", 10, True, b["_accent"])
        _tb(s, MX + 0.35, 3.0, bw_ - 0.7, 1.9, ad.get("why") or "No reason given.", 16, False, INK)
        _tb(s, MX + 0.35, 5.0, bw_ - 0.7, 0.3, "ASK", 10, True, b["_accent"])
        _tb(s, MX + 0.35, 5.3, bw_ - 0.7, 1.2, ad.get("ask") or "", 16, True, INK)
        if ad.get("facts"):
            x = MX + 7.7; w = CW - 7.7
            _box(s, x, 2.5, w, 4.2, SOFT); _box(s, x, 2.5, 0.09, 4.2, GREEN, radius=False)
            _tb(s, x + 0.35, 2.7, w - 0.6, 0.3, f"{ad['site'].upper()} · CALCULATED", 10, True, GREEN)
            _tb(s, x + 0.35, 3.1, w - 0.6, 3.4, "\n\n".join(ad["facts"]), 15, False, INK)

    # ---------------------------------------------------------------- unsure
    O = _open_issues(b)
    s = _head(prs, b, (f"{len(O)} data point(s) could change what you just read" if len(O) else "No data points are flagged for this customer"), "What I'm unsure about", UN,
              "Each line names the sheet and the Excel rows. Excluding a row or reporting it as an exception rebuilds this deck with the change noted.")
    rows = [["Severity", "What was found", "Where", "Rows"]]
    for r in O.sort_values("severity", key=lambda x: x.map({"ERROR": 0, "WARNING": 1})).head(6).itertuples():
        what, where = _plain_issue(r)
        rows.append([r.severity.title(), what, where, str(int(r.n_rows)) if pd.notna(r.n_rows) and r.n_rows else "-"])
    if len(rows) > 1:
        xp._table(s, rows, MX, 2.2, CW, [1.3, 6.4, 3.5, 0.93], 12, 0.6, False)
    else:
        _tb(s, MX, 2.4, CW, 1.0, "Nothing needs a decision. The KAM still reviews this deck before it goes to the customer.", 18, False, GREEN)
    ch = b.get("changes") or []
    _tb(s, MX, 6.3, CW, 0.8, ("Since the last version: " + "; ".join(ch[:4]) + ".") if ch else "Review them with Copilot or in the app, then rebuild. The deck updates and notes what changed.", 13, False, b["_accent"])

    # ---------------------------------------------------------------- appendix
    s = _head(prs, b, "How these numbers were made", "Appendix", UN + 1, "Formulas, statuses, the ranking rule and the data behind each number.")
    rows = [["Measure", "Value", "How it is made"]] + [[m.label, m.fmt(), (m.formula or "")[:105]] for m in b["ordered"][:8]]
    xp._table(s, rows, MX, 2.0, CW, [3.2, 1.9, 7.03], 11, 0.44, True)
    _tb(s, MX, 6.0, CW, 0.6, "Ranking of findings: " + anomalies.rule_text(), 10.5, False, MUTE)
    _tb(s, MX, 6.75, CW, 0.4, "Calculated = straight from your data. Allocated = laundry resources shared across customers by washed kg. Estimate = depends on an assumption. KAM reported = said by a person.", 10, False, MUTE)
    return _bytes(prs)


def _plain_issue(r):
    chk, tbl, loc = str(r.check), str(r.table), str(r.location)
    if chk.startswith("customer kg exceeds"):
        return ("Customer washed kg is larger than the laundry's own total in some months, so water, energy and emissions shares may be overstated.", "Service activity vs laundry totals")
    if chk == "no status label":
        return (f"The {tbl} sheet does not say whether its figures are measured, estimated or synthetic, so they show as unlabelled.", f"{tbl.title()} sheet, {loc}")
    txt = str(r.explanation)
    txt = txt if len(txt) <= 115 else txt[:txt.rfind(" ", 0, 112)] + "…"
    return (txt, f"{tbl}, {loc}"[:60])


def _bytes(prs):
    import io
    bio = io.BytesIO(); prs.save(bio); return bio.getvalue()


SHORT_OPP = {"baseline": "Agree a fair comparison baseline", "continuity": "Service continuity at flagged sites", "scope3": "Scope 3 evidence for reporting",
             "traceability": "Garment control threshold", "allocation": "Right-size the garment pool", "repair": "Durability of repair-heavy items"}


def _short_opp(c):
    return ("★ " if c.get("fit") else "") + SHORT_OPP.get(c.get("id"), " ".join(c["title"].split()[:5]))


def _short_label(m):
    t = m.label.split(" (")[0].split(" vs ")[0].split(", ")[0]
    return t[:34]


def _heroes(b):
    seen, out = set(), []
    for m in b["ordered"]:
        if m.key in ("sites", "wearers", "kg", "pieces", "requests", "water_per_kg", "energy_per_kg", "cycle_hours") or m.theme in seen and len(out) < 3:
            continue
        seen.add(m.theme); out.append(m)
    for m in b["ordered"]:
        if m not in out and m.key not in ("sites", "wearers", "kg", "pieces", "requests", "water_per_kg", "energy_per_kg", "cycle_hours"):
            out.append(m)
    return out


def _headline(b):
    an = b["anoms"]
    if not an:
        return "No threshold was crossed — that is not proof that service is healthy"
    more = f" {len(an) - 1} more on slide {b.get('_rest', 4)}." if len(an) > 1 else ""
    return f"Start with this: {an[0]['short']}.{more}"


def _receives(M):
    parts = []
    if "sites" in M: parts.append(f"{M['sites'].fmt().split(' ')[0]} sites")
    if "wearers" in M: parts.append(f"{M['wearers'].fmt().replace(' wearers', '')} wearers")
    if "kg" in M: parts.append(f"{M['kg'].fmt()} washed")
    return "  ·  ".join(parts)


def _why(a):
    ref = a["ref"]
    if a["kind"] == "utilisation":
        return f"{a['value']:.0f} % vs range {ref[0]:.0f} to {ref[1]:.0f} %"
    return f"{a['fmt'].format(a['value'])} vs {a['fmt'].format(ref)} typical"


_PREF = {"service": ("ontime", "requests"), "water": ("water_saving", "energy_saving"), "cost": ("utilisation", "avoided_cost"), "emissions": ("co2_service", "avoided_co2"), "circularity": ("repairs", "recycling_pct")}


def _metric_for(b, theme):
    for k in _PREF.get(theme, ()):
        if k in b["M"]:
            return b["M"][k]
    return None


_TOPIC_METRICS = [
    ("ontime", "direct", ("on-time", "on time", "delivery punctuality", "punctual", "late delivery", "delivery reliability", "delivery window")),
    ("requests", "direct", ("service request", "requests per", "complaint", "response time")),
    ("water_saving", "direct", ("water",)),
    ("energy_saving", "direct", ("energy",)),
    ("co2_service", "direct", ("emission", "co2", "carbon", "scope 3")),
    ("recycling_pct", "direct", ("recycl", "circular", "reuse")),
    ("repairs", "direct", ("repair", "durab")),
    ("utilisation", "direct", ("utilisation", "utilization", "garment use", "pool size", "right-size")),
    ("avoided_cost", "proxy", ("cost", "price", "spend", "saving")),
]
_HYGIENE_WORDS = ("hygiene", "food safety", "infection", "cleanliness", "wash quality", "sanitation")


def _metric_for_topic(b, topic):
    """Match a customer's stated topic to a measure by the topic's own words. No fallback to the theme: returns
    (measure, "direct"|"proxy", "") or (None, "", reason)."""
    low = (topic or "").lower()
    if any(k in low for k in _HYGIENE_WORDS):
        return None, "", "Hygiene is not measured in this data"
    for key, kind, words in _TOPIC_METRICS:
        if key in b["M"] and any(w in low for w in words):
            return b["M"][key], kind, ""
    return None, "", "No direct measure available in this data"


def _n0(x):
    return f"{x:,.0f}".replace(",", " ")


def _anomaly_chart(s, a, b, x, y, w, h):
    ser = sorted(a["chart"], key=lambda t: -t[1])
    names = [n for n, _ in ser]
    if len(ser) > 12:                                   # keep the flagged item visible, show the extremes around it
        keep = ser[:6] + [t for t in ser[6:-5] if t[0] == a["entity"]] + ser[-5:]
        ser = keep; names = [n for n, _ in ser]
    cd = CategoryChartData(); cd.categories = names; cd.add_series(a["metric"], [round(v, 2) for _, v in ser])
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(x), Inches(y), Inches(w), Inches(h), cd)
    ch = gf.chart; ch.has_legend = False; ch.font.size = Pt(11); ch.font.name = FONT
    pl = ch.plots[0]; pl.gap_width = 40; pl.has_data_labels = True; pl.data_labels.font.size = Pt(11)
    pl.data_labels.number_format = {"%": '0.0"%"'}.get(a["unit"], "0.00" if a["kind"] == "repairs" else "0"); pl.data_labels.number_format_is_linked = False
    pl.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    ch.value_axis.has_major_gridlines = False; ch.value_axis.visible = False; ch.value_axis.minimum_scale = 0
    ch.category_axis.reverse_order = True; ch.category_axis.tick_labels.font.size = Pt(11)
    for i, n in enumerate(names):
        pt = pl.series[0].points[i]; pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = AMBER if n == a["entity"] else RGBColor(0xB8, 0xC4, 0xD0)


# ---------------------------------------------------------------------------------------- Copilot paste-back
import re as _re
PASTE_FOOTER = "Pasted from Copilot: unverified. It did not change any data, calculation or decision."
ADD_HEADER = "DECK ADDITIONS"
ADD_FORMAT = """DECK ADDITIONS
Customer: <customer name>
1. Title: <a short headline for the slide>
   Why it matters: <one or two sentences>
   Ask: <the question the KAM should raise>
   Site: <site name, optional>
2. Title: ...
(Topics, questions and requests only. Do not put calculated figures in this block.)"""


def _loose_items(text: str) -> list[dict]:
    """Fallback when there is no 'Title:' structure: every bullet or numbered line becomes a topic."""
    items = []
    for raw in (text or "").splitlines():
        m = _re.match(r"^\s*(?:[-*\u2022]|\d+[.)])\s+(.+)$", raw.replace("**", "").replace("__", ""))
        if not m:
            continue
        t = m.group(1).strip()
        if len(t) < 8 or _re.match(r"^(customer|deck additions)\b", t, _re.I):
            continue
        head, _, tail = t.partition(":") if ":" in t[:80] else (t, "", "")
        if not tail:
            head = _re.split(r"(?<=[.?!])\s", t, 1)[0]
            tail = t[len(head):].strip()
        items.append(dict(title=head.strip().rstrip(".?")[:90], why=tail.strip() if "?" not in tail else "", ask=(t if t.endswith("?") else (tail if tail.endswith("?") else "")), site="", loose=True))
    return items[:6]


def parse_customer(text: str) -> str:
    """The customer named inside a pasted block ("Customer: <name>"), or "" when it names none."""
    m = _re.search(r"^\s*[*#>\-\s]*customer\s*[:\-]\s*(.+?)\s*$", text or "", _re.I | _re.M)
    return m.group(1).strip(" *_") if m else ""


def parse_additions(text: str) -> list[dict]:
    """Forgiving parser for what Copilot hands back. Uses the structured block when present (Title/Why/Ask/Site, markdown tolerated);
    otherwise reads any bulleted or numbered list as topics."""
    items, cur = [], None
    for raw in (text or "").splitlines():
        line = _re.sub(r"^[\s>*#\-]+", "", raw.replace("**", "").replace("__", "")).strip()
        if not line:
            continue
        m = _re.match(r"^(?:\d+[.)]\s*)?(title|slide|topic)\s*[:\-]\s*(.+)$", line, _re.I)
        if m:
            cur = dict(title=m.group(2).strip(), why="", ask="", site=""); items.append(cur); continue
        m = _re.match(r"^(why(?: it matters)?|reason|evidence)\s*[:\-]\s*(.+)$", line, _re.I)
        if m and cur is not None:
            cur["why"] = m.group(2).strip(); continue
        m = _re.match(r"^(ask|question|raise)\s*[:\-]\s*(.+)$", line, _re.I)
        if m and cur is not None:
            cur["ask"] = m.group(2).strip(); continue
        m = _re.match(r"^(site|location)\s*[:\-]\s*(.+)$", line, _re.I)
        if m and cur is not None:
            cur["site"] = m.group(2).strip(); continue
    items = [i for i in items if i["title"]][:6]
    return items or _loose_items(text)


def resolve_additions(items: list[dict], S: pd.DataFrame) -> list[dict]:
    """Attach code-calculated facts for a named site; flag any figure typed in the text as unverified."""
    out = []
    by = {str(r.site).lower(): r for r in S.itertuples()} if len(S) else {}
    for it in items:
        d = dict(it)
        d["unverified"] = True                          # every pasted item, with or without figures
        d["figures"] = bool(_re.search(r"\d+[.,]\d+|\d{2,}|\d\s?(%|k\b|m\b|kg|kwh|l\b|eur|€|co2)", " ".join([d.get("title", ""), d.get("why", ""), d.get("ask", "")]), _re.I))
        r = by.get(str(d.get("site", "")).strip().lower())
        d["facts"] = []
        if r is not None:
            d["site"] = str(r.site)
            if pd.notna(r.utilisation): d["facts"].append(f"Garment use {r.utilisation:.1f} %")
            if pd.notna(r.ontime): d["facts"].append(f"On-time delivery {r.ontime:.1f} %")
            if pd.notna(r.requests_per_1000): d["facts"].append(f"Service requests {r.requests_per_1000:.0f} per 1000 garments")
            d["facts"].append(f"{_n0(r.pieces)} garments allocated")
        else:
            d["site"] = ""
        out.append(d)
    return out


def _story(b):
    M, S = b["M"], b["S"]
    good, raise_, unsure = [], [], []
    if "ontime" in M: good.append(f"On-time delivery {M['ontime'].fmt()}.")
    if "water_saving" in M: good.append(f"Water saved: {M['water_saving'].fmt()} against {b['baseline']}.")
    if "repairs" in M: good.append(f"{M['repairs'].fmt()} completed, keeping garments in use.")
    lo, hi = b["band"][0], b["band"][1]
    if len(S):
        n_att = int(S.attention.sum())
        if n_att: raise_.append(f"{n_att} of {len(S)} sites stand out on two or more signals against this customer's other sites.")
        n_lo, n_hi = int((S.utilisation < lo).sum()), int((S.utilisation > hi).sum())
        if n_lo or n_hi: raise_.append(f"Garment use is outside {lo:.0f} to {hi:.0f} % at {n_lo + n_hi} site(s). Worth asking how they plan their garment pool.")
    if b["opps"]: raise_.append(b["opps"][0]["title"] + ".")
    O = _open_issues(b)
    if len(O): unsure.append(f"{len(O)} flagged data point(s).")
    for m in b["M"].values():
        if m.status == "ESTIMATED": unsure.append(f"{m.label} is an estimate, not a measurement."); break
    unsure.append("Water and emissions are shared across customers by washed kg.")
    return good[:3], raise_[:3], unsure[:3]


def _util_headline(b):
    S = b["S"]; lo, hi = b["band"][0], b["band"][1]
    if not len(S) or S.utilisation.isna().all(): return "Garment use by site is not available in this data"
    n = int(((S.utilisation < lo) | (S.utilisation > hi)).sum())
    return f"{n} of {len(S)} sites sit outside the healthy garment-use range" if n else f"All {len(S)} sites are inside the healthy garment-use range"
