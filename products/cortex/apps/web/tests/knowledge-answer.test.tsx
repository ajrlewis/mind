import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const { state } = vi.hoisted(() => ({ state: { current: { result: null } as unknown } }));
vi.mock("react", async () => {
  const actual = await vi.importActual<typeof import("react")>("react");
  return { ...actual, useActionState: () => [state.current, vi.fn(), false] };
});
vi.mock("@/app/conversations/knowledge/answer-action", () => ({ submitAnswer: vi.fn() }));
import { KnowledgeAnswer } from "@/components/knowledge-answer";

afterEach(cleanup);
it("renders generated and retrieved text inert with a visible version reference", () => {
  state.current = { result: { answer: "<script>alert(1)</script>", synthetic: true, references: [{ label: "1", page_id: "id", page_version_id: "version-1", title: "<img src=x>", path: "policy", source_titles: ["Visible memo"] }, { label: "2", page_id: "id-2", page_version_id: "version-2", title: "Second page", path: "second", source_titles: [] }] } };
  render(<KnowledgeAnswer />);
  const article = screen.getByRole("article", { name: "Knowledge answer" });
  expect(article).toHaveTextContent("Synthetic local model answer");
  expect(article).toHaveTextContent("PageVersion: version-1");
  expect(article).toHaveTextContent("PageVersion: version-2");
  expect(article).toHaveTextContent("Visible memo");
  expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
  expect(document.querySelector("script, img")).toBeNull();
});
