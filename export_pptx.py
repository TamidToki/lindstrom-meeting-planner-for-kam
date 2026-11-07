"""Editable PowerPoint export (native text, shapes, tables and charts, no pictures).

Structure: cover with 3 hero numbers -> summary -> value delivered -> priority view -> countries and sites
-> garment control (RFID) -> discussion points -> topics -> agreed actions -> APPENDIX (formulas, method,
data used, data readiness). Detail that a CAM needs only when challenged (formulas, basis, questions to ask)
goes to the speaker notes or the appendix, so the main slides stay readable on a screen."""
from __future__ import annotations
import io
import re
import pandas as pd
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION
from assumptions import APP_ASSUMPTIONS, THRESH, scenario_text

NAVY = RGBColor(0x0B, 0x2A, 0x4A)
TEAL = RGBColor(0x00, 0x7A, 0x87)
GREY = RGBColor(0x55, 0x5B, 0x66)
RED = RGBColor(0xB4, 0x3B, 0x2E)
LIGHT = RGBColor(0xF1, 0xF5, 0xF8)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LINE = RGBColor(0xD5, 0xDD, 0xE5)
BANNER = "SYNTHETIC / ILLUSTRATIVE DATA unless stated. Estimates only: not audited or verified Lindström or customer figures. Contains only this customer's data."
MX = 0.6          # left/right margin (inches)
CW = 13.33 - 2 * MX

UNIT_WORD = {"L": "litres", "kgCO2e": "kg CO2e"}
HERO_KEYS = ("water_saving", "energy_saving", "co2_service", "avoided_cost", "postponed", "repairs", "recycling_pct", "ontime", "utilisation")


# ----------------------------------------------------------------------------------------------- formatting
def _num(v, unit):
    """Reader-friendly number: million / thousand words, litres, tonnes."""
    if unit == "%":
        return f"{v:.1f} %"
    if unit == "kgCO2e" and abs(v) >= 1000:
        return f"{v / 1000:,.1f} t CO2e".replace(",", " ")
    if unit == "kg" and abs(v) >= 1000:
        return f"{v / 1000:,.1f} t".replace(",", " ")
    u = UNIT_WORD.get(unit, unit)
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:.2f} million {u}"
    if a >= 1e4:
        return f"{v / 1e3:.1f} thousand {u}"
    if float(v).is_integer() or a >= 100:
        return f"{v:,.0f} {u}".replace(",", " ").strip()
    return f"{v:.1f} {u}".strip()


def _val(m):
    return _num(m.value, m.unit)


def _rng(m):
    return "exact, no assumption applied" if m.exact else f"range {_num(m.low, m.unit)} to {_num(m.high, m.unit)}"


def _status(m):
    return m.status.title()


def _clean(text):
    """Spell out the compact units used in the dashboard text (1.41 M L -> 1.41 million litres)."""
    t = str(text)
    t = re.sub(r"(\d) M L\b", r"\1 million litres", t)
    t = re.sub(r"(\d) k L\b", r"\1 thousand litres", t)
    t = re.sub(r"(\d) k kgCO2e\b", r"\1 t CO2e", t)
    t = re.sub(r"(\d) k kg\b", r"\1 t", t)
    t = re.sub(r"(\d) k EUR\b", r"\1 thousand EUR", t)
    return t


def _short(text, n=150):
    """First sentence (not split at e.g./i.e.), cut at a word boundary if still long."""
    t = re.sub(r"\s+", " ", _clean(text)).strip().replace("e.g.", "e§g§").replace("i.e.", "i§e§")
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    t = (m.group(1) if m else t).replace("§", ".")
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return t


# ----------------------------------------------------------------------------------------------- primitives
def _rect(slide, x, y, w, h, fill, rounded=True):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    if rounded:
        s.adjustments[0] = 0.06
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    s.line.fill.background()
    s.shadow.inherit = False
    return s


def _tb(slide, x, y, w, h, text, size=14, bold=False, color=NAVY, align=None, anchor=None):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    if anchor:
        tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.text, p.font.size, p.font.bold, p.font.color.rgb = text, Pt(size), bold, color
    if align:
        p.alignment = align
    return tf


