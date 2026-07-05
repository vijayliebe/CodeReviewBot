# Workspace config examples (local only — not committed)

CodeReviewBot is **generic**: each user or team defines their own workspace for the repos they work on. These files are **templates** — copy them to your machine-local workspace config directory.

## Where local config lives

```
<workspace-root>/                    # parent directory of codereviewbot/
└── .crb-workspace/                # gitignored — your machine only
    ├── workspace.yaml             # repo registry + relationships
    ├── shared_rules.yaml          # product-wide business rules
    └── chroma_db/                 # vector index (rebuilt via `index`)
```

Per-repo rules (also local, created by `init`):

```
<repo>/.crb/rules.yaml   # e.g. benchmark_repos/django_app/.crb/rules.yaml
```

**Exception:** `benchmark_repos/*/.crb/rules.yaml` stays in git — those are golden-set fixtures, not your personal workspace.

## Quick setup

From the monorepo root (parent of `codereviewbot/`):

```bash
mkdir -p .crb-workspace

# Option A — copy examples and edit
cp codereviewbot/examples/workspace/workspace.yaml.example .crb-workspace/workspace.yaml
cp codereviewbot/examples/workspace/shared_rules.yaml.example .crb-workspace/shared_rules.yaml

# Option B — CLI scaffold (empty registry + empty shared rules)
codereviewbot workspace init --product "my-product"

# Register YOUR repos (paths relative to workspace root)
codereviewbot workspace register --id backend --path path/to/backend --kind backend
codereviewbot workspace register --id frontend --path path/to/frontend --kind frontend
codereviewbot workspace link --consumer frontend --provider backend --contract "REST /api/v1"

codereviewbot workspace show
```

Per repo you review:

```bash
codereviewbot init --path path/to/backend
codereviewbot index --path path/to/backend --repo-id backend
```

## Why not in git?

Workspace layout differs by project, team, and which repos are checked out locally. Committing one team's `workspace.yaml` would be wrong for another clone. The agent code is shared; **configuration is local**.
