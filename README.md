# Mind

Mind is the product workspace for Brain and Cortex.

- [Brain](products/brain/README.md) stores governed organisational knowledge and reusable
  agent Skills.
- [Cortex](products/cortex/README.md) is the agent runtime that reasons and acts using Brain and
  external tools.

Cortex currently has a FastAPI service, Next.js conversation application, typed Brain HTTP client,
provider-neutral deterministic and OpenAI model adapters, and its own durable conversation store.
Agent execution and production identity remain intentionally deferred.

The products are developed together but remain independently deployable. Cortex integrates with
Brain through Brain's public HTTP or MCP interfaces and never through Brain's database.

```text
products/
├── brain/
│   ├── apps/
│   ├── packages/
│   └── tests/
└── cortex/
    ├── apps/
    ├── tests/
    └── README.md
```

Root workspace files coordinate shared development commands and local infrastructure. Product
implementations, tests, migrations, content, and product-specific documentation remain inside
their product directory.

The Compose service keys make product ownership explicit: `brain-postgres`, `brain-migrate`,
`brain-api`, `brain-web`, `cortex-db-init`, `cortex-migrate`, `cortex-api`, and `cortex-web`.
