# Cortex

> Implementation status: the repository provides a FastAPI service, a minimal Next.js product
> conversation application, a typed HTTP client for Brain health and identity context, and a provider-neutral
> chat-model boundary plus durable authenticated conversations. The agent runtime and all other capabilities below remain target
> state unless explicitly documented otherwise in `.agents/ARCHITECTURE.md`.

## Implemented web conversation flow

The authenticated workspace also has a separate read-only Knowledge lookup page. Its server
action calls Cortex's public lookup endpoint with the server-only bearer and validates the
generated response contract. The browser receives only the returned evidence. Title, path,
source titles, snippet, and Page Markdown are rendered as escaped text; lookup results are not
conversation messages and are not retained after a page reload. Empty, changed, disabled,
unavailable, and malformed results have safe messages.

The same page can ask for a transient answer. Its signed server action calls authenticated
`POST /knowledge/answer`, validates the response, and displays an escaped answer beside a
ordered, server-selected PageVersion references and visible source titles. The deterministic local model
is labeled synthetic. Answers disappear on reload and never enter conversation history.

The Cortex Next.js application provides a minimal local authenticated conversation workspace. A
local user can sign in, create a conversation, watch a bounded streamed turn arrive, navigate
away, and reopen the backend's canonical ordered history. Conversation titles are not inferred
from message content; untitled conversations use a stable ID-based label. Empty, loading,
missing, conflict, history-full, timeout, unavailable, rejected, malformed-response, and
unexpected-failure states are explicit and safe.

The browser talks only to Next.js Server Components, route handlers, and server actions. Those
server-only modules call Cortex's public create/list/get/append HTTP API using checked-in Zod
validators generated from FastAPI OpenAPI. Requests are bounded, uncached, and never retry. The
API bearer, local password, and signed-session secret are never placed in client code or cookies;
the cookie contains only a signed opaque authentication marker and is HTTP-only, same-site lax, and secure when
served through HTTPS.

Host development uses `CORTEX_API_URL`, `CORTEX_API_BEARER_TOKEN`, `CORTEX_WEB_USER`,
`CORTEX_WEB_PASSWORD`, and `CORTEX_WEB_SESSION_SECRET`. Compose sets the API URL to the internal
`cortex-api` service while browsers use the published Cortex web port. These names and the
`cortex-session` cookie are separate from Brain. This is development authentication only;
production SSO, provisioning, roles, password management, shared Brain sessions,
automatic titles, retries, and optimistic messages remain deferred.

## Implemented durable conversations

Cortex owns a separate PostgreSQL database named `cortex`, Cortex-only SQLAlchemy metadata, and
an explicit Alembic lifecycle. Applications never migrate at startup. All `/conversations`
operations require the configured local bearer token, which maps server-side to one opaque owner;
identity is never accepted from requests. Missing and invalid credentials return the same safe
unauthorized response. Production identity remains deferred.

The API creates empty conversations, lists only the caller's conversations newest-first with
bounded pagination, reopens ordered public messages, and appends one model-backed turn. It holds
no transaction during the model call, then atomically publishes user and assistant messages with
an observed-version compare-and-swap. A stale writer conflicts; model or commit failures publish
neither message. Missing and cross-owner IDs are indistinguishable. Histories are capped at 50
model-input messages and content at 8,000 characters. Credentials, provider payloads, hidden
reasoning, exception text, and tool state are never persisted.

Checkpoints, tools, retries, editing, sharing, title generation, and agent-run state
remain deferred. `POST /chat/turn` stays stateless and unauthenticated for compatibility.

`POST /conversations/{id}/turns/stream` returns `text/event-stream` without replay IDs or automatic
reconnection. Ordered `delta` events contain only `{"text":"..."}`. One terminal `completed`
event contains the canonical conversation, model identity, and optional usage; a terminal `error`
contains one safe error code. Assistant output is capped at 32,000 characters. The service holds
no database transaction while streaming and publishes the complete user/assistant pair only after
a valid provider terminal event whose assistant content exactly matches the accumulated non-empty
deltas. Missing, duplicate, non-assistant, mismatched, post-terminal, and oversized output is
rejected. Disconnect, cancellation, invalid output, provider failure, or a stale commit publishes
neither message. The web proxy requires an SSE response, validates every frame, forwards aborts,
and shows partial content only in a dashed, explicitly unsaved transient region.

The hand-maintained SSE envelope is exactly `event: <delta|completed|error>`, followed by one
`data: <JSON>` line and a blank line. Immutable FastAPI schemas own all three JSON payloads because
OpenAPI does not describe event streams directly. Structured stream logs contain only the start or
safe terminal category, duration, and emitted character count; they exclude content, deltas,
provider data, credentials, and identity.

