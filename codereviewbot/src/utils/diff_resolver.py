"""Resolve a review reference (PR, commit range, or patch file) to unified diff text."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{7,40}$", re.I)
_PR_URL = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", re.I)
_COMPARE_URL = re.compile(
    r"github\.com/([^/]+)/([^/]+)/compare/([^/\s]+)\.\.\.([^/\s]+)", re.I
)


class DiffResolveError(ValueError):
    pass


def is_commit_reference(reference: str) -> bool:
    """Return True if the reference looks like a commit SHA or commit range."""
    ref = reference.strip()
    if _COMPARE_URL.search(ref):
        return True
    if _SHA.match(ref):
        return True
    if re.match(r"^[^/@:]+/[^/@:]+[@:].*\.\.", ref):
        return True
    parts = ref.split("/")
    if len(parts) == 3 and ".." in parts[2] and not parts[2].replace(".", "").isdigit():
        return True
    if ".." in ref and "/" not in ref.split("..")[0]:
        return True
    return False


def is_pr_reference(reference: str) -> bool:
    ref = reference.strip()
    if _PR_URL.search(ref):
        return True
    parts = ref.split("/")
    if len(parts) == 3 and parts[2].isdigit():
        return True
    if ref.isdigit() and os.environ.get("GITHUB_REPOSITORY"):
        return True
    return False


def parse_commit_reference(reference: str) -> dict[str, str | None]:
    """Parse a commit reference into owner, repo, base, head (head None = single commit)."""
    ref = reference.strip()

    m = _COMPARE_URL.search(ref)
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2),
            "base": m.group(3),
            "head": m.group(4),
        }

    m = re.match(r"^([^/@:]+)/([^/@:]+)[@:](.+)$", ref)
    if m and ".." in m.group(3):
        base, head = re.split(r"\.\.+", m.group(3), maxsplit=1)
        return {"owner": m.group(1), "repo": m.group(2), "base": base, "head": head}

    parts = ref.split("/")
    if len(parts) == 3 and ".." in parts[2] and not parts[2].replace(".", "").isdigit():
        base, head = re.split(r"\.\.+", parts[2], maxsplit=1)
        return {"owner": parts[0], "repo": parts[1], "base": base, "head": head}

    if ".." in ref and "/" not in ref:
        base, head = re.split(r"\.\.+", ref, maxsplit=1)
        return {"owner": None, "repo": None, "base": base, "head": head}

    if _SHA.match(ref):
        return {"owner": None, "repo": None, "base": ref, "head": None}

    raise DiffResolveError(
        f"Invalid commit reference: '{reference}'. "
        "Expected: '<sha>', '<base>..<head>', 'owner/repo@<base>..<head>', "
        "or 'https://github.com/owner/repo/compare/base...head'."
    )


def local_git_diff(repo_root: Path, base: str, head: str | None = None) -> str:
    """Run git show or git diff in a local repository."""
    repo_root = repo_root.resolve()
    if not (repo_root / ".git").exists():
        raise DiffResolveError(f"Not a git repository: {repo_root}")

    if head is None:
        proc = subprocess.run(
            ["git", "show", "--format=", "--patch", "--no-ext-diff", base],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    else:
        proc = subprocess.run(
            ["git", "diff", f"{base}..{head}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=120,
        )

    if proc.returncode != 0:
        raise DiffResolveError((proc.stderr or proc.stdout or "git command failed").strip())
    if not proc.stdout.strip():
        raise DiffResolveError("git returned an empty diff for the requested commit(s).")
    return proc.stdout


def github_compare_diff(owner: str, repo: str, base: str, head: str | None = None) -> str:
    """Fetch a compare diff from the GitHub API."""
    import requests

    from src.mcp_servers.github_mcp_server import _get_headers

    if head is None:
        compare_ref = f"{base}^...{base}"
    else:
        compare_ref = f"{base}...{head}"

    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{compare_ref}"
    headers = _get_headers()
    headers["Accept"] = "application/vnd.github.diff"

    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        if not response.text.strip():
            raise DiffResolveError("GitHub returned an empty diff for the requested commit(s).")
        return response.text
    if response.status_code in (401, 403):
        raise DiffResolveError(
            f"Unauthorized GitHub access (status {response.status_code}). Set GITHUB_TOKEN."
        )
    if response.status_code == 404:
        raise DiffResolveError(
            f"Commit compare not found (404) for {owner}/{repo} {compare_ref}."
        )
    raise DiffResolveError(
        f"GitHub compare failed (status {response.status_code}): {response.text[:500]}"
    )


def resolve_commit_diff(reference: str, local_repo: Path | None = None) -> str:
    """Resolve a commit reference to unified diff text (local git or GitHub)."""
    parsed = parse_commit_reference(reference)
    owner = parsed["owner"]
    repo = parsed["repo"]
    base = parsed["base"]
    head = parsed["head"]

    if owner and repo:
        return github_compare_diff(owner, repo, base, head)

    if local_repo is not None:
        return local_git_diff(local_repo, base, head)

    default_repo = os.environ.get("GITHUB_REPOSITORY", "")
    if default_repo and "/" in default_repo:
        o, r = default_repo.split("/", 1)
        return github_compare_diff(o, r, base, head)

    raise DiffResolveError(
        "Bare commit SHA/range requires --repo (local git checkout) "
        "or owner/repo@base..head / GITHUB_REPOSITORY for GitHub API."
    )


def resolve_diff(reference: str, local_repo: Path | None = None) -> str:
    """Resolve any supported review reference to unified diff text."""
    reference = reference.strip()
    path = Path(reference)
    if path.is_file() and path.suffix in (".patch", ".diff"):
        return path.read_text(encoding="utf-8", errors="replace")

    if is_commit_reference(reference):
        return resolve_commit_diff(reference, local_repo)

    if is_pr_reference(reference):
        from src.mcp_servers.github_mcp_server import get_pr_diff

        result = get_pr_diff(reference)
        if result.startswith("Error"):
            raise DiffResolveError(result)
        return result

    # Last resort: let GitHub MCP try (patch path, PR, etc.)
    from src.mcp_servers.github_mcp_server import get_pr_diff

    result = get_pr_diff(reference)
    if result.startswith("Error"):
        raise DiffResolveError(result)
    return result
