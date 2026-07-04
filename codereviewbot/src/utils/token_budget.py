"""Token budget helpers — reduce LLM input size without losing review signal."""

import re
from pathlib import Path

SKIP_FILE_SUFFIXES = {
    ".lock", ".min.js", ".min.css", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".ico", ".svg", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip",
}
SKIP_FILE_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Gemfile.lock", "Podfile.lock", "pubspec.lock",
}


def should_skip_file(path: str) -> bool:
    name = Path(path).name
    if name in SKIP_FILE_NAMES:
        return True
    return Path(path).suffix.lower() in SKIP_FILE_SUFFIXES


def compact_diff(diff_text: str, max_lines: int = 400, context_lines: int = 15) -> str:
    """Trim large diffs: keep file headers and hunks, cap total lines."""
    if not diff_text:
        return diff_text

    lines = diff_text.splitlines()
    if len(lines) <= max_lines:
        return diff_text

    kept: list[str] = []
    hunk_buffer: list[str] = []
    in_hunk = False

    for line in lines:
        if line.startswith("diff --git") or line.startswith("--- ") or line.startswith("+++ "):
            if hunk_buffer:
                kept.extend(_trim_hunk(hunk_buffer, context_lines))
                hunk_buffer = []
            in_hunk = False
            kept.append(line)
            continue
        if line.startswith("@@"):
            if hunk_buffer:
                kept.extend(_trim_hunk(hunk_buffer, context_lines))
            hunk_buffer = [line]
            in_hunk = True
            continue
        if in_hunk:
            hunk_buffer.append(line)

    if hunk_buffer:
        kept.extend(_trim_hunk(hunk_buffer, context_lines))

    if len(kept) > max_lines:
        kept = kept[:max_lines]
        kept.append(f"\n... [diff truncated to {max_lines} lines for token budget] ...")

    return "\n".join(kept)


def _trim_hunk(hunk_lines: list[str], context_lines: int) -> list[str]:
    if len(hunk_lines) <= context_lines * 2 + 5:
        return hunk_lines
    header = hunk_lines[:1]
    body = hunk_lines[1:]
    changed_idx = [i for i, ln in enumerate(body) if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
    if not changed_idx:
        return hunk_lines
    keep: set[int] = set()
    for idx in changed_idx:
        for j in range(max(0, idx - context_lines), min(len(body), idx + context_lines + 1)):
            keep.add(j)
    trimmed = header + [body[i] for i in sorted(keep)]
    if len(trimmed) < len(hunk_lines):
        trimmed.append("... [hunk context trimmed] ...")
    return trimmed


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token for code)."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Diff-level filtering — applied BEFORE compact_diff to drop whole files/hunks
# that should never go to the LLM (lockfiles, binaries, whitespace-only noise).
# ---------------------------------------------------------------------------


def filter_diff(diff_text: str) -> str:
    """Strip hunks for files that should be skipped (lockfiles, binaries, assets)
    and drop whitespace-only hunks. Run before `compact_diff` for maximum savings.

    A diff is a sequence of file sections, each starting with `diff --git a/... b/...`
    followed by headers and one or more hunks. We drop entire file sections whose
    path triggers `should_skip_file`, and drop individual hunks whose only changes
    are whitespace.
    """
    if not diff_text:
        return diff_text

    lines = diff_text.splitlines()
    out: list[str] = []
    current_file: str | None = None
    skip_current_file = False
    hunk_buffer: list[str] = []

    def flush_hunk() -> None:
        nonlocal hunk_buffer
        if not hunk_buffer:
            return
        if not _hunk_is_whitespace_only(hunk_buffer):
            out.extend(hunk_buffer)
        hunk_buffer = []

    for line in lines:
        if line.startswith("diff --git"):
            flush_hunk()
            # Parse the file path: "diff --git a/foo/bar.py b/foo/bar.py"
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                current_file = parts[1].strip()
                skip_current_file = should_skip_file(current_file)
            else:
                skip_current_file = False
            if not skip_current_file:
                out.append(line)
            continue

        if skip_current_file:
            continue

        if line.startswith("@@"):
            flush_hunk()
            hunk_buffer = [line]
            continue

        if hunk_buffer or line.startswith(("--- ", "+++ ", "new file", "deleted file", "index ", "rename ")):
            if hunk_buffer:
                hunk_buffer.append(line)
            else:
                out.append(line)
        else:
            out.append(line)

    flush_hunk()
    return "\n".join(out)


def _hunk_is_whitespace_only(hunk_lines: list[str]) -> bool:
    """A hunk is whitespace-only if the non-whitespace content of its `+` lines
    equals the non-whitespace content of its `-` lines (order-insensitive).
    """
    plus: list[str] = []
    minus: list[str] = []
    for ln in hunk_lines:
        if ln.startswith(("+++", "---", "@@", "diff ")):
            continue
        if ln.startswith("+"):
            plus.append("".join(ln[1:].split()))
        elif ln.startswith("-"):
            minus.append("".join(ln[1:].split()))
    if not plus and not minus:
        return False
    return sorted(plus) == sorted(minus)


def extract_changed_files(diff_text: str) -> list[str]:
    """Return the list of file paths changed in the diff (added/modified/deleted)."""
    if not diff_text:
        return []
    files: list[str] = []
    seen: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                path = parts[1].strip()
                if path and path not in seen:
                    seen.add(path)
                    files.append(path)
    return files


def changed_files_summary(diff_text: str, max_files: int = 40) -> str:
    """Compact one-line-per-file summary of the diff, skipping lockfiles/binaries.
    Use this in the review preamble instead of the raw diff when the PR is huge."""
    files = [f for f in extract_changed_files(diff_text) if not should_skip_file(f)]
    if not files:
        return "No reviewable files changed."
    shown = files[:max_files]
    lines = [f"- {f}" for f in shown]
    if len(files) > max_files:
        lines.append(f"... and {len(files) - max_files} more files (omitted for token budget)")
    return "\n".join(lines)


def diff_stats(diff_text: str) -> dict:
    """Return {files, additions, deletions, hunks} for a diff — useful for logging token budget."""
    if not diff_text:
        return {"files": 0, "additions": 0, "deletions": 0, "hunks": 0}
    files = additions = deletions = hunks = 0
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            files += 1
        elif line.startswith("@@"):
            hunks += 1
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return {"files": files, "additions": additions, "deletions": deletions, "hunks": hunks}
