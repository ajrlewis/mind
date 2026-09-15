# Architecture

`README.md` defines the Mind workspace. `products/brain/README.md` and
`products/cortex/README.md` are the product specifications. Brain is the implemented knowledge
product: a Python
3.13 uv workspace with HTTP and MCP interfaces over shared application services, a
provider-neutral authorization context, and PostgreSQL identity/access plus governed
knowledge and Skill persistence plus authorization-safe hybrid Page search managed by Alembic.

## Workspace And Product Boundary

Mind is a product monorepo rooted at `products/`. Brain owns governed knowledge and Skills;
Cortex owns agent reasoning and action. Both products remain independently deployable, and
Cortex must integrate with Brain through Brain's public HTTP or MCP interfaces rather than its
database or internal packages. Root manifests, Compose, CI, and agent guidance coordinate the
workspace. Cortex implements an independently runnable FastAPI health service, Next.js conversation
application, and the responsibility-focused `cortex-brain` HTTP client package. The Cortex application
owns the client lifecycle and uses Brain's public health and authenticated identity-context routes
through bounded requests. Its dependency diagnostic exposes safe status categories while local
health remains dependency-free. The provider-neutral `cortex-ai` package defines immutable
single-turn chat contracts, controlled model errors, an async non-streaming protocol, and a
deterministic synthetic implementation plus a bounded, no-retry OpenAI Responses API adapter.
Cortex exposes a stateless `POST /chat/turn` through an injected application service. The
application owns and closes configured provider clients while directly injected clients remain
caller-owned; deterministic remains the local, Compose, and CI default. Cortex additionally owns
local bearer caller identity and durable public Conversation/message persistence in a separate
PostgreSQL database through `cortex-auth` and `cortex-state`. Thin authenticated HTTP routes use
optimistic versions to publish each user/assistant pair atomically without holding a transaction
during the model call or stream. Authenticated POST SSE passes provider-neutral text deltas through
a validating same-origin Next.js proxy; partial turns remain transient, and only a valid terminal
model result is atomically published with a 32,000-character assistant cap. Cortex has no agent
runtime, production identity implementation, or additional production model provider yet. No
cross-product package has been extracted.

Streaming validates non-empty deltas and exactly one assistant terminal whose complete content
matches the accumulated deltas before publication. Its structured operational logs are bounded to
start/safe outcome, duration, and emitted character count. Compose service DNS uses explicit
`brain-*` and `cortex-*` ownership names without fixed container names.

The Cortex web application uses a separate signed HTTP-only local session and server-only Cortex
API bearer. Server Components and actions call only the public conversation HTTP contract through
generated OpenAPI Zod validation. The browser can create, list, reopen, and append non-streaming
turns without optimistic durable messages or direct backend access. Brain credentials, identity,
APIs, and sessions are not used by Cortex web.

## Brain Purpose And Boundary

Brain is a self-hosted, agent-agnostic store for governed organisational knowledge and reusable agent Skills. It stores and serves durable state through HTTP and MCP. It does not browse, fetch provider content, execute Skills, select tools, or orchestrate agent workflows; Cortex or another external agent owns those responsibilities.

## Components And Dependency Direction

```text
HTTP API ─┐
          ├─> shared domain/application services ─> persistence/search ─> PostgreSQL + pgvector
MCP ──────┘                                  └─────> provider-neutral embeddings
```

- `products/brain/apps/api` and `products/brain/apps/mcp` are thin transport boundaries over shared services. `products/brain/apps/web`
  is a read-only Next.js console over the public HTTP API and owns no domain rules.
- `products/brain/packages/core` owns typed settings plus shared health, identity, knowledge, and Skill application services.
- `products/brain/packages/schemas` owns explicit transport-neutral public request/response contracts.
- `products/brain/packages/auth` owns immutable `AuthContext`, local bearer authentication, and the initial same-tenant/any-group policy evaluator.
- `products/brain/packages/db` owns declarative metadata, identity/access, knowledge, and Skill models, engine/session factories, caller-owned repositories, Alembic, and explicit idempotent seeds.
- `products/brain/packages/ai` owns the provider-neutral embedding protocol and deterministic synthetic local
  implementation. `products/brain/packages/search` owns deterministic Markdown chunking and PostgreSQL
  full-text/pgvector retrieval without exposing database details to transports.

Applications may depend on packages; packages must not depend on applications. HTTP and MCP must not independently implement domain rules.

Both implemented interfaces accept injected shared services. FastAPI exposes `GET /health`
and mounts FastMCP's Streamable HTTP transport at `/mcp/` in the same ASGI application;
FastMCP exposes the `health` tool. HTTP `GET /auth/context` and MCP `auth_context` use thin
adapters around the same local bearer authenticator and IdentityService. The separate
`brain-mcp` command preserves stdio, though bearer authentication is available over HTTP.
Neither health check performs authentication or database work.

HTTP `POST /search` and MCP `search` are thin adapters over `SearchService`. The service
validates the authorization context and shapes bounded typed results; the search repository
filters organization, current PageVersion, deletion, and access policy inside a materialized
candidate relation before lexical or semantic ranking and limiting.

The web console uses Server Components for API reads and an HTTP-only signed local session
cookie. Backend bearer credentials remain server-only. Runtime company palettes are validated
semantic CSS custom properties. FastAPI OpenAPI deterministically generates checked-in Zod
validators used at the server-side transport boundary.

Authenticated HTTP routes and matching MCP tools create/read Page folders and Sources,
create Pages with extracted Markdown, append immutable PageVersions, and read Pages with
only the provenance Sources visible to the caller. Both transports invoke the same
`KnowledgeService`; Cortex remains responsible for retrieval and extraction.

The same interfaces create, list, and read Skills and append validated immutable
SkillVersions through `SkillService`. Version mutations require the current version ID
observed during review; a stale Page or Skill mutation conflicts before history or the
current pointer changes. Page inventory exposes authorized stable folder/Page paths and
current hashes. Skill inventory exposes authorized stable slugs and current hashes.

The initial migration creates Organization, Principal, Group, GroupMembership,
AccessPolicy, and AccessPolicyGroup. Composite tenant foreign keys prevent cross-tenant
links. The second migration adds Page folders, Sources, Pages, immutable PageVersions,
and retained PageVersionSource provenance. The third adds Skills and immutable
SkillVersions. The fourth adds regenerable PageVersion Chunks with GIN full-text and HNSW
cosine-vector indexes. Both parent/version pairs enforce same-tenant/current-version constraints.
The application process never migrates implicitly: Compose orders PostgreSQL
health, one-shot migration completion, then API startup.

Repository-owned content has three explicit lifecycles. `products/brain/content/default` is the packaged
canonical built-in Skill bundle, with executable documents at `<slug>/SKILL.md` and optional
validated references. `products/brain/examples/northstar` is a packaged, text-only fictional example whose
manifest drives the explicit idempotent database seed while retaining immutable history and
stable UUIDs. `products/brain/tests/fixtures/dummy` is provider-neutral content-only test data and is neither
a production default nor a database seed.

## Durable Data Rules

- `Source` records provenance; `Page` records stable knowledge identity; immutable `PageVersion` records content.
- Provenance attaches to the version produced from a source through `PageVersionSource`.
- `Skill` is the only capability primitive. Immutable `SkillVersion` documents contain YAML frontmatter plus Markdown instructions.
- Parent entities point to their current version; version content and hashes are not duplicated onto parents.
- Chunks and embeddings are derived, attributable, and safe to regenerate without changing canonical content.
- Folders provide typed hierarchy; tags provide classification and never authorization.
- Top-level domain data is organization-scoped.

The initial operational model is one Brain/Cortex stack with one active customer
Organization per tenant. Organization scoping remains a database and authorization
invariant for defense in depth and synthetic tests; shared-SaaS tenant discovery,
provisioning, and cross-tenant administration are not current product requirements.

## Security And Retrieval Invariants

Authorization must constrain retrieval candidates before ranking or result limiting. Unauthorized titles, snippets, semantic matches, chunks, provenance, and other metadata must never be returned. HTTP and MCP enforce identical authorization and domain rules.

Use a provider-neutral `AuthContext` containing organization, principal, and group identities. Access policies are organization-wide when unrestricted; when groups are configured, membership in at least one permitted group is required. `docs/ACCESS_CONTROL.md` is the executable-semantics contract and `docs/DATA_MODEL.md` is the storage contract.

## Runtime And External Boundaries

The implemented stack is Python 3.13+, uv, FastAPI, FastMCP, Pydantic v2, SQLAlchemy 2.x,
Alembic, psycopg, pgvector, PostgreSQL 17 with pgvector, pytest, Ruff, Pyright, Next.js 16,
React 19, TypeScript, Tailwind CSS, Zod, Vitest, Testing Library, Playwright, npm workspaces,
Docker, and GitHub Actions.

Web testing is layered: Vitest covers themes, semantic rendering, Markdown sanitization, and
the validated server-side API transport across success, deny, missing, malformed, and failure
responses. Playwright exercises local sign-in, authorized Northstar inventory, Page detail,
visible provenance, and hybrid search against the real Compose boundary. These tests consume synthetic data
and do not replace backend authorization tests.

Runtime database access uses SQLAlchemy `AsyncSession` with psycopg async. FastAPI and FastMCP
directly await the same persistence-backed application services with one caller-owned session
per operation; sessions are never shared across concurrent tasks. Page and Skill publication
lock the parent row before comparing the reviewed current version and atomically committing a
new immutable version. Alembic and explicit seed commands alone use the clearly separated
synchronous offline database utility.

The supported initial deployment remains one Organization with roughly 400 potential users.
Typed pool size, overflow, acquisition timeout, recycling, PostgreSQL statement timeout, and
lock timeout settings bound database work. Pool capacity is sized against the PostgreSQL
connection budget across all processes and replicas, not against the raw potential-user count.

The service should remain containerizable and host-independent even though production is intended for Vercel with managed PostgreSQL. Repository code and migrations are canonical; hosted systems are authoritative only for live deployment and database state. Deployment, production data access or mutation, hosted configuration changes, and secret changes require explicit maintainer authorization.

Structured logs should carry correlation IDs across HTTP/MCP, database, search, and embedding-provider boundaries without recording secrets, sensitive content, or hidden model reasoning.
