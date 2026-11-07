"""Read any set of Lindström Excel files, classify each sheet into the internal model,
auto-map columns and units, and build canonical tables. Nothing here calculates a metric."""
from __future__ import annotations
import io, os, re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
import numpy as np
import pandas as pd
from schema import TABLES, norm, status_tokens

CLASSIFY_MIN = 0.50
COLUMN_MIN = 0.60
_ID_A = re.compile(r"^[A-Za-z]{1,8}[-_ ]?\d{1,10}$")
_ID_B = re.compile(r"^[A-Z0-9][A-Z0-9_\-]{1,24}$")


class _IdRe:
    @staticmethod
    def match(x):
        return _ID_A.match(x) or _ID_B.match(x)


ID_RE = _IdRe()
GENERIC = {"id", "code", "name", "no", "nr", "number", "type", "kg", "per", "total", "of", "the"}


@dataclass
class RawSheet:
    key: str
    file: str
    sheet: str
    df: pd.DataFrame      # header-detected frame, index = Excel row number
    header_row: int


@dataclass
class SheetMap:
    key: str
    table: str | None
    score: float = 0.0
    cols: dict = field(default_factory=dict)       # field -> source column or None
    conf: dict = field(default_factory=dict)       # field -> 0..1
    factor: dict = field(default_factory=dict)     # field -> multiplier to canonical unit
    why: dict = field(default_factory=dict)        # field -> unit reason
    include: bool = True
    note: str = ""


# ------------------------------------------------------------------ reading
def _header_row(raw: pd.DataFrame) -> int:
    head = raw.head(15)
    counts = head.map(lambda v: isinstance(v, str) and v.strip() != "").sum(axis=1)
    nonnull = head.notna().sum(axis=1)
    if nonnull.max() == 0:
        return 0
    for i in range(len(head)):
        if counts.iloc[i] >= 2 and counts.iloc[i] >= 0.6 * nonnull.max():
            return i
    return 0


DOC_SHEET_NAMES = {"readme", "data dictionary", "quick start", "suggested prompts", "data quality", "notes", "about", "instructions", "cover"}


def _is_doc_sheet(name: str) -> bool:
    return norm(name) in DOC_SHEET_NAMES


def _frame_to_raw(fname: str, sname: str, raw: pd.DataFrame):
    raw = raw.dropna(how="all").dropna(axis=1, how="all")
    if raw.empty:
        return None
    h = _header_row(raw)
    hdr_idx = raw.index[h]
    cols, seen = [], {}
    for c in raw.loc[hdr_idx]:
        c = str(c).strip() if pd.notna(c) else "unnamed"
        seen[c] = seen.get(c, 0) + 1
        cols.append(c if seen[c] == 1 else f"{c}.{seen[c]}")
    body = raw.loc[raw.index > hdr_idx].copy()
    body.columns = cols
    body.index = body.index + 1                       # Excel row number
    return RawSheet(f"{fname}::{sname}", fname, sname, body, int(hdr_idx) + 1)


_READ_CACHE: dict = {}          # parsed workbooks by content hash, so a multi-customer build parses each file once (copies are returned)


def read_workbooks(files: list[tuple[str, bytes]], skip_docs: bool = False, skipped: list | None = None,
                   errors: list | None = None) -> dict[str, RawSheet]:
    if errors is None or len(files) != 1 or not isinstance(files[0][1], (bytes, bytearray)):
        return _read_workbooks(files, skip_docs, skipped, errors)
    import copy, hashlib
    fname, blob = files[0]
    key = (str(fname), hashlib.sha256(blob).hexdigest(), bool(skip_docs))
    hit = _READ_CACHE.get(key)
    if hit is None:
        sk, er = [], []
        hit = (_read_workbooks(files, skip_docs, sk, er), sk, er)
        while len(_READ_CACHE) >= 3:
            _READ_CACHE.pop(next(iter(_READ_CACHE)), None)
        _READ_CACHE[key] = hit
    out, sk, er = copy.deepcopy(hit)
    if skipped is not None:
        skipped += sk
    errors += er
    return out


