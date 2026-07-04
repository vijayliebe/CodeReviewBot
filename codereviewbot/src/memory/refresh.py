"""Lazy-at-review index refresh.

Before a PR review, we check whether the target repo (and its upstream related
repos) have advanced on their default branch since the last index. If they have,
we refresh the CodeMemory snapshot so the review runs against the current
baseline — not a stale one.

The refresh is incremental (git-native diff where possible, content-hash
fallback otherwise) and cheap when nothing moved (one `git rev-parse` per repo,
~5ms). Re-embeds only fire when a repo's HEAD actually advanced.

This is the "lazy at review" trigger: no merge hook or cron required. A future
GitHub Action / post-merge webhook can call `refresh_index(repo_id)` directly
to make refreshes eager without changing this module.
"""

from pathlib import Path

from src.memory.index_manifest import git_head_sha, load_manifest
from src.memory.indexer import CodebaseIndexer
from src.utils.paths import get_workspace_root
from src.workspace.store import (
    get_related_repos,
    find_repo_id_for_path,
    workspace_chroma_path,
    load_workspace,
)


def _is_stale(repo_root: Path, db_path: Path, repo_id: str) -> bool:
    """True if the repo's HEAD has moved since the last index (or no manifest yet)."""
    manifest = load_manifest(db_path, repo_id)
    if manifest is None:
        return True  # never indexed
    last_sha = manifest.get("last_indexed_sha")
    if not last_sha:
        return True
    current_sha = git_head_sha(repo_root)
    if not current_sha:
        return False  # not a git repo → can't detect staleness via SHA; assume current
    return current_sha != last_sha


def refresh_index(
    repo_id: str,
    repo_root: Path,
    workspace_root: Path | None = None,
    force_full: bool = False,
) -> dict:
    """Refresh the CodeMemory index for a single repo.

    Returns the indexer summary dict (with `mode`: skip | git-incremental |
    hash-incremental | full). Safe to call on every review — does nothing if
    the repo's HEAD hasn't moved.
    """
    ws = (workspace_root or get_workspace_root()).resolve()
    db_path = workspace_chroma_path(ws)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    indexer = CodebaseIndexer(ws, db_path, repo_id=repo_id)
    return indexer.index_repo(repo_root, incremental=not force_full)


def refresh_index_if_stale(
    repo_id: str,
    repo_root: Path,
    workspace_root: Path | None = None,
) -> dict:
    """Refresh `repo_id` only if its HEAD has moved since the last index.

    If the repo isn't stale (HEAD == last_indexed_sha), returns a `{"mode":
    "skip"}` summary without re-indexing. This is the function the `review`
    command calls for the target repo and each upstream related repo.
    """
    ws = (workspace_root or get_workspace_root()).resolve()
    db_path = workspace_chroma_path(ws)

    if not _is_stale(repo_root, db_path, repo_id):
        return {"repo_id": repo_id, "mode": "skip", "reason": "HEAD unchanged since last index"}

    return refresh_index(repo_id, repo_root, ws)


def refresh_target_and_upstream(
    target_repo_root: Path,
    workspace_root: Path | None = None,
) -> list[dict]:
    """Refresh the target repo + every repo it consumes (upstream), lazily.

    Used by the `review` command: a PR for repo A is reviewed against the
    current baseline of A AND of every repo A depends on (B, C, ...). If B's
    contract changed on main, the impact analyzer needs B's current snapshot
    to detect the break.

    Downstream repos (repos that consume A) are NOT refreshed here — they
    matter for A's impact analysis only when reviewing THEIR PRs, where A is
    upstream.

    Repos that aren't cloned locally or aren't git repos are skipped with a
    warning, never blocking the review.
    """
    ws = (workspace_root or get_workspace_root()).resolve()
    results: list[dict] = []

    # 1. The target repo — find its repo_id in the workspace registry if registered
    target_id = find_repo_id_for_path(target_repo_root, ws) or target_repo_root.name
    try:
        results.append(refresh_index_if_stale(target_id, target_repo_root, ws))
    except Exception as e:
        results.append({"repo_id": target_id, "mode": "error", "error": str(e)})

    # 2. Upstream repos (those the target consumes)
    cfg = load_workspace(ws)
    if cfg and target_id in cfg.repos:
        related = get_related_repos(target_id, ws)
        for upstream in related.get("upstream", []):
            upstream_root = (ws / upstream.path).resolve() if upstream.path else None
            if not upstream_root or not upstream_root.is_dir():
                results.append({
                    "repo_id": upstream.id,
                    "mode": "skipped",
                    "reason": f"path not found locally: {upstream.path}",
                })
                continue
            try:
                results.append(refresh_index_if_stale(upstream.id, upstream_root, ws))
            except Exception as e:
                results.append({"repo_id": upstream.id, "mode": "error", "error": str(e)})

    return results


def format_refresh_summary(results: list[dict]) -> str:
    """Compact one-line-per-repo summary for CLI output."""
    if not results:
        return "No repos to refresh."
    lines = []
    for r in results:
        rid = r.get("repo_id", "?")
        mode = r.get("mode", "?")
        if mode == "skip":
            lines.append(f"  {rid:15} up-to-date (HEAD unchanged)")
        elif mode == "git-incremental":
            lines.append(
                f"  {rid:15} refreshed via git diff "
                f"({r.get('embedded', 0)} embedded, {r.get('deleted', 0)} deleted)"
            )
        elif mode == "hash-incremental":
            lines.append(
                f"  {rid:15} refreshed via content-hash walk "
                f"({r.get('embedded', 0)} embedded, {r.get('deleted', 0)} deleted)"
            )
        elif mode == "full":
            lines.append(f"  {rid:15} full re-index ({r.get('indexed_files', 0)} files)")
        elif mode == "skipped":
            lines.append(f"  {rid:15} skipped — {r.get('reason', 'not available locally')}")
        elif mode == "error":
            lines.append(f"  {rid:15} error — {r.get('error', 'unknown')}")
        else:
            lines.append(f"  {rid:15} {mode}")
    return "\n".join(lines)
