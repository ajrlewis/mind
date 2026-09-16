# Brain

Brain is a self-hosted knowledge and capability store for AI agents.

## Implementation status

The repository implements its persistent identity/access, governed knowledge, and first
authorization-safe hybrid search slices plus a read-only Next.js enterprise console in
`apps/web`. PostgreSQL stores Page folders, Sources, Pages, immutable PageVersions, and
access-filtered provenance and regenerable PageVersion chunks. Shared application services expose equivalent create/read and search
operations through FastAPI and FastMCP, and a deterministic Northstar seed demonstrates
versioned synthetic knowledge. It also stores validated immutable Skills, exposes bounded
authorized inventories, and explicitly seeds five repository-owned defaults. Search, chunks,
embeddings, document retrieval/parsing, and production identity integration remain target state.

The console provides local sign-in, three-pane Page/content/provenance browsing, Skills and
reference inventories, authorized hybrid search, runtime Brain/Northstar themes, and sanitized Markdown. It calls the
public HTTP API from Server Components, so `LOCAL_BEARER_TOKEN` is never delivered to browser
JavaScript. FastAPI's generated OpenAPI document deterministically generates the checked-in
Zod validators; `npm run web:contracts:check` detects drift.

For local Docker use, copy `.env.example`, run `docker compose up -d --build`, and open
`http://localhost:3000`. The disposable defaults are `brain-admin` / `brain-local-dev`.

## Connect a local MCP client

Brain exposes Streamable HTTP MCP at `http://127.0.0.1:8000/mcp/`. After starting the Compose
stack, a local Codex client can register it without storing the bearer token in Codex config:

```bash
export BRAIN_MCP_TOKEN=brain-local-dev
codex mcp add brain-local \
  --url http://127.0.0.1:8000/mcp/ \
  --bearer-token-env-var BRAIN_MCP_TOKEN
codex mcp get brain-local
```

Start a new Codex session after adding the server so its tools are discovered. The token above
is the disposable Compose default; set both `LOCAL_BEARER_TOKEN` and `BRAIN_MCP_TOKEN` to the
same replacement value when using a non-default local environment. Keep tokens in the shell or
an ignored environment file, never in repository or Codex configuration. Use
`codex mcp remove brain-local` to remove the registration.

The HTTP transport is recommended for authenticated local use. The standalone `brain-mcp`
stdio command remains useful for process-level development, but governed operations currently
authenticate from the HTTP `Authorization` header.

It provides a persistent, structured place for an organisation to store:

* what it knows
* where that knowledge came from
* who is allowed to access it
* how AI agents should perform reusable tasks

Brain is deliberately **not an agent runtime**.

It does not autonomously browse websites, connect to SharePoint, read email, orchestrate workflows, select tools, or execute long-running tasks.

Those responsibilities belong to an agent harness such as Cortex.

Brain stores and serves the durable organisational state that agents operate against.

```text
Cortex / Claude / ChatGPT / another agent
                    │
                    │ HTTP / MCP
                    ▼
                  Brain
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
   Knowledge      Skills        Search
       │            │            │
       └────────────┼────────────┘
                    ▼
                PostgreSQL
```

Brain must remain agent-agnostic.

Cortex will be its primary client during development, but nothing in Brain should require Cortex to exist.

---

# Core concepts

Brain has two primary responsibilities:

1. organisational knowledge
2. reusable agent skills

The distinction is simple:

```text
Pages  = what the organisation knows
Skills = how agents should perform work
```

Brain stores both.

Agents consume them.

---

# Knowledge

Knowledge begins with a `Source`.

A Source represents where information came from. It is provenance, not necessarily a file.

Examples include:

* PDF
* SharePoint page
* email
* web page
* GitHub file
* Notion page
* API resource
* manually supplied document

Brain does not need to fetch these resources itself.

An external agent or process retrieves information and submits structured knowledge to Brain.

For the initial integration, Cortex supplies already-extracted Markdown with Source and
provenance metadata. Brain does not accept, fetch, or parse the original document through
MCP; the Markdown becomes immutable PageVersion content.

For example:

```text
Cortex
  │
  ├── retrieves Brain's "ingest" skill
  ├── retrieves a PDF
  ├── extracts/interprets its contents
  └── writes structured knowledge to Brain
                           │
                           ▼
                         Source
                           │
                           ▼
                          Page
                           │
                           ▼
                      PageVersion
                           │
                           ▼
                         Chunks
```

The `ingest` skill describes how ingestion should happen.

Cortex performs the ingestion.

This separation is fundamental:

```text
Brain defines and stores the knowledge contract.

Cortex executes it.
```

---

# Sources

`Source` is intentionally generic.

Do not create provider-specific database models such as:

```text
PdfSource
SharePointSource
EmailSource
WebSource
```

Use a flexible `source_type` string instead.

Conceptually:

