"""200 small per-customer exports (distinct ids) for a scale check. Usage: python tests/make_many.py <outdir> [n]"""
import os, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "data", "pack.xlsx")


def make(outdir, n=200):
    os.makedirs(outdir, exist_ok=True)
    x = pd.read_excel(SRC, sheet_name=None, dtype=object)
    cust = x["Customers"][x["Customers"].customer_id == "CUST003"]
    sites = x["Sites"][x["Sites"].customer_id == "CUST003"]
    sset = set(sites.site_id)
    for i in range(n):
        cid = f"C{i:04d}"
        def re_(df, cols=("customer_id",), site=True):
            df = df.copy()
            if "customer_id" in df: df["customer_id"] = cid
            if "site_id" in df: df["site_id"] = df.site_id.map(lambda s: f"{s}_{i:04d}")
            return df
        sh = {"Customers": cust.assign(customer_id=cid, customer_name=f"Customer {i:04d}"), "Sites": re_(sites),
              "Service_Activity": re_(x["Service_Activity"][x["Service_Activity"].site_id.isin(sset)]),
              "Repairs": re_(x["Repairs"][x["Repairs"].site_id.isin(sset)]),
              "Service_Cycles": re_(x["Service_Cycles"][x["Service_Cycles"].site_id.isin(sset)].head(150)).assign(asset_id=lambda d: d.asset_id.map(lambda a: f"{a}_{i:04d}")),
              "Laundries": x["Laundries"], "Laundry_Resources": x["Laundry_Resources"], "Waste_Circularity": x["Waste_Circularity"],
              "Products": x["Products"], "Baselines": x["Baselines"]}
        with pd.ExcelWriter(os.path.join(outdir, f"export_{cid}.xlsx")) as w:
            for k, df in sh.items():
                df.to_excel(w, sheet_name=k, index=False)
    return outdir


if __name__ == "__main__":
    make(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 200)
