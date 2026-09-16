"use client";

import { useActionState } from "react";
import { submitLookup, type LookupState } from "@/app/conversations/knowledge/actions";

const initialState: LookupState = { evidence: null, status: "idle" };

export function EvidenceLookup() {
  const [state, action, pending] = useActionState(submitLookup, initialState);
  return <div className="knowledge-content"><p className="lede">Search authorized Brain pages. Evidence stays separate from conversation history.</p><form action={action} className="knowledge-form"><label htmlFor="knowledge-query">Search knowledge</label><input id="knowledge-query" name="query" maxLength={500} required autoComplete="off" /><button className="primary" type="submit" disabled={pending}>{pending ? "Searching…" : "Search"}</button></form><div aria-live="polite">{pending ? <p>Searching knowledge…</p> : state.message ? <p role="status">{state.message}</p> : null}</div>{!pending && state.evidence && <article className="evidence" aria-label="Knowledge evidence"><p className="eyebrow">Current page evidence</p><h2>{state.evidence.title}</h2><p className="evidence-path">{state.evidence.path}</p><h3>Sources</h3>{state.evidence.source_titles.length ? <ul>{state.evidence.source_titles.map((title, index) => <li key={`${title}-${index}`}>{title}</li>)}</ul> : <p>No visible sources.</p>}<h3>Search snippet</h3><p className="evidence-text">{state.evidence.snippet}</p><h3>Page content</h3><pre className="evidence-text">{state.evidence.content_markdown}</pre></article>}</div>;
}