```text
Source
├── id
├── organization_id
├── source_type
├── title
├── canonical_uri
├── external_id
├── status
├── access_policy_id
├── metadata
├── provenance
├── created_by_id
├── updated_by_id
├── steward_id
├── created_at
├── updated_at
└── deleted_at
```

Provider-specific information should generally live in JSONB rather than continuously expanding the core schema.

Brain should preserve enough external identity information to reliably recognise, deduplicate and update Sources.

A Source describes where knowledge originated.

It does not necessarily contain Brain's canonical representation of that knowledge.

That is the role of Pages.

---

# Pages

A `Page` is Brain's canonical representation of a piece of organisational knowledge.

Examples include:

```text
Parental Leave Policy
Customer Onboarding
Expenses Policy
Project Alpha
How We Price Projects
Engineering Standards
```

A Page represents stable identity.

Its content changes through immutable `PageVersion` records.

```text
Page: Expenses Policy
  ├── Version 1
  ├── Version 2
  └── Version 3 ← current
```

The Page itself should contain identity, navigation, ownership and access-control information.

The actual knowledge content belongs to PageVersion.

Conceptually:

```text
Page
├── id
├── organization_id
├── folder_id
├── slug
├── title
├── current_version_id
├── access_policy_id
├── position
├── steward_id
├── created_by_id
├── updated_by_id
├── created_at
├── updated_at
└── deleted_at
```

A Page should not duplicate the Markdown or content hash of its current version.

---

# Page versions

A `PageVersion` is an immutable snapshot of Page content.

Conceptually:

```text
PageVersion
├── id
├── page_id
├── version
├── content_markdown
├── content_hash
├── created_by_id
└── created_at
```

The content hash is used to detect identical content and avoid creating unnecessary versions.

Version records should not normally be mutated after creation.

A Page points to whichever PageVersion is currently active.

This provides:

* history
* rollback
* reproducibility
* provenance
* deterministic chunk generation
* clean change detection

---

# Provenance

Pages can be derived from multiple Sources.

Provenance therefore belongs to the PageVersion that was actually produced from those Sources.

```text
PageVersion
  ├── Source: Finance Handbook PDF
  ├── Source: CFO policy email
  └── Source: SharePoint expenses page
```

Represent this using `PageVersionSource`.

Conceptually:

```text
PageVersionSource
├── page_version_id
├── source_id
├── relationship
└── metadata
```

This allows different versions of the same Page to have different provenance.

For example:

```text
Expenses Policy v1
└── Employee Handbook 2024

Expenses Policy v2
├── Employee Handbook 2024
└── Finance Policy 2025

Expenses Policy v3
├── Finance Policy 2025
└── CFO policy update
```

An answer retrieved from Brain should eventually be traceable through:

```text
Answer
  ↓
Chunk
  ↓
PageVersion
  ↓
PageVersionSource
  ↓
Source
  ↓
original system / URI
```

Brain should make it easy for an agent to answer both:

> What does the organisation know?

and:

> Why does the organisation believe this?

---

# Chunks and embeddings

PageVersions are transformed into Chunks for retrieval.

Chunks are derived data.

They are not canonical knowledge and must always be safe to regenerate from a PageVersion.

Conceptually:

```text
Chunk
├── id
├── page_version_id
├── text
├── position
├── heading_path
├── token_count
├── content_hash
├── embedding
├── embedding_provider
├── embedding_model
├── embedding_dimensions
└── created_at
```

Chunks should not have independently editable access policies.

They inherit authorization from their Page.

Deleting or regenerating chunks must never affect canonical Page content.

---

# Skills

A `Skill` is Brain's single capability primitive.

There is deliberately **no separate Prompt model**.

A prompt is simply a Skill that instructs an agent or model to perform a particular task.

Skills may range from simple transformations:

```text
extract_markdown(data)
summarize(content)
classify(content, categories)
```

to more complex agent behaviours:

```text
ingest(source)
onboard_employee(employee)
prepare_investment_memo(company, materials)
review_contract(contract)
```

Brain stores Skills.

Brain does not execute Skills.

An agent such as Cortex retrieves a Skill and decides how to execute it using its model, tools and runtime.

---

# Skill structure

A Skill has a stable identity:

```text
Skill
├── id
├── organization_id
├── folder_id
├── slug
├── name
├── current_version_id
├── access_policy_id
├── position
├── steward_id
├── created_by_id
├── updated_by_id
├── created_at
├── updated_at
└── deleted_at
```

Its actual instructions live in immutable `SkillVersion` records:

```text
Skill
  ├── SkillVersion 1
  ├── SkillVersion 2
  └── SkillVersion 3 ← current
```

A SkillVersion primarily contains the Skill document itself:

```text
SkillVersion
├── id
├── skill_id
├── version
├── content
├── content_hash
├── created_by_id
└── created_at
```

The Skill document is Markdown with YAML frontmatter.

Do not duplicate arbitrary Skill metadata into database columns unless Brain itself genuinely needs to query or enforce that property.