## Implemented model boundary

`cortex-ai` owns immutable provider-neutral message, response, streaming-delta/terminal, model
identity, optional token usage, and failure contracts. Its async `ChatModel` protocol exposes
streaming and non-streaming invocation;
provider SDK types do not cross the package boundary. `ChatTurnService` preserves ordered messages,
requires the final role to be `user`, invokes its injected model once, and accepts only an
`assistant` response.

`POST /chat/turn` is stateless. It accepts 1–50 `system`, `user`, or `assistant` messages, each with
1–8,000 non-whitespace characters, and returns one assistant message plus model identity and
optional token usage. Invalid request shapes and histories return stable HTTP 422 errors without
echoing content. Model timeout and unavailability return HTTP 503; rejection, invalid output, and
unexpected failure return distinct safe HTTP 502 error codes. Provider bodies, exception text,
credentials, prompts, and hidden reasoning are never returned.

`MODEL_BACKEND` selects `deterministic` (the default) or `openai`. Local, Compose, and CI execution
use `cortex-deterministic-v1`. It makes no network calls and emits
an explicitly synthetic response with deterministic word-count usage. It is a development and CI
test implementation, not an intelligent or production model. `GET /health` remains independent of
both Brain and model calls.

`DETERMINISTIC_STREAM_DELAY_SECONDS` defaults to zero. Local Compose sets it to 0.25 seconds so
browser tests can deterministically observe and cancel after the first of two synthetic deltas;
`CORTEX_DETERMINISTIC_STREAM_DELAY_SECONDS` can override that Compose-only test seam.

The production adapter uses the official OpenAI Python SDK's async streaming and non-streaming
Responses API.
Select it with `MODEL_BACKEND=openai` and set both `OPENAI_API_KEY` and `OPENAI_MODEL` to nonblank
values. `OPENAI_TIMEOUT_SECONDS` defaults to 30 seconds and accepts 0.1–120 seconds. Optional
`OPENAI_BASE_URL`, `OPENAI_ORGANIZATION`, and `OPENAI_PROJECT` settings support explicit endpoint
and account routing. The application constructs one shared client during application creation and
closes it on shutdown; clients injected directly into the adapter remain caller-owned.

Each turn sends the supplied `system`, `user`, and `assistant` messages in order with `store=false`.
The adapter accepts exactly one completed assistant text output, returning the provider's model
identifier and optional input/output token counts. Authentication, permission, and invalid-request
failures map to request rejection; rate limits and provider/server or connectivity failures map to
model unavailability; SDK timeouts map to model timeout. There are no Cortex or SDK retries,
fallback, startup probes, or health probes. Provider messages and response bodies never cross the
adapter.

The normal test suite is hermetic and does not use a credential. There is currently no live smoke
test; exercise a real account only by explicitly configuring the OpenAI settings and making a
`POST /chat/turn` request outside CI.

## Implemented Brain boundary

The first bounded knowledge workflow is `POST /knowledge/lookup`. A local authenticated Cortex
caller supplies a query (1–500 characters). Cortex asks Brain's public authorized `POST /search`
for one hit, then reads that Page through public `GET /pages/{id}`. It returns the current Page's
Markdown, search snippet, path, version ID, and visible provenance source titles. No hit returns
`{"result":null}`; a version change between search and read returns `knowledge_changed` so the
caller can retry. Brain credential, owner identity, raw upstream failures, and hidden model state
are absent from the response. This is read-only evidence retrieval, not a generated answer.

`POST /knowledge/answer` searches for at most three authorized hits and reads each current Page.
An empty search returns no answer without invoking the model; a changed or unreadable Page fails
the whole answer before invocation. Each Page has an ordered label and a 2,300-character context
block; the three blocks total at most 6,904 characters including separators, within the existing
8,000-character model-message limit. Titles, paths, snippets, Markdown, and provenance are
untrusted context. The service sends the question and context to the existing provider-neutral
model once and accepts only a bounded assistant response. Cortex builds displayed references from
verified PageVersions and caller-visible provenance, never from model output. The response holds
no owner or credential data, provider payloads, or hidden reasoning; it is not persisted.

This initial workflow was selected over document ingestion and onboarding actions because it
has a narrow read-only outcome and exercises Brain's existing authorization boundary. Its only
run state is the query, search hit, and Page response in one request; nothing is checkpointed or
added to public conversation history. The local Cortex bearer maps to one local owner and one
configured Brain credential. Per-user Brain identity propagation must be designed before adding
multiple Cortex users; the current credential must not be treated as their individual access.

