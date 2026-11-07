"""Generate the two synthetic regression packs (stand-ins for pack_nordwind*.xlsx):
  pack_nordwind.xlsx          canonical names, customers renamed to Nordwind*
  pack_nordwind_renamed.xlsx  renamed sheets/columns (Location ID / Plant / SKU ...), header on row 3
Run:  python tests/make_packs.py"""
import os, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "data", "pack.xlsx")
OUT = os.path.join(HERE, "packs")
DOC = {"README", "Data_Quality", "Suggested_Prompts", "Quick_Start", "Data_Dictionary"}
CUST = {"NorthStar Foods Group": "Nordwind Foods", "Apex Industrial": "Nordwind Industrial", "Mediora Health": "Nordwind Care"}
COLS = {"site_id": "Location ID", "laundry_id": "Plant", "product_id": "SKU", "customer_id": "Account", "month": "Reporting month",
        "customer_washed_kg": "Washed kg", "washed_kg": "Laundry washed kg", "allocated_pieces": "Garments allocated",
        "active_assets_scanned": "Active garments", "service_requests": "Number of service requests", "repair_count": "Repairs",
        "active_wearers": "Wearers"}
SHEETS = {"Customers": "Accounts", "Sites": "Delivery sites", "Products": "Articles", "Laundries": "Plants", "Service_Activity": "Usage data",
          "Repairs": "Repair report", "Service_Cycles": "RFID scans", "Laundry_Resources": "Plant resources", "Waste_Circularity": "Textile waste",
          "Baselines": "Comparison", "Customer_Impacts": "Allocated impacts"}


def main():
    x = pd.read_excel(SRC, sheet_name=None, header=None, dtype=object)
    os.makedirs(OUT, exist_ok=True)
    keep = {k: v for k, v in x.items() if k not in DOC and k not in ("Sample_Output", "Assumptions", "Industry_Priorities")}
    keep["Industry_Priorities"] = x["Industry_Priorities"]
    for k in keep:
        keep[k] = keep[k].map(lambda v: CUST.get(v, v) if isinstance(v, str) else v)
    with pd.ExcelWriter(os.path.join(OUT, "pack_nordwind.xlsx")) as w:
        for k, v in keep.items():
            v.to_excel(w, sheet_name=k, header=False, index=False)
    with pd.ExcelWriter(os.path.join(OUT, "pack_nordwind_renamed.xlsx")) as w:
        for k, v in keep.items():
            v = v.copy()
            v.iloc[0] = [COLS.get(c, c) for c in v.iloc[0]]
            top = pd.DataFrame([["Nordwind export", *([None] * (v.shape[1] - 1))], [None] * v.shape[1]])   # 2 junk rows: header on Excel row 3
            pd.concat([top, v], ignore_index=True).to_excel(w, sheet_name=SHEETS.get(k, k), header=False, index=False)
    print("written", OUT)


if __name__ == "__main__":
    main()