def _add_p(tf, text, size, color=GREY, bold=False, space=4):
    p = tf.add_paragraph()
    p.text, p.font.size, p.font.bold, p.font.color.rgb = text, Pt(size), bold, color
    p.space_before = Pt(space)
    return p


def _notes(slide, text):
    if text:
        slide.notes_slide.notes_text_frame.text = text


def _slide(prs, title, sub=None, tag=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _rect(s, 0, 0, 13.33, 0.14, TEAL, rounded=False)
    _tb(s, MX, 0.38, CW - 2.4, 0.75, title, 30, True)
    if tag:
        _tb(s, 13.33 - MX - 2.3, 0.45, 2.3, 0.35, tag, 11, True, TEAL, PP_ALIGN.RIGHT)
    if sub:
        _tb(s, MX, 1.08, CW, 0.45, sub, 14, False, GREY)
    _tb(s, MX, 7.08, CW - 0.8, 0.3, BANNER, 9, False, RED)
    _tb(s, 13.33 - MX - 0.6, 7.08, 0.6, 0.3, str(len(prs.slides)), 10, False, GREY, PP_ALIGN.RIGHT)
    return s


def _table(slide, rows, x, y, w, col_w, size=12, row_h=0.4, bold_first_col=False):
    shp = slide.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(row_h * len(rows)))
    t = shp.table
    tot = sum(col_w)
    for j, cw in enumerate(col_w):
        t.columns[j].width = Inches(w * cw / tot)
    for i in range(len(rows)):
        t.rows[i].height = Inches(row_h)
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            c = t.cell(i, j)
            c.text = str(v)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.margin_left = c.margin_right = Inches(0.08)
            c.margin_top = c.margin_bottom = Inches(0.03)
            c.fill.solid()
            c.fill.fore_color.rgb = NAVY if i == 0 else (LIGHT if i % 2 == 0 else WHITE)
            for p in c.text_frame.paragraphs:
                p.font.size = Pt(size)
                p.font.bold = (i == 0) or (bold_first_col and j == 0)
                p.font.color.rgb = WHITE if i == 0 else NAVY
    return t


def _card(slide, x, y, w, h, label, value, line3=None, line4=None, value_size=26, status_red=False):
    _rect(slide, x, y, w, h, LIGHT)
    _rect(slide, x, y + 0.12, 0.07, h - 0.24, TEAL, rounded=False)
    _tb(slide, x + 0.2, y + 0.1, w - 0.3, 0.55, label, 12, False, GREY)
    _tb(slide, x + 0.2, y + 0.62, w - 0.3, 0.65, value, value_size, True, TEAL, anchor=MSO_ANCHOR.MIDDLE)
    if line3:
        _tb(slide, x + 0.2, y + 1.3, w - 0.3, 0.3, line3, 11, False, GREY)
    if line4:
        _tb(slide, x + 0.2, y + 1.58, w - 0.3, 0.3, line4, 10, False, RED if status_red else GREY)


def _hero_pick(ordered):
    picked, themes_used = [], set()
    for m in ordered:
        if m.key in HERO_KEYS and m.theme not in themes_used:
            picked.append(m)
            themes_used.add(m.theme)
        if len(picked) == 3:
            return picked
    for m in ordered:
        if m not in picked and m.key in HERO_KEYS:
            picked.append(m)
        if len(picked) == 3:
            break
    return picked


# ----------------------------------------------------------------------------------------------- deck
def _rgb(h):
    h = h.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _lum(c):
    return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255


def _mix(c, to, k):
    return RGBColor(*[int(c[i] + (to[i] - c[i]) * k) for i in range(3)])


def _readable(c, max_lum):
    """Darken a colour until white text on it (or it on white) stays readable."""
    for _ in range(12):
        if _lum(c) <= max_lum:
            break
        c = _mix(c, (0, 0, 0), 0.15)
    return c


def build(customer, industry, themes, bname, scenario, unc, M, ordered, recs, story, S, C, ctx) -> bytes:
    """ctx['brand'] = (primary hex, accent hex) restyles the deck in the customer's colours; text stays readable."""
    global NAVY, TEAL
    saved = (NAVY, TEAL)
    b = ctx.get("brand")
    if b:
        NAVY, TEAL = _readable(_rgb(b[0]), 0.35), _readable(_rgb(b[1]), 0.5)
    try:
        return _build(customer, industry, themes, bname, scenario, unc, M, ordered, recs, story, S, C, ctx)
    finally:
        NAVY, TEAL = saved