`cortex-brain` is a Cortex-owned, typed `httpx` client for Brain's public `GET /health`,
`GET /auth/context`, `POST /search`, and `GET /pages/{id}` operations. It does not import Brain
packages or access Brain persistence.
The Cortex API constructs and closes the client at the application boundary and keeps its bearer
credential server-side.

Set `BRAIN_URL` and `BRAIN_API_KEY` together to enable the integration; omit both to run Cortex
independently. `BRAIN_CONNECT_TIMEOUT_SECONDS` (default 2, maximum 30) and
`BRAIN_READ_TIMEOUT_SECONDS` (default 5, maximum 60) bound requests. Partial configuration is an
application configuration error.

`GET /health` remains a local process check and never calls Brain. `GET /health/brain` calls both
Brain operations but returns only `{"dependency":"brain","status":"..."}`. Success is HTTP 200;
rejected credentials, malformed responses, and unexpected upstream statuses return HTTP 502 with
`unauthorized`, `malformed`, or `error`; disabled configuration and network/timeouts return HTTP
503 with `disabled` or `unavailable`. No raw body, exception, credential, or identity is returned.

Cortex is an AI agent runtime and application for performing knowledge work.

It provides the reasoning, conversation, tool use, workflow execution, context management and user-facing experience required for an AI agent to operate against company systems and organisational knowledge.

Cortex is deliberately **not the canonical knowledge store**.

Durable organisational knowledge, provenance, access-controlled retrieval and reusable Skill definitions belong in Brain.

A useful mental model is:

```text
                         User
                          │
                          ▼
                       Cortex
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
          Reasoning      Tools       Memory/
                                   Agent State
             │            │
             └──────┬─────┘
                    ▼
                  Brain
                    │
        knowledge + skills + search
```

Cortex should be thought of as:

> The runtime that understands a user's request, decides what needs to happen, retrieves the required knowledge and Skills, uses tools, performs the work, and returns the result.

Brain stores what the organisation knows and how reusable work should be performed.

Cortex actually performs the work.

---

# Core responsibilities

Cortex owns:

* conversation
* reasoning
* agent orchestration
* tool selection
* tool execution
* external connectors
* workflow execution
* Skill execution
* context construction
* model interaction
* streaming
* approvals
* user interaction
* transient agent state

Brain owns:

* Sources
* Pages
* PageVersions
* provenance
* search
* authorization over stored knowledge
* Skills
* SkillVersions

The boundary should remain explicit.

```text
Brain knows.

Cortex thinks and acts.
```

---

# Example

Suppose the user asks:

> Ingest these company PDFs and then tell me the current expenses policy.

Cortex might:

```text
User
  ↓
Cortex
  ↓
get_skill("ingest") from Brain
  ↓
read local PDFs
  ↓
extract / interpret contents
  ↓
create Sources in Brain
  ↓
create Pages / PageVersions in Brain
  ↓
Brain indexes them
  ↓
search Brain for expenses policy
  ↓
reason over retrieved knowledge
  ↓
answer user with provenance
```

Brain does not autonomously perform those steps.

Cortex does.

---

# Architecture

Cortex is composed of two major parts:

```text
Cortex
├── Web application
└── Agent backend
```

The recommended stack is:

## Frontend

* TypeScript
* React
* Next.js
* Vercel
* server-sent events or equivalent streaming transport
* modern component library where useful

## Backend

* Python 3.13+
* `uv`
* FastAPI
* LangGraph
* Pydantic v2
* httpx
* provider-neutral model abstractions
* structured tool interfaces
* PostgreSQL where durable Cortex state is required

The frontend and backend may live in the same repository but should remain cleanly separated.

---

# Repository structure

A target structure is:

```text
cortex/
├── apps/
│   ├── web/
│   └── api/
│
├── packages/
│   ├── agent/
│   ├── ai/
│   ├── tools/
│   ├── brain/
│   ├── auth/
│   ├── state/
│   ├── schemas/
│   └── observability/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── examples/
│   └── northstar/
│
├── docs/
│
├── .github/
│   └── workflows/
│
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
├── package.json
├── pnpm-lock.yaml
├── .env.example
└── README.md
```

The exact package structure may evolve.

Prefer responsibility-oriented boundaries over arbitrary technical layering.

---

# Agent runtime

`packages/agent` contains Cortex's core orchestration logic.

LangGraph should be used to model agent execution where graph/state semantics are useful.

Do not make every operation a graph node purely because LangGraph exists.

The agent runtime should own things such as:

* conversation state
* reasoning steps
* model invocation
* tool selection
* tool execution
* Skill retrieval
* Skill execution
* approval pauses
* continuation after tool calls
* response construction
* error recovery
* cancellation

