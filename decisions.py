"""Sidecar decisions: everything a user decides about the data lives in ONE small JSON file, never in the source workbooks.

{
  "mapping":    {"<file>::<sheet>": {"table": "sites"|null, "include": true, "cols": {"site_id": "Location ID"}, "factor": {"customer_washed_kg": 1000}}},
  "exclusions": [{"file": "a.xlsx", "sheet": "Usage", "row": 12, "rule": "manual", "reason": "..."}],
  "issue_actions": {"<check>|<table>": "exclude"|"keep"},      # stable across re-runs (issue ids V001.. are not)
  "bands":      {"default": [30, 70], "industry_aware": true, "overrides": {"CUST001": [40, 80]}}
}
Exclusions are applied only to the derived tables / master pack."""
from __future__ import annotations
import json, os
from dataclasses import dataclass, field


@dataclass
class Decisions:
    mapping: dict = field(default_factory=dict)
    exclusions: list = field(default_factory=list)
    issue_actions: dict = field(default_factory=dict)
    bands: dict = field(default_factory=dict)

    # ---- io
    @classmethod
    def load(cls, path: str | None):
        if not path or not os.path.exists(path):
            return cls()
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return cls(d.get("mapping", {}), d.get("exclusions", []), d.get("issue_actions", {}), d.get("bands", {}))

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(mapping=self.mapping, exclusions=self.exclusions, issue_actions=self.issue_actions, bands=self.bands),
                      f, indent=2, ensure_ascii=False)

    # ---- mapping overrides
    def apply_mapping(self, raw, mapping):
        """Overlay saved mapping choices on the auto-mapping. Unknown sheets/columns are ignored (files may change)."""
        from data_loader import SheetMap, map_sheet
        from schema import TABLES
        for key, ov in self.mapping.items():
            # saved key is "<file>::<sheet>"; match on the same key, or on sheet name alone if the file name changed
            k = key if key in raw else next((r for r in raw if r.split("::")[-1] == key.split("::")[-1]), None)
            if k is None:
                continue
            sm = mapping.get(k)
            tbl = ov.get("table", sm.table if sm else None)
            if tbl is not None and tbl not in TABLES:
                continue
            if tbl != (sm.table if sm else None) or sm is None:
                base = map_sheet(raw[k], tbl) if tbl else SheetMap(k, None, 0.0, include=False)
                base.include = ov.get("include", bool(tbl))
                sm = mapping[k] = base
            if "include" in ov:
                sm.include = bool(ov["include"])
            for fld, col in (ov.get("cols") or {}).items():
                if fld in sm.cols and (col is None or col in raw[k].df.columns):
                    sm.cols[fld] = col
                    sm.conf[fld] = 1.0 if col else 0.0
            for fld, fac in (ov.get("factor") or {}).items():
                if fld in sm.factor:
                    sm.factor[fld] = float(fac)
                    sm.why[fld] = "set by user"
            sm.note = (sm.note + " " if sm.note else "") + "mapping adjusted by user"
        return mapping

    def set_sheet(self, key, table=None, include=None, cols=None, factor=None):
        e = self.mapping.setdefault(key, {})
        if table is not None:
            e["table"] = table or None
        if include is not None:
            e["include"] = include
        if cols:
            e.setdefault("cols", {}).update(cols)
        if factor:
            e.setdefault("factor", {}).update(factor)

    # ---- exclusions
    def uid_reasons(self):
        out = {}
        for e in self.exclusions:
            out[f"{e['file']}::{e['sheet']}#{int(e['row'])}"] = f"{e.get('rule', 'manual')}: {e.get('reason', 'excluded by user')}"
        return out

    def exclude_row(self, file, sheet, row, rule="manual", reason="excluded by user"):
        e = dict(file=file, sheet=sheet, row=int(row), rule=rule, reason=reason)
        if e not in self.exclusions:
            self.exclusions.append(e)

    def actions_for(self, issues):
        """issue id -> action, using the stable (check|table) key, falling back to the default."""
        out = {}
        for r in issues.itertuples():
            k = f"{r.check}|{r.table}"
            if k in self.issue_actions:
                out[r.id] = self.issue_actions[k]
        return out

    def set_issue_action(self, check, table, action):
        self.issue_actions[f"{check}|{table}"] = action

    def bands_obj(self):
        from measures import Bands, DEFAULT_BAND
        b = self.bands or {}
        return Bands(tuple(b.get("default", DEFAULT_BAND)), bool(b.get("industry_aware", True)),
                     {k: tuple(v) for k, v in (b.get("overrides") or {}).items()})
