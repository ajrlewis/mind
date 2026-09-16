import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { state } = vi.hoisted(() => ({ state: { current: { evidence: null, status: "idle" } as unknown } }));
vi.mock("react", async () => {
  const actual = await vi.importActual<typeof import("react")>("react");
  return { ...actual, useActionState: () => [state.current, vi.fn(), false] };
});
vi.mock("@/app/conversations/knowledge/actions", () => ({ submitLookup: vi.fn() }));
import { EvidenceLookup } from "@/components/evidence-lookup";

describe("knowledge evidence", () => {
  afterEach(cleanup);
  it("renders retrieved HTML and Markdown as inert text outside messages", () => {
    state.current = { status: "found", evidence: { page_id: "10000000-0000-4000-8000-000000000001", page_version_id: "20000000-0000-4000-8000-000000000001", title: "Northstar policy", path: "/policy", source_titles: ["Project Orion operating update"], snippet: "<img src=x onerror=alert(1)>", content_markdown: "# Policy\n<script>window.secret=1</script>" } };
    render(<EvidenceLookup />);
    expect(screen.getByRole("article", { name: "Knowledge evidence" })).toHaveTextContent("Project Orion operating update");
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(screen.getByText(/<script>window.secret=1<\/script>/)).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector(".messages")).toBeNull();
  });
  it("shows safe empty and failure states", () => {
    state.current = { status: "empty", evidence: null, message: "No matching knowledge was found." };
    const view = render(<EvidenceLookup />);
    expect(screen.getByRole("status")).toHaveTextContent("No matching knowledge was found.");
    state.current = { status: "error", evidence: null, message: "Knowledge lookup is temporarily unavailable." };
    view.rerender(<EvidenceLookup />);
    expect(screen.getByRole("status")).toHaveTextContent("Knowledge lookup is temporarily unavailable.");
    expect(screen.queryByRole("article")).toBeNull();
  });
});