The runtime should remain understandable.

Avoid deeply implicit agent behaviour that is difficult to inspect, test or reproduce.

---

# Agent state

Cortex needs explicit agent state.

Conceptually:

```text
AgentState
├── conversation_id
├── user
├── messages
├── active_task
├── selected_model
├── available_tools
├── retrieved_context
├── active_skill
├── tool_results
├── approvals
├── execution_metadata
└── status
```

Not all state must be persisted.

Differentiate between:

```text
transient execution state
durable conversation state
durable organisational knowledge
```

Durable organisational knowledge belongs in Brain.

Do not gradually turn Cortex into a second knowledge database.

---

# Conversations

Cortex provides a conversational interface similar in broad interaction style to products such as ChatGPT or Claude.

A Conversation contains a sequence of messages and agent runs.

Conceptually:

```text
Conversation
├── id
├── user_id
├── title
├── created_at
├── updated_at
└── metadata
```

Messages may represent:

```text
user
assistant
tool
system
```

The exact persistence model should support:

* reopening conversations
* streaming partial responses
* tool call history
* execution trace references
* cancellation
* retries where appropriate

Do not store hidden chain-of-thought.

Persist operationally useful traces, not private model reasoning.

---

# Models

All model-provider-specific behaviour belongs behind `packages/ai`.

The rest of Cortex should not directly depend on OpenAI, Anthropic or another provider SDK.

Expose interfaces such as:

```python
class ChatModel(Protocol):
    async def invoke(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
    ) -> ModelResponse:
        ...
```

Implementations may include:

```text
OpenAIChatModel
AzureOpenAIChatModel
AnthropicChatModel
```

Configuration selects the implementation.

Provider abstractions should support at least:

* streaming
* tool calling
* structured outputs
* usage metadata
* cancellation
* model identification

Do not prematurely create an elaborate universal LLM abstraction.

Support what Cortex actually needs.

---

# Tools

Tools are how Cortex interacts with the outside world.

Examples include:

```text
Brain tools
filesystem tools
web search
Microsoft 365
SharePoint
email
calendar
GitHub
internal APIs
```

Tools belong in `packages/tools`.

Each tool should have:

* stable name
* description
* typed input schema
* typed output where practical
* explicit authorization requirements
* clear error semantics

A tool should perform one understandable action.

Avoid giant tools such as:

```text
do_everything_in_sharepoint(...)
```

Prefer composable operations.

---

# Tool registry

Cortex should expose a clear Tool Registry to the agent runtime.

Conceptually:

```text
ToolRegistry
├── brain.search
├── brain.get_page
├── brain.get_skill
├── files.read
├── web.search
├── sharepoint.get_page
└── ...
```

The registry should allow tools to be:

* discovered
* enabled
* disabled
* filtered by user/session
* described to models
* invoked consistently

Tool registration should be explicit rather than based on hidden import magic.

---

# Brain integration

Brain is a first-class external dependency of Cortex.

All Brain-specific integration should live in `packages/brain`.

That package should provide a typed client over Brain's HTTP and/or MCP interfaces.

Conceptually:

```python
class BrainClient:
    async def search(...)
    async def get_page(...)
    async def get_skill(...)
    async def create_source(...)
    async def create_page(...)
    async def create_page_version(...)
```

Do not duplicate Brain's domain models or business logic inside Cortex.

Brain remains the source of truth for its own data.

Cortex should treat Brain as an external capability.

---

# Skills

Skills are stored in Brain and executed by Cortex.

A Skill is a Markdown document with YAML frontmatter.

For example:

```markdown
---
name: extract_markdown
description: Convert source data into canonical Markdown.
inputs:
  data:
    type: string
    required: true
outputs:
  markdown:
    type: string
---

# Extract Markdown

Convert the supplied source data into clean Markdown.

Preserve headings, lists, tables and meaningful structure.

Do not invent information.

## Source data

{{ data }}
```

Cortex should be able to retrieve this Skill and conceptually execute:

```text
extract_markdown(data=...)
```

Cortex owns the execution semantics.

Brain owns the Skill definition.

The planned canonical Skill families include PDF and PowerPoint extraction, SharePoint source
retrieval and ingestion, and public web search/research. Brain should store their reviewed
instructions; Cortex should provide the file, SharePoint, and web tools needed to execute them.
A Skill may describe a workflow using those tools, but it does not grant access to them. Each
addition needs a bounded input/output contract, authorization and provenance rules, and a
working tool boundary before it is advertised as available. The current default bundle does
not contain these Skills.

---

# Skill execution

Skill execution should generally follow:

