"""KAM-level views: portfolio across customers and sites, how they relate, evidence-backed opportunities,
the 'be ready to be challenged' panel and trends. Pure deterministic pandas; every figure comes from metrics.py
or an exact aggregation shown with its basis."""
from __future__ import annotations
import re
import numpy as np
import pandas as pd
import metrics as mt
from assumptions import Uncertainty


def customers(T) -> pd.DataFrame:
    S = T["sites"]
    ids = sorted(S.customer_id.dropna().unique())
    C = T.get("customers")
    rows = []
    for c in ids:
        r = C[C.customer_id == c].iloc[0] if C is not None and len(C[C.customer_id == c]) else None
        g = lambda f, d="": (r[f] if r is not None and f in r and pd.notna(r[f]) else d)
        rows.append(dict(customer_id=c, customer=g("customer_name", c), industry=g("industry"), segment=g("segment"), topics=g("priority_topics")))
    return pd.DataFrame(rows)


def repair_intensity(T) -> pd.DataFrame:
    """Repairs per allocated garment per year, by customer and product (allocated = mean monthly allocation)."""
    A, R, P = T.get("service_activity"), T.get("repairs"), T.get("products")
    if A is None or R is None or A.empty or R.empty or "allocated_pieces" not in A or not A.allocated_pieces.notna().any():
        return pd.DataFrame(columns=["customer_id", "product_id", "product", "repairs", "pieces", "per_piece"])
    pieces = A.groupby(["customer_id", "product_id", "month"]).allocated_pieces.sum().groupby(["customer_id", "product_id"]).mean().rename("pieces")
    rep = R.groupby(["customer_id", "product_id"]).repair_count.sum().rename("repairs")
    d = pd.concat([rep, pieces], axis=1).dropna().reset_index()
    d["per_piece"] = d.repairs / d.pieces
    nm = P.set_index("product_id").product_name if P is not None and not P.empty and "product_name" in P else None
    d["product"] = d.product_id.map(nm) if nm is not None else d.product_id
    return d


def portfolio(T, baseline=None, scenario="Base", unc: Uncertainty = Uncertainty()):
    """-> (customer rows, all sites). One row per customer, one row per site with its customer."""
    cu = customers(T)
    rows, sites = [], []
    for r in cu.itertuples():
        M = mt.metrics(T, r.customer_id, baseline, scenario, unc)
        St = mt.site_table(T, r.customer_id, baseline, scenario, unc)
        St = St.assign(customer_id=r.customer_id, customer=r.customer, industry=r.industry)
        sites.append(St)
        g = lambda k: M[k].value if k in M else np.nan
        rows.append(dict(customer_id=r.customer_id, customer=r.customer, industry=r.industry, segment=r.segment,
                         sites=len(St), countries=", ".join(sorted(St.country.dropna().unique())), kg=g("kg"),
                         utilisation=g("utilisation"), ontime=g("ontime"),
                         requests_per_1000=1000 * g("requests") / g("pieces") if "requests" in M and "pieces" in M else np.nan,
                         repairs_per_100=100 * g("repairs") / g("pieces") if "repairs" in M and "pieces" in M else np.nan,
                         sites_attention=int(St.attention.sum()),
                         water_saving=g("water_saving"), water_low=M["water_saving"].low if "water_saving" in M else np.nan,
                         water_high=M["water_saving"].high if "water_saving" in M else np.nan, co2_saving=g("co2_service")))
    P = pd.DataFrame(rows)
    if len(P):
        P["share_of_portfolio_kg"] = 100 * P.kg / P.kg.sum()
    return P, (pd.concat(sites, ignore_index=True) if sites else pd.DataFrame())


