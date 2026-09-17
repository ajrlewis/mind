import { z } from "zod";

export const ChatMessage = z.object({
  content: z.string().min(1).max(8000),
  role: z.enum(["system", "user", "assistant"]),
});
export const ChatTurnRequest = z.object({
  messages: z.array(ChatMessage).min(1).max(50),
});
export const TokenUsage = z.object({
  input_tokens: z.number().int().gte(0),
  output_tokens: z.number().int().gte(0),
});
export const ChatTurnResponse = z.object({
  message: ChatMessage,
  model: z.string().min(1).max(100),
  usage: z.union([TokenUsage, z.null()]).optional(),
});
export const ValidationError = z
  .object({
    ctx: z.object({}).partial().passthrough().optional(),
    input: z.unknown().optional(),
    loc: z.array(z.union([z.string(), z.number()])),
    msg: z.string(),
    type: z.string(),
  })
  .passthrough();
export const HTTPValidationError = z
  .object({ detail: z.array(ValidationError) })
  .partial()
  .passthrough();
export const authorization = z.union([z.string(), z.null()]).optional();
export const ConversationSummary = z
  .object({
    created_at: z.string().datetime({ offset: true }),
    id: z.string().uuid(),
    title: z.union([z.string(), z.null()]),
    updated_at: z.string().datetime({ offset: true }),
  })
  .passthrough();
export const ConversationListResponse = z
  .object({
    conversations: z.array(ConversationSummary),
    limit: z.number().int(),
    offset: z.number().int(),
  })
  .passthrough();
export const ConversationMessageResponse = z
  .object({
    content: z.string(),
    created_at: z.string().datetime({ offset: true }),
    id: z.string().uuid(),
    role: z.string(),
    sequence: z.number().int(),
  })
  .passthrough();
export const ConversationResponse = z
  .object({
    created_at: z.string().datetime({ offset: true }),
    id: z.string().uuid(),
    messages: z.array(ConversationMessageResponse),
    title: z.union([z.string(), z.null()]),
    updated_at: z.string().datetime({ offset: true }),
  })
  .passthrough();
export const AppendTurnRequest = z.object({
  content: z.string().min(1).max(8000),
});
export const AppendTurnResponse = z
  .object({
    conversation: ConversationResponse,
    model: z.string(),
    usage: z.union([TokenUsage, z.null()]).optional(),
  })
  .passthrough();
export const HealthResponse = z
  .object({ service: z.string(), status: z.string() })
  .passthrough();
export const BrainDiagnosticResponse = z
  .object({
    dependency: z.string().optional().default("brain"),
    status: z.enum([
      "ok",
      "disabled",
      "unauthorized",
      "malformed",
      "unavailable",
      "error",
    ]),
  })
  .passthrough();
export const LookupRequest = z.object({ query: z.string().min(1).max(500) });
export const AnswerReference = z
  .object({
    page_id: z.string().uuid(),
    page_version_id: z.string().uuid(),
    path: z.string(),
    source_titles: z.array(z.string()),
    title: z.string(),
  })
  .passthrough();
export const AnswerResult = z
  .object({
    answer: z.string().min(1).max(32000),
    reference: AnswerReference,
    synthetic: z.boolean(),
  })
  .passthrough();
export const AnswerResponse = z
  .object({ result: z.union([AnswerResult, z.null()]) })
  .passthrough();
export const LookupResult = z
  .object({
    content_markdown: z.string(),
    page_id: z.string().uuid(),
    page_version_id: z.string().uuid(),
    path: z.string(),
    snippet: z.string(),
    source_titles: z.array(z.string()),
    title: z.string(),
  })
  .passthrough();
export const LookupResponse = z
  .object({ result: z.union([LookupResult, z.null()]) })
  .passthrough();
