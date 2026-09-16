"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, lookupKnowledge, type LookupEvidence } from "@/lib/api";
import { readSession, sessionCookie } from "@/lib/session";

export type LookupState = { evidence: LookupEvidence | null; status: "idle" | "found" | "empty" | "error"; message?: string };

export async function submitLookup(_state: LookupState, formData: FormData): Promise<LookupState> {
  if (!readSession((await cookies()).get(sessionCookie)?.value)) redirect("/sign-in");
  const query = String(formData.get("query") ?? "").trim();
  if (!query || query.length > 500) return { evidence: null, status: "error", message: "Enter a query of 1 to 500 characters." };
  try {
    const response = await lookupKnowledge(query);
    return response.result
      ? { evidence: {
          page_id: response.result.page_id,
          page_version_id: response.result.page_version_id,
          title: response.result.title,
          path: response.result.path,
          snippet: response.result.snippet,
          content_markdown: response.result.content_markdown,
          source_titles: response.result.source_titles,
        }, status: "found" }
      : { evidence: null, status: "empty", message: "No matching knowledge was found." };
  } catch (error) {
    if (error instanceof ApiError && error.kind === "unauthorized") redirect("/sign-in?error=session");
    const messages: Partial<Record<ApiError["kind"], string>> = {
      knowledge_changed: "This page changed during lookup. Search again for the current version.",
      brain_disabled: "Knowledge lookup is not enabled.",
      unavailable: "Knowledge lookup is temporarily unavailable. Try again shortly.",
      timeout: "Knowledge lookup took too long. Try again shortly.",
      invalid_response: "Knowledge lookup returned an invalid response. Try again shortly.",
    };
    const message = error instanceof ApiError ? messages[error.kind] : undefined;
    return { evidence: null, status: "error", message: message ?? "Knowledge lookup could not be completed. Try again shortly." };
  }
}
