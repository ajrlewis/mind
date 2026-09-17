// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
vi.mock("@/lib/env", () => ({ env: () => ({ CORTEX_API_URL: "http://api.test", CORTEX_API_BEARER_TOKEN: "server-secret" }) }));
import { ApiError, answerKnowledge, appendTurn, createConversation, getConversation, listConversations, lookupKnowledge } from "@/lib/api";

const summary = { id: "10000000-0000-4000-8000-000000000001", title: null, created_at: "2026-09-15T10:00:00Z", updated_at: "2026-09-15T10:00:00Z" };
const conversation = { ...summary, messages: [] };
describe("Cortex API transport", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("encodes each request, disables caching, bounds it, and keeps auth server-side", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(conversation), { status: 201 })).mockResolvedValueOnce(new Response(JSON.stringify({ conversations: [summary], limit: 100, offset: 0 }))).mockResolvedValueOnce(new Response(JSON.stringify(conversation))).mockResolvedValueOnce(new Response(JSON.stringify({ conversation, model: "synthetic", usage: null })));
    vi.stubGlobal("fetch", fetcher);
    await createConversation(); await listConversations(); await getConversation(summary.id); await appendTurn(summary.id, "hello");
    for (const call of fetcher.mock.calls) { expect(call[1]).toEqual(expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal), headers: expect.objectContaining({ Authorization: "Bearer server-secret" }) })); }
    expect(fetcher.mock.calls[3][1]).toEqual(expect.objectContaining({ method: "POST", body: JSON.stringify({ content: "hello" }), headers: { "Content-Type": "application/json", Authorization: "Bearer server-secret" } }));
  });
  it.each([[401,"unauthorized"],[404,"not_found"],[409,"conflict"]] as const)("maps HTTP %s safely", async (status, kind) => { vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("sensitive", { status }))); await expect(getConversation("id")).rejects.toEqual(new ApiError(kind)); });
  it.each([[422,"conversation_history_full","history_full"],[502,"model_rejected_request","rejected"],[503,"model_timeout","timeout"],[503,"model_unavailable","unavailable"],[502,"invalid_model_response","invalid_response"],[502,"conversation_error","unexpected"]] as const)("maps actionable API error %s/%s", async (status, code, kind) => { vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: code }), { status }))); await expect(appendTurn("id", "private text")).rejects.toEqual(new ApiError(kind)); try { await appendTurn("id", "private text"); } catch (error) { expect(String(error)).not.toContain("private text"); expect(String(error)).not.toContain("server-secret"); } });
  it("rejects malformed success and maps network failure", async () => { vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "bad" })))); await expect(createConversation()).rejects.toEqual(new ApiError("invalid_response")); vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("secret body"))); await expect(listConversations()).rejects.toEqual(new ApiError("unavailable")); });
  it("sends a bounded lookup through server auth and validates the response", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ result: null })));
    vi.stubGlobal("fetch", fetcher);
    await expect(lookupKnowledge("Northstar expenses")).resolves.toEqual({ result: null });
    expect(fetcher).toHaveBeenCalledWith("http://api.test/knowledge/lookup", expect.objectContaining({ method: "POST", body: JSON.stringify({ query: "Northstar expenses" }), cache: "no-store", headers: { "Content-Type": "application/json", Authorization: "Bearer server-secret" } }));
    fetcher.mockResolvedValue(new Response(JSON.stringify({ result: { title: "unsafe", content_markdown: "<script>x</script>" } })));
    await expect(lookupKnowledge("Northstar")).rejects.toEqual(new ApiError("invalid_response"));
  });
  it("validates answers and their server-selected PageVersion references", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ result: null })));
    vi.stubGlobal("fetch", fetcher);
    await expect(answerKnowledge("Northstar policy")).resolves.toEqual({ result: null });
    expect(fetcher).toHaveBeenCalledWith("http://api.test/knowledge/answer", expect.objectContaining({ method: "POST", body: JSON.stringify({ query: "Northstar policy" }), cache: "no-store", headers: { "Content-Type": "application/json", Authorization: "Bearer server-secret" } }));
    fetcher.mockResolvedValue(new Response(JSON.stringify({ result: { answer: "Invented", references: [{ page_version_id: "bad" }], synthetic: false } })));
    await expect(answerKnowledge("Northstar policy")).rejects.toEqual(new ApiError("invalid_response"));
    fetcher.mockResolvedValue(new Response(JSON.stringify({ result: { answer: "", references: [{ label: "1", page_id: summary.id, page_version_id: summary.id, title: "Policy", path: "policy", source_titles: [] }], synthetic: false } })));
    await expect(answerKnowledge("Northstar policy")).rejects.toEqual(new ApiError("invalid_response"));
  });
  it.each([[409, "knowledge_changed", "knowledge_changed"], [503, "brain_disabled", "brain_disabled"], [503, "brain_unavailable", "unavailable"], [502, "brain_malformed", "invalid_response"]] as const)("maps lookup %s/%s safely", async (status, code, kind) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: code, detail: "private" }), { status })));
    await expect(lookupKnowledge("private query")).rejects.toEqual(new ApiError(kind));
  });
});