```text
1. identify required Skill
2. retrieve current or requested SkillVersion
3. parse YAML frontmatter
4. validate required inputs
5. bind variables
6. expose required tools
7. construct model context
8. execute
9. validate output where possible
10. return result to calling workflow
```

A Skill should not necessarily map to exactly one model call.

Some Skills may be simple:

```text
input
  ↓
prompt
  ↓
output
```

Others may require:

```text
input
  ↓
reasoning
  ↓
tool
  ↓
reasoning
  ↓
tool
  ↓
result
```

The Skill describes the capability.

Cortex decides how to execute it using the agent runtime.

---

# Skill variables

Cortex is responsible for variable binding.

For a Skill containing:

```text
{{ data }}
{{ company }}
{{ materials }}
```

Cortex should ensure values exist before execution.

Do not rely solely on naïve string replacement.

Skill rendering should be deterministic and tested.

Use a deliberately small templating feature set initially.

Avoid allowing arbitrary code execution from Skill templates.

---

# Skill tools

Skills may declare tools in their YAML header.

For example:

```yaml
tools:
  - brain.search
  - brain.create_source
  - brain.create_page
  - brain.create_page_version
```

This should be treated as part of the Skill execution contract.

Cortex should resolve these names against its Tool Registry.

A Skill cannot grant itself permission to use a tool.

The available tools must also be allowed by the current Cortex execution context.

Conceptually:

```text
skill requests tool
        +
runtime allows tool
        +
user is authorized
        ↓
tool available
```

---

# Ingestion

Ingestion belongs to Cortex.

Brain may store an `ingest` Skill defining the desired process and data contract.

Cortex performs the work.

For a PDF-based ingestion flow:

```text
PDF
 ↓
Cortex reads file
 ↓
Cortex retrieves ingest Skill
 ↓
Cortex extracts Markdown
 ↓
Cortex identifies Source
 ↓
Cortex identifies canonical Page(s)
 ↓
Cortex creates/updates Brain objects
 ↓
Brain chunks + indexes PageVersion
```

Later the same execution pattern may support:

```text
SharePoint
email
web pages
GitHub
Notion
other APIs
```

Those connectors remain Cortex concerns.

Do not add SharePoint SDKs or Graph clients to Brain merely because Cortex uses them.

---

# Context construction

Context management is a core Cortex responsibility.

The runtime should deliberately construct model context from:

* recent conversation
* system instructions
* active Skill
* relevant Brain search results
* tool results
* execution state

Do not simply append everything indefinitely.

Cortex should eventually support context curation such as:

* recency windows
* conversation summarisation
* selective tool result retention
* retrieval on demand
* token budgeting

The context layer should remain inspectable and testable.

---

# Retrieval

Cortex does not implement Brain's retrieval engine.

It asks Brain for relevant knowledge.

For example:

```text
User question
    ↓
Cortex
    ↓
brain.search(...)
    ↓
authorized results
    ↓
Cortex constructs model context
    ↓
answer
```

Cortex may decide:

* when search is required
* what query to send
* whether to perform multiple searches
* how retrieved knowledge should be used

Brain decides:

* which content is searchable
* authorization
* ranking
* chunk retrieval
* provenance

---

# Provenance and citations

Cortex should preserve provenance received from Brain.

Where a response is based on Brain knowledge, the UI should eventually make the underlying Source or Page visible.

Conceptually:

```text
Answer
  ↓
Brain result
  ↓
PageVersion
  ↓
Source
```

Do not discard provenance during context conversion.

Where practical, model context should use stable reference identifiers so generated answers can map back to retrieved records.

---

# Authentication

Cortex owns user authentication for the product experience.

Initially, keep authentication simple.

The first implementation may use:

* development auth
* simple session-based auth
* Microsoft SSO when required for Microsoft integrations

Avoid spending substantial development time on speculative enterprise identity infrastructure.

Cortex needs a reliable concept of the current user.

Brain needs a reliable authorization context supplied by Cortex or another trusted mechanism.

---

# Microsoft identity

Microsoft SSO is likely useful because Cortex may eventually interact with Microsoft 365.

A future production flow may resemble:

```text
User
 ↓
Microsoft Entra login
 ↓
Cortex
 ↓
delegated Microsoft token / OBO flow
 ↓
Microsoft Graph / SharePoint
```

That architecture should remain possible.

It does not need to be fully implemented for the initial Northstar demonstration.

---

# Approvals

Some actions should require explicit user approval.

Examples:

```text
send email
delete file
modify external records
publish content
perform consequential action
```

The agent runtime should support an approval state:

```text
running
  ↓
approval_required
  ↓
approved / rejected
  ↓
continue / stop
```