def _build(customer, industry, themes, bname, scenario, unc, M, ordered, recs, story, S, C, ctx) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.33), Inches(7.5)
    issues, log = ctx["issues"], ctx["log"]
    n_att, n_sites = int(S.attention.sum()), len(S)

    # ---- 1. Cover: title + three hero numbers in the customer's priority order
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _rect(s, 0, 0, 13.33, 7.5, NAVY, rounded=False)
    _rect(s, 0, 0, 13.33, 0.14, TEAL, rounded=False)
    _tb(s, MX, 0.9, CW, 0.9, f"{customer}", 44, True, WHITE)
    _tb(s, MX, 1.75, CW, 0.6, "Annual value review", 26, False, RGBColor(0x9F, 0xD8, 0xDE))
    _tb(s, MX, 2.45, CW, 0.4, f"{industry} · focus: {', '.join(themes[:2])} · baseline: {bname}", 14, False, RGBColor(0xC9, 0xD3, 0xDD))
    heroes = _hero_pick(ordered)
    cards = [(m.label, _val(m), _rng(m)) for m in heroes]
    cards.append(("Sites needing attention", f"{n_att} of {n_sites}", "relative to this customer's own sites"))
    cw_ = (CW - 0.3 * 3) / 4
    for i, (lab, val, ln) in enumerate(cards[:4]):
        x = MX + i * (cw_ + 0.3)
        _rect(s, x, 3.5, cw_, 2.6, _mix(NAVY, (255, 255, 255), 0.10))
        _tb(s, x + 0.2, 3.65, cw_ - 0.4, 0.7, lab, 13, False, RGBColor(0xC9, 0xD3, 0xDD))
        _tb(s, x + 0.2, 4.4, cw_ - 0.4, 0.9, val, 24, True, WHITE, anchor=MSO_ANCHOR.MIDDLE)
        _tb(s, x + 0.2, 5.4, cw_ - 0.4, 0.55, ln, 11, False, RGBColor(0x9F, 0xD8, 0xDE))
    _tb(s, MX, 6.45, CW, 0.35, "Prepared by Lindström", 13, False, RGBColor(0xC9, 0xD3, 0xDD))
    _tb(s, MX, 7.08, CW, 0.3, BANNER, 9, False, RGBColor(0xF2, 0xA9, 0x9F))
    _notes(s, f"Scenario {scenario}: {scenario_text(scenario, unc)}\nEvery figure has a Low-High range, status and formula in the appendix.")

    # ---- 2. Summary
    s = _slide(prs, "What this year looked like", f"{industry} · baseline: {bname} · scenario: {scenario}", "LOOKING BACK")
    _tb(s, MX, 1.75, CW, 2.2, _clean(story.replace("**", "")), 22, False, NAVY)
    scale = [M[k] for k in ("sites", "wearers", "kg", "repairs") if k in M]
    cw_ = (CW - 0.3 * 3) / 4
    for i, m in enumerate(scale[:4]):
        _card(s, MX + i * (cw_ + 0.3), 4.45, cw_, 1.95, m.label, _val(m), _rng(m), value_size=22)
    _notes(s, f"Scenario {scenario}: {scenario_text(scenario, unc)}")

    # ---- 3. Value delivered
    s = _slide(prs, "Value delivered", "Key results in your priority order. Savings are measured against the selected baseline", "LOOKING BACK")
    shown = ordered[:6]
    cw_, ch_ = (CW - 0.3 * 2) / 3, 2.4
    for i, m in enumerate(shown):
        x, y = MX + (i % 3) * (cw_ + 0.3), 1.75 + (i // 3) * (ch_ + 0.25)
        _card(s, x, y, cw_, ch_, m.label, _val(m), _rng(m), f"{_status(m)} · data: {m.input_status.split(';')[0].lower() or 'n/a'}", 28, m.status == "ESTIMATED")
    _notes(s, "\n".join(f"{m.label}: {m.formula}" for m in shown) + "\n\nEvery formula and assumption is in the appendix and can be challenged.")

    # ---- 4. Priority view (compact table, formulas in the appendix)
    s = _slide(prs, "All indicators, in priority order", f"Ordered by customer priority: {' > '.join(themes)}", "LOOKING BACK")
    top = ordered[:10]
    rows = [["Indicator", "Value", "Range (Low to High)", "Status"]] + [[m.label, _val(m), "exact" if m.exact else f"{_num(m.low, m.unit)} to {_num(m.high, m.unit)}", _status(m)] for m in top]
    _table(s, rows, MX, 1.7, CW, [4.6, 2.4, 3.6, 1.5], 13, 0.44, True)
    if M.missing:
        _tb(s, MX, 6.65, CW, 0.35, "Not calculated (no valid data): " + "; ".join(f"{k}" for k in M.missing)[:200], 10, False, RED)
    _notes(s, "Formulas for every indicator are in the appendix.")

    # ---- 5. Countries and sites
    s = _slide(prs, "Countries and sites", f"{n_att} of {n_sites} sites need attention (at least 2 weak signals vs this customer's own sites)", "LOOKING FORWARD")
    cd = CategoryChartData()
    cd.categories = list(C.country)
    cd.add_series("Sites", [int(v) for v in C.sites])
    cd.add_series("Sites needing attention", [int(v) for v in C.attention])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(MX), Inches(1.7), Inches(5.6), Inches(5.0), cd)
    ch = gf.chart
    ch.font.size = Pt(13)
    ch.has_legend, ch.legend.position, ch.legend.include_in_layout = True, XL_LEGEND_POSITION.BOTTOM, False
    for ser, col in zip(ch.plots[0].series, (TEAL, RED)):
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = col
    pl_ = ch.plots[0]
    pl_.has_data_labels = True
    pl_.data_labels.font.size = Pt(12)
    pl_.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    ch.value_axis.has_major_gridlines = False
    topS = S[S.attention].sort_values("n_flags", ascending=False).head(6)
    rows = [["Site", "Country", "Utilisation", "On-time", "Req / 1000"]] + [
        [r.site, r.country, f"{r.utilisation:.0f} %", f"{r.ontime:.1f} %", f"{r.requests_per_1000:.1f}"] for r in topS.itertuples()]
    if len(rows) == 1:
        rows.append(["No site stands out", "", "", "", ""])
    _table(s, rows, 6.5, 1.8, 6.2, [2.4, 1.2, 1.3, 1.1, 1.2], 12, 0.46)
    _tb(s, 6.5, 5.15, 6.2, 1.2, "Flagged against this customer's own other sites (median and MAD), not an absolute standard. "
                               "Utilisation = scanned ÷ allocated garments. Requests per 1000 = service requests per 1000 garments.", 11, False, GREY)
    _notes(s, f"By country: {C[['country', 'sites', 'attention']].to_dict('records')}")

    # ---- 6. Garment control (RFID scans): the look-forward example from the brief
    st = ctx.get("stale") or {}
    if st:
        s = _slide(prs, "Garment control from RFID scans", "Based on RFID scan data: last completed delivery per garment", "LOOKING FORWARD")
        _rect(s, MX, 1.75, 4.4, 4.6, LIGHT)
        _tb(s, MX + 0.25, 1.95, 3.9, 0.4, f"Not delivered in over {st['days']} days", 14, False, GREY)
        _tb(s, MX + 0.25, 2.45, 3.9, 1.1, f"{st['stale']:,}".replace(",", " "), 54, True, TEAL)
        _tb(s, MX + 0.25, 3.55, 3.9, 0.5, f"garments ({st['share']:.0f} % of the {st['assets']:,} in the scan data)".replace(",", " "), 14, False, NAVY)
        _tb(s, MX + 0.25, 4.45, 3.9, 0.4, f"Median days since last delivery: {st['median_age']:.0f}", 13, False, GREY)
        _tb(s, MX + 0.25, 4.85, 3.9, 0.4, f"90th percentile: {st['p90_age']:.0f} days", 13, False, GREY)
        _tb(s, MX + 0.25, 5.45, 3.9, 0.7, f"As of {st['end']}. Threshold is illustrative: the customer defines what is acceptable.", 11, False, GREY)
        rows = [["Sites with most flagged garments", "Garments"]] + [[n, str(k)] for n, k in st.get("top_sites", [])]
        _table(s, rows, 5.4, 1.75, 7.3, [5.5, 1.8], 13, 0.46)
        t2 = _tb(s, 5.4, 3.9, 7.3, 2.4, "Why this matters", 16, True, NAVY)
        _add_p(t2, "A garment that has not been washed for a long time can be a hygiene risk, especially in the food industry.", 14, GREY, False, 8)
        _add_p(t2, "A long gap can also mean allocated garments that are not in use (allocation too high) or lost: both are worth a question. This is a signal to investigate, not a conclusion.", 14, GREY, False, 8)
        _add_p(t2, "Proposed next step: agree a garment-control threshold together, then follow it every month.", 14, NAVY, True, 8)
        _notes(s, "Scan gaps are a signal, not proof: the data counts garments by their last completed delivery. Aggregated to site and group level; no individual wearers are shown (GDPR).")

    # ---- 7. Discussion points (title + one line; basis in notes)
    s = _slide(prs, "Suggested discussion points", "Generated from the calculated figures", "LOOKING FORWARD")
    y, notes = 1.7, []
    for i, r in enumerate(recs[:4], 1):
        _tb(s, MX, y, 0.7, 0.8, str(i), 34, True, TEAL)
        tf = _tb(s, MX + 0.8, y + 0.02, CW - 0.8, 1.2, r["title"], 19, True)
        _add_p(tf, _short(r["text"], 170), 14, GREY, False, 3)
        notes.append(f"{i}. {r['title']}\n{r['text']}\nBasis: {r['basis']}")
        y += 1.22
    _notes(s, "\n\n".join(notes))

    # ---- 8. Topics to explore together
    tp = ctx.get("topics") or []
    if tp:
        s = _slide(prs, "Topics to explore together", "Hypotheses from your own data, to confirm with you. Not commitments or savings claims", "LOOKING FORWARD")
        y, notes = 1.7, []
        for i, c in enumerate(tp[:4], 1):
            _tb(s, MX, y, 0.7, 0.8, str(i), 34, True, TEAL)
            tf = _tb(s, MX + 0.8, y + 0.02, CW - 0.8, 1.2, c["title"], 19, True)
            _add_p(tf, _short(c["hypothesis"], 170), 14, GREY, False, 3)
            _add_p(tf, "What we see: " + _short(" ".join(c["evidence_customer"]), 140), 12, NAVY, False, 3)
            notes.append(f"{i}. {c['title']}\n{c['hypothesis']}\nStatus: {c['status'].title()}. To confirm: " + "; ".join(c["confirm"]))
            y += 1.22
        _notes(s, "\n\n".join(notes))

    # ---- 9. Agreed actions
    acts = ctx.get("actions")
    if acts is not None:
        s = _slide(prs, "Agreed actions and next steps", "Priorities, owners and dates agreed in this meeting", "NEXT YEAR")
        blank = "________"
        rows = [["#", "Action", "Lindström owner", "Customer owner", "Target date", "Status"]] + [
            [str(i), str(a.get("action", ""))[:80], str(a.get("lindstrom_owner") or blank)[:28], str(a.get("customer_owner") or blank)[:28],
             str(a.get("target_date") or blank)[:16], str(a.get("status") or "Proposed")] for i, a in enumerate(acts[:6], 1) if str(a.get("action", "")).strip()]
        if len(rows) == 1:
            rows.append(["1", blank, blank, blank, blank, "Proposed"])
        _table(s, rows, MX, 1.7, CW, [0.5, 5.6, 2.0, 2.0, 1.5, 1.3], 13, 0.62)
        _tb(s, MX, 6.35, CW, 0.6, "Next review: ________   ·   Data to add before then: customer-specific baseline (litres/kWh per kg), agreed hygiene threshold.", 12, False, GREY)

    # ---- Appendix divider
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _rect(s, 0, 0, 13.33, 7.5, NAVY, rounded=False)
    _rect(s, 0, 0, 13.33, 0.14, TEAL, rounded=False)
    _tb(s, MX, 2.8, CW, 1.0, "Appendix", 44, True, WHITE)
    _tb(s, MX, 3.8, CW, 1.0, "How every number is calculated, what we assumed, which data we used and what is missing for production.", 18, False, RGBColor(0xC9, 0xD3, 0xDD))
    _tb(s, MX, 7.08, CW, 0.3, BANNER, 9, False, RGBColor(0xF2, 0xA9, 0x9F))

    # ---- A1. Formulas
    s = _slide(prs, "Formulas behind the indicators", "Every figure is plain arithmetic on the data; no figure comes from a language model", "APPENDIX")
    rows = [["Indicator", "Formula"]] + [[m.label[:46], m.formula[:150]] for m in ordered[:10]]
    _table(s, rows, MX, 1.7, CW, [3.6, 8.5], 10.5, 0.46, True)

    # ---- A2. Method and assumptions
    s = _slide(prs, "Method, assumptions and limitations", "Everything here can be challenged and changed in the dashboard", "APPENDIX")
    rows = [["Assumption", "Value / rule", "Confidence"]]
    A = ctx.get("assumptions")
    if A is not None and len(A):
        rows += [[a.assumption[:44], str(a.value_or_rule)[:90], a.confidence] for a in A.itertuples()][:5]
    fmtd = dict(baseline_pct=unc.baseline_pct, allocation_pct=unc.allocation_pct, repair_low=unc.repair_low, repair_high=unc.repair_high, **THRESH)
    rows += [[f"{a[0]} {a[1]}"[:44], a[2].format(**fmtd)[:90], a[4]] for a in APP_ASSUMPTIONS[:5]]
    _table(s, rows, MX, 1.7, CW, [3.6, 7.0, 1.5], 10.5, 0.4)
    _tb(s, MX, 6.2, CW, 0.8, f"Baseline: {bname}. {scenario_text(scenario, unc)} Sites are flagged relative to this customer's own other sites (median and MAD).", 11, False, GREY)

    # ---- A3. Data used and validation
    s = _slide(prs, "Data used and validation", f"{len(ctx['mapping_df'])} sheets read, {int(ctx['mapping_df'].used.sum())} used · {int((issues.severity == 'ERROR').sum())} errors, {int((issues.severity == 'WARNING').sum())} warnings, {int((issues.severity == 'INFO').sum())} notes · {len(log)} rows excluded", "APPENDIX")
    md = ctx["mapping_df"]
    rows = [["Sheet", "Mapped to", "Rows"]] + [[r.sheet[:30], r.maps_to, r.rows] for r in md[md.used].itertuples()][:10]
    _table(s, rows, MX, 1.7, 5.4, [2.6, 1.9, 0.9], 10.5, 0.4)
    topi = issues[issues.severity.isin(["ERROR", "WARNING"])].head(7)
    rows = [["Severity", "Issue", "Where", "Action"]] + [[r.severity.title(), r.check[:34], (r.scope or r.location)[:30], ("excluded" if (r.default_action == "exclude" and r.id in ctx["excluded_ids"]) else "kept, flagged")] for r in topi.itertuples()]
    _table(s, rows, 6.3, 1.7, 6.4, [1.0, 2.6, 1.7, 1.2], 10.5, 0.42)
    if len(log):
        g = log.groupby(["table", "reason"]).size().reset_index(name="n").head(4)
        _tb(s, MX, 6.3, CW, 0.7, "Excluded from the calculation: " + "; ".join(f"{r.n} {r.table} row(s) ({r.reason})" for r in g.itertuples()), 11, False, RED)
    else:
        _tb(s, MX, 6.3, CW, 0.7, "No rows were excluded. Issues marked 'kept, flagged' stay visible next to the numbers they may affect.", 11, False, GREY)

    # ---- A4. Data readiness
    s = _slide(prs, "Data readiness for production", "What was provided, what is missing, and the approved source that would replace it", "APPENDIX")
    rd = ctx["readiness"]
    rows = [["Internal table", "Provided", "Missing fields", "Future Lindström source"]] + [
        [r.table, r.provided, r.missing[:60], r.future_source[:110]] for r in rd.itertuples() if r.table not in ("Reference totals (control totals)", "Industry priorities", "Assumption registry")][:10]
    _table(s, rows, MX, 1.7, CW, [2.8, 1.0, 3.0, 5.3], 10.5, 0.44)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