def _read_workbooks(files: list[tuple[str, bytes]], skip_docs: bool = False, skipped: list | None = None,
                    errors: list | None = None) -> dict[str, RawSheet]:
    """files: (name, bytes|path-like). .csv is read as one sheet named after the file.
    skip_docs: do not read README/dictionary-type sheets (faster for big folders); their names go to `skipped`.
    errors: collects (file, message) instead of raising, so one broken file never stops a batch."""
    out: dict[str, RawSheet] = {}
    for fname, blob in files:
        try:
            src = io.BytesIO(blob) if isinstance(blob, (bytes, bytearray)) else blob
            if str(fname).lower().endswith(".csv"):
                df = pd.read_csv(src, header=None, dtype=object, sep=None, engine="python", encoding_errors="replace")
                rs = _frame_to_raw(fname, os.path.splitext(os.path.basename(fname))[0], df)
                if rs is not None:
                    out[rs.key] = rs
                continue
            xl = pd.ExcelFile(src)
            names = xl.sheet_names
            use = [n for n in names if not (skip_docs and _is_doc_sheet(n))]
            if skipped is not None:
                skipped += [(fname, n) for n in names if n not in use]
            for sname in use:
                rs = _frame_to_raw(fname, sname, xl.parse(sname, header=None))
                if rs is not None:
                    out[rs.key] = rs
        except Exception as e:                      # one unreadable file must not stop the batch
            if errors is None:
                raise
            errors.append((fname, f"{type(e).__name__}: {str(e)[:160]}"))
    return out


