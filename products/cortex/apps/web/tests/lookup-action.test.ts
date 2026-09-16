// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

const { lookup, session } = vi.hoisted(() => ({ lookup: vi.fn(), session: vi.fn(() => true) }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => ({ value: "signed-session" }) }) }));
vi.mock("next/navigation", () => ({ redirect: (path: string) => { throw new Error(`redirect:${path}`); } }));
vi.mock("@/lib/session", () => ({ readSession: session, sessionCookie: "cortex-session" }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, lookupKnowledge: lookup };
});
import { ApiError } from "@/lib/api";
import { submitLookup, type LookupState } from "@/app/conversations/knowledge/actions";

const initial: LookupState = { evidence: null, status: "idle" };
function form(query: string) { const data = new FormData(); data.set("query", query); return data; }

describe("knowledge lookup action", () => {
  afterEach(() => { vi.clearAllMocks(); session.mockReturnValue(true); });
  it("requires the signed session and rejects invalid input before backend access", async () => {
    session.mockReturnValueOnce(false);
    await expect(submitLookup(initial, form("Northstar"))).rejects.toThrow("redirect:/sign-in");
    expect((await submitLookup(initial, form("  "))).message).toMatch(/1 to 500/);
    expect(lookup).not.toHaveBeenCalled();
  });
  it("returns current evidence and empty results", async () => {
    const evidence = { page_id: "10000000-0000-4000-8000-000000000001", page_version_id: "20000000-0000-4000-8000-000000000001", title: "Project Orion", path: "/orion", snippet: "Synthetic", source_titles: ["Synthetic source"], content_markdown: "# Synthetic" };
    lookup.mockResolvedValueOnce({ result: { ...evidence, private_extra: "must not cross" } }).mockResolvedValueOnce({ result: null });
    expect(await submitLookup(initial, form(" Northstar "))).toEqual({ evidence, status: "found" });
    expect(lookup).toHaveBeenCalledWith("Northstar");
    expect((await submitLookup(initial, form("absent"))).status).toBe("empty");
  });
  it.each(["knowledge_changed", "brain_disabled", "unavailable", "invalid_response"] as const)("returns a safe %s message", async (kind) => {
    lookup.mockRejectedValue(new ApiError(kind));
    const result = await submitLookup(initial, form("private query"));
    expect(result.status).toBe("error");
    expect(result.evidence).toBeNull();
    expect(result.message).not.toContain("private query");
  });
});
