import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
import { Composer } from "@/components/composer";

const encoder = new TextEncoder();
const frame = (event: string, data: object) => encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

function controlledFetch() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start(value) { controller = value; } });
  const fetcher = vi.fn().mockResolvedValue(new Response(stream, { headers: { "Content-Type": "text/event-stream" } }));
  vi.stubGlobal("fetch", fetcher);
  return { controller, fetcher };
}

function send(text = "Synthetic question") {
  fireEvent.change(screen.getByLabelText("Message Cortex"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

describe("streaming composer", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); refresh.mockClear(); });

  it("shows two transient deltas, prevents duplicate submit, and replaces them with canonical history", async () => {
    const { controller, fetcher } = controlledFetch();
    render(<Composer conversationId="synthetic-id" />);
    send();
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => { controller.enqueue(frame("delta", { text: "first " })); });
    expect(screen.getByLabelText("Unsaved response")).toHaveTextContent("first");
    await act(async () => { controller.enqueue(frame("delta", { text: "second" })); });
    expect(screen.getByLabelText("Unsaved response")).toHaveTextContent("first second");
    const conversation = {
      id: "00000000-0000-4000-8000-000000000001", title: null,
      created_at: "2026-09-15T10:00:00Z", updated_at: "2026-09-15T10:00:00Z",
      messages: [
        { id: "00000000-0000-4000-8000-000000000003", sequence: 2, role: "assistant", content: "canonical answer", created_at: "2026-09-15T10:00:00Z" },
        { id: "00000000-0000-4000-8000-000000000002", sequence: 1, role: "user", content: "Synthetic question", created_at: "2026-09-15T10:00:00Z" },
      ],
    };
    await act(async () => { controller.enqueue(frame("completed", { conversation, model: "synthetic", usage: null })); controller.close(); });
    expect(screen.queryByLabelText("Unsaved response")).not.toBeInTheDocument();
    expect(screen.getByText("canonical answer")).toBeInTheDocument();
    expect((screen.getByLabelText("Message Cortex") as HTMLTextAreaElement).value).toBe("");
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("preserves input and refreshes canonical history on conflict", async () => {
    const { controller } = controlledFetch();
    render(<Composer conversationId="synthetic-id" />);
    send();
    await act(async () => { controller.enqueue(frame("delta", { text: "partial" })); });
    await act(async () => { controller.enqueue(frame("error", { error: "conversation_conflict" })); controller.close(); });
    expect(screen.queryByLabelText("Unsaved response")).not.toBeInTheDocument();
    expect((screen.getByLabelText("Message Cortex") as HTMLTextAreaElement).value).toBe("Synthetic question");
    expect(screen.getByText(/Canonical history has been reloaded/)).toBeInTheDocument();
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("stops after a visible delta and preserves input", async () => {
    let signal!: AbortSignal;
    const fetcher = vi.fn().mockImplementation((_url, options: RequestInit) => {
      signal = options.signal!;
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(frame("delta", { text: "partial" }));
          signal.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
        },
      });
      return Promise.resolve(new Response(stream));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<Composer conversationId="synthetic-id" />);
    send();
    await waitFor(() => expect(screen.getByLabelText("Unsaved response")).toHaveTextContent("partial"));
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(signal.aborted).toBe(true);
    await waitFor(() => expect(screen.queryByLabelText("Unsaved response")).not.toBeInTheDocument());
    expect(screen.getByText("Stopped. Nothing was saved.")).toBeInTheDocument();
    expect((screen.getByLabelText("Message Cortex") as HTMLTextAreaElement).value).toBe("Synthetic question");
  });
});
