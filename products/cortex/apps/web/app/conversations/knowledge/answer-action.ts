"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { answerKnowledge, ApiError, type KnowledgeAnswer } from "@/lib/api";
import { readSession, sessionCookie } from "@/lib/session";

export type AnswerState = { result: KnowledgeAnswer | null; message?: string };

export async function submitAnswer(_state: AnswerState, formData: FormData): Promise<AnswerState> {
  if (!readSession((await cookies()).get(sessionCookie)?.value)) redirect("/sign-in");
  const query = String(formData.get("question") ?? "").trim();
  if (!query || query.length > 500) return { result: null, message: "Enter a question of 1 to 500 characters." };
  try {
    const response = await answerKnowledge(query);
    return response.result
      ? { result: response.result }
      : { result: null, message: "No matching knowledge was found. No model was called." };
  } catch (error) {
    if (error instanceof ApiError && error.kind === "unauthorized") redirect("/sign-in?error=session");
    const messages: Partial<Record<ApiError["kind"], string>> = {
      knowledge_changed: "This page changed during retrieval. Ask again for the current version.",
      brain_disabled: "Knowledge answers are not enabled.",
      timeout: "The answer took too long. Try again shortly.",
      rejected: "The model could not answer this question.",
      invalid_response: "The answer service returned an invalid response. Try again shortly.",
      unavailable: "The answer service is temporarily unavailable. Try again shortly.",
    };
    return { result: null, message: error instanceof ApiError ? messages[error.kind] ?? "The answer could not be completed." : "The answer could not be completed." };
  }
}
