import { cookies } from "next/headers";
import { z } from "zod";
import { ConversationResponse } from "@/lib/generated/api";
import { env } from "@/lib/env";
import { readSession, sessionCookie } from "@/lib/session";

const requestSchema = z.object({ content: z.string().trim().min(1).max(8_000) }).strict();
const deltaSchema = z.object({ text: z.string().min(1) }).strict();
const completedSchema = z.object({ conversation: ConversationResponse, model: z.string().min(1).max(100), usage: z.object({ input_tokens: z.number().int().nonnegative(), output_tokens: z.number().int().nonnegative() }).strict().nullable() }).strict();
const errorSchema = z.object({ error: z.enum(["conversation_not_found", "conversation_conflict", "conversation_history_full", "model_timeout", "model_unavailable", "invalid_model_response", "model_rejected_request", "conversation_error"]) }).strict();
const safeError = 'event: error\ndata: {"error":"conversation_error"}\n\n';
const streamHeaders = { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no" };

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  if (!readSession((await cookies()).get(sessionCookie)?.value)) return Response.json({ error: "unauthorized" }, { status: 401 });
  let body: unknown; try { body = await request.json(); } catch { return Response.json({ error: "invalid_request" }, { status: 422 }); }
  const parsedRequest = requestSchema.safeParse(body); if (!parsedRequest.success) return Response.json({ error: "invalid_request" }, { status: 422 });
  const { id } = await context.params; const config = env(); const controller = new AbortController(); request.signal.addEventListener("abort", () => controller.abort(), { once: true }); const timeout = setTimeout(() => controller.abort(), 35_000);
  let backend: Response;
  try { backend = await fetch(`${config.CORTEX_API_URL}/conversations/${encodeURIComponent(id)}/turns/stream`, { method: "POST", cache: "no-store", signal: controller.signal, headers: { Authorization: `Bearer ${config.CORTEX_API_BEARER_TOKEN}`, "Content-Type": "application/json", Accept: "text/event-stream" }, body: JSON.stringify(parsedRequest.data) }); }
  catch { clearTimeout(timeout); return new Response(safeError, { headers: streamHeaders }); }
  if (!backend.ok || !backend.body || !backend.headers.get("content-type")?.toLowerCase().startsWith("text/event-stream")) { clearTimeout(timeout); controller.abort(); return new Response(safeError, { headers: streamHeaders }); }
  const stream = new ReadableStream<Uint8Array>({
    async start(output) {
      const reader = backend.body!.getReader(); const decoder = new TextDecoder(); const encoder = new TextEncoder(); let buffer = ""; let terminal = false;
      try { while (!terminal) { const { value, done } = await reader.read(); buffer += decoder.decode(value, { stream: !done }); let boundary: number; while ((boundary = buffer.indexOf("\n\n")) >= 0) { const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2); const event = frame.match(/^event: (delta|completed|error)\ndata: (.+)$/s); if (!event) throw new Error("invalid stream"); let data: unknown; try { data = JSON.parse(event[2]); } catch { throw new Error("invalid stream"); } const valid = event[1] === "delta" ? deltaSchema.safeParse(data).success : event[1] === "completed" ? completedSchema.safeParse(data).success : errorSchema.safeParse(data).success; if (!valid || terminal) throw new Error("invalid stream"); output.enqueue(encoder.encode(`${frame}\n\n`)); terminal = event[1] !== "delta"; } if (done) break; } if (!terminal) output.enqueue(encoder.encode(safeError)); }
      catch { if (!terminal) output.enqueue(encoder.encode(safeError)); }
      finally { clearTimeout(timeout); await reader.cancel().catch(() => undefined); output.close(); }
    }, cancel() { clearTimeout(timeout); controller.abort(); },
  });
  return new Response(stream, { headers: streamHeaders });
}
