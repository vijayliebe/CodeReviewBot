"""Per-repo index manifest — tracks what was indexed so re-indexing is diff-aware.

The manifest records, for each `repo_id`:
  - `last_indexed_sha`: git HEAD at index time (null if not a git repo)
  - `file_hashes`: {relative_path: sha256_of_content} for every indexed file
  - `last_run`: ISO timestamp of the last index operation
  - `indexed_files` / `code_chunks` / `imports`: counts from the last run

This is what makes incremental indexing possible: on re-index we compare the
current file hashes to the manifest, and only re-chunk/re-embed the files that
changed. Unchanged files keep their existing ChromaDB vectors — no re-embedding,
no API/model cost.

Manifests live at `<db_path>/manifests/<repo_id>.json`, alongside the ChromaDB
persisted data, so they share the lifecycle of the vector store.
"""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def manifest_dir(db_path: Path) -> Path:
    return Path(db_path) / "manifests"


def manifest_path(db_path: Path, repo_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in repo_id)
    return manifest_dir(db_path) / f"{safe}.json"


def file_hash(path: Path) -> str:
    """SHA-256 of a file's bytes. Used to detect content changes without git."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


def git_head_sha(repo_root: Path) -> str | None:
    """Return the current HEAD SHA of a git repo, or None if not a git repo / git missing."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def git_default_branch(repo_root: Path) -> str | None:
    """Best-effort default branch detection (main / master / configured default).

    Used as the comparison ref for "has main moved since we last indexed?"
    Returns None if the repo isn't a git repo.
    """
    # 1. Explicit config: init.defaultBranch or refs/remotes/.../HEAD symlink
    for ref in ("main", "master"):
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), "rev-parse", "--verify", ref],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return ref
        except (OSError, subprocess.TimeoutExpired):
            continue
    # 2. Symbolic-ref of HEAD (works for checked-out default branches)
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def git_is_ancestor(old_sha: str, new_sha: str, repo_root: Path) -> bool:
    """Return True if `old_sha` is an ancestor of `new_sha` in the git DAG.

    This is the canonical force-push / rebase detector. If the old SHA is no
    longer reachable from the new HEAD, history was rewritten — we must fall
    back to a content-hash walk instead of a git-native diff.

    Returns False if either SHA is unknown to the repo or git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", old_sha, new_sha],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def git_changed_files(
    old_sha: str,
    new_sha: str,
    repo_root: Path,
) -> dict[str, list[str]]:
    """Return files that changed between two SHAs using git's native tree diff.

    This is the combined diff — it compares the tree at `old_sha` to the tree
    at `new_sha`, regardless of how many commits sit between them. Intermediate
    churn (a file changed then reverted) is automatically deduped.

    Returns:
      {
        "added":    [paths present in new but not old],
        "modified": [paths present in both, content differs],
        "deleted":  [paths present in old but not new],
        "renamed":  [new paths (old name dropped, new name added)],
      }
    """
    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []
    renamed: list[str] = []

    try:
        # --name-status gives A/M/D/R/C codes per file
        result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--name-status", f"{old_sha}..{new_sha}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return {"added": [], "modified": [], "deleted": [], "renamed": []}
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status = parts[0]
            path = parts[-1]  # for renames, take the new path (last column)
            if status.startswith("A"):
                added.append(path)
            elif status.startswith("M"):
                modified.append(path)
            elif status.startswith("D"):
                deleted.append(path)
            elif status.startswith("R"):
                renamed.append(path)
            elif status.startswith("C"):
                added.append(path)
    except (OSError, subprocess.TimeoutExpired):
        pass

    return {"added": added, "modified": modified, "deleted": deleted, "renamed": renamed}


def load_manifest(db_path: Path, repo_id: str) -> dict | None:
    """Load the manifest for a repo, or None if no prior manifest exists."""
    p = manifest_path(db_path, repo_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_manifest(db_path: Path, repo_id: str, data: dict) -> Path:
    p = manifest_path(db_path, repo_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return p


def diff_files(
    current_files: dict[str, str],
    manifest: dict | None,
) -> dict[str, list[str]]:
    """Compare current file hashes to the manifest.

    Returns:
      {
        "added":     [paths present now but not in manifest],
        "changed":   [paths present in both but hash differs],
        "unchanged": [paths present in both with same hash],
        "deleted":   [paths in manifest but not on disk now],
      }
    """
    old = (manifest or {}).get("file_hashes", {})
    added = [p for p in current_files if p not in old]
    changed = [p for p in current_files if p in old and old[p] != current_files[p]]
    unchanged = [p for p in current_files if p in old and old[p] == current_files[p]]
    deleted = [p for p in old if p not in current_files]
    return {"added": added, "changed": changed, "unchanged": unchanged, "deleted": deleted}


def build_manifest_entry(
    repo_id: str,
    repo_root: Path,
    file_hashes: dict[str, str],
    stats: dict[str, Any],
) -> dict:
    return {
        "repo_id": repo_id,
        "last_indexed_sha": git_head_sha(repo_root),
        "file_hashes": file_hashes,
        "last_run": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
    }