---

# Skill format

Skills use Markdown with YAML frontmatter.

For example:

```markdown
---
name: extract_markdown
description: Convert supplied source data into clean canonical Markdown.
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

Preserve headings, lists, tables and meaningful document structure.

Remove presentation-only noise.

Do not invent information.

## Source data

{{ data }}
```

The YAML frontmatter is the structured Skill contract.

The Markdown body contains the instructions.

Brain should parse and validate the YAML header when a SkillVersion is created.

The original complete Skill document should remain available so an agent can retrieve it directly.

---

# Skill variables

Skills may declare inputs in their YAML frontmatter.

For example:

```yaml
inputs:
  data:
    type: string
    required: true
```

An agent can therefore conceptually invoke:

```text
extract_markdown(data)
```

Brain is responsible for storing and serving the Skill definition.

The agent runtime is responsible for:

1. retrieving the Skill
2. supplying the variables
3. validating required inputs
4. rendering or otherwise interpreting the Skill
5. executing it
6. handling its output

For example:

```text
Cortex
  ↓
get_skill("extract_markdown")
  ↓
Brain returns current SkillVersion
  ↓
Cortex supplies:
  data = "..."
  ↓
Cortex executes the instructions
  ↓
Markdown
```

Brain should not become a template execution engine or agent framework.

---

# Skill YAML

YAML frontmatter should remain flexible.

Possible fields include:

```yaml
---
name: ingest
description: Ingest external information into Brain.

inputs:
  source:
    type: object
    required: true

outputs:
  pages:
    type: array

tools:
  - brain.search
  - brain.create_source
  - brain.create_page
  - brain.create_page_version
---
```

These fields describe the Skill to an agent.

They are not necessarily database columns.

This distinction is intentional.

The database stores the durable Skill document.

The Skill document describes its execution contract.

If a future feature requires Brain itself to query a particular property efficiently, that property may later be promoted into the relational schema.

Do not prematurely normalize the entire YAML header into database tables.

---

# The ingest skill

`ingest` should be one of Brain's first built-in/example Skills.

It describes how an external agent should turn external information into canonical Brain knowledge.

It should eventually define things such as:

* Source identity
* Source deduplication
* canonical URI handling
* Page identity
* Page naming
* Markdown standards
* provenance requirements
* when to update an existing Page
* when to create a new Page
* when to create a PageVersion
* handling conflicting information
* handling partial information
* avoiding invented information
* required Brain mutation operations

The important architectural boundary remains:

```text
Brain stores the ingest skill.

Cortex reads the ingest skill.

Cortex retrieves the external data.

Cortex performs the reasoning.

Cortex writes the result to Brain.
```

Brain does not need SharePoint, email, web browsing or PDF-agent logic to implement this architecture.

---

# Built-in Skills and governance

Brain should ship a small, repository-owned default Skill bundle independently of any
client-specific agent files or example corpus:

```text
content/default/
├── manifest.yaml
└── skills/
    ├── index/
    │   ├── SKILL.md
    │   └── references/
    │       └── governance.md
    ├── ingest/SKILL.md
    ├── retrieve/SKILL.md
    ├── update/SKILL.md
    └── lint/SKILL.md
```

Each Skill uses the conventional `<slug>/SKILL.md` layout. `SKILL.md` is the exact executable
document stored in a SkillVersion; optional `references/` files are validated and packaged
supporting guidance, not additional database records. `assets/` is reserved for files served
as assets. These documents are canonical seed content, so `content/default/skills/` makes
their lifecycle explicit. Python packaging and Docker builds include this directory. An
explicit `brain-seed-defaults` bootstrap
command should create deterministic Skill and SkillVersion records for the selected
Organization, policy and steward. It must be idempotent, must not run implicitly during
migration or application startup, and must not overwrite a locally edited current version.
Later bundled updates should be proposed as reviewed new versions rather than silently
replacing deployment state.

The version-one bundle has these responsibilities:

* `index` is the stable entry point and routes a client to the other current Skills by
  stable slug, purpose, required inputs and available Brain tools;
* `ingest` governs Source identity, extracted Markdown, Page selection and provenance;
* `retrieve` governs folder navigation and authorized Page/Source retrieval using only
  operations Brain actually exposes;
* `update` governs immutable version creation and stale-write handling;
* `lint` audits Skill routing and knowledge quality without mutating by default.

Future repository-owned canonical Skills should cover PDF and PowerPoint extraction, SharePoint
source retrieval and ingestion, and public web search/research. Document Skills should specify
how to preserve useful page or slide structure and source references when producing Markdown.
Connector-facing Skills should specify inputs, authorized tool use, provenance, and outputs;
Cortex owns file parsing, network access, and connector execution. Add each Skill to the default
bundle only with a reviewed `SKILL.md`, an executable Cortex capability, and tests for its
declared contract. These are planned additions, not part of the version-one bundle above.

