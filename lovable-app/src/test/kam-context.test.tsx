import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KamContext } from "@/lib/kam/context";
import { KamProvider } from "@/lib/kam/store";

afterEach(() => {
  cleanup();
  vi.doUnmock("@/lib/kam/context");
  vi.resetModules();
});

describe("KAM context across live updates", () => {
  it("connects a reloaded consumer to an already-mounted provider", async () => {
    // Reload the store while retaining the unchanged context dependency, as Vite does.
    vi.doMock("@/lib/kam/context", () => ({ KamContext }));
    vi.resetModules();
    const { useKam } = await import("@/lib/kam/store");
    function ReloadedConsumer() {
      const { customer } = useKam();
      return <span>{customer.customer_id}</span>;
    }
    render(<KamProvider><ReloadedConsumer /></KamProvider>);
    expect(await screen.findByText("", { selector: "span" })).toBeInTheDocument();
  });
});