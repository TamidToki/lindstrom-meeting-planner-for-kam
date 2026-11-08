import type { Slide } from "./story";
import { ATTENDEES, type Attendee } from "./store";

export async function exportPptx(customerName: string, summary: string, slides: Slide[], attendees: Attendee[], aiSession?: string, isSample = false, chartImages: Record<string, string> = {}) {
  const { default: PptxGenJS } = await import("pptxgenjs");
  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_WIDE";
  const BG = "00205B";
  const FG = "FFFFFF";
  const ACC = "4FB3E8";
  const banner = isSample ? "SYNTHETIC DEMO DATA · Not audited" : "DRAFT · KAM must review before customer use";

  const title = pptx.addSlide();
  title.background = { color: BG };
  title.addText(banner, { x: 0.6, y: 0.3, w: 12, fontSize: 10, color: ACC, bold: true });
  title.addText("Customer Value & Sustainability Review 2025", { x: 0.6, y: 1.6, w: 12, fontSize: 18, color: ACC, bold: true });
  title.addText(customerName, { x: 0.6, y: 2.2, w: 12, fontSize: 44, color: FG, bold: true, fontFace: "Arial" });
  title.addText(summary, { x: 0.6, y: 3.6, w: 11.5, h: 2.6, fontSize: 16, color: FG, valign: "top" });

  slides.forEach((s, i) => {
    const sl = pptx.addSlide();
    sl.background = { color: BG };
    sl.addText(banner, { x: 0.6, y: 0.12, w: 12, fontSize: 10, color: ACC, bold: true });
    sl.addText(s.kicker.toUpperCase(), { x: 0.6, y: 0.4, w: 8, fontSize: 12, color: ACC, bold: true, charSpacing: 3 });
    sl.addText(`${i + 1}`, { x: 12, y: 0.4, w: 0.8, fontSize: 12, color: FG, align: "right" });
    sl.addText(s.title, { x: 0.6, y: 0.8, w: 12, h: 1, fontSize: 30, color: FG, bold: true });
    const chartImage = chartImages[s.id];
    if (s.chart && !chartImage) throw new Error(`Missing graph for ${s.title}`);
    if (chartImage) sl.addImage({ data: chartImage, x: 5.3, y: 2.0, w: 7.4, h: 3.1 });
    s.big.forEach((b, j) => {
      sl.addText(b.value, { x: chartImage ? 0.6 : 0.6 + j * 4.1, y: chartImage ? 2.0 + j * 1.4 : 2.2, w: 4, h: 0.6, fontSize: 36, color: ACC, bold: true });
      sl.addText(b.label, { x: chartImage ? 0.6 : 0.6 + j * 4.1, y: chartImage ? 2.65 + j * 1.4 : 2.9, w: 4, h: 0.6, fontSize: 14, color: FG });
    });
    sl.addText(
      s.bullets.map((b) => ({ text: b, options: { bullet: true } })),
      { x: chartImage ? 5.3 : 0.6, y: chartImage ? 5.3 : s.big.length ? 3.9 : 2.2, w: chartImage ? 7.4 : 12, h: chartImage ? 1.7 : 3, fontSize: chartImage ? 14 : 18, color: FG, valign: "top", paraSpaceAfter: 8 },
    );
    const notes = attendees
      .flatMap((a) => (s.talking[a] ?? []).map((t) => `[${ATTENDEES.find((x) => x.id === a)?.label}] ${t}`))
      .join("\n");
    if (notes) sl.addNotes(notes);
  });

  if (aiSession) {
    const qa = pptx.addSlide();
    qa.background = { color: BG };
    qa.addText("AI DATA Q&A (PREP NOTES)", { x: 0.6, y: 0.4, w: 12, fontSize: 12, color: ACC, bold: true });
    qa.addText("TEXT NOT VERIFIED · PREP NOTES ONLY", { x: 0.6, y: 0.75, w: 4.2, h: 0.35, fontSize: 10, bold: true, color: BG, fill: { color: ACC }, align: "center", valign: "middle" });
    qa.addText(aiSession.slice(0, 2500), { x: 0.6, y: 1.25, w: 12, h: 5.6, fontSize: 11, color: FG, valign: "top" });
    qa.addText("Pasted AI notes are unverified and did not alter any underlying data, calculations, or review decisions.", { x: 0.6, y: 6.95, w: 12, fontSize: 9, color: FG, italic: true });
    qa.addNotes(aiSession);
  }

  await pptx.writeFile({ fileName: `${customerName.replace(/\s+/g, "_")}_review_2025_DRAFT.pptx` });
}