def flows(T) -> pd.DataFrame:
    """customer -> site country -> laundry, by washed kg (how the portfolio relates through shared laundries)."""
    A, S, Lc = T["service_activity"], T["sites"], T.get("laundries")
    cu = customers(T).set_index("customer_id").customer
    a = A.merge(S[["site_id", "country"]].drop_duplicates("site_id"), on="site_id", how="left")
    lname = Lc.set_index("laundry_id").laundry_name if Lc is not None and not Lc.empty and "laundry_name" in Lc else {}
    g = a.groupby(["customer_id", "country", "laundry_id"], dropna=False).customer_washed_kg.sum().reset_index()
    g["customer"] = g.customer_id.map(cu)
    g["laundry"] = g.laundry_id.map(lambda x: lname.get(x, x) if hasattr(lname, "get") else x)
    g["country"] = g.country.fillna("n/a")
    return g


def monthly(T, cid) -> pd.DataFrame:
    A = T["service_activity"]
    A = A[A.customer_id == cid]
    m = A.groupby("month").agg(kg=("customer_washed_kg", "sum"), requests=("service_requests", "sum"),
                               scanned=("active_assets_scanned", "sum"), allocated=("allocated_pieces", "sum")).reset_index()
    m["utilisation"] = 100 * m.scanned / m.allocated.replace(0, np.nan)
    R = T.get("repairs")
    if R is not None and not R.empty:
        r = R[R.customer_id == cid].groupby("month").repair_count.sum().rename("repairs")
        m = m.merge(r, on="month", how="left")
    return m


def stale_assets(T, cid, days: int) -> dict:
    """RFID view: assets whose last completed delivery is more than `days` before the end of the data (exact count, editable threshold)."""
    C = T.get("service_cycles")
    if C is None or C.empty or "delivered_timestamp" not in C or not C.delivered_timestamp.notna().any():
        return {}
    c = C[C.customer_id == cid]
    end = C.delivered_timestamp.max()
    last = c.groupby(["asset_id", "site_id"]).delivered_timestamp.max().reset_index()
    last["age"] = (end - last.delivered_timestamp).dt.days
    old = last[last.age > days]
    S = T["sites"].drop_duplicates("site_id").set_index("site_id").site_name
    by_site = old.groupby("site_id").size().sort_values(ascending=False).head(3)
    return dict(days=days, assets=len(last), stale=len(old), share=100 * len(old) / max(len(last), 1), end=str(end.date()),
                median_age=float(last.age.median()), p90_age=float(last.age.quantile(0.9)),
                top_sites=[(S.get(s, s), int(n)) for s, n in by_site.items()])


# =============================================================================== opportunities
def _n(x) -> str:
    return f"{x:,.0f}".replace(",", "\u00a0")


def _topics(text) -> list[str]:
    return [t.strip().lower() for t in re.split(r"[|;,]", str(text)) if t.strip()]


