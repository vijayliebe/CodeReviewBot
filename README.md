# CodeReviewBot

Multi-agent PR review and security audit agent built with **Google ADK** and **Model Context Protocol (MCP)**.

## Repository layout

| Directory | Purpose |
|---|---|
| [`codereviewbot/`](codereviewbot/) | Main project — agents, MCP servers, CLI, tests, skills, Docker |
| [`benchmark_repos/`](benchmark_repos/) | Golden-set benchmark repos + ground-truth labels |
| [`codereviewbot/examples/workspace/`](codereviewbot/examples/workspace/) | **Templates** for local workspace config (copy to gitignored `.crb-workspace/`) |

Workspace config (`workspace.yaml`, `shared_rules.yaml`) is **local per user/project** — not in git. See [Workspace setup](codereviewbot/examples/workspace/README.md).

## Quick start

```bash
cd codereviewbot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # add GOOGLE_API_KEY

# Profile + index + review a local patch
codereviewbot init --path ../benchmark_repos/django_app
codereviewbot index --path ../benchmark_repos/django_app --repo-id django
codereviewbot review --pr tests/fixtures/sample_pr_diff.patch --repo ../benchmark_repos/backend_service
# Free-tier Gemini (~5 req/min): add --sequential if you hit rate limits

# Run benchmark scorecard (no LLM required)
codereviewbot benchmark

# Run tests
PYTHONPATH=. pytest -q
```

Full documentation: [`codereviewbot/README.md`](codereviewbot/README.md)

## What not to commit

See [`.gitignore`](.gitignore). Local-only (create on your machine):

- `.crb-workspace/` at workspace root — copy from [`codereviewbot/examples/workspace/`](codereviewbot/examples/workspace/)
- `codereviewbot/.crb/` — run `codereviewbot init` per repo
- `.env`, `.venv/`, `chroma_db/`, `.docs/`

Golden-set rules under `benchmark_repos/*/.crb/` **are** in git (test fixtures).