The `index` Skill is a routing contract, not a duplicate implementation of every Skill.
Linting must verify that its routes resolve to live current Skills, advertised tools exist,
frontmatter and declared inputs/outputs are valid, and no built-in Skill is unreachable.

## Knowledge linting

The lint Skill should inspect both structural correctness and content quality:

* resolve internal Page links against stable folder/Page paths such as
  `/about/our-team` and report broken, ambiguous or unauthorized links;
* identify exact duplicates by content hash and generate semantic duplicate candidates;
* propose merging materially similar content into one canonical Page while preserving all
  source provenance and immutable history;
* find conflicting or superseded facts, Pages without current versions or provenance,
  stale Source revisions, and navigation/layout drift;
* validate the curated home Page and Skill index without treating either as the database's
  authoritative inventory.

A canonical home Page should describe the knowledge base and link to important folder and
Page entry points. It should remain curated and compact. Exhaustively duplicating hundreds
of Pages into that Markdown would create another stale index; the folder tree and a
lightweight generated inventory should remain authoritative for exhaustive navigation.

Linting must scale as a staged workflow rather than loading the whole corpus into one
model context:

```text
cheap structural checks and hashes
            ↓
authorized folder/Page/Skill inventory
            ↓
chunk/search-generated duplicate and drift candidates
            ↓
bounded folder or candidate clusters reviewed in parallel
            ↓
one compact lint report and proposed change set
```

Cortex may delegate bounded folders or candidate clusters to subagents, but each agent
should receive only the relevant content and provenance rather than an intentionally full
context window. Checkpoints make large audits resumable. Brain supplies deterministic
inventory, retrieval and mutation contracts; Cortex owns scheduling and orchestration.

A scheduled lint run is read-only by default. Content merges, link rewrites, Source status
changes and new Page/Skill versions require human confirmation. After approval, Cortex
must re-read the current version and revalidate the proposal before writing.

## Concurrent edits

Immutable versions prevent history loss, but they do not alone prevent an older edit from
becoming current after another writer has published. Page and Skill mutations should use
optimistic concurrency:

```text
read current version A
prepare and review update based on A
create new version only if current version is still A
otherwise return a conflict and rebase/review against the latest version
```

The public mutation contract should require `expected_current_version_id` (and may expose
the same value as an HTTP ETag/`If-Match`). Inside one transaction Brain should lock the
parent, compare the expected pointer, append the immutable version, and conditionally move
the current pointer. Ingestion retries should additionally support idempotency keys. A
human approval is bound to the reviewed base version; it becomes invalid if that base is
no longer current. Automatic semantic merges are not permitted.

---

# Organisation and navigation

Brain is organisation-aware even if the first deployment contains only one organisation.

The intended deployment model is one Brain/Cortex stack per tenant, with one active
customer Organization. Brain is not initially a shared multi-tenant SaaS control plane.
`organization_id` remains valuable as a hard isolation invariant, for synthetic test
Organizations, and to avoid baking the single deployment assumption into every record;
tenant discovery, cross-tenant administration and shared-instance provisioning are not
product requirements.

Top-level domain records should carry an `organization_id`.

Knowledge and Skills are organised into hierarchical Folders.

The checked-in initial corpus is intentionally text-only and reviewable:

```text
Knowledge
├── Company
├── Finance
│   ├── Policies
│   └── Procedures
├── People
└── Operations

Skills
├── Knowledge Management
├── Finance
└── Operations
```

Folders are typed:

```text
page
skill
```

Folders can contain folders of the same type.

Pages and Skills reference their parent Folder.

Items and folders have a `position` field for deterministic presentation ordering.

Position is navigation metadata only.

It must not influence retrieval relevance.

---

# Identity and access

Brain should begin with deliberately simple authentication and authorization while keeping the domain model capable of evolving.

A `Principal` represents an actor interacting with Brain.

A Principal may represent:

```text
user
service
agent
```

Principals are used for ownership and audit fields such as:

```text
created_by_id
updated_by_id
steward_id
```

Human-owned top-level domain objects such as Pages, Sources, Skills and Folders should generally record:

```text
created_by_id
updated_by_id
created_at
updated_at
steward_id
```

Derived records such as Chunks do not need stewardship.

---

# Groups and access policies

Brain has Groups.

Groups use stable internal identifiers.

They may later be mapped to external identity providers such as Microsoft Entra ID.

Access policies provide group-based restrictions.

The initial semantics are deliberately simple:

```text
no restricted groups
    → organisation-wide access

one or more permitted groups
    → principal must belong to at least one permitted group
```

The first implementation does not need to become an enterprise identity-management platform.

Do not prematurely build:

* SCIM
* SAML administration
* complex tenant provisioning
* billing
* sophisticated identity synchronization

The important requirement is that authorization is correct.

---

# Authorization and search

Authorization applies to all representations of knowledge.

Brain must never return:

* a Page
* Page content
* a Chunk
* search result
* title
* snippet
* semantic match
* provenance information