Approval should be part of graph/state semantics rather than implemented as ad hoc blocking UI logic.

Read-only operations generally should not require approval unless a tool has a specific reason.

---

# Streaming

The frontend should receive agent progress incrementally.

Use streaming for:

* assistant text
* status changes
* tool calls
* tool results where appropriate
* approval requests
* completion
* errors

Server-Sent Events are a reasonable initial transport.

The UI should not need to wait for the entire agent execution to finish before showing useful information.

---

# Frontend

The frontend lives in `apps/web`.

It should initially provide:

* authentication
* conversation list
* chat interface
* streamed responses
* tool activity
* approval UI
* citations/provenance
* basic settings

Avoid building a giant administration product initially.

The primary product surface is the conversation with the agent.

---

# Agent activity UI

Cortex should show enough execution activity to make the agent understandable without exposing hidden chain-of-thought.

Useful activity includes:

```text
Searching company knowledge…
Reading Expenses Policy…
Using extract_markdown…
Creating Brain page…
Waiting for approval…
```

Do not expose raw private model reasoning.

Show actions and operational state instead.

---

# External connectors

Connector implementations belong in Cortex.

Examples may include:

```text
packages/tools/sharepoint
packages/tools/email
packages/tools/calendar
packages/tools/github
```

A connector translates an external system into typed tools.

Avoid allowing provider-specific models to leak throughout the agent runtime.

For example:

```text
SharePointClient
  ↓
SharePoint tools
  ↓
Tool Registry
  ↓
Agent
```

rather than Graph API calls scattered across workflows.

---

# Web search

Web search should be exposed as a normal Cortex tool.

The agent runtime should decide when external web knowledge is needed versus internal Brain knowledge.

Conceptually:

```text
brain.search
    → internal organisational knowledge

web.search
    → external public information
```

Keep the distinction clear.

---

# File handling

Cortex may receive user-uploaded files.

Files are execution inputs unless they are deliberately ingested into Brain.

For example:

```text
User uploads contract.pdf
       ↓
Cortex reads contract
       ↓
review_contract skill
       ↓
response
```

This does not automatically imply the contract becomes organisational knowledge.

If the user asks Cortex to ingest it:

```text
contract.pdf
   ↓
ingest skill
   ↓
Brain Source + PageVersion
```

This distinction prevents every temporary attachment from becoming permanent company knowledge.

---

# Persistence

Cortex should persist only the state it owns.

Likely durable Cortex data includes:

```text
users
conversations
messages
agent runs
tool executions
approval state
```

Do not duplicate:

```text
Brain Pages
Brain Sources
Brain Skills
Brain search indexes
```

References to Brain entities should use Brain IDs.

---

# Agent runs

Each substantial execution should have an identifiable AgentRun.

Conceptually:

```text
AgentRun
├── id
├── conversation_id
├── user_id
├── status
├── model
├── started_at
├── completed_at
├── error
└── metadata
```

Tool executions should be traceable to their AgentRun.

This supports:

* debugging
* observability
* cancellation
* retries
* metrics

Do not store hidden chain-of-thought in AgentRun records.

---

# Errors

Errors should be explicit and typed where practical.

Distinguish between:

```text
model failure
tool failure
authorization failure
validation failure
Brain failure
connector failure
user cancellation
approval rejection
```

The runtime should determine whether an error is:

```text
retryable
recoverable through another tool
fatal
```

Avoid swallowing tool exceptions and returning vague "something went wrong" messages internally.

The user-facing message can remain concise while structured error details are preserved operationally.

---

# Cancellation

Users should be able to stop long-running agent runs.

Cancellation should propagate through:

```text
frontend
  ↓
API
  ↓
AgentRun
  ↓
LangGraph execution
  ↓
model/tool calls where supported
```

Design for cancellation early rather than retrofitting it after long-running workflows exist.

---

# `packages/ai`

This package owns model-provider integrations.

It should provide provider-neutral abstractions around:

* chat completion
* streaming
* tool calling
* structured output
* model metadata

It should not contain:

* Brain search
* Skill storage
* ingestion workflows
* business workflows

---

# `packages/tools`

This package owns Cortex tools and connector adapters.

Examples:

```text
tools/
├── web/
├── files/
├── sharepoint/
├── email/
└── github/
```

Brain-facing tools may wrap `packages/brain`.

---

# `packages/brain`

This package owns communication with Brain.

It should contain:

* typed client
* Brain tool adapters
* response normalization
* authentication to Brain
* error mapping

Do not reproduce Brain's persistence or search implementation here.

---

# `packages/auth`

This package owns:

* current-user identity
* authentication
* sessions/tokens
* Microsoft SSO integration when implemented
* authorization context passed downstream

Do not intermingle authentication code with agent orchestration.

---

# `packages/state`

This package owns Cortex persistence.

It may contain:

* SQLAlchemy models
* repositories
* sessions
* conversation persistence
* AgentRun persistence
* approval persistence

If Cortex uses PostgreSQL, it should use its own schema/database ownership boundaries rather than reaching directly into Brain's tables.

Cortex must communicate with Brain through Brain's public interfaces.

---

# `packages/schemas`

Contains shared Pydantic contracts where useful.

Avoid creating a duplicate schema layer for every architectural layer.

Use explicit schemas when they clarify public boundaries.

---

# Observability

Observability is important because agent systems are difficult to debug without execution traces.

Use structured logging.

Every user request should have a correlation ID.

Conceptually:

```text
request_id
   ↓
conversation
   ↓
agent_run_id
   ↓
model calls
   ↓
tool calls
   ↓
Brain calls
```

Preserve correlation IDs when communicating with Brain.

Capture useful operational metrics such as:

* model
* latency
* token usage
* tool latency
* number of tool calls
* run status
* errors

Do not log sensitive content unnecessarily.

Do not persist chain-of-thought.

---

# Testing

Use:

```text
tests/unit
tests/integration
tests/e2e
```

Unit tests should cover:

* Skill parsing
* variable binding
* tool registry
* agent state transitions
* approval logic
* context construction
* error handling

Integration tests should cover:

* model abstraction with deterministic test providers
* Brain client
* database persistence
* streaming
* tools

End-to-end tests should cover real user flows.

Important scenarios include:

```text
ask question
  → search Brain
  → answer

upload PDF
  → execute ingest Skill
  → create Brain knowledge

request consequential action
  → approval
  → execute tool

cancel agent run
  → execution stops cleanly
```

Tests should not depend on expensive live model calls unless explicitly marked.

Provide fake/deterministic model providers for most automated testing.

---

# Example company

Cortex should use the same fictional `Northstar` organisation as Brain.

The public demo should not require Microsoft 365.

Initial tools can operate on local fixtures.

For example:

```text
examples/northstar/
├── files/
├── mock-email/
├── mock-calendar/
└── config/
```

Brain contains Northstar's durable knowledge.

Cortex provides the runtime that can work with it.

A useful demo might include:

```text
User:
"What is our expenses policy?"

Cortex:
→ searches Brain
→ answers with source provenance
```

Then:

```text
User:
"Ingest these updated policy documents."

Cortex:
→ gets ingest Skill
→ reads PDFs
→ creates updated Brain knowledge
```

Then:

```text
User:
"We've hired Sarah as a project manager.
What should happen next?"

Cortex:
→ retrieves onboarding knowledge
→ retrieves relevant Skill
→ reasons through process
→ uses available mock tools
→ requests approval where required
→ performs actions
```

This demonstrates the full Cortex/Brain thesis without requiring private infrastructure.

---

# Local development

A developer should eventually be able to run something close to:

```bash
uv sync
pnpm install

docker compose up -d

uv run cortex-api
pnpm --filter web dev
```

The exact commands may evolve.

Local development should support:

* Cortex API
* Cortex web UI
* PostgreSQL where needed
* Brain
* Northstar fixtures

Use Docker Compose to make the complete demo reproducible.

---

# Configuration

Configuration should use typed environment-based settings.

Expected areas include:

```text
DATABASE_URL

BRAIN_URL
BRAIN_API_KEY

AUTH_MODE
AUTH_SECRET

MODEL_PROVIDER
MODEL_NAME

OPENAI_API_KEY
AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_API_KEY
ANTHROPIC_API_KEY

WEB_SEARCH_PROVIDER

MICROSOFT_CLIENT_ID
MICROSOFT_CLIENT_SECRET
MICROSOFT_TENANT_ID

LOG_LEVEL
ENVIRONMENT
```

Only variables required by enabled providers should be mandatory.

Secrets must never be committed.

---

# Docker

Provide a production-oriented Dockerfile for the Python backend.

Docker Compose should support local development.

The application should not depend on Docker-specific behaviour.

---

# CI/CD

GitHub Actions should run on pull requests and the default branch.

Python checks should include:

```text
uv sync
ruff check
ruff format --check
pyright
pytest
```

Frontend checks should include:

```text
pnpm install --frozen-lockfile
lint
typecheck
test
build
```

Docker builds should also be validated.

Production credentials must never be exposed to pull-request jobs.

---

# Deployment

The web application is intended to deploy on Vercel.

The Python agent backend should be deployable independently.

