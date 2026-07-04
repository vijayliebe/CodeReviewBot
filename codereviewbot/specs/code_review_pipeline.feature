Feature: CodeReviewBot multi-agent PR review pipeline
  As a developer merging a vibe-coded PR
  I want the multi-agent pipeline to surface security, style, impact, and
  business-rule findings before merge
  So that integration-layer breaks and dependency hallucinations never reach
  the default branch.

  Background:
    Given the target repository has been profiled by the Repo Profiler agent
    And the CodeMemory index reflects the merged default branch (lazy-at-review refresh)
    And a PR diff has been filtered to strip lockfiles, binaries, and whitespace-only hunks

  Scenario: Detecting a hallucinated package in a Python import
    Given the diff introduces `import fancy_fast_crypto` in `app/payments.py`
    When the Security Auditor calls the package_validator MCP tool against PyPI
    Then the registry lookup returns 404 for `fancy-fast-crypto`
    And a CRITICAL finding is emitted under 🔒 SECURITY FINDINGS
    And the finding suggestion recommends a real alternative from the indexed imports

  Scenario: Blocking float-for-money business rule violation
    Given the repo's `.crb/rules.yaml` contains rule `no-float-for-money`
    And the diff adds `price = float(amount)` in `app/billing.py`
    When the static pre-pass runs the merged regex rules locally
    Then the rule fires WITHOUT invoking the Business Rules LLM agent
    And the finding is injected as STATIC_FINDINGS so the LLM does not re-derive it
    And tokens are saved versus a no-static-pre-pass baseline

  Scenario: Cross-repo impact analysis surfaces a Redis key rename
    Given the workspace registry links `frontend` → `backend` (contract: `cache:user:{id}`)
    And the diff renames the Redis key `cache:user:{id}` to `usr:{id}` in `backend`
    When the Impact & Integration Analyzer runs the dependency-graph query
    Then it returns a HIGH severity blast-radius finding
    And the finding names `frontend` as an affected downstream consumer

  Scenario: Lazy-at-review refresh skips when default branch has not advanced
    Given the CodeMemory manifest's `last_indexed_sha` equals the target repo's HEAD SHA
    When the review command triggers `refresh_target_and_upstream`
    Then the refresh mode is `skip` for the target repo
    And no re-embedding occurs
    And the review proceeds against the existing index

  Scenario: Force-push falls back to content-hash incremental indexing
    Given the default branch was force-pushed so `last_indexed_sha` is no longer an ancestor of HEAD
    When `refresh_target_and_upstream` runs
    Then `git merge-base --is-ancestor` returns False
    And the indexer falls back to a content-hash walk using the manifest's `file_hashes` dict
    And unchanged files retain their existing embeddings
