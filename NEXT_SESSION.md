# Next Session

## Status — 2026-09-17

The multi-Page answer slice is implemented on `feature/multi-page-knowledge-answer`.
`/knowledge/answer` searches for at most three authorized Pages, reads and validates every
current PageVersion before one model call, and returns ordered server-selected references with
caller-visible provenance. The model receives deterministic labeled blocks of at most 2,300
characters each (6,904 including separators), with untrusted Page fields encoded as data.
`/knowledge/lookup` remains a single-Page contract. The Knowledge view displays the reference
list, preserves the synthetic label, and keeps the answer transient.

Verification passed: Ruff, format, Pyright, 186 non-integration Python tests with 90.62%
coverage, 10 Brain and 11 Cortex PostgreSQL tests, both web lint/typecheck/unit/build suites,
contract generation and drift checks, Compose build and health, Northstar seed, three live
Cortex-to-Brain checks, and both Playwright suites (one Brain, three Cortex tests). The seeded
“Operating Partner” browser answer displayed three references. The Cortex client bundle scan
found no local bearer strings. Compose was stopped with its data volume retained.

## Objective

Make Cortex's evidence-backed answers useful when a question spans a small number of Brain
Pages. Extend the transient Knowledge answer flow to use at most three authorized current
Pages, with a visible PageVersion reference and caller-visible provenance for each Page used.
Keep retrieval bounded, model context untrusted, and conversation history untouched.

## Starting Point

PR #30 (`59794a1`, merged as `9609c81`) added authenticated `POST /knowledge/answer` and a
signed-session answer form at `/conversations/knowledge`. Cortex currently searches Brain's
public authorized interface for one hit, reads that Page, checks the current PageVersion,
and invokes the provider-neutral model once with a bounded excerpt. The response contains a
server-selected PageVersion reference and visible source titles. Empty or stale lookup never
invokes the model. The deterministic local model is labeled synthetic; answers disappear on
reload and never enter canonical conversation history. API, model-boundary, web, and seeded
Northstar tests cover the flow. PR #30 passed `quality`, `docker`, and `web` CI, including both
Playwright suites.

PR #31 (`506e0a9`, merged as `c9f97a7`) added this handoff to the repository. It changed no
runtime behavior and passed `quality`, `docker`, and `web` CI. The multi-Page answer flow below
is implemented in the current branch; CI has not run for it yet.

The local bearer still maps to one owner and one configured Brain authorization identity. It
does not enforce separate Brain permissions for multiple Cortex users. Compose was stopped
after earlier verification with its data volume retained. It was restarted for this slice.

Before changing code, read `AGENTS.md`, `.agents/WORKFLOW.md`, `.agents/ARCHITECTURE.md`,
`.agents/COMMANDS.md`, and `products/cortex/README.md`. Start from up-to-date `main` on a focused
branch. Update this handoff as implementation facts change.

## Next Bounded Slice

- Leave the existing single-Page `/knowledge/lookup` contract intact. For `/knowledge/answer`,
  request no more than three search hits through Brain's public authorized HTTP API and read
  each selected Page. Require every Page ID and current PageVersion to match its search hit;
  reject the whole answer safely if any selected Page changed or cannot be read. An empty
  search must return without a model call.
- Give each Page a stable reference label in a deterministic context layout. Set explicit
  per-Page and total character budgets within the existing 8,000-character model-message
  limit. Treat titles, paths, snippets, Markdown, and provenance as untrusted data with no
  instruction or tool authority. Invoke the configured provider-neutral model once; add no
  retry, agent runtime, or direct Brain database access.
- Return only server-selected references for the exact PageVersions supplied to the model,
  with only provenance visible to the caller. Do not accept model-generated IDs or links as
  references. Show the answer and its small reference list clearly in the Knowledge view,
  keeping the synthetic label and escaped text rendering. Keep answers transient and outside
  public user/assistant conversation messages.
- Add focused tests for two or three authorized Pages, empty search, a stale later Page,
  denied or malformed reads, context bounds and ordering, one model invocation, and response
  references matching validated Brain evidence. Extend the seeded Northstar browser flow to
  show multiple references without exposing credentials or hidden content. Preserve existing
  streaming and cancellation behavior.

## Verification

Run relevant `.agents/COMMANDS.md` checks for every changed boundary: Ruff, format, Pyright,
the PostgreSQL-backed Python suite with coverage, both web lint/typecheck/unit/build suites,
contract drift, Docker builds, Compose health and Northstar seeding, Cortex-to-Brain checks,
and both Playwright suites. Review the diff and CI results. Inspect rendered HTML, client
bundles, cookies, SSE frames, logs, fixtures, and generated artifacts for credentials, identity,
submitted content, provider payloads, hidden reasoning, unsafe HTML, and cross-product coupling.
Keep fixtures synthetic.

## Deferred

- Planned PDF, PowerPoint, SharePoint, and public web search Skills and connectors;
- multi-user Brain identity propagation and broader tool, approval, and agent workflows;
- durable run state, checkpoints, graph runtime, resumable streams, replay IDs, idempotency,
  background delivery, and partial-output persistence;
- retries, provider fallback/routing, quotas, analytics, production deployment, and
  production SSO.
