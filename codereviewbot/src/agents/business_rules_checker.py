from pathlib import Path
from google.adk.agents.llm_agent import Agent
from src.mcp_servers.code_memory_mcp_server import get_pattern_frequency
from src.mcp_servers.filesystem_mcp_server import read_file, search_files
from src.utils.rules_parser import parse_rules_file, check_file_rules
from src.utils.paths import CRB_REPO_DIR, find_rules_yaml, get_workspace_root
from src.workspace.store import (
    load_shared_rules,
    get_related_repos,
    find_repo_id_for_path,
)


def check_custom_rules(file_path: str, content: str) -> str:
    """Run validation against merged rules: workspace shared + repo-level + platform.

    This ensures product-wide business rules (e.g. 'no-float-for-money' across all
    backend services) are enforced even if the individual repo's rules.yaml doesn't
    define them, while still respecting repo-level overrides.
    """
    try:
        repo_path = Path(file_path).resolve().parent if file_path else None
        # Walk up to find the repo root (heuristic: directory containing .crb/)
        repo_root = _find_repo_root(file_path)
        if repo_root is None:
            repo_root = get_workspace_root()

        # Gather rules from all three layers
        rules: list[dict] = []

        # Layer 1: workspace shared rules (product-level)
        rules.extend(load_shared_rules(get_workspace_root()))

        # Layer 2: repo-level rules
        rules_path = find_rules_yaml(repo_root)
        if rules_path:
            config = parse_rules_file(rules_path)
            rules.extend(config.get("rules", []))

        if not rules:
            return "No rules found. Run `codereviewbot init --path <repo>` or create .crb-workspace/shared_rules.yaml."

        # Deduplicate by rule_id (repo overrides shared)
        seen: dict[str, dict] = {}
        for r in rules:
            rid = r.get("id")
            if rid:
                seen[rid] = r
            else:
                seen[f"_{len(seen)}"] = r
        merged_config = {"rules": list(seen.values())}

        findings = check_file_rules(file_path, content, merged_config)
        if not findings:
            return "Success: No rules violated."

        lines = []
        for f in findings:
            source = f.get("source", "config-file")
            lines.append(
                f"- [{f['severity']}] Rule {f['rule_id']} ({f['category']}) in {f['file']}:{f['line']}: "
                f"{f['description']}. Suggestion: {f['suggestion']} [source: {source}]"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error executing custom rules check: {e}"


def get_repo_relationships(file_path: str) -> str:
    """Return upstream/downstream repos for the repo containing the given file.

    This lets the Business Rules and Impact agents know which other repos share
    business rules or could be affected by contract changes.
    """
    try:
        repo_root = _find_repo_root(file_path)
        if repo_root is None:
            return "No workspace registry found. Create .crb-workspace/workspace.yaml to enable cross-repo rules."

        repo_id = find_repo_id_for_path(repo_root)
        if not repo_id:
            return f"Repo at {repo_root} is not registered in the workspace."

        related = get_related_repos(repo_id)
        upstream = [f"{r.id} ({r.kind})" for r in related["upstream"]]
        downstream = [f"{r.id} ({r.kind})" for r in related["downstream"]]
        return (
            f"Repo: {repo_id}\n"
            f"Upstream (consumes): {', '.join(upstream) or 'none'}\n"
            f"Downstream (provides to): {', '.join(downstream) or 'none'}\n"
            f"Shared business rules from workspace apply automatically."
        )
    except Exception as e:
        return f"Error looking up repo relationships: {e}"


def _find_repo_root(file_path: str) -> Path | None:
    """Walk up from file_path to find the nearest directory with .crb/."""
    if not file_path:
        return None
    p = Path(file_path).resolve()
    if p.is_file():
        p = p.parent
    ws_root = get_workspace_root()
    while p != p.parent:
        if (p / CRB_REPO_DIR).is_dir():
            return p
        if p == ws_root:
            return p
        p = p.parent
    return None


RULES_INSTRUCTION = """You are the Business Rules Agent.
Validate code changes against the project's domain rules, architecture policies, and shared product rules.

You must handle:
1. **Merged Rules (workspace shared + repo-level)**: Call `check_custom_rules` for each modified file.
   This tool automatically merges product-level shared rules (from .crb-workspace/shared_rules.yaml)
   with repo-level rules (from the repo's .crb/rules.yaml). Repo-level rules override shared
   rules by rule_id. This avoids duplicating the same business rule across every backend/frontend repo.
2. **Inline Annotations**: Parse for `# crb:ignore <rule_id>` (suppress) and `# crb:rule "<desc>"` (custom per-line).
   The `check_custom_rules` tool already respects `# crb:ignore`.
3. **Auto-Discovered Patterns**: Call `get_pattern_frequency` to check how common a convention is.
   Suggest it as a new rule if it appears in >80% of similar files.
4. **Cross-Repo Context**: Call `get_repo_relationships` to learn which other repos in the workspace
   share business rules or could be affected by contract changes in this PR.

Input provided:
- The REPO_PROFILE: active technologies.
- The DIFF_SUMMARY: code changes.

Output a structured Markdown report under "📏 BUSINESS RULES FINDINGS". For each violation:
- Rule ID, Severity, Category, File, Line, Description, Source (shared/repo-config/auto-discovered/inline), Suggestion
If no violations, output: "No business rule violations detected."
"""

business_rules_checker = Agent(
    name="business_rules_checker",
    model="gemini-2.5-flash",
    description="Validates code against workspace shared rules, repo-specific rules.yaml, inline annotations, and auto-discovered patterns.",
    instruction=RULES_INSTRUCTION,
    tools=[check_custom_rules, get_repo_relationships, get_pattern_frequency, read_file, search_files],
)
