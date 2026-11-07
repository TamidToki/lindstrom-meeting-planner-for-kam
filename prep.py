"""Meeting preparation: who is the customer, what matters to them (CRM + public information), who is in the room.

Rules, not magic: the priority order is a transparent score. Every theme lists the reasons that moved it, and the key
account manager can override the result. Public information is optional, always carries a source, and is never used in a
calculation: it only steers emphasis and suggests deck colours. No number in the app comes from this module."""
from __future__ import annotations
import json
import os
import re
import story as sy

THEME_LABEL = {"service": "Service & delivery", "water": "Water & energy", "cost": "Cost & utilisation",
               "emissions": "Emissions & Scope 3", "circularity": "Circularity & repairs"}

# who is in the room -> what they usually care about (themes, strongest first)
ROLES = {
    "Quality / health & safety": ["service"],
    "Procurement": ["cost"],
    "Finance": ["cost"],
    "Operations / site management": ["service", "cost"],
    "Sustainability / ESG": ["emissions", "water", "circularity"],
    "Management / board": ["cost", "emissions"],
}
W_CRM, W_ATT, W_PUB, W_IND = 3.0, 2.0, 1.0, 1.0


def rank_themes(industry_order: list[str], crm_text: str, public_points: list[dict], attendees: list[str]):
    """Return (ordered themes, {theme: [reasons]}). Score = CRM priorities x3 + attendees x2 + public info x1 + industry lens x1."""
    score = {t: 0.0 for t in sy.THEMES}
    why = {t: [] for t in sy.THEMES}
    seen = []
    parts = []
    for line in (crm_text or "").splitlines():
        if ":" in line:                      # "Industry: ..." / "Sites: ..." are facts, not priorities
            label, rest = line.split(":", 1)
            if label.lower().strip().startswith(("priorit", "important", "focus", "topic", "cares", "key")):
                parts += re.split(r"[|;,]", rest)
        else:                                # free notes pasted from the CRM
            parts += re.split(r"[|;,]", line)
    for part in parts:
        th = sy._theme_of(part)
        if th and th not in seen:
            seen.append(th)
    for i, th in enumerate(seen):
        score[th] += W_CRM - 0.2 * i
        why[th].append("named as a priority in the CRM notes")
    for r in attendees:
        for i, th in enumerate(ROLES.get(r, [])):
            score[th] += W_ATT - 0.4 * i
            why[th].append(f"matters to {r.split(' / ')[0].lower()} in the meeting")
    for p in public_points:
        if p.get("include", True) and p.get("theme") in score:
            score[p["theme"]] += W_PUB
            why[p["theme"]].append("their public information points to it")
    for i, th in enumerate(industry_order):
        if th in score:
            score[th] += W_IND - 0.25 * i
            if i == 0:
                why[th].append("usual first priority in this industry")
    order = sorted(score, key=lambda t: -score[t])
    return order, why


# ----------------------------------------------------------------------------------------------- public information
SAMPLE = {
    "Food & Beverage": [
        dict(include=True, text="Publishes a food-safety and hygiene programme across its plants", theme="service"),
        dict(include=True, text="Has a stated water-reduction target for its production sites", theme="water"),
        dict(include=True, text="Asks suppliers for Scope 3 emission data", theme="emissions"),
    ],
    "Manufacturing": [
        dict(include=True, text="Running a cost-efficiency programme across its factories", theme="cost"),
        dict(include=True, text="Reports on circular-economy and repair initiatives", theme="circularity"),
        dict(include=True, text="Safety record is part of its annual report", theme="service"),
    ],
    "Healthcare": [
        dict(include=True, text="Hospitals follow strict infection-control and textile-hygiene rules", theme="service"),
        dict(include=True, text="Needs traceable, auditable service records", theme="service"),
        dict(include=True, text="Has a public sustainability roadmap", theme="emissions"),
    ],
}
SAMPLE_BRAND = {"Food & Beverage": ("#1F5F3A", "#E2A400"), "Manufacturing": ("#1B3A6B", "#D9531E"), "Healthcare": ("#0B5E7E", "#6CB33F")}


def sample_brief(industry: str):
    pts = [dict(p, source="sample text, not real public information") for p in SAMPLE.get(industry, SAMPLE["Manufacturing"])]
    return pts, SAMPLE_BRAND.get(industry, ("#0B2A4A", "#007A87"))


def _hex_ok(v):
    return isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v.strip() or "") is not None


def public_brief(company: str, industry: str, country: str = ""):
    """Return (points, (primary, accent) or None, mode). Live web search needs ANTHROPIC_API_KEY; anything that fails falls back to
    a clearly labelled sample. Points without a source URL are discarded."""
    import providers
    cfg = providers.current()
    if cfg is None:
        pts, br = sample_brief(industry)
        return pts, br, "sample: no model configured"
    if cfg.provider != "anthropic":
        pts, br = sample_brief(industry)
        return pts, br, "sample: live web lookup needs an Anthropic key (other providers have no built-in web search here)"
    try:
        import anthropic
        prompt = (f"Search the public web for the company '{company}' ({industry}{', ' + country if country else ''}). "
                  f"Find up to 5 short facts that show what matters to this company when buying workwear and textile services "
                  f"(for example food safety and hygiene, water or emission targets, cost programmes, repair and circularity goals, sustainability reporting). "
                  f"Also find its main brand colour and an accent colour if clearly visible. "
                  f"Reply with JSON only: {{\"points\":[{{\"text\":\"...\",\"theme\":\"one of {list(sy.THEMES)}\",\"url\":\"https://...\"}}],"
                  f"\"brand\":{{\"primary\":\"#RRGGBB\",\"accent\":\"#RRGGBB\"}}}}. Use only what you found; every point needs the source URL. "
                  f"If you cannot identify the company, return an empty points list. Do not invent facts or numbers.")
        r = anthropic.Anthropic(api_key=cfg.api_key).messages.create(
            model=cfg.model, max_tokens=1500,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
            messages=[{"role": "user", "content": prompt}])
        txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        data = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        pts = [dict(include=True, text=str(p["text"])[:200], theme=p.get("theme") if p.get("theme") in sy.THEMES else "", source=str(p["url"]))
               for p in data.get("points", []) if str(p.get("url", "")).startswith("http") and p.get("text")]
        b = data.get("brand") or {}
        brand = (b["primary"], b["accent"]) if _hex_ok(b.get("primary")) and _hex_ok(b.get("accent")) else None
        if not pts:
            raise ValueError("no sourced points")
        return pts, brand, "live: web search"
    except Exception as e:
        pts, br = sample_brief(industry)
        return pts, br, f"sample: live lookup failed ({type(e).__name__})"