# ------------------------------------------------------------------ matching
@lru_cache(maxsize=None)
def _sim(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    best = SequenceMatcher(None, na, nb).ratio()
    ca, cb = ta - GENERIC, tb - GENERIC
    if ca and cb and not (ca & cb) and best < 0.85:      # no meaningful word in common: approximate match is not trusted
        return best * 0.6
    if tb <= ta and len(ta) <= len(tb) + 2:
        best = max(best, 0.85)
    if ta <= tb and len(ta) >= 2:
        best = max(best, 0.75)
    return best


def _name_sim(col: str, fld) -> float:
    return max(_sim(col, n) for n in (fld.name, *fld.aliases))


def _parse_month_value(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    if isinstance(v, (pd.Timestamp, np.datetime64)) or hasattr(v, "strftime"):
        return pd.Timestamp(v).strftime("%Y-%m")
    if isinstance(v, (int, np.integer)) or (isinstance(v, float) and float(v).is_integer()):
        s = str(int(v))
        if re.fullmatch(r"\d{6}", s):
            return f"{s[:4]}-{s[4:]}"
        return np.nan
    s = str(v).strip()
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?(?:[ T].*)?", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{4})", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    try:
        return pd.to_datetime(s, errors="raise").strftime("%Y-%m")
    except Exception:
        return np.nan


def parse_month(series: pd.Series) -> pd.Series:
    u = {v: _parse_month_value(v) for v in series.dropna().unique()}
    return series.map(lambda v: u.get(v, np.nan) if pd.notna(v) else np.nan)


def _to_num(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")

    def conv(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        if isinstance(v, (int, float, np.number)):
            return float(v)
        s = str(v).strip().replace(" ", "").replace(" ", "")
        if re.fullmatch(r"-?\d+,\d{1,2}", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
        try:
            return float(s)
        except ValueError:
            return np.nan
    return series.map(conv)


def _fit(series: pd.Series, kind: str) -> float:
    v = series.dropna().head(200)
    if v.empty:
        return 0.5
    if kind == "id":
        m = v.astype(str).str.strip().map(lambda x: bool(ID_RE.match(x))).mean()
        if m < 0.5 and pd.api.types.is_integer_dtype(series.dropna()):
            return 0.6
        return max(m, 0.15)
    if kind == "text":
        s = v.astype(str).str.strip()
        idlike = s.map(lambda x: bool(_ID_A.match(x))).mean()
        numlike = _to_num(v).notna().mean()
        return max(1 - max(idlike, numlike), 0.15)
    if kind == "num":
        if pd.api.types.is_datetime64_any_dtype(series):
            return 0.1
        return max(_to_num(v).notna().mean(), 0.1)
    if kind == "month":
        return max(parse_month(v).notna().mean(), 0.1)
    if kind == "ts":
        if pd.api.types.is_datetime64_any_dtype(series):
            return 1.0
        return max(pd.to_datetime(v, errors="coerce", format="mixed").notna().mean(), 0.1)
    if kind == "status":
        return max(v.astype(str).map(lambda x: bool(status_tokens(x)[0])).mean(), 0.2)
    return 1.0


# ------------------------------------------------------------------ units
def detect_factor(header: str, fld, series: pd.Series) -> tuple[float, str]:
    h = str(header).lower()
    num = _to_num(series.dropna().head(500))
    if fld.dim == "kg":
        if re.search(r"\b(t|ton|tons|tonne|tonnes)\b|\(t\)|\[t\]", h):
            return 1000.0, "header says tonnes → ×1000 to kg"
        if re.search(r"\bg\b|gram", h):
            return 0.001, "header says grams → ×0.001 to kg"
    elif fld.dim == "l":
        if re.search(r"m3|m³|cbm|cubic", h):
            return 1000.0, "header says m³ → ×1000 to litres"
        if re.search(r"\bml\b", h):
            return 0.001, "header says ml → ×0.001 to litres"
    elif fld.dim == "kwh":
        if "mwh" in h: return 1000.0, "header says MWh → ×1000 to kWh"
        if "gwh" in h: return 1e6, "header says GWh → ×1,000,000 to kWh"
        if re.search(r"\bgj\b", h): return 277.78, "header says GJ → ×277.78 to kWh"
    elif fld.dim == "co2":
        if re.search(r"\bt\s?co2|tco2|tonne.*co2", h):
            return 1000.0, "header says tCO2e → ×1000 to kgCO2e"
    elif fld.dim == "eur":
        if re.search(r"k€|keur|k eur|thousand|teur", h): return 1000.0, "header says thousand EUR → ×1000"
        if re.search(r"m€|meur", h): return 1e6, "header says million EUR → ×1,000,000"
    elif fld.dim == "h":
        if re.search(r"\bmin", h): return 1 / 60, "header says minutes → ÷60 to hours"
        if re.search(r"\bday", h): return 24.0, "header says days → ×24 to hours"
    elif fld.dim == "pct":
        if len(num) and num.max() <= 1.0 and num.quantile(0.9) >= 0.2 and (fld.hi or 0) <= 100:
            return 100.0, "values look like fractions (max ≤ 1) → ×100 to percent"
    return 1.0, ""


# ------------------------------------------------------------------ mapping
def map_sheet(rs: RawSheet, table: str) -> SheetMap:
    t = TABLES[table]
    df = rs.df
    cand, fitc = [], {}
    for f in t.fields:
        for c in df.columns:
            ns = _name_sim(c, f)
            if ns < 0.5:
                continue
            if (c, f.kind) not in fitc:
                fitc[(c, f.kind)] = _fit(df[c], f.kind)
            cand.append((ns * (0.6 + 0.4 * fitc[(c, f.kind)]), f.name, c))
    cand.sort(reverse=True)
    used_f, used_c, cols, conf = set(), set(), {f.name: None for f in t.fields}, {f.name: 0.0 for f in t.fields}
    for s, fn, c in cand:
        if s < COLUMN_MIN or fn in used_f or c in used_c:
            continue
        cols[fn], conf[fn] = c, round(s, 2)
        used_f.add(fn); used_c.add(c)
    factor, why = {}, {}
    for f in t.fields:
        if cols[f.name] is not None and f.kind == "num":
            factor[f.name], why[f.name] = detect_factor(cols[f.name], f, df[cols[f.name]])
        else:
            factor[f.name], why[f.name] = 1.0, ""
    req = [conf[f.name] for f in t.fields if f.required]
    cover = sum(conf.values()) / len(t.fields)
    name_sim = max(_sim(rs.sheet, a) for a in (t.label, *t.sheet_aliases))
    score = 0.45 * cover + 0.35 * (np.mean(req) if req else cover) + 0.20 * name_sim
    return SheetMap(rs.key, table, round(float(score), 3), cols, conf, factor, why)


def classify(rs: RawSheet) -> SheetMap:
    if rs.df.shape[1] < 3 or rs.df.shape[0] < 1:
        return SheetMap(rs.key, None, 0.0, include=False, note="too small to be a data table (documentation?)")
    best = max((map_sheet(rs, t) for t in TABLES), key=lambda m: m.score)
    if best.score < CLASSIFY_MIN:
        return SheetMap(rs.key, None, best.score, include=False,
                        note=f"not recognised as a data table (best guess '{best.table}' at {best.score:.2f}); treated as documentation")
    return best


def _signature(rs: RawSheet):
    return (norm(rs.sheet), tuple(rs.df.columns), rs.df.shape[1])


def auto_map(raw: dict[str, RawSheet]) -> dict[str, SheetMap]:
    """Classify every sheet. Exports from the same system share a layout, so the (sheet name, column names) signature is
    classified once and reused; unit factors are still detected per sheet from its own data."""
    cache: dict = {}
    out = {}
    for k, rs in raw.items():
        sig = _signature(rs)
        if sig in cache:
            base = cache[sig]
            sm = SheetMap(k, base.table, base.score, dict(base.cols), dict(base.conf), {}, {}, base.include, base.note)
            if sm.table:
                t = TABLES[sm.table]
                for f in t.fields:
                    c = sm.cols.get(f.name)
                    if c is not None and f.kind == "num" and c in rs.df.columns:
                        sm.factor[f.name], sm.why[f.name] = detect_factor(c, f, rs.df[c])
                    else:
                        sm.factor[f.name], sm.why[f.name] = 1.0, ""
            out[k] = sm
        else:
            sm = classify(rs)
            cache[sig] = sm
            out[k] = sm
    return out


# ------------------------------------------------------------------ build
def build_tables(raw: dict[str, RawSheet], mapping: dict[str, SheetMap]):
    """-> (tables, load_issues, field_presence). Tables use canonical names and units;
    every row keeps _uid/_sheet/_row so that issues can point at the exact source row."""
    parts: dict[str, list[pd.DataFrame]] = {}
    load_issues: list[dict] = []
    presence: dict[str, dict[str, bool]] = {}
    for key, sm in mapping.items():
        if not sm.include or sm.table is None:
            continue
        t, rs = TABLES[sm.table], raw[key]
        out = pd.DataFrame(index=rs.df.index)
        for f in t.fields:
            src = sm.cols.get(f.name)
            if not src or src not in rs.df.columns:
                out[f.name] = pd.Series(np.nan, index=rs.df.index, dtype=("float64" if f.kind == "num" else "datetime64[ns]" if f.kind == "ts" else object))
                continue
            s = rs.df[src]
            presence.setdefault(sm.table, {})[f.name] = True
            if f.kind == "id":
                s = s.map(lambda v: (str(int(v)) if isinstance(v, float) and float(v).is_integer() else str(v).strip()) if pd.notna(v) and str(v).strip() != "" else np.nan)
            elif f.kind in ("text", "status"):
                s = s.map(lambda v: str(v).strip() if pd.notna(v) and str(v).strip() != "" else np.nan)
            elif f.kind == "num":
                n = _to_num(s)
                bad = s.notna() & n.isna() & s.map(lambda v: str(v).strip() != "")
                if sm.table == "reference_totals":      # control-total sheets legitimately mix text and numbers
                    out["value_text"] = s.map(lambda v: str(v).strip() if pd.notna(v) else np.nan)
                    bad = bad & False
                if bad.any():
                    load_issues.append(dict(table=sm.table, field=f.name, kind="non_numeric", sheet=key,
                                            uids=[f"{key}#{r}" for r in rs.df.index[bad]],
                                            examples=list(s[bad].astype(str).head(3))))
                s = n * sm.factor.get(f.name, 1.0)
            elif f.kind == "month":
                m = parse_month(s)
                bad = s.notna() & m.isna()
                if bad.any():
                    load_issues.append(dict(table=sm.table, field=f.name, kind="bad_month", sheet=key,
                                            uids=[f"{key}#{r}" for r in rs.df.index[bad]], examples=list(s[bad].astype(str).head(3))))
                s = m
            elif f.kind == "ts":
                tt = pd.to_datetime(s, errors="coerce")
                bad = s.notna() & tt.isna()
                if bad.any():
                    load_issues.append(dict(table=sm.table, field=f.name, kind="bad_ts", sheet=key,
                                            uids=[f"{key}#{r}" for r in rs.df.index[bad]], examples=list(s[bad].astype(str).head(3))))
                s = tt
            out[f.name] = s
        out["_sheet"] = key
        out["_row"] = rs.df.index
        out["_uid"] = [f"{key}#{r}" for r in rs.df.index]
        parts.setdefault(sm.table, []).append(out)
    tables = {t: pd.concat(p, ignore_index=True) for t, p in parts.items()}
    return tables, load_issues, presence


# ------------------------------------------------------------------ helpers
def status_summary(tables: dict, names: list[str]) -> str:
    """Summarise data_status labels of the tables a metric uses; name tables that carry no label."""
    cats, unl = set(), []
    for n in names:
        df = tables.get(n)
        if df is None or df.empty:
            continue
        if "data_status" not in df or df.data_status.isna().all():
            unl.append(n); continue
        if df.data_status.isna().any():
            unl.append(n)
        for v in df.data_status.dropna().unique():
            cats |= status_tokens(v)[0]
    s = "/".join(sorted(cats)) if cats else "UNLABELLED"
    return s + (f"; unlabelled input: {', '.join(unl)}" if unl and cats else "")


def mapping_table(raw: dict[str, RawSheet], mapping: dict[str, SheetMap]) -> pd.DataFrame:
    rows = []
    for k, sm in mapping.items():
        rows.append(dict(file=raw[k].file, sheet=raw[k].sheet, rows=len(raw[k].df), maps_to=sm.table or "(ignored)",
                         confidence=sm.score, used=bool(sm.include and sm.table), note=sm.note))
    return pd.DataFrame(rows)
