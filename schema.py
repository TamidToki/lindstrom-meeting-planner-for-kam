"""Internal data model: the tables and fields the app understands, with the aliases used by
auto-mapping, expected units/limits used by validation, and the status-label vocabulary.
Canonical field names follow the hackathon data pack so the sample pack maps 1:1."""
from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    name: str
    kind: str                 # id | text | num | month | ts | status
    aliases: tuple = ()
    required: bool = False
    dim: str | None = None    # kg l kwh co2 eur h pct frac count l_per_kg kwh_per_kg
    nonneg: bool = True
    hi: float | None = None   # upper plausibility limit (None = no limit)
    feeds: str = ""           # what is lost if the field is missing


def F(name, kind, aliases=(), req=False, dim=None, hi=None, feeds="", nonneg=True):
    return Field(name, kind, tuple(aliases), req, dim, nonneg, hi, feeds)


@dataclass(frozen=True)
class Table:
    name: str
    label: str
    sheet_aliases: tuple
    fields: tuple
    key: tuple = ()           # duplicate-detection key
    required_for_run: bool = False
    future_source: str = ""   # data-readiness note

    def f(self, name):
        return next(x for x in self.fields if x.name == name)

    @property
    def names(self):
        return [x.name for x in self.fields]


STATUS = F("data_status", "status", ("status", "data status", "value status", "data label", "label", "provenance"))

