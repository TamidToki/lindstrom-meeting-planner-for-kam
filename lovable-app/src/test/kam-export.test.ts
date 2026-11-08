import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Slide } from "@/lib/kam/story";
import { exportPptx } from "@/lib/kam/exportPptx";

const mocks = vi.hoisted(() => ({ addImage: vi.fn(), writeFile: vi.fn(), addNotes: vi.fn() }));
vi.mock("pptxgenjs", () => ({
  default: class {
    layout = "";
    addSlide() { return { addText: vi.fn(), addImage: mocks.addImage, addNotes: mocks.addNotes, background: {} }; }
    writeFile = mocks.writeFile;
  },
}));

const slide: Slide = {
  id: "utilisation", title: "Utilisation", kicker: "Right-sizing", chart: "sites",
  big: [], bullets: [], tags: [], talking: { procurement: ["Review allocation"] },
};

describe("presentation graph export", () => {
  beforeEach(() => vi.clearAllMocks());
  it("embeds the supplied graph and preserves talking notes", async () => {
    const image = "data:image/png;base64,aGVsbG8=";
    await exportPptx("Customer", "Summary", [slide], ["procurement"], undefined, false, { utilisation: image });
    expect(mocks.addImage).toHaveBeenCalledWith(expect.objectContaining({ data: image }));
    expect(mocks.addNotes).toHaveBeenCalledWith(expect.stringContaining("Review allocation"));
    expect(mocks.writeFile).toHaveBeenCalledOnce();
    expect(mocks.writeFile).toHaveBeenCalledWith({ fileName: "Customer_review_2025_DRAFT.pptx" });
  });
  it("does not silently download a graph slide without its graph", async () => {
    await expect(exportPptx("Customer", "Summary", [slide], [])).rejects.toThrow("Missing graph");
    expect(mocks.writeFile).not.toHaveBeenCalled();
  });
});