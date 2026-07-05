# CodeReviewBot

Multi-agent PR review and security audit agent built with **Google ADK** and **Model Context Protocol (MCP)**.

## Repository layout

| Directory | Purpose |
|---|---|
| [`codereviewbot/`](codereviewbot/) | Main project — agents, MCP servers, CLI, tests, skills, Docker |
| [`benchmark_repos/`](benchmark_repos/) | Golden-set benchmark repos + ground-truth labels |
| [`codereviewbot/examples/workspace/`](codereviewbot/examples/workspace/) | **Templates** for local workspace config (copy to gitignored `.crb-workspace/`) |
| [`demo_all_use_cases.py`](demo_all_use_cases.py) | End-to-end CLI demo (all 11 use-cases) |

Workspace config (`workspace.yaml`, `shared_rules.yaml`) is **local per user/project** — not in git. See [Workspace setup](codereviewbot/examples/workspace/README.md).

## Quick start

```bash
cd codereviewbot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # add GOOGLE_API_KEY
```

### Full terminal demo (recommended)

From `codereviewbot/`, run the automated walkthrough of all 11 use-cases. It sets up `.crb-workspace/`, indexes repos, runs the benchmark, and writes sample artifacts to the repo root:

```bash
python ../demo_all_use_cases.py --fresh          # clean workspace + full demo (no LLM)
python ../demo_all_use_cases.py --list           # show all use-case IDs
python ../demo_all_use_cases.py --only workspace # run one use-case
python ../demo_all_use_cases.py --with-llm       # include live Gemini review (needs API key)
```

Outputs at repo root: `sample_review_output.txt`, `sample_review_report.md`.

### Manual CLI (step by step)

```bash
# 1. Workspace — local config (gitignored)
codereviewbot workspace init --product "my-product"
codereviewbot workspace register --id backend --path benchmark_repos/backend_service --kind backend
codereviewbot workspace register --id frontend --path benchmark_repos/frontend_app --kind frontend
codereviewbot workspace link --consumer frontend --provider backend --contract "REST /api/billing"
codereviewbot workspace show

# 2. Per-repo rules — already in benchmark_repos/*/.crb/ (golden set)
#    For your own repo: codereviewbot init --path path/to/your-repo

# 3. Index both registered repos + review (LLM) or benchmark (no LLM)
codereviewbot index --path ../benchmark_repos/backend_service --repo-id backend_service
codereviewbot index --path ../benchmark_repos/frontend_app --repo-id frontend_app
codereviewbot review --pr tests/fixtures/sample_pr_diff.patch --repo ../benchmark_repos/backend_service
# Free-tier Gemini (~5 req/min): add --sequential if you hit rate limits

# Golden-set regression scorecard — local regex rules vs ground truth (no API key, not a PR review)
codereviewbot benchmark

# Run tests
PYTHONPATH=. pytest -q
```

Full documentation: [`codereviewbot/README.md`](codereviewbot/README.md)

## What not to commit

See [`.gitignore`](.gitignore). Local-only (create on your machine):

- `.crb-workspace/` at workspace root — copy from [`codereviewbot/examples/workspace/`](codereviewbot/examples/workspace/)
- `.env`, `.venv/`, `chroma_db/`, `.docs/`

Per-repo rules live under `benchmark_repos/*/.crb/` (golden-set fixtures, in git). Do **not** run `init` on the workspace root or `codereviewbot/` package — use `--path ../benchmark_repos/<repo>`.
