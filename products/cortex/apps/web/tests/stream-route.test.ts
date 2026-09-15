// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => ({ value: "signed-session" }) }),
}));
vi.mock("@/lib/session", () => ({
  readSession: () => true,
  sessionCookie: "cortex-session",
}));
vi.mock("@/lib/env", () => ({
  env: () => ({
    CORTEX_API_URL: "http://cortex-api.test",
    CORTEX_API_BEARER_TOKEN: "server-secret",
  }),
}));

import { POST } from "@/app/api/conversations/[id]/turns/stream/route";

const context = { params: Promise.resolve({ id: "conversation/id" }) };
const request = () =>
  new Request("http://web.test/api/conversations/id/turns/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: "synthetic content" }),
  });

describe("conversation stream proxy", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("injects server auth, encodes exactly, and forwards validated frames", async () => {
    const body =
      'event: delta\ndata: {"text":"one"}\n\n' +
      'event: error\ndata: {"error":"model_timeout"}\n\n';
    const fetcher = vi.fn().mockResolvedValue(
      new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    );
    vi.stubGlobal("fetch", fetcher);

    const response = await POST(request(), context);
    expect(await response.text()).toBe(body);
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("cache-control")).toBe("no-cache, no-store");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(fetcher).toHaveBeenCalledWith(
      "http://cortex-api.test/conversations/conversation%2Fid/turns/stream",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        body: JSON.stringify({ content: "synthetic content" }),
        headers: {
          Authorization: "Bearer server-secret",
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
      }),
    );
  });

  it.each([
    ['event: delta\ndata: {"text":"one"}', "abrupt stream"],
    ['event: delta\ndata: {"text":""}\n\n', "malformed stream"],
  ])("maps %s safely", async (body) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(body, { headers: { "Content-Type": "text/event-stream" } }),
      ),
    );
    const response = await POST(request(), context);
    const text = await response.text();
    expect(text).toContain('event: error\ndata: {"error":"conversation_error"}');
    expect(text).not.toContain("server-secret");
    expect(text).not.toContain("synthetic content");
  });
});