Do not assume the agent backend must run inside the same environment as the frontend.

Agent runs may become long-running.

The backend architecture should therefore remain compatible with deployment to a durable container/service platform if execution duration, connection lifetime or workload characteristics outgrow a serverless environment.

Avoid coupling the agent runtime to a single hosting provider.

---

# Security

Treat tool execution as a security boundary.

Never assume that because a model requested a tool call it should automatically be allowed.

Every tool invocation should ultimately be constrained by:

```text
authenticated user
        +
available tool policy
        +
external system permissions
        +
approval requirements
```

Do not allow Skill definitions to bypass these controls.

User-supplied or externally retrieved content should be treated as untrusted input.

Do not allow instructions inside documents, web pages or retrieved content to silently redefine system behaviour or grant access to tools.

---

# Design principles

## Cortex acts; Brain stores

Cortex owns execution.

Brain owns durable organisational knowledge and Skills.

Keep this boundary clear.

## Skills are instructions, not code

Skills tell Cortex how work should be performed.

They must not provide an arbitrary remote-code-execution mechanism.

## Tools are capabilities

Models do not directly interact with external systems.

They request typed Cortex tools.

## Models are replaceable

Provider-specific assumptions should remain behind `packages/ai`.

## Brain is replaceable from Cortex's perspective

Cortex should use Brain's public interface rather than accessing its database.

## Context is deliberate

Do not endlessly append conversation, search results and tool outputs into prompts.

Construct model context intentionally.

## Approval before consequential actions

The agent should be helpful and autonomous where safe, while retaining clear user control over consequential operations.

## No hidden chain-of-thought storage

Store actions, decisions, tool invocations and useful execution metadata.

Do not store private hidden reasoning.

## One agent runtime

Avoid implementing independent orchestration logic in routes, tools or connectors.

Agent behaviour belongs in the agent runtime.

## Thin interfaces

HTTP routes and frontend components should not contain core orchestration logic.

## Explicit state

Agent workflows should have understandable state transitions.

Avoid magical implicit state.

## Simple first

Cortex is initially a working portfolio project and experimentation platform.

Do not build speculative enterprise infrastructure before there is a concrete need.

## Agent-friendly repository

The codebase should be straightforward for both humans and coding agents.

Prefer:

* explicit naming
* strong typing
* small modules
* clear package boundaries
* deterministic tests
* documented invariants
* minimal magic

A coding agent should be able to read this README and understand both what Cortex should do and what belongs elsewhere.

---

# Initial conceptual architecture

```text
User
 │
 ▼
Web UI
 │
 ▼
Cortex API
 │
 ▼
Agent Runtime
 ├── Model Provider
 ├── Context Builder
 ├── Skill Executor
 ├── Tool Registry
 ├── Approval Manager
 └── Agent State
        │
        ├──────────────┐
        ▼              ▼
      Brain       External Tools
        │         ├── files
        │         ├── web
        │         ├── Microsoft 365
        │         └── future connectors
        ▼
 knowledge + skills
```

---

# Documentation

Maintain focused documentation as the implementation develops.

```text
README.md
PLAN.md

docs/
├── ARCHITECTURE.md
├── AGENT_RUNTIME.md
├── STATE.md
├── TOOLS.md
├── SKILLS.md
├── CONTEXT.md
├── AUTH.md
├── APPROVALS.md
├── BRAIN.md
└── DEPLOYMENT.md
```

`README.md` explains what Cortex is.

`ARCHITECTURE.md` defines system boundaries.

`AGENT_RUNTIME.md` defines the LangGraph/runtime architecture.

`STATE.md` defines conversation and AgentRun state.

`TOOLS.md` defines tool contracts and registration.

`SKILLS.md` defines how Cortex consumes and executes Brain Skills.

`CONTEXT.md` defines context construction and token management.

`AUTH.md` defines authentication and identity propagation.

`APPROVALS.md` defines consequential-action approval semantics.

`BRAIN.md` defines integration with Brain.

`DEPLOYMENT.md` defines Vercel/frontend and agent-backend deployment.

---

# What Cortex should become

Cortex should become a general-purpose company agent runtime.

It should be able to:

```text
understand what a user wants
retrieve what the company knows
retrieve how the company performs work
reason about the task
use the right tools
ask for approval when needed
perform the work
return a useful result
```

Brain provides durable knowledge and capabilities.

Cortex turns them into action.

The goal is not to build another chat wrapper.

The goal is:

> An agent harness that can understand an organisation, learn its reusable ways of working through Brain Skills, safely interact with its tools, and perform useful company work on behalf of its users.

Everything added to Cortex should justify its place against that goal.
