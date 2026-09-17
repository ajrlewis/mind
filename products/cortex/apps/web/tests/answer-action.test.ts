// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";

const { answer, session } = vi.hoisted(() => ({ answer: vi.fn(), session: vi.fn(() => true) }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => ({ value: "signed-session" }) }) }));
vi.mock("next/navigation", () => ({ redirect: (path: string) => { throw new Error(`redirect:${path}`); } }));
vi.mock("@/lib/session", () => ({ readSession: session, sessionCookie: "cortex-session" }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, answerKnowledge: answer };
});
import { ApiError } from "@/lib/api";
import { submitAnswer } from "@/app/conversations/knowledge/answer-action";

function form(question: string) { const data = new FormData(); data.set("question", question); return data; }
afterEach(() => { vi.clearAllMocks(); session.mockReturnValue(true); });

it("requires a session and valid question before backend access", async () => {
  session.mockReturnValueOnce(false);
  await expect(submitAnswer({ result: null }, form("policy"))).rejects.toThrow("redirect:/sign-in");
  expect((await submitAnswer({ result: null }, form(" "))).message).toMatch(/1 to 500/);
  expect(answer).not.toHaveBeenCalled();
});

it("returns a transient answer or a safe empty result", async () => {
  const result = { answer: "Synthetic", reference: { page_id: "id", page_version_id: "version", title: "Policy", path: "policy", source_titles: ["Memo"] }, synthetic: true };
  answer.mockResolvedValueOnce({ result }).mockResolvedValueOnce({ result: null });
  expect(await submitAnswer({ result: null }, form(" policy "))).toEqual({ result });
  expect(answer).toHaveBeenCalledWith("policy");
  expect((await submitAnswer({ result: null }, form("missing"))).result).toBeNull();
});

it.each(["knowledge_changed", "brain_disabled", "timeout", "rejected", "invalid_response", "unavailable"] as const)("shows a safe %s failure", async (kind) => {
  answer.mockRejectedValue(new ApiError(kind));
  const result = await submitAnswer({ result: null }, form("private question"));
  expect(result.result).toBeNull();
  expect(result.message).not.toContain("private question");
});