to a Principal that cannot access the underlying Page.

Authorization must therefore happen as part of retrieval.

Do not:

```text
search everything
    ↓
take top 10
    ↓
remove unauthorized results
```

Instead, authorized candidates must be constrained as part of the search operation itself.

This is a core correctness requirement.

---

# Versioning

Versioning is a core Brain primitive.

The versioned entities are:

```text
Page
└── PageVersion[]

Skill
└── SkillVersion[]
```

The parent entity provides stable identity.

The Version provides immutable content.

The parent points to its current version.

Version records carry content hashes so identical content can be detected without unnecessarily creating new versions.

Avoid duplicating version content onto the parent entity.

---

# Tags

Brain may support lightweight Tags for classification and retrieval.

Conceptually:

```text
Tag
PageTag
SourceTag
```

Tags are different from Folders.

Folders provide hierarchical navigation.

Tags provide many-to-many classification.

Do not use Tags as an access-control mechanism.

---

# Audit

Brain may maintain an append-only `AuditEvent` table for important mutations not naturally represented by version history.

Examples include:

```text
page.created
page.version.created
page.current_version.changed
page.deleted

skill.created
skill.version.created
skill.current_version.changed

access_policy.changed
folder.moved
group.mapping.changed
```

Conceptually:

```text
AuditEvent
├── id
├── organization_id
├── actor_id
├── action
├── entity_type
├── entity_id
├── related_entity_id
├── request_id
├── metadata
└── created_at
```

Audit logging is useful but should not overcomplicate the initial implementation.

---

# Technical architecture

Brain is a Python application.

Recommended stack:

* Python 3.13+
* `uv`
* FastAPI
* FastMCP
* Pydantic v2
* SQLAlchemy 2.x
* Alembic
* PostgreSQL
* pgvector
* pytest
* Ruff
* Pyright
* Docker
* GitHub Actions

The production application is intended to run on Vercel with managed PostgreSQL.

The architecture must not tightly couple Brain to Vercel.

Brain should remain a normal containerizable Python service that can run locally or on another hosting platform.

---

# Repository structure

Prefer a Python monorepo with small internal packages.

```text
brain/
├── apps/
│   ├── api/
│   ├── mcp/
│   └── web/                 # target-state Next.js console
│
├── packages/
│   ├── core/
│   ├── db/
│   ├── ai/
│   ├── search/
│   ├── auth/
│   └── schemas/
│
├── migrations/
│
├── content/
│   └── default/
│       ├── manifest.yaml
│       └── skills/
│
├── examples/
│   └── northstar/
│       ├── assets/
│       ├── documents/
│       ├── skills/
│       └── seed/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── docs/
├── scripts/
│
├── .github/
│   └── workflows/
│
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── .env.example
└── README.md
```

The exact structure may evolve.

Package boundaries should reflect responsibilities rather than arbitrary technical layers.

---

# `packages/core`

`core` contains Brain's domain behaviour.

It should express concepts such as:

```text
Organization
Principal
Group
AccessPolicy

Folder

Source

Page
PageVersion
PageVersionSource

Skill
SkillVersion
```

Business rules belong here rather than inside FastAPI route handlers or MCP tools.

HTTP and MCP must not contain independent implementations of Brain behaviour.

Both interfaces call the same application/domain services.

---

# `packages/db`

`db` owns persistence.

It contains:

* SQLAlchemy models
* sessions
* repositories
* database configuration
* PostgreSQL-specific behaviour
* pgvector integration where appropriate

Alembic migrations operate against these models.

Avoid leaking SQLAlchemy models throughout the entire application.

Public boundaries should primarily use explicit Pydantic/domain types.

---

# `packages/ai`

`ai` contains model-provider-specific infrastructure used by Brain itself.

Initially its primary responsibility is embeddings.

Brain must not scatter direct provider SDK calls throughout the codebase.

Expose provider-neutral interfaces such as:

```python
class EmbeddingProvider(Protocol):
    async def embed_documents(
        self,
        texts: list[str],
    ) -> list[Embedding]:
        ...
```

Implementations may include:

```text
OpenAIEmbeddingProvider
AzureOpenAIEmbeddingProvider
LocalEmbeddingProvider
```

Configuration chooses the implementation.

The rest of Brain should conceptually do:

```python
vectors = await embeddings.embed_documents(texts)
```

without knowing which vendor produced them.

Embedding results should expose enough information to persist:

```text
vector
provider
model
dimensions
```

Stored vectors must remain attributable to the model that generated them.

If Brain later requires reranking or other model-backed retrieval operations, those provider abstractions should also live here.

Do not put Skill execution here.

Do not put ingestion agents here.

Do not build an agent framework inside Brain.

---

# `packages/search`

`search` owns retrieval.

It may combine:

* semantic vector search
* PostgreSQL full-text search
* metadata filtering
* authorization filtering
* ranking
* result shaping