def opportunities(T, cid, M, St, RI: pd.DataFrame, unc: Uncertainty = Uncertainty(), stale_days: int = 90) -> list[dict]:
    """Evidence-backed discussion hypotheses for the yearly meeting. Not sales claims: each one states evidence,
    sizing in units (never invented revenue), assumptions, what to confirm with the customer and data caveats.
    `evidence_customer` uses this customer's own data only and is safe to put in their deck."""
    cu = customers(T).set_index("customer_id").loc[cid]
    topics = _topics(cu.topics)
    cards = []

    def add(**k):
        k.setdefault("caveat", ""); k.setdefault("evidence_internal", k["evidence_customer"]); cards.append(k)

    # --- A: right-size garment allocation
    if "utilisation" in M and "pieces" in M and St.utilisation.notna().any():
        idle = (St.pieces * (1 - St.utilisation / 100)).sum()
        low = St.dropna(subset=["utilisation"]).sort_values("utilisation").head(3)
        share_top3 = 100 * (low.pieces * (1 - low.utilisation / 100)).sum() / idle if idle else 0
        add(id="allocation", theme="cost", title="Review garment allocation per site",
            hypothesis="Some allocated garments are not in active use. A site-by-site review could match allocation to real use and improve garment control.",
            evidence_customer=[f"Garment utilisation {M['utilisation'].fmt()} (scanned ÷ allocated, last month).",
                               f"About {_n(idle)} of {_n(M['pieces'].value)} allocated garments were not scanned; the 3 lowest sites ({', '.join(low.site)}) hold {share_top3:.0f} % of them."],
            sizing=f"≈ {_n(idle)} garments not scanned in the last month ({100*idle/M['pieces'].value:.0f} % of allocation); a buffer stock is normal, its size is the customer's to define.",
            assumptions=["Scanned = in use during the month.", "Seasonality and buffer policy are not in the data."],
            confirm=["What buffer level does each site need?", "Are there seasonal or shift-based peaks?"],
            status="CALCULATED", fit=[t for t in topics if any(k in t for k in ("util", "garment", "cost", "alloc"))],
            caveat="A smaller allocation can reduce rental volume. Frame it as retention and trust, not as a sales lever.")
    # --- B: service continuity at flagged sites
    att = St[St.attention]
    if len(att):
        top = att.sort_values(["extreme", "n_flags", "requests_per_1000"], ascending=False).head(4)
        med = St.requests_per_1000.median()
        ev = [f"{len(att)} of {len(St)} sites stand out against this customer's other sites: " + "; ".join(
            f"{r.site} (requests {r.requests_per_1000:.0f} per 1000 vs median {med:.0f}; on-time {r.ontime:.1f} %)" for r in top.itertuples()) + "."]
        add(id="continuity", theme="service", title="Agree a service-continuity plan for the sites that stand out",
            hypothesis="A few sites show more service requests or weaker on-time delivery than the rest. A joint root-cause review could improve reliability where it matters most.",
            evidence_customer=ev, sizing=f"{len(att)} site(s); {int(att.requests.sum())} service requests at these sites in the period.",
            assumptions=["Flag = robust outlier vs this customer's own sites with a minimum effect size; a signal, not a diagnosis."],
            confirm=["What happened at these sites (contacts, layout, delivery windows)?", "Are the requests about the same cause?"],
            status="CALCULATED", fit=[t for t in topics if any(k in t for k in ("service", "continuity", "reliab"))])
    # --- C: hygiene / traceability evidence (RFID)
    sa = stale_assets(T, cid, stale_days)
    if sa and (cu.industry in ("Food & Beverage", "Healthcare") or any(k in " ".join(topics) for k in ("hygiene", "traceab", "compliance"))):
        add(id="traceability", theme="service", title="Set a hygiene-control threshold using garment scan data",
            hypothesis="Scan data can show garments that have not been through the wash cycle for a long time. With a threshold agreed per customer, this becomes a garment-control routine.",
            evidence_customer=[f"{sa['assets']} garments with scans; median time since last delivery {sa['median_age']:.0f} days (90th percentile {sa['p90_age']:.0f}).",
                               f"At a {sa['days']}-day threshold, {sa['stale']} garments ({sa['share']:.0f} %) would be flagged as of {sa['end']}."],
            sizing=f"{sa['stale']} garments at {sa['days']} days (threshold editable); top sites: " + ", ".join(f"{n} ({k})" for n, k in sa["top_sites"]),
            assumptions=[f"The {sa['days']}-day threshold is illustrative; the customer defines what is acceptable.", "Sample cycles are sparse (3-8 per garment per year), so results are indicative."],
            confirm=["Which threshold fits your hygiene plan?", "Who acts on a flag, and how fast?"],
            status="CALCULATED", fit=[t for t in topics if any(k in t for k in ("hygiene", "traceab", "compliance"))],
            caveat="RFID is per garment; shown at site/group level only, never named wearers (GDPR).")
    # --- D: water / baseline verification
    if "water_saving" in M and "water_per_kg" in M:
        add(id="baseline", theme="water", title="Agree the right comparison baseline and make the resource story reportable",
            hypothesis="The water and energy saving depends heavily on what the customer would otherwise use. Agreeing the baseline turns an estimate into evidence the customer can use in its own reporting.",
            evidence_customer=[f"Allocated water use {M['water_per_kg'].fmt()} vs baseline; saving {M['water_saving'].fmt()} (range {M['water_saving'].fmt_range()}).",
                               f"The saving holds for any alternative that uses more than {M['water_per_kg'].value:.1f} L/kg."],
            sizing=f"{M['water_saving'].fmt()} of water and {M['energy_saving'].fmt() if 'energy_saving' in M else 'n/a'} of energy versus the selected baseline.",
            assumptions=["Baseline intensities are illustrative pack values.", "Laundry use is allocated by washed kg."],
            confirm=["What would you use otherwise: local laundry, in-house, home washing?", "Do you have your own litres/kg or kWh/kg?"],
            status="ALLOCATED", fit=[t for t in topics if any(k in t for k in ("water", "resource", "efficien"))])
    # --- E: Scope 3 evidence
    if "co2_service" in M:
        add(id="scope3", theme="emissions", title="Provide Scope 3 evidence the customer can use",
            hypothesis="Customers increasingly ask for customer-specific footprint evidence. An agreed method and data status would let them use these figures in reporting.",
            evidence_customer=[f"Service emissions {M['co2_service'].fmt()} lower than the selected baseline (range {M['co2_service'].fmt_range()})."
                               + (f" Avoided product emissions through repair: {M['avoided_co2'].fmt()} (estimate)." if "avoided_co2" in M else "")],
            sizing=f"{M['co2_service'].fmt()} service emissions saving (allocated estimate).",
            assumptions=["Synthetic factors and allocation by washed kg.", "Repair handprint assumes 1 repair postpones 1 replacement (upper bound)."],
            confirm=["Which reporting framework do you use?", "What data status do you need (measured vs allocated)?"],
            status="ALLOCATED", fit=[t for t in topics if any(k in t for k in ("scope", "emission", "carbon", "co2"))],
            caveat="Not usable as an audited figure until approved factors and measured allocation replace the synthetic data.")
    # --- F: repair & durability (own products; peers only internal)
    own = RI[RI.customer_id == cid].sort_values("per_piece", ascending=False) if len(RI) else RI
    if len(own) and "repairs" in M:
        top = own.iloc[0]
        peers = RI[(RI.product_id == top.product_id) & (RI.customer_id != cid)]
        cust_ev = [f"{M['repairs'].fmt()} completed. Highest repair rate: {top['product']} at {top.per_piece:.2f} repairs per allocated garment per year (all products: {own.repairs.sum()/own.pieces.sum():.2f})."]
        internal = list(cust_ev)
        if len(peers):
            internal.append(f"Internal benchmark (do not share): same product at your other accounts: {', '.join(f'{p:.2f}' for p in peers.per_piece)}.")
        add(id="repair", theme="circularity", title="Review repair-heavy products for durability",
            hypothesis="Products with a high repair rate may benefit from a durability or fit review, which reduces repairs and extends garment life.",
            evidence_customer=cust_ev, evidence_internal=internal,
            sizing=f"{int(own.iloc[0].repairs)} repairs on {top['product']}; {_n(M['postponed'].value)} replacements postponed at the selected assumption (range {_n(M['postponed'].low)} to {_n(M['postponed'].high)}).",
            assumptions=["1 repair postpones 1 replacement is an upper bound (Low case 0.5).", "Repair rate = repairs ÷ mean allocated garments."],
            confirm=["Do wearers report fit or wear problems with this product?", "Is the damage type consistent (button, zip, seam)?"],
            status="ESTIMATED", fit=[t for t in topics if any(k in t for k in ("repair", "circular", "safety"))],
            caveat="Rates across products are similar in the sample data; treat as a prompt for discussion, not a finding.")
    for c in cards:
        c["fit_score"] = len(c["fit"])
    return sorted(cards, key=lambda c: (-c["fit_score"], c["id"]))


