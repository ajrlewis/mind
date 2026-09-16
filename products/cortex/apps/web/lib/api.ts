import "server-only";
import { z } from "zod";
import {
  AppendTurnResponse,
  ConversationListResponse,
  ConversationResponse,
  LookupResponse,
} from "./generated/api";
import { env } from "./env";

export type ApiErrorKind =
  | "unauthorized"
  | "not_found"
  | "conflict"
  | "history_full"
  | "rejected"
  | "timeout"
  | "unavailable"
  | "invalid_response"
  | "unexpected"
  | "knowledge_changed"
  | "brain_disabled";

export class ApiError extends Error {
  constructor(public kind: ApiErrorKind) {
    super(kind);
    this.name = "ApiError";
  }
}

const errorResponse = z.object({ error: z.string() });

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
): Promise<T> {
  const config = env();
  let response: Response;
  try {
    response = await fetch(`${config.CORTEX_API_URL}${path}`, {
      ...init,
      headers: {
        ...init.headers,
        Authorization: `Bearer ${config.CORTEX_API_BEARER_TOKEN}`,
      },
      cache: "no-store",
      signal: AbortSignal.timeout(35_000),
    });
  } catch (error) {
    throw new ApiError(error instanceof DOMException && error.name === "TimeoutError" ? "timeout" : "unavailable");
  }

  if (!response.ok) {
    let code = "";
    try {
      const parsed = errorResponse.safeParse(await response.json());
      if (parsed.success) code = parsed.data.error;
    } catch {}
    if (response.status === 401) throw new ApiError("unauthorized");
    if (response.status === 404) throw new ApiError("not_found");
    if (code === "knowledge_changed") throw new ApiError("knowledge_changed");
    if (code === "brain_disabled") throw new ApiError("brain_disabled");
    if (code === "brain_unavailable") throw new ApiError("unavailable");
    if (code === "brain_malformed") throw new ApiError("invalid_response");
    if (code === "brain_unauthorized" || code === "brain_error") throw new ApiError("unavailable");
    if (response.status === 409) throw new ApiError("conflict");
    if (code === "conversation_history_full") throw new ApiError("history_full");
    if (code === "model_rejected_request") throw new ApiError("rejected");
    if (code === "model_timeout") throw new ApiError("timeout");
    if (code === "model_unavailable") throw new ApiError("unavailable");
    if (code === "invalid_model_response") throw new ApiError("invalid_response");
    throw new ApiError("unexpected");
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("invalid_response");
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) throw new ApiError("invalid_response");
  return parsed.data;
}

export type Conversation = z.infer<typeof ConversationResponse>;
export type ConversationSummary = z.infer<typeof ConversationListResponse>["conversations"][number];
export type LookupEvidence = NonNullable<z.infer<typeof LookupResponse>["result"]>;

export const createConversation = () =>
  request("/conversations", ConversationResponse, { method: "POST" });
export const listConversations = (limit = 100, offset = 0) =>
  request(
    `/conversations?limit=${limit}&offset=${offset}`,
    ConversationListResponse,
  );
export const getConversation = (id: string) =>
  request(`/conversations/${encodeURIComponent(id)}`, ConversationResponse);
export const appendTurn = (id: string, content: string) =>
  request(`/conversations/${encodeURIComponent(id)}/turns`, AppendTurnResponse, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
export const lookupKnowledge = (query: string) =>
  request("/knowledge/lookup", LookupResponse, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