The public search abstraction should not expose pgvector implementation details.

Search results should preserve enough provenance for callers to cite their origin.

Authorization is part of search correctness.

Tests must explicitly prove that unauthorized content cannot leak through search.

---

# `packages/auth`

`auth` turns an incoming request into Brain's authorization context.

Conceptually:

```text
AuthContext
├── organization_id
├── principal_id
└── group_ids
```

Domain and search services use this context to evaluate access consistently.

Authentication mechanisms should remain separate from authorization semantics.

The first version can use deliberately simple authentication suitable for local development, portfolio demonstrations and trusted Cortex-to-Brain communication.

Later, Cortex may authenticate as a service while forwarding trusted user/group context, or Brain may integrate directly with an identity provider.

Do not make the initial implementation depend on solving the final enterprise authentication architecture.

---

# `packages/schemas`

Shared Pydantic request/response and public contract schemas live here where appropriate.

Avoid unnecessary duplicate schema hierarchies.

Schemas should make Brain's external contracts explicit and strongly typed.

---

# HTTP API

FastAPI exposes Brain's conventional application API.

Expected resource areas include:

```text
/organizations
/sources
/pages
/folders
/search
/skills
/groups
/access-policies
```

Routes should remain thin.

A route should generally:

1. authenticate the request
2. validate input
3. invoke a domain/application service
4. serialize the result

Routes should not implement knowledge, versioning, authorization or search logic themselves.

Use generated OpenAPI documentation.

---

# MCP

Brain exposes an MCP server using FastMCP.

MCP is a first-class interface.

It allows compatible agents to use Brain without understanding Brain's internal HTTP API.

Likely operations include:

```text
search

get_page
list_pages

get_source
list_sources

get_skill
list_skills

create_source
create_page
create_page_version
```

Skill retrieval should return the current SkillVersion by default, while allowing a caller to request a specific version when reproducibility matters.

Mutation tools must enforce the same authorization and domain rules as HTTP operations.

Do not implement separate MCP-specific business logic.

```text
HTTP ─┐
      ├── Brain domain services
MCP ──┘
```

MCP and HTTP are two interfaces over the same Brain.

---

# Web console

Brain should eventually include a Next.js application under `apps/web` for humans to
inspect and manage the same governed content exposed through HTTP and MCP.

The initial console should consume Brain's public HTTP API and support:

* Source and Page browsing
* folder-tree navigation
* rendered Page Markdown
* rendered Skill Markdown and parsed YAML frontmatter
* visibility into the tools exposed through MCP

Later iterations may add governed editing, version history, access-policy administration,
and search diagnostics. Authorization remains enforced by the backend; the web console
must not become a separate implementation of Brain's domain rules.

---

# Example company

The repository should include a realistic fictional organisation for development, demonstrations and end-to-end testing.

The working name is `Northstar`.

It should contain a small but believable corporate knowledge base built from PDFs and local fixtures.

For example:

```text
examples/northstar/
├── assets/
│   └── README.md
├── documents/
│   ├── company/
│   │   ├── investment-team.md
│   │   └── operating-partner.md
│   ├── people/
│   │   └── alex-rowan.md
│   └── portfolio/
│       ├── orion-investment-memo.md
│       ├── orion-operating-update.md
│       └── orion-committee-notes.md
├── skills/
│   ├── brand/SKILL.md
│   └── voice/SKILL.md
└── seed/
    └── manifest.yaml
```

Northstar should be a credible but entirely fictional private-equity firm. Its seed corpus
should cover the company, investment approach, portfolio operations, team, and positions.
Team structure should initially be represented as knowledge rather than introducing a
special-purpose HR schema.

The seed manifest owns stable identity keys, relationships, ordering, provenance, and paths
to exact source/PageVersion Markdown. `brain-seed-northstar` consumes it deterministically;
the example Skills are illustrative content and are not inserted as production defaults.
Binary assets remain deferred until their generation, licensing, storage, and delivery
contract is explicit.

`tests/fixtures/dummy/` is a separate, deliberately tiny provider-neutral content fixture
for unit and transport tests. It is not a database seed, production default, or customer
example and must remain synthetic and text-only unless a focused test documents otherwise.

The corpus should eventually contain overlapping, evolving and occasionally conflicting information.

For example:

```text
Employee Handbook 2024
→ expense limit £50

Finance Policy 2026
→ expense limit £75
```

This demonstrates why Sources, provenance, canonical Pages and PageVersions exist.

The example organisation must contain no real confidential company information.

---

# Local development

A developer can install the workspace and run each lifecycle step explicitly:

```bash
UV_CACHE_DIR="$PWD/.uv-cache" uv sync --frozen --all-packages
docker compose up -d brain-postgres
docker compose up brain-migrate
docker compose up -d brain-api
```

Or build and start the complete dependency chain in one command:

```bash
docker compose up -d --build
```

