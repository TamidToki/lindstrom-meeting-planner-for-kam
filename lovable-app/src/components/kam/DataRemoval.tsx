import { useMemo, useState } from "react";
import { Search, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { dataGroups } from "@/lib/kam/dataRemoval";
import { useKam } from "@/lib/kam/store";

export function DataRemoval({ onRemoved }: { onRemoved: () => void }) {
  const { data, removeDatasets, clearImports } = useKam();
  const groups = useMemo(() => dataGroups(data), [data]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<"selected" | "all" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const query = search.trim().toLocaleLowerCase();
  const visible = groups.filter((g) => `${g.company} ${g.customerId} ${g.year} ${g.source}`.toLocaleLowerCase().includes(query));
  const active = selected.filter((key) => groups.some((g) => g.key === key));
  const allVisible = visible.length > 0 && visible.every((g) => active.includes(g.key));
  const chosen = groups.filter((g) => active.includes(g.key));
  const remove = async () => {
    setBusy(true); setError(""); setSuccess("");
    try {
      if (confirm === "all") await clearImports();
      else await removeDatasets(active);
      setSuccess(confirm === "all" ? "All company data, including demo data, was removed." : `${active.length} company-year datasets removed. Other data was kept.`);
      setSelected([]); setConfirm(null); onRemoved();
    } catch { setError("Could not remove the saved data. Please try again."); }
    finally { setBusy(false); }
  };
  return <section className="min-w-0 space-y-3 border-t pt-4" aria-label="Manage saved data">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">Manage saved data</h3><span className="text-xs text-muted-foreground">{groups.length} company-year datasets · Demo included</span></div>
    <div className="relative"><Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" /><Input aria-label="Search saved data" placeholder="Search company, year or demo…" value={search} disabled={busy || !!confirm} onChange={(e) => setSearch(e.target.value)} className="pl-9" /></div>
    <div className="flex items-center justify-between gap-2 text-sm"><label className="flex items-center gap-2"><Checkbox checked={allVisible} disabled={!visible.length || busy || !!confirm} onCheckedChange={(checked) => setSelected((old) => checked ? [...new Set([...old, ...visible.map((g) => g.key)])] : old.filter((key) => !visible.some((g) => g.key === key)))} />Select search results</label><span className="text-muted-foreground">{active.length} selected</span></div>
    <div className="max-h-60 overflow-y-auto rounded-md border">
      {visible.length === 0 && <p className="p-4 text-sm text-muted-foreground">{groups.length ? "No matching data." : "No saved data. Import a workbook to add companies."}</p>}
      {visible.map((g) => <label key={g.key} className="flex cursor-pointer items-center gap-3 border-b p-3 last:border-b-0 hover:bg-muted/40"><Checkbox aria-label={`Select ${g.company} ${g.year}`} checked={active.includes(g.key)} disabled={busy || !!confirm} onCheckedChange={(checked) => setSelected((old) => checked ? [...old, g.key] : old.filter((key) => key !== g.key))} /><div className="min-w-0 flex-1"><p className="break-words text-sm font-medium">{g.company}</p><p className="text-xs text-muted-foreground">{g.year} · {g.source} · {g.count.toLocaleString()} data lines</p></div><span className="shrink-0 text-sm font-semibold">{g.year}</span></label>)}
    </div>
    {confirm ? <div className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 p-3">
      <p className="text-sm font-medium">{confirm === "all" ? "Remove ALL company data, including demo data?" : `Remove ${active.length} selected company-year datasets?`}</p>
      {confirm === "selected" && <ul className="max-h-28 overflow-y-auto text-xs text-muted-foreground">{chosen.map((g) => <li key={g.key}>{g.company} · {g.year}</li>)}</ul>}
      <p className="text-xs text-muted-foreground">This removes saved data from this browser. You can import your workbook again later.</p>
      <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={busy} onClick={() => setConfirm(null)}>Cancel</Button><Button variant="destructive" size="sm" disabled={busy} onClick={() => void remove()}><Trash2 className="h-4 w-4" />{busy ? "Removing…" : "Confirm removal"}</Button></div>
    </div> : <div className="flex flex-wrap gap-2"><Button variant="destructive" size="sm" disabled={!active.length || busy} onClick={() => { setConfirm("selected"); setSuccess(""); }}><Trash2 className="h-4 w-4" />Remove selected data</Button><Button variant="outline" size="sm" disabled={!groups.length || busy} onClick={() => { setConfirm("all"); setSuccess(""); }}><Trash2 className="h-4 w-4" />Remove all data</Button></div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{success && <p role="status" className="text-sm text-success">{success}</p>}
  </section>;
}