TABLES: dict[str, Table] = {t.name: t for t in [
    Table("customers", "Customers", ("customers", "customer", "accounts", "customer master", "clients", "account top level"), (
        F("customer_id", "id", ("customer", "account", "account top level", "account id", "client id", "customer number", "cust id", "customer code"), True),
        F("customer_name", "text", ("name", "account name", "client", "customer", "customer name")),
        F("industry", "text", ("sector", "industry segment", "branch", "industry type"), feeds="industry-aware priorities"),
        F("segment", "text", ("customer segment", "tier")), F("hq_country", "text", ("headquarters country", "hq", "country")),
        F("priority_topics", "text", ("priorities", "topics", "priority")), STATUS),
        ("customer_id",), False, "Customer master data / CRM (account top level hierarchy)"),
    Table("sites", "Sites", ("sites", "site", "delivery sites", "site master", "locations", "delivery customers"), (
        F("site_id", "id", ("site", "delivery site", "delivery site id", "delivery customer", "location id", "site code", "site number", "site no"), True),
        F("customer_id", "id", ("customer", "account", "account top level", "account id", "client id", "customer number", "customer code"), True),
        F("site_name", "text", ("name", "delivery site name", "location", "site", "delivery customer name")),
        F("country", "text", ("site country",)), F("city", "text", ("town",)), F("site_type", "text", ("type", "site category")),
        F("primary_laundry_id", "id", ("laundry", "laundry id", "wws", "primary laundry", "plant id")), STATUS),
        ("site_id",), True, "Customer master data: delivery customer to account top-level mapping"),
    Table("products", "Products", ("products", "product", "articles", "product master", "items"), (
        F("product_id", "id", ("product", "product code", "article", "item code", "sku", "article number"), True),
        F("product_name", "text", ("name", "article name", "description")),
        F("product_group", "text", ("category", "group", "product category")),
        F("avg_weight_kg", "num", ("weight", "avg weight", "weight kg", "average weight", "unit weight"), dim="kg", feeds="kg per piece sanity check"),
        F("product_footprint_kgco2e", "num", ("footprint", "synthetic_product_footprint_kgco2e", "product co2e", "carbon footprint", "product kgco2e"), dim="co2", feeds="avoided product emissions"),
        F("purchase_cost_eur", "num", ("purchase cost", "synthetic_purchase_cost_eur", "cost eur", "unit cost", "price", "replacement cost"), dim="eur", feeds="purchases avoided (EUR)"),
        F("material_note", "text", ("material",))),
        ("product_id",), False, "Product master with approved LCA footprints and replacement cost"),
    Table("laundries", "Laundries", ("laundries", "laundry", "wws", "plants", "laundry master"), (
        F("laundry_id", "id", ("laundry", "wws", "wws id", "plant id", "laundry code", "plant"), True),
        F("laundry_name", "text", ("name", "plant name", "laundry name", "wws")), F("country", "text"),
        F("country_code", "text", ("cc", "iso", "country iso")), F("note", "text", ("notes", "comment"))),
        ("laundry_id",), False, "Laundry / WWS master data"),
    Table("service_activity", "Service activity", ("service activity", "activity", "allocated pieces", "washing", "usage", "service data"), (
        F("month", "month", ("period", "reporting month", "date", "year month", "ym", "month year"), True),
        F("customer_id", "id", ("customer", "account", "account top level", "account id", "client id", "customer code")),
        F("site_id", "id", ("site", "delivery site", "delivery site id", "delivery customer", "location id", "site code"), True),
        F("laundry_id", "id", ("laundry", "wws id", "plant id", "laundry name", "wws")),
        F("product_id", "id", ("product", "product code", "article", "item code", "sku")),
        F("active_wearers", "num", ("wearers", "active users", "users", "number of wearers", "active wearer"), dim="count", feeds="wearer KPIs"),
        F("allocated_pieces", "num", ("allocated", "allocated garments", "pieces allocated", "garments allocated", "garments in circulation", "allocated pieces"), dim="count", feeds="garment utilisation"),
        F("active_assets_scanned", "num", ("scanned assets", "active assets", "scanned garments", "active garments", "assets scanned"), dim="count", feeds="garment utilisation"),
        F("washed_pieces", "num", ("washed garments", "pieces washed", "garments washed", "washed items"), dim="count"),
        F("packed_pieces", "num", ("packed garments", "pieces packed", "packed items"), dim="count"),
        F("washing_pct", "num", ("washing %", "wash %", "washing percentage", "wash rate", "washing"), dim="pct", hi=1000),
        F("customer_washed_kg", "num", ("washed kg", "kg washed", "washed weight", "kilograms", "weight washed", "customer kg", "washed kilos", "customer washed"), True, "kg",
          feeds="ALL resource, emissions and waste metrics"),
        F("service_requests", "num", ("requests", "service request", "tickets", "complaints", "number of service requests"), dim="count", feeds="service-request KPI"),
        STATUS),
        ("month", "site_id", "product_id", "laundry_id"), True, "Allocated pieces / Washing % reports (Tableau), by site, product and month"),
    Table("repairs", "Repairs", ("repairs", "repair", "repair report", "repair table", "mending"), (
        F("month", "month", ("period", "reporting month", "date", "year month"), True),
        F("customer_id", "id", ("customer", "account", "account top level", "account id", "client id")),
        F("site_id", "id", ("site", "delivery site", "delivery customer", "location id"), True),
        F("product_id", "id", ("product", "product code", "article", "item code", "sku")),
        F("laundry_id", "id", ("laundry", "laundry name", "wws id", "plant", "plant id")),
        F("repair_type", "text", ("repair name", "type of repair", "repair category", "repair", "repair kind")),
        F("repair_count", "num", ("repairs", "number of repairs", "repair qty", "repairs completed", "count", "quantity", "repair count"), True, "count",
          feeds="repair, replacements-postponed and avoided-purchase metrics"),
        F("repair_quotient_pct", "num", ("repair quotient", "repair %", "repair rate", "repair quotient %"), dim="pct", hi=100),
        F("estimated_replacements_postponed", "num", ("replacements postponed", "postponed replacements", "est replacements postponed"), dim="count"),
        F("product_footprint_kgco2e", "num", ("product footprint", "footprint"), dim="co2"),
        F("estimated_avoided_product_kgco2e", "num", ("avoided product kgco2e", "avoided emissions", "avoided co2e", "avoided product emissions"), dim="co2", feeds="avoided product emissions"),
        STATUS),
        ("month", "site_id", "product_id", "repair_type", "laundry_id"), False, "Repairs table (monthly by account top level, delivery customer, product code, laundry, repair name)"),
    Table("service_cycles", "Service cycles", ("service cycles", "cycles", "end to end delivery", "rfid", "scans", "asset cycles", "delivery cycles"), (
        F("asset_id", "id", ("asset", "garment id", "rfid", "tag id", "chip id", "item id", "asset number", "garment"), True),
        F("cycle_number", "num", ("cycle", "cycle no", "cycle nr", "round"), dim="count"),
        F("customer_id", "id", ("customer", "account", "account id")),
        F("site_id", "id", ("site", "delivery site", "delivery customer", "location id"), True),
        F("laundry_id", "id", ("laundry", "wws id", "plant", "plant id")), F("product_id", "id", ("product", "product code", "article", "sku", "item code")),
        F("pickup_timestamp", "ts", ("pickup", "picked up", "collected", "pickup time", "pickup date"), feeds="cycle times"),
        F("in_laundry_timestamp", "ts", ("in laundry", "received", "laundry in", "arrived laundry", "in laundry time")),
        F("out_laundry_timestamp", "ts", ("out laundry", "laundry out", "washed", "out of laundry", "out laundry time")),
        F("delivered_timestamp", "ts", ("delivered", "delivery", "delivered at", "delivery time", "delivered date"), feeds="cycle times"),
        F("cycle_hours", "num", ("cycle time", "turnaround", "lead time hours", "cycle duration", "turnaround hours", "total hours"), dim="h", feeds="turnaround KPI"),
        F("performance_flag", "text", ("on time flag", "delivery performance", "status flag", "performance", "on time", "flag"), feeds="on-time KPI"),
        STATUS),
        ("asset_id", "cycle_number"), False, "End-to-end delivery report (RFID scan timestamps per asset and cycle)"),
    Table("resources", "Laundry resources", ("laundry resources", "resources", "wws washed kg", "laundry environmental", "laundry data", "environmental impact"), (
        F("month", "month", ("period", "reporting month", "date", "year month"), True),
        F("laundry_id", "id", ("laundry", "wws id", "plant id", "plant", "laundry code"), True),
        F("laundry_name", "text", ("name", "plant name", "wws")), F("country", "text"),
        F("washed_kg", "num", ("laundry washed kg", "total washed kg", "washed weight", "kg", "washed kilos", "total kg"), True, "kg"),
        F("energy_kwh_per_kg", "num", ("energy intensity", "kwh/kg", "energy per kg", "kwh per kg", "specific energy"), dim="kwh_per_kg", feeds="energy and emissions metrics"),
        F("fresh_water_l_per_kg", "num", ("water intensity", "water per kg", "l/kg", "fresh water per kg", "litres per kg", "liters per kg", "specific water"), dim="l_per_kg", feeds="water metrics"),
        F("process_energy_kwh", "num", ("energy kwh", "process energy", "energy use", "energy consumption"), dim="kwh"),
        F("fresh_water_l", "num", ("fresh water", "water use", "water consumption", "water litres", "water l"), dim="l"),
        F("process_emissions_kgco2e", "num", ("process emissions", "process co2e", "laundry emissions", "process kgco2e"), dim="co2", feeds="emissions metrics"),
        F("delivery_emissions_kgco2e", "num", ("delivery emissions", "logistics emissions", "transport emissions", "delivery co2e"), dim="co2", feeds="emissions metrics"),
        STATUS),
        ("month", "laundry_id"), False, "WWS laundry resource reports (washed kg, water, energy, emissions per laundry and month)"),
    Table("waste", "Waste & circularity", ("waste circularity", "waste", "textile waste", "circularity", "textile waste kg"), (
        F("month", "month", ("period", "reporting month", "date"), True),
        F("laundry_id", "id", ("laundry", "wws id", "plant id", "plant", "laundry code"), True),
        F("recycling_kg", "num", ("recycling", "recycled kg", "recycled"), dim="kg", feeds="recycling share"),
        F("reuse_kg", "num", ("reuse", "reused kg", "reused"), dim="kg", feeds="recycling share"),
        F("energy_recovery_kg", "num", ("energy recovery", "energy recovered kg"), dim="kg"),
        F("incineration_kg", "num", ("incineration", "incinerated kg", "landfill kg"), dim="kg"),
        F("textile_waste_total_kg", "num", ("textile waste total", "total waste kg", "waste total", "total textile waste"), dim="kg", feeds="waste metrics"),
        F("waste_kg_per_washed_kg", "num", ("waste per washed kg", "waste intensity", "waste per kg"), dim="frac"),
        STATUS),
        ("month", "laundry_id"), False, "Textile Waste kg report (treatment routes per laundry and month)"),
    Table("baselines", "Baselines", ("baselines", "baseline", "comparison", "factors", "comparison baselines", "scenarios"), (
        F("baseline_id", "id", ("id", "baseline code", "scenario id"), True),
        F("baseline_name", "text", ("name", "baseline", "scenario", "scenario name")),
        F("selection_status", "text", ("status", "default", "selection")),
        F("water_l_per_kg", "num", ("water l/kg", "water per kg", "water intensity", "litres per kg"), True, "l_per_kg"),
        F("energy_kwh_per_kg", "num", ("energy kwh/kg", "energy per kg", "kwh/kg", "energy intensity"), True, "kwh_per_kg"),
        F("process_kgco2e_per_kg", "num", ("process kgco2e/kg", "process emissions per kg", "process co2e per kg"), True, "frac"),
        F("delivery_kgco2e_per_kg", "num", ("delivery kgco2e/kg", "delivery emissions per kg", "delivery co2e per kg"), dim="frac"),
        F("mixed_waste_share", "num", ("mixed waste", "mixed waste %", "waste share"), dim="frac", hi=1),
        F("assumption_note", "text", ("note", "notes", "assumption", "comment"))),
        ("baseline_id",), False, "Approved comparison calculator (Workwear laundry environmental impact comparison)"),
    Table("impacts", "Customer impacts (pre-calculated)", ("customer impacts", "impacts", "allocated impacts", "customer impact"), (
        F("month", "month", ("period", "date"), True),
        F("customer_id", "id", ("customer", "account", "account top level", "account id", "client id", "customer code")),
        F("site_id", "id", ("site", "delivery site", "delivery site id", "delivery customer", "location id", "site code", "site number", "site no"), True),
        F("laundry_id", "id", ("laundry", "wws id", "plant", "plant id", "laundry code")),
        F("product_id", "id", ("product", "product code", "article", "item code", "sku", "article number")),
        F("customer_washed_kg", "num", ("washed kg", "customer kg", "kg washed", "washed weight", "kilograms", "weight washed", "washed kilos", "customer washed"), True, "kg"),
        F("share_of_laundry_washed_kg", "num", ("share of laundry", "laundry share", "share"), dim="frac", hi=1),
        F("allocated_water_l", "num", ("allocated water", "water l"), dim="l"),
        F("allocated_energy_kwh", "num", ("allocated energy", "energy kwh"), dim="kwh"),
        F("allocated_process_kgco2e", "num", ("allocated process", "process co2e"), dim="co2"),
        F("allocated_delivery_kgco2e", "num", ("allocated delivery", "delivery co2e"), dim="co2"),
        F("allocated_textile_waste_kg", "num", ("allocated waste", "textile waste kg"), dim="kg"),
        F("water_saving_vs_local_l", "num", ("water saving", "water saved"), dim="l", nonneg=False),
        F("energy_saving_vs_local_kwh", "num", ("energy saving", "energy saved"), dim="kwh", nonneg=False),
        F("emissions_saving_vs_local_kgco2e", "num", ("emissions saving", "co2 saving", "emissions saved"), dim="co2", nonneg=False),
        STATUS),
        ("month", "site_id", "product_id", "laundry_id"), False, "Optional pre-calculated allocation; used only as a cross-check, never as input"),
    Table("assumptions", "Assumption registry", ("assumptions", "assumption registry", "assumption"), (
        F("assumption_id", "id", ("id", "ref"), True), F("assumption", "text", ("name", "assumption name", "description")),
        F("value_or_rule", "text", ("value", "rule", "value rule", "setting")), F("rationale", "text", ("reason", "justification")),
        F("category", "text"), F("confidence", "text", ("confidence level",)), F("treatment", "text", ("handling", "editable"))),
        ("assumption_id",), False, "Lindström-approved assumption registry"),
    Table("industry_priorities", "Industry priorities", ("industry priorities", "priorities", "industry rules"), (
        F("industry", "text", ("sector",), True), F("priority_rank", "num", ("rank", "priority"), dim="count"),
        F("priority_theme", "text", ("theme", "topic"), True), F("dashboard_emphasis", "text", ("emphasis", "description"))),
        ("industry", "priority_rank"), False, "Industry-specific value drivers agreed with sales / sustainability"),
    Table("reference_totals", "Reference totals (control totals)", ("sample output", "reference totals", "control totals", "summary", "kpi summary", "totals"), (
        F("metric", "text", ("kpi", "indicator", "measure", "name"), True),
        F("value", "num", ("amount", "result", "total"), True, nonneg=False),
        F("unit", "text", ("units", "uom")),
        F("status_interpretation", "text", ("status/interpretation", "status interpretation", "interpretation", "note", "status"))),
        (), False, "Control totals from an approved report; used to reconcile the calculated totals"),
]}