Compose waits for PostgreSQL health, requires the one-shot migration service to finish
successfully, and only then starts the API. The API never applies migrations itself.
FastAPI serves `/health`, `/auth/context`, and authenticated create/read routes for
`/folders`, `/sources`, `/pages`, and `/pages/{page_id}/versions`. MCP Streamable HTTP is
mounted at `/mcp/` with matching tools. Set `LOCAL_BEARER_TOKEN` (the disposable Compose
default is `brain-local-dev`) and send it as `Authorization: Bearer <token>` to
authenticated operations. Both health interfaces remain unauthenticated and database-free.

After applying migrations, seed the wholly fictional Northstar corpus explicitly. The
command uses stable UUIDs and conflict-safe inserts, so rerunning it does not duplicate
records:

```bash
DATABASE_URL=postgresql+psycopg://brain:brain@localhost:5432/brain \
  UV_CACHE_DIR="$PWD/.uv-cache" uv run brain-seed-northstar
```

Run the PostgreSQL integration tests against the Compose database (use the same selected
host port):

```bash
TEST_DATABASE_URL=postgresql://brain:brain@localhost:5432/brain \
  UV_CACHE_DIR="$PWD/.uv-cache" uv run pytest -m integration
```

To reset the disposable database, stop the stack and permanently delete its volume:

```bash
docker compose down -v
```

**Data-loss warning:** `down -v` irreversibly removes all data in the local Brain Compose
database volume.

Brain should also have a production-oriented Dockerfile.

`.env.example` should document every required configuration value.

Local development must not require:

* Cortex
* SharePoint
* Microsoft 365
* proprietary external systems

The Northstar example should provide everything needed to demonstrate Brain locally.

---

# Configuration

Use environment variables parsed through a typed settings object.

Expected areas include:

```text
DATABASE_URL
DATABASE_POOL_SIZE
DATABASE_MAX_OVERFLOW
DATABASE_POOL_TIMEOUT_SECONDS
DATABASE_POOL_RECYCLE_SECONDS
DATABASE_STATEMENT_TIMEOUT_MS
DATABASE_LOCK_TIMEOUT_MS

LOCAL_BEARER_TOKEN
LOCAL_ORGANIZATION_ID
LOCAL_PRINCIPAL_ID
LOCAL_GROUP_IDS

AUTH_MODE
AUTH_SECRET

EMBEDDING_PROVIDER
EMBEDDING_MODEL
EMBEDDING_DIMENSIONS

OPENAI_API_KEY

AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_API_KEY

LOG_LEVEL
ENVIRONMENT
```

Only configuration required for the selected mode/provider should be mandatory.

Secrets must never be committed.

---

# Testing

Tests are part of the architecture.

Use:

```text
tests/unit
tests/integration
tests/e2e
```

Unit tests cover domain behaviour.

Integration tests should use real PostgreSQL + pgvector where database behaviour matters.

End-to-end tests exercise HTTP and MCP.

Important invariants include:

* PageVersions are immutable
* SkillVersions are immutable
* identical content does not unnecessarily create versions
* current-version pointers remain valid
* PageVersion provenance is preserved
* Skill YAML frontmatter is validated
* required Skill inputs can be identified
* deleting/regenerating Chunks does not damage canonical knowledge
* unauthorized Principals cannot retrieve restricted Pages
* unauthorized Principals cannot discover restricted content through search
* authorized Principals receive correct search results
* embedding provider/model information remains attached to vectors
* HTTP and MCP enforce equivalent domain rules

---

# CI/CD

GitHub Actions should run on pull requests and the default branch.

Initial CI should perform:

```text
uv sync
ruff check
ruff format --check
pyright
pytest
```

Integration tests should run against PostgreSQL with pgvector enabled.

Docker builds should be validated in CI.

Database schema changes must include corresponding Alembic migrations.

Production credentials must never be available to pull-request jobs.

Deployment workflows can be added once the Vercel environment is established.

---

# Docker

Provide:

```text
Dockerfile
docker-compose.yml
```

Docker Compose should initially provide PostgreSQL + pgvector and may optionally run Brain itself.

Brain must not behave differently merely because it runs inside Docker.

---

# Observability

Use structured logging from the beginning.

Requests should have correlation IDs that can propagate through:

```text
Cortex
  ↓
Brain HTTP/MCP
  ↓
database/search/AI
```

Where Cortex supplies a correlation ID, preserve it.

Do not store chain-of-thought or hidden model reasoning.

Logging should focus on:

* requests
* timings
* failures
* mutations
* search operations
* provider calls
* correlation

without unnecessarily recording sensitive content.

---

# Design principles

## Brain is not Cortex

If functionality involves autonomous reasoning, browsing, workflow orchestration, connector execution, external system interaction or tool selection, it probably belongs in Cortex rather than Brain.

## Pages are knowledge

Pages and PageVersions represent canonical organisational knowledge.

Sources represent where that knowledge came from.

Do not conflate the two.

