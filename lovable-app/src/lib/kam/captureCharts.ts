import type { Slide } from "./story";

/** Wait for off-screen, non-animated charts before print or local capture. */
export async function readyDeckCharts(root: HTMLElement, slides: Slide[]) {
  await document.fonts.ready;
  const expected = slides.filter((s) => s.chart);
  for (let attempt = 0; attempt < 120; attempt++) {
    const nodes = Array.from(root.querySelectorAll<HTMLElement>("[data-chart-slide]"));
    const ready = expected.every((slide) => {
      const node = nodes.find((n) => n.dataset['chartSlide'] === slide.id);
      const svg = node?.querySelector("svg");
      return svg && svg.getBoundingClientRect().width > 0 && svg.getBoundingClientRect().height > 0
        && svg.querySelector(".recharts-line-curve, .recharts-rectangle, .recharts-sector");
    });
    if (ready) return nodes;
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  }
  throw new Error("The slide graphs are not ready. Please try again.");
}

export async function captureDeckCharts(root: HTMLElement, slides: Slide[]) {
  const nodes = await readyDeckCharts(root, slides);
  const { toPng } = await import("html-to-image");
  const images: Record<string, string> = {};
  for (const slide of slides) {
    if (!slide.chart) continue;
    const node = nodes.find((n) => n.dataset['chartSlide'] === slide.id);
    if (!node) throw new Error(`Missing graph for ${slide.title}`);
    images[slide.id] = await toPng(node, { pixelRatio: 2, skipFonts: true });
  }
  return images;
}