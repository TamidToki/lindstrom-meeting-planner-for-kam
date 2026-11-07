"""Orchestration: files -> mapping -> (user confirms) -> tables -> validation -> (user decides) -> clean tables."""
from __future__ import annotations
import os
import pandas as pd
import data_loader as dl
import validation as vd
import metrics as mt

SAMPLE = os.path.join(os.path.dirname(__file__), "data", "pack.xlsx")


def sample_files():
    with open(SAMPLE, "rb") as f:
        return [("Lindstrom_SinceAI_Customer_Value_Synthetic_Data_Pack.xlsx", f.read())]


def ingest(files):
    raw = dl.read_workbooks(files)
    return raw, dl.auto_map(raw)


def validate_mapping(raw, mapping):
    T, load_issues, presence = dl.build_tables(raw, mapping)
    issues = vd.validate(T, load_issues, mapping, raw, presence)
    return dict(T=T, issues=issues, presence=presence)


def finalize(V, actions=None, extra=None):
    """Apply the user's decisions; return enriched clean tables + exclusion log."""
    T, log = vd.apply_exclusions(V["T"], V["issues"], actions or {}, extra)
    return mt.enrich(T), log


def run_all(files, actions=None):
    """Headless: defaults everywhere. Used by the sample demo and the tests."""
    raw, mapping = ingest(files)
    V = validate_mapping(raw, mapping)
    T, log = finalize(V, actions)
    return dict(raw=raw, mapping=mapping, V=V, T=T, log=log, issues=V["issues"])


def readiness(T, mapping, raw) -> pd.DataFrame:
    """Data-readiness table: what was provided per internal table, what is missing, and the future Lindström source type."""
    from schema import TABLES
    rows = []
    for name, t in TABLES.items():
        srcs = [f"{raw[k].file} › {raw[k].sheet}" for k, sm in mapping.items() if sm.include and sm.table == name]
        mapped = set()
        for k, sm in mapping.items():
            if sm.include and sm.table == name:
                mapped |= {f for f, c in sm.cols.items() if c}
        missing = [f.name for f in t.fields if f.name not in mapped]
        n = sum(len(T[name]) for _ in [0]) if name in T else 0
        rows.append(dict(table=t.label, provided="yes" if srcs else "NO", source="; ".join(srcs) or "-", rows=n,
                         fields=f"{len(mapped)}/{len(t.fields)}", missing=", ".join(missing) or "-", future_source=t.future_source))
    return pd.DataFrame(rows)
