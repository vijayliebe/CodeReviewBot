import os
import re
import urllib.parse
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("GitHubServer")

# Read token from environment
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

def _parse_github_url(url_or_str: str) -> tuple[str, str, str]:
    """Parses owner, repo, and pull_number from a GitHub pull request URL.
    Example: https://github.com/owner/repo/pull/123 -> ('owner', 'repo', '123')
    If url_or_str is just a number, assumes a default owner/repo if configured.
    """
    url_or_str = url_or_str.strip()
    
    # Try parsing URL
    pattern = r"github\.com/([^/]+)/([^/]+)/pull/(\d+)"
    match = re.search(pattern, url_or_str)
    if match:
        return match.group(1), match.group(2), match.group(3)
        
    # Fallback to owner/repo/number format
    parts = url_or_str.split("/")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
        
    # If just a number and env vars exist for default repo
    default_repo = os.environ.get("GITHUB_REPOSITORY", "") # e.g. "owner/repo"
    if url_or_str.isdigit() and "/" in default_repo:
        owner, repo = default_repo.split("/", 1)
        return owner, repo, url_or_str
        
    raise ValueError(
        f"Invalid GitHub PR URL or reference: '{url_or_str}'. "
        "Expected format: 'https://github.com/owner/repo/pull/123' or 'owner/repo/123'."
    )

def _get_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "CodeReviewBot-MCP"
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers

@mcp.tool()
def get_commit_diff(commit_reference: str) -> str:
    """Fetch the unified diff for one commit or a commit range.

    Supported formats:
      - Single SHA: ``abc1234`` (requires local repo via CRB_WORKSPACE_ROOT or
        ``owner/repo@abc1234`` / ``GITHUB_REPOSITORY`` for GitHub API)
      - Range: ``base..head`` or ``base...head`` (local git with --repo)
      - GitHub repo + range: ``owner/repo@base..head`` or ``owner/repo:base..head``
      - Compare URL: ``https://github.com/owner/repo/compare/base...head``

    Args:
        commit_reference: Commit SHA, range, or GitHub compare reference.
    """
    try:
        from src.utils.diff_resolver import resolve_commit_diff, DiffResolveError

        local_root = os.environ.get("CRB_WORKSPACE_ROOT", "")
        local_repo = Path(local_root) if local_root else None
        return resolve_commit_diff(commit_reference, local_repo)
    except DiffResolveError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def get_pr_diff(pr_reference: str) -> str:
    """Fetch the raw diff of a GitHub pull request, commit range, or local patch.

    Args:
        pr_reference: PR URL ('https://github.com/owner/repo/pull/12'), short form
                      ('owner/repo/12'), commit SHA/range ('abc..def', 'owner/repo@abc..def'),
                      compare URL, or path to a local ``.patch`` / ``.diff`` file.
    """
    pr_reference = pr_reference.strip()

    # Support local patch files for offline/mock testing
    if pr_reference.endswith(".patch") or pr_reference.endswith(".diff") or os.path.exists(pr_reference):
        if os.path.exists(pr_reference):
            try:
                with open(pr_reference, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
            except Exception as e:
                return f"Error reading local patch file: {str(e)}"
        return f"Error: Local file '{pr_reference}' not found."

    try:
        from src.utils.diff_resolver import is_commit_reference, resolve_commit_diff, DiffResolveError

        if is_commit_reference(pr_reference):
            local_root = os.environ.get("CRB_WORKSPACE_ROOT", "")
            local_repo = Path(local_root) if local_root else None
            return resolve_commit_diff(pr_reference, local_repo)
    except DiffResolveError as e:
        return f"Error: {e}"
    except Exception:
        pass

    try:
        owner, repo, pull_number = _parse_github_url(pr_reference)
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}"
        
        # GitHub API returns diff when Accept header is application/vnd.github.diff
        headers = _get_headers()
        headers["Accept"] = "application/vnd.github.diff"
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            return response.text
        elif response.status_code == 401 or response.status_code == 403:
            return f"Error: Unauthorized access (status {response.status_code}). Please check your GITHUB_TOKEN."
        elif response.status_code == 404:
            return f"Error: PR not found (status 404). Ensure repository and PR number '{pull_number}' exist."
        else:
            return f"Error fetching diff from GitHub: Status code {response.status_code}\n{response.text}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def get_pr_files(pr_reference: str) -> str:
    """List all files changed in a Pull Request with their additions and deletions.
    
    Args:
        pr_reference: PR URL or reference string.
    """
    try:
        owner, repo, pull_number = _parse_github_url(pr_reference)
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}/files"
        
        response = requests.get(url, headers=_get_headers(), timeout=15)
        
        if response.status_code == 200:
            files_data = response.json()
            lines = []
            for f in files_data:
                status = f.get("status", "modified").upper()
                filename = f.get("filename", "")
                additions = f.get("additions", 0)
                deletions = f.get("deletions", 0)
                lines.append(f"[{status}] {filename} (+{additions}, -{deletions})")
            return "\n".join(lines) if lines else "No files changed in this PR."
        else:
            return f"Error fetching PR files: Status code {response.status_code}\n{response.text}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def get_file_content(pr_reference: str, filename: str, ref: str = "main") -> str:
    """Get the raw content of a specific file in the repository at a given commit/branch.
    
    Args:
        pr_reference: PR URL or reference to identify owner/repo.
        filename: Relative path of the file in the repo.
        ref: Commit SHA, branch, or tag (defaults to 'main').
    """
    try:
        owner, repo, _ = _parse_github_url(pr_reference)
        # Urlencode filename
        safe_filename = urllib.parse.quote(filename)
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{safe_filename}?ref={ref}"
        
        headers = _get_headers()
        # Fetch raw content directly
        headers["Accept"] = "application/vnd.github.raw"
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            return response.text
        else:
            return f"Error fetching file content: Status code {response.status_code}\n{response.text}"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def post_review_comment(pr_reference: str, body: str) -> str:
    """Post a high-level review comment on a Pull Request.
    
    Args:
        pr_reference: PR URL or reference string.
        body: The markdown text of the comment.
    """
    if not GITHUB_TOKEN:
        return "Error: GITHUB_TOKEN is not set. Cannot post comment. (Output would have been: \n" + body + ")"
        
    try:
        owner, repo, pull_number = _parse_github_url(pr_reference)
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pull_number}/comments"
        
        response = requests.post(url, headers=_get_headers(), json={"body": body}, timeout=15)
        
        if response.status_code == 201:
            return "Successfully posted review comment on the PR."
        else:
            return f"Error posting comment: Status code {response.status_code}\n{response.text}"
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    mcp.run()