IGNORED_NOTE = "README, data dictionary, quick-start, prompts and data-quality sheets are read as documentation and not used for calculation."

# ---- status labels ---------------------------------------------------------
STATUS_TOKENS = {
    "MEASURED": "MEASURED", "ACTUAL": "MEASURED", "REPORTED": "MEASURED",
    "CALCULATED": "CALCULATED", "DERIVED": "CALCULATED",
    "ESTIMATE": "ESTIMATED", "ESTIMATED": "ESTIMATED",
    "ALLOCATED": "ALLOCATED", "SYNTHETIC": "SYNTHETIC",
    "PUBLIC": "PUBLIC_REFERENCE", "REFERENCE": "PUBLIC_REFERENCE",
}
NEUTRAL_TOKENS = {"STRUCTURALLY", "REPRESENTATIVE", "STRUCTURAL", "FACTOR", "ILLUSTRATIVE", "ONLY", "DATA", "PACK", "FICTIONAL"}


def status_tokens(raw) -> tuple[set, set]:
    """-> (recognised categories, unknown tokens). Blank -> (set(), set())."""
    if raw is None or (isinstance(raw, float) and raw != raw) or str(raw).strip() == "":
        return set(), set()
    toks = [t for t in re.split(r"[^A-Za-z]+", str(raw).upper()) if t]
    rec = {STATUS_TOKENS[t] for t in toks if t in STATUS_TOKENS}
    unk = {t for t in toks if t not in STATUS_TOKENS and t not in NEUTRAL_TOKENS}
    return rec, unk


def norm(s: str) -> str:
    s = re.sub(r"[\(\[].*?[\)\]]", " ", str(s))            # drop (units)
    s = s.replace("%", " pct ").replace("/", " per ").replace("€", " eur ")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()
