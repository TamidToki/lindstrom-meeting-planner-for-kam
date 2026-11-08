import { useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { FileSpreadsheet, Upload, ShieldCheck, AlertTriangle, CheckCircle2, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useKam } from "@/lib/kam/store";
import type { ImportPreview } from "@/lib/kam/importWorkbook";
import { DataRemoval } from "./DataRemoval";

export function ExcelImport() {
  const { data, importData, dataReady, started } = useKam();
  const navigate = useNavigate();
  const removeFile = () => { setPreview(null); setFilename(""); setError(""); setSuccess(""); };
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [sheetName, setSheetName] = useState("Service_Activity");
  const [filename, setFilename] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const read = async (file: File) => {
    setPreview(null); setError(""); setSuccess(""); setFilename(file.name);
    if (!/\.(xlsx|xls)$/i.test(file.name)) { setError("Choose an Excel workbook (.xlsx or .xls)."); return; }
    setBusy(true);
    try {
      const { parseWorkbook } = await import("@/lib/kam/importWorkbook");
      const result = parseWorkbook(await file.arrayBuffer(), data);
      setPreview(result);
      setSheetName(result.sheets.find((s) => s.name === "Service_Activity")?.name ?? result.sheets[0]?.name ?? "");
    } catch { setError("This workbook could not be read. Check that it is a valid, unprotected Excel file."); }
    finally { setBusy(false); }
  };
  const sheet = preview?.sheets.find((s) => s.name === sheetName);
  const newRows = preview ? preview.data.rows.length - preview.duplicates : 0;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button variant="outline" disabled={!dataReady}><Upload className="h-4 w-4" /> Import Excel</Button></DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><FileSpreadsheet className="h-5 w-5 text-primary" /> Import company data</DialogTitle>
          <DialogDescription>Workbooks stay on this device. Nothing is sent to Microsoft or cloud storage.</DialogDescription>
        </DialogHeader>
        <input ref={input} type="file" accept=".xlsx,.xls" className="hidden" aria-label="Excel workbook" onChange={(e) => { const file = e.target.files?.[0]; if (file) void read(file); e.target.value = ""; }} />
        <div onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); const file = e.dataTransfer.files[0]; if (file && !busy) void read(file); }} className={`flex flex-col items-center gap-3 rounded-lg border-2 border-dashed p-7 text-center ${dragging ? "border-primary bg-primary/10" : "border-border bg-muted/30"}`}>
          {busy ? <Loader2 className="h-8 w-8 animate-spin text-primary" /> : <FileSpreadsheet className="h-8 w-8 text-primary" />}
          <p className="max-w-full break-all font-semibold">{busy ? "Reading workbook…" : filename || "Drop an Excel workbook here"}</p>
          <Button variant="outline" disabled={busy} onClick={() => input.current?.click()}><Upload className="h-4 w-4" /> {filename ? "Choose another workbook" : "Choose workbook"}</Button>
          {filename && !busy && <Button variant="ghost" size="sm" onClick={removeFile}><X className="h-4 w-4" /> Remove file</Button>}
          <span className="text-xs text-muted-foreground">.xlsx / .xls · Reference workbook worksheets and column names</span>
        </div>
        <p className="text-xs text-muted-foreground">Required: Customers, Sites, Products, Service_Activity, Customer_Impacts, Repairs. Optional: Service_Cycles, Laundries, Waste_Circularity, Industry_Priorities.</p>
        {!busy && <DataRemoval onRemoved={removeFile} />}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {success && <p role="status" className="flex items-center gap-2 text-sm text-success"><CheckCircle2 className="h-4 w-4" />{success}</p>}
        {preview && <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[["Companies", preview.data.customers.length], ["Years", preview.years.join(", ") || "—"], ["New data lines", newRows], ["Existing lines kept", preview.duplicates]].map(([label, value]) => <div key={label} className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 break-words text-lg font-bold">{value}</p></div>)}
          </div>
          <div className="text-sm"><p className="font-medium">{preview.errors.length ? `${preview.errors.length} validation errors — correct these before importing` : "Worksheet and column validation passed"}</p>
            {preview.errors.length > 0 && <ul role="alert" className="mt-2 max-h-40 space-y-1 overflow-y-auto text-destructive">{preview.errors.map((s) => <li key={s}>{s}</li>)}</ul>}
            {preview.warnings.length > 0 && <details className="mt-3" open><summary className="cursor-pointer font-medium text-warning"><AlertTriangle className="mr-1 inline h-4 w-4" />{preview.warnings.length} exceptions / notes</summary><ul className="mt-2 max-h-36 space-y-1 overflow-y-auto text-muted-foreground">{preview.warnings.map((s) => <li key={s}>{s}</li>)}</ul></details>}
            {preview.errors.length === 0 && preview.data.rows.length > 0 && newRows === 0 && !success && <div role="status" className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/30 bg-secondary p-3"><p className="font-medium">This workbook is already loaded. No new rows will be added; existing data is unchanged.</p><Button size="sm" variant="outline" onClick={() => { removeFile(); setOpen(false); }}>Return to account</Button></div>}
            {preview.duplicates > 0 && <p className="mt-2 text-muted-foreground">Matching month, site and product lines will be skipped. Existing data and account details will not be overwritten.</p>}
          </div>
          <div className="min-w-0 border-t pt-3">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">Workbook preview</h3><Select value={sheetName} onValueChange={setSheetName}><SelectTrigger className="w-64" aria-label="Preview worksheet"><SelectValue /></SelectTrigger><SelectContent>{preview.sheets.map((s) => <SelectItem key={s.name} value={s.name}>{s.name} · {s.count} rows</SelectItem>)}</SelectContent></Select></div>
            <div className="max-h-56 overflow-auto"><table className="w-full text-xs"><thead><tr>{sheet?.columns.map((c, i) => <th key={`${c}-${i}`} className="whitespace-nowrap border-b bg-muted p-2 text-left font-medium">{c}</th>)}</tr></thead><tbody>{sheet?.preview.map((r, i) => <tr key={i}>{sheet.columns.map((c, j) => <td key={`${c}-${j}`} className="max-w-64 truncate border-b p-2">{r[c] instanceof Date ? (r[c] as Date).toISOString().slice(0, 10) : String(r[c] ?? "")}</td>)}</tr>)}</tbody></table></div>
            <p className="mt-2 text-xs text-muted-foreground">Showing first {sheet?.preview.length ?? 0} of {sheet?.count ?? 0} rows.</p>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4"><span className="flex items-center gap-1.5 text-xs text-muted-foreground"><ShieldCheck className="h-4 w-4" /> Saved only in this browser on this device</span><Button disabled={busy || preview.errors.length > 0 || newRows === 0 || !!success} onClick={async () => { setBusy(true); setError(""); try { await importData(preview.data); setSuccess(`${newRows.toLocaleString()} data lines imported. Accounts and years are ready in the meeting steps.`); if (!started) { setOpen(false); void navigate({ to: "/" }); } } catch { setError("Your browser could not save the imported data. Free device storage or allow browser storage, then try again."); } finally { setBusy(false); } }}><CheckCircle2 className="h-4 w-4" />{busy ? "Saving…" : "Import validated data"}</Button></div>
        </>}
      </DialogContent>
    </Dialog>
  );
}