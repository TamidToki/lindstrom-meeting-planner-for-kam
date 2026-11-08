import { createContext } from "react";
import type { Dataset } from "./data";
import type { Band, findCustomer } from "./metrics";

export type Attendee = "procurement" | "sustainability" | "operations";
export type Priority = "cost" | "co2" | "water" | "recycling" | "hygiene";

export type State = {
  year: string;
  customerId: string;
  excluded: number[];
  bands: Record<string, Band>;
  attendees: Attendee[];
  priorities: Priority[];
  hiddenSlides: string[];
  started: boolean;
};

export type KamState = State & {
  data: Dataset;
  years: string[];
  setYear: (year: string) => void;
  importData: (data: Dataset) => Promise<void>;
  clearImports: () => Promise<void>;
  removeDatasets: (keys: string[]) => Promise<void>;
  hasImports: boolean;
  dataReady: boolean;
  customer: ReturnType<typeof findCustomer>;
  band: Band;
  excludedSet: Set<number>;
  setCustomer: (id: string) => void;
  toggleExcluded: (ids: number[], exclude: boolean) => void;
  clearExcluded: () => void;
  setBand: (band: Band | null) => void;
  toggleAttendee: (attendee: Attendee) => void;
  togglePriority: (priority: Priority) => void;
  toggleSlide: (id: string) => void;
  startSample: () => void;
  isSample: boolean;
};

// Keep context identity independent of the provider's Fast Refresh boundary.
export const KamContext = createContext<KamState | null>(null);