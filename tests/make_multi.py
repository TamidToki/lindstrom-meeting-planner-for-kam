"""Split the sample pack into one workbook per customer (what a KAM with many exports really has).
File 3 is renamed (sheets, columns, header on Excel row 3). Laundry/product/baseline sheets repeat in every file
on purpose: this tests duplicate handling across files."""
import os
import pandas as pd
from make_packs import COLS, SHEETS
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "data", "pack.xlsx")
KEEP = ["Customers", "Laundries", "Products", "Sites", "Industry_Priorities", "Service_Activity", "Repairs", "Service_Cycles", "Laundry_Resources",
        "Waste_Circularity", "Baselines", "Customer_Impacts"]
CUST_COL = {"Customers", "Sites", "Service_Activity", "Repairs", "Service_Cycles", "Customer_Impacts"}


def make(outdir, renamed_last=True):
    os.makedirs(outdir, exist_ok=True)
    x = pd.read_excel(SRC, sheet_name=None, header=None, dtype=object)
    cust = list(x["Customers"].iloc[1:, 0])
    paths = []
    for i, c in enumerate(cust):
        p = os.path.join(outdir, f"export_{c}.xlsx")
        ren = renamed_last and i == len(cust) - 1
        with pd.ExcelWriter(p) as w:
            for k in KEEP:
                df = x[k].copy()
                if k in CUST_COL:
                    hdr = list(df.iloc[0])
                    ci = hdr.index("customer_id")
                    df = pd.concat([df.iloc[:1], df.iloc[1:][df.iloc[1:, ci] == c]], ignore_index=True)
                if ren:
                    df.iloc[0] = [COLS.get(v, v) for v in df.iloc[0]]
                    top = pd.DataFrame([["Export for " + c, *([None] * (df.shape[1] - 1))], [None] * df.shape[1]])
                    df = pd.concat([top, df], ignore_index=True)
                df.to_excel(w, sheet_name=SHEETS.get(k, k) if ren else k, header=False, index=False)
        paths.append(p)
    return paths
