# Benchmark Repos — Golden Set Fixtures

These directories are **intentional test fixtures** for CodeReviewBot's golden-set benchmark (`codereviewbot benchmark`). They are **not production code**.

## Purpose

Each repo is small and self-contained, with **deliberate violations** baked in so the benchmark scorecard can measure precision, recall, and F1 against labeled ground truth in `ground_truth/*.yaml`.

## Important: fake secrets are intentional

Several repos contain **hardcoded fake API keys and tokens** on purpose — for example:

- `ai_agent_repo/orchestrator.py` — fake `GOOGLE_API_KEY`
- `ai_agent_mcp/orchestrator.py` — fake `OPENAI_API_KEY`

The Security Auditor is expected to **flag these as findings**. They are not real credentials.

If GitHub secret scanning alerts on push, you can safely dismiss them as test fixtures.

## Layout

```
benchmark_repos/
├── manifest.yaml           # Repo list, weights, ground-truth paths
├── ground_truth/*.yaml     # Expected findings (TP labels + tolerated FPs)
├── backend_service/        # Generic backend violations
├── backend_service_clean/  # False-positive control (should find nothing)
├── django_app/ · flask_app/ · zango_app/
├── flutter_app/ · react_native_app/ · ios_native/ · android_native/
├── ai_agent_repo/ · ai_agent_mcp/
├── frontend_app/ · database_infra/
└── ...
```

## Running the benchmark

From the `codereviewbot/` directory:

```bash
codereviewbot benchmark
codereviewbot benchmark --json-out scorecard.json
```

No LLM or API key is required — the scorecard runs static rule checks against these fixtures.