## Skills are capabilities

Skills describe how agents should perform reusable work.

There is no separate Prompt abstraction.

A simple prompt is a simple Skill.

A complex agent procedure is also a Skill.

## Skills are documents

The SkillVersion's Markdown document and YAML frontmatter are its canonical definition.

Do not turn every YAML property into a database column.

## Brain stores; agents execute

Brain can validate and serve a Skill.

It should not become responsible for executing arbitrary Skills.

## Canonical data over derived data

Pages, PageVersions, Sources, Skills and SkillVersions are durable.

Chunks and embeddings are derived.

Derived data must be rebuildable.

## Provenance by default

Knowledge should retain a path back to the Sources from which it was produced.

## Immutable versions

Versioned content should be immutable.

Create a new version instead of silently changing history.

## Authorization before retrieval

Restricted knowledge must not leak through semantic search, metadata, titles, snippets or ranking.

## Provider independence

AI providers and deployment environments should sit behind deliberate boundaries where useful.

Avoid abstraction for its own sake, but do not spread vendor SDK assumptions throughout the domain.

## One domain, multiple interfaces

HTTP and MCP expose the same Brain.

They must not become independent implementations.

## Database execution model

Runtime database access uses SQLAlchemy `AsyncSession` and psycopg's async driver. FastAPI
handlers and FastMCP tools directly await the same async application services; each operation
owns a session, and no session is shared across concurrent tasks. Alembic and explicit seed
commands use a separately named synchronous offline utility and are never request paths.

The conservative per-process defaults are a 10-connection pool, 5 temporary overflow
connections, a 10-second acquisition timeout, 30-minute recycling, a 30-second PostgreSQL
statement timeout, and a 5-second lock timeout. These values bound database resource use and
failure time; they are not derived from the roughly 400 potential users in the initial
single-Organization deployment. Most users do not hold a connection, and async requests wait
for a pool slot.

Size the pool against the managed PostgreSQL connection budget. Reserve connections for
administration, migrations, monitoring, and provider requirements, then ensure
`replicas × processes_per_replica × (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)` does not
exceed the remaining application budget. Treat overflow as real peak capacity. Measure
request concurrency and database wait time before increasing it; more connections can reduce
database throughput. Async I/O improves request concurrency but does not replace transactions,
row locks, optimistic version checks, or a deliberately sized pool.

## Simple first

Brain is initially a working portfolio project and foundation for experimentation, not a finished multi-tenant SaaS platform.

Prefer correctness and architectural clarity over speculative enterprise features.

Do not build something merely because a hypothetical future customer might need it.

## Agent-friendly repository

The repository should be straightforward for humans and coding agents to navigate.

Prefer:

* clear names
* explicit types
* small modules
* predictable package boundaries
* useful docstrings
* strong tests
* documented invariants
* minimal hidden magic

A coding agent reading this README should be able to understand not only what to build, but also what **not** to build.

---

# Initial domain model

The current conceptual model is:

```text
Core
├── Organization
├── Principal
├── Group
├── ExternalGroupMapping
├── AccessPolicy
└── AccessPolicyGroup

Navigation
└── Folder

Knowledge
├── Source
├── Page
├── PageVersion
├── PageVersionSource
├── Chunk
├── Tag
├── PageTag
└── SourceTag

Capabilities
├── Skill
└── SkillVersion

Operations
└── AuditEvent
```

This model is not immutable.

Before implementing the complete database schema, define fields, constraints, relationships and authorization semantics in `docs/DATA_MODEL.md`.

---

# Documentation

Maintain focused architecture documents rather than allowing this README to become the entire specification.

```text
README.md
PLAN.md

docs/
├── DATA_MODEL.md
├── ARCHITECTURE.md
├── ACCESS_CONTROL.md
├── SEARCH.md
├── INGESTION.md
├── SKILLS.md
└── MCP.md
```

`README.md` explains what Brain is.

`DATA_MODEL.md` defines what Brain stores.

`ARCHITECTURE.md` defines how the application is structured.

`ACCESS_CONTROL.md` defines authorization semantics.

`SEARCH.md` defines indexing and retrieval.

`INGESTION.md` defines the contract expected of agents writing knowledge into Brain.

Brain defines and enforces that contract. Cortex or another external agent performs the actual ingestion work.

`SKILLS.md` defines the Skill document format, YAML frontmatter, variables, versioning and retrieval semantics.

`MCP.md` defines the agent-facing MCP interface.

---

# What Brain should become

The goal is not to build another vector database.

Brain is a more useful abstraction:

> A governed, versioned repository of organisational knowledge and reusable agent skills that any authorized AI agent can use.

Brain should know:

```text
what the organisation knows
where that knowledge came from
which version is current
who is allowed to know it
how agents should perform reusable work
```

Brain exposes that state through HTTP and MCP.

Cortex and other agents provide the intelligence and execution around it.

Everything added to Brain should justify its place against that boundary.
