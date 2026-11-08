import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KamProvider, useKam } from "@/lib/kam/store";
import type { KamState } from "@/lib/kam/context";
import { sampleDataset } from "@/lib/kam/data";

const storage = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn().mockResolvedValue(undefined) }));
vi.mock("@/lib/kam/localDataset", () => ({ readLocalDataset: storage.read, saveLocalDataset: storage.save }));
let current: KamState;
function Consumer() { current = useKam(); return null; }
const mount = () => render(<KamProvider><Consumer /></KamProvider>);

beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); });
afterEach(cleanup);

describe("explicit session start", () => {
  it("ignores legacy started and never restores saved data on full load", async () => {
    localStorage.setItem("kam-assistant-v1", JSON.stringify({ started: true }));
    storage.read.mockResolvedValue(sampleDataset);
    mount();
    await waitFor(() => expect(current.started).toBe(false));
    expect(current.data.rows).toHaveLength(0);
    expect(storage.read).not.toHaveBeenCalled();
    expect(JSON.parse(localStorage.getItem("kam-assistant-v1") ?? "{}")).not.toHaveProperty("started");
  });
  it("starts with a fresh sample, stays started on rerender, but goes blank on remount", () => {
    const view = mount();
    act(() => current.startSample());
    expect(current.started).toBe(true);
    expect(current.data.rows).toEqual(sampleDataset.rows);
    expect(current.data).not.toBe(sampleDataset);
    view.rerender(<KamProvider><Consumer /></KamProvider>);
    expect(current.started).toBe(true);
    view.unmount();
    mount();
    expect(current.started).toBe(false);
    expect(current.data.rows).toHaveLength(0);
    expect(storage.save).not.toHaveBeenCalled();
  });
  it("starts with only the selected workbook, preserves previous saves, and goes blank on remount", async () => {
    const first = sampleDataset.rows[0];
    if (!first) throw new Error("Missing sample fixture row");
    const incoming = { ...structuredClone(sampleDataset), rows: [{ ...first, month: "2026-01" }] };
    const view = mount();
    await act(async () => current.importData(incoming));
    expect(current.started).toBe(true);
    expect(current.data.rows).toHaveLength(1);
    expect(current.data.rows[0]?.month).toBe("2026-01");
    expect(storage.save).toHaveBeenCalledWith(current.data, true);
    view.unmount();
    mount();
    expect(current.started).toBe(false);
    expect(current.data.rows).toHaveLength(0);
  });
});