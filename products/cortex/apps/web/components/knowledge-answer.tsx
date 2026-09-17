"use client";

import { useActionState } from "react";
import { submitAnswer, type AnswerState } from "@/app/conversations/knowledge/answer-action";

const initialState: AnswerState = { result: null };

export function KnowledgeAnswer() {
  const [state, action, pending] = useActionState(submitAnswer, initialState);
  return <div className="knowledge-content"><p className="lede">Ask a question using up to three authorized current Brain Pages. Answers are temporary.</p><form action={action} className="knowledge-form"><label htmlFor="knowledge-question">Ask Cortex</label><input id="knowledge-question" name="question" maxLength={500} required autoComplete="off" /><button className="primary" type="submit" disabled={pending}>{pending ? "Answering…" : "Ask"}</button></form><div aria-live="polite">{pending ? <p>Answering…</p> : state.message ? <p role="status">{state.message}</p> : null}</div>{!pending && state.result && <article className="evidence" aria-label="Knowledge answer"><p className="eyebrow">Answer from current pages</p>{state.result.synthetic && <p>Synthetic local model answer</p>}<p className="evidence-text">{state.result.answer}</p><h3>References</h3><ol>{state.result.references.map((reference) => <li key={reference.label}><p>[Page {reference.label}] {reference.title}</p><p className="evidence-path">{reference.path}</p><p>PageVersion: {reference.page_version_id}</p><h4>Visible sources</h4>{reference.source_titles.length ? <ul>{reference.source_titles.map((title, index) => <li key={`${title}-${index}`}>{title}</li>)}</ul> : <p>No visible sources.</p>}</li>)}</ol></article>}</div>;
}