# =============================================================================== challenge-ready
def challenges(T, M, cid, bsel, unc: Uncertainty = Uncertainty(), issues: pd.DataFrame | None = None) -> list[dict]:
    """The questions a customer's finance or sustainability person is most likely to ask, with the exact number,
    the break-even, and what would change the result. For the KAM's eyes."""
    out = []
    B = T.get("baselines")
    if B is not None and not B.empty and "water_saving" in M:
        rows = []
        for b in B.itertuples():
            Mb = mt.metrics(T, cid, b.baseline_id, "Base", unc)
            if "water_saving" in Mb:
                rows.append((mt.baseline_name(T, b.baseline_id), b.water_l_per_kg, Mb["water_saving"].value, Mb["energy_saving"].value if "energy_saving" in Mb else np.nan))
        out.append(dict(q="Is the comparison baseline fair for us?", number=f"Water saved {M['water_saving'].fmt()} vs {M.baseline_name}",
                        table=pd.DataFrame(rows, columns=["baseline", "baseline L/kg", "water saved (L)", "energy saved (kWh)"]).round(0),
                        answer=f"The saving is positive for any alternative above {M['water_per_kg'].value:.1f} L/kg (our allocated intensity). The three baselines in the data give the range shown. Ask which alternative the customer really uses.",
                        changes="A customer-specific baseline (their own litres/kg) replaces the illustrative one."))
    if "avoided_cost" in M:
        g = M["avoided_cost"].inputs.get("gross_EUR", np.nan)
        out.append(dict(q="Do repairs really avoid purchases?", number=f"{M['avoided_cost'].fmt()} at the selected assumption",
                        table=pd.DataFrame({"share of repairs that prevent a purchase": ["25 %", "50 %", "100 % (upper bound)"], "purchases avoided (EUR)": [round(g * .25), round(g * .5), round(g)]}),
                        answer="Only the direct purchase is counted (no labour, lifetime or residual value). The 1:1 rule is an upper bound: not every repaired garment would otherwise have been replaced. Lead with the repair count, not the euro figure.",
                        changes="Evidence on how often a repair actually replaces a purchase; real replacement cost per product."))
    if "water_saving" in M:
        out.append(dict(q="Is the allocation of laundry resources to us fair?", number=f"Allocation ±{unc.allocation_pct:.0%} moves the saving between {M['water_saving'].fmt_range()} (with the baseline sensitivity)",
                        answer="Laundry water, energy and waste are shared out by washed kg because the data is laundry-level. It is an estimate, disclosed on every affected number.",
                        changes="Customer-level metering or an agreed allocation key."))
    if "wearers" in M:
        out.append(dict(q="How many people wear these garments?", number=M["wearers"].fmt(),
                        answer="Wearers are summed across product rows, so a person with two products is counted twice, and garments are often shared. Use garments and washed kg as the scale measures.",
                        changes="An agreed wearer definition (and, if needed, a deduplicated count at group level)."))
    if issues is not None and len(issues):
        keep = issues[issues.severity.isin(["ERROR", "WARNING"])]
        if len(keep):
            out.append(dict(q="How good is the data behind this?", number=f"{(keep.severity=='ERROR').sum()} error(s), {(keep.severity=='WARNING').sum()} warning(s) in the validation report",
                            answer="; ".join(keep.check.drop_duplicates().head(4)) + ". All are listed in the Validation tab and in the deck.",
                            changes="Fixes at source; approved status labels on every sheet."))
    return out


def issues_for_customer(I: pd.DataFrame, T, cid) -> pd.DataFrame:
    """Drop issues that mention another customer's sites, names or ids, so a customer deck never shows other accounts."""
    S, cu = T["sites"], customers(T)
    other_c = cu[cu.customer_id != cid]
    tokens = set(S[S.customer_id != cid].site_id.dropna()) | set(S[S.customer_id != cid].site_name.dropna()) | set(other_c.customer_id) | set(other_c.customer)
    tokens = {t for t in tokens if t and len(str(t)) > 2}

    def clean(r):
        txt = f"{r.location} {r.scope} {r.explanation}"
        return not any(re.search(r"(?<![A-Za-z0-9])" + re.escape(str(t)) + r"(?![A-Za-z0-9])", txt) for t in tokens)
    return I[I.apply(clean, axis=1)].reset_index(drop=True)
