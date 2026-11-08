import { useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { sampleDataset, mergeDataset } from "./data";
import { saveLocalDataset } from "./localDataset";
import { emptyDataset, removeDataGroups } from "./dataRemoval";
import { defaultBandFor, findCustomer } from "./metrics";
import { PRESETS } from "./period";
import { KamContext, type KamState, type State, type Attendee, type Priority } from "./context";

export type { Attendee, Priority } from "./context";

export const ATTENDEES: { id: Attendee; label: string; hint: string }[] = [
  { id: "procurement", label: "Procurement / Finance", hint: "Cost, contract value, garment stock" },
  { id: "sustainability", label: "Sustainability Lead", hint: "CO₂, water, circularity evidence" },
  { id: "operations", label: "Operations / Site Manager", hint: "Availability, service, sites" },
];
export const PRIORITIES: { id: Priority; label: string }[] = [
  { id: "cost", label: "Cost reduction" },
  { id: "co2", label: "CO₂ emissions" },
  { id: "water", label: "Water conservation" },
  { id: "recycling", label: "Textile recycling / circularity" },
  { id: "hygiene", label: "Hygiene standards" },
];

const PRESET_IDS: string[] = PRESETS.map((p) => p.id);
const KEY = "kam-assistant-v1";
const initial: State = {
  year: "last12",
  customerId: findCustomer("", sampleDataset).customer_id,
  excluded: [],
  bands: {},
  attendees: ["procurement", "sustainability"],
  priorities: ["cost", "co2"],
  hiddenSlides: [],
  started: false,
};

export function KamProvider({ children }: { children: ReactNode }) {
  const [s, set] = useState<State>(initial);
  const [loaded, setLoaded] = useState(false);
  const [data, setData] = useState(emptyDataset);
  const savedThisSession = useRef(false);
  const dataReady = true;

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const { started: _legacyStarted, ...saved } = JSON.parse(raw);
        set({ ...initial, ...saved, started: false });
        localStorage.setItem(KEY, JSON.stringify(saved));
      }
    } catch {
      /* ignore corrupt storage */
    }
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (loaded) {
      const { started: _sessionOnly, ...saved } = s;
      localStorage.setItem(KEY, JSON.stringify(saved));
    }
  }, [s, loaded]);

  const value = useMemo<KamState>(() => {
    const customer = findCustomer(s.customerId, data);
    const siteIds = new Set(data.sites.filter((v) => v.customer_id === customer.customer_id).map((v) => v.site_id));
    const years = [...new Set(data.rows.filter((v) => siteIds.has(v.site)).map((v) => v.month.slice(0, 4)))].sort();
    const toggle = <T,>(arr: T[], v: T) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
    return {
      ...s,
      data,
      dataReady,
      years,
      year: years.includes(s.year) || s.year.startsWith("custom:") || PRESET_IDS.includes(s.year) ? s.year : "last12",
      setYear: (year) => set((p) => ({ ...p, year })),
      importData: async (incoming) => {
        const merged = mergeDataset(data, incoming);
        await saveLocalDataset(merged, !savedThisSession.current);
        savedThisSession.current = true;
        setData(merged);
        const first = incoming.customers[0];
        set((p) => ({ ...(p.started ? p : initial), started: true, customerId: first?.customer_id ?? "", year: [...new Set(incoming.rows.map((r) => r.month.slice(0, 4)))].sort().at(-1) ?? "last12" }));
      },
      hasImports: s.started && data.customers.length > 0,
      clearImports: async () => {
        const empty = emptyDataset();
        await saveLocalDataset(empty);
        setData(empty);
        set((p) => ({ ...p, customerId: "", year: "last12", excluded: [], bands: {} }));
      },
      removeDatasets: async (keys) => {
        const remaining = removeDataGroups(data, keys);
        await saveLocalDataset(remaining);
        setData(remaining);
        set((p) => ({ ...p, customerId: findCustomer(p.customerId, remaining).customer_id, year: "last12", excluded: p.excluded.filter((id) => remaining.rows.some((r) => r.id === id)) }));
      },
      customer,
      startSample: () => {
        const fresh = structuredClone(sampleDataset);
        setData(fresh);
        set({ ...initial, started: true, customerId: findCustomer("", fresh).customer_id });
      },
      isSample: sampleDataset.customers.some((c) => c.customer_id === customer.customer_id),
      band: s.bands[customer.customer_id] ?? defaultBandFor(customer.industry),
      excludedSet: new Set(s.excluded),
      setCustomer: (id) => set((p) => ({ ...p, customerId: id })),
      toggleExcluded: (ids, exclude) =>
        set((p) => {
          const next = new Set(p.excluded);
          ids.forEach((i) => (exclude ? next.add(i) : next.delete(i)));
          return { ...p, excluded: [...next] };
        }),
      clearExcluded: () => set((p) => ({ ...p, excluded: [] })),
      setBand: (b) =>
        set((p) => {
          const bands = { ...p.bands };
          if (b) bands[p.customerId] = b;
          else delete bands[p.customerId];
          return { ...p, bands };
        }),
      toggleAttendee: (a) => set((p) => ({ ...p, attendees: toggle(p.attendees, a) })),
      togglePriority: (x) => set((p) => ({ ...p, priorities: toggle(p.priorities, x) })),
      toggleSlide: (id) => set((p) => ({ ...p, hiddenSlides: toggle(p.hiddenSlides, id) })),
    };
  }, [s, data, dataReady]);

  return <KamContext.Provider value={value}>{children}</KamContext.Provider>;
}

export function useKam() {
  const v = useContext(KamContext);
  if (!v) throw new Error("useKam outside KamProvider");
  return v;
}
