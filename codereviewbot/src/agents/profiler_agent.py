from google.adk.agents.llm_agent import Agent
from src.mcp_servers.filesystem_mcp_server import list_directory, read_file
from src.mcp_servers.github_mcp_server import get_pr_diff, get_pr_files, get_commit_diff

PROFILER_INSTRUCTION = """You are the Repo Profiler & Diff Analyzer Agent.
Analyze the PR reference, commit range, or local patch, detect the repository stack, and parse the diff.

Steps:
1. Determine if the reference is a GitHub PR, commit SHA/range, or a local file/patch.
2. Fetch the diff via `get_pr_diff` (PRs and patches) or `get_commit_diff` (commit SHAs/ranges).
   Commit examples: `abc1234`, `base..head`, `owner/repo@base..head`.
3. Use `get_pr_files` for PR file lists; for commits the diff headers list changed files.
4. Use `list_directory` only when stack is unclear from the diff headers.
4. Detect REPO_PROFILE including:
   - Languages: Python, JS/TS, Swift, Kotlin, Dart, Java, Go, HCL
   - Frameworks: React, Django, Flask, FastAPI, Zango, Flutter, React Native, NestJS, google-adk, LangGraph, CrewAI
   - Platform adapters: python_web | mobile | web_frontend | ai_agent | infra
   - Architecture: monolith | microservice | mobile-app | ai-agent | library | infra
   - Integration layers: Redis, PostgreSQL, MongoDB, Bull/Kafka queues
5. If PRELOADED_REPO_PROFILE is provided in the user message, trust it for stack detection.

Output Markdown with two sections:
- **REPO_PROFILE**: languages, frameworks, platform_adapters, architecture, integration_layers
- **DIFF_SUMMARY**: changed files list + diff hunks only (do NOT paste full unchanged files; ±15 lines context per hunk)

Downstream agents use REPO_PROFILE for mobile, Python web, and AI-agent specific checks.
"""

profiler_agent = Agent(
    name="profiler_agent",
    model="gemini-2.5-flash",
    description="Analyzes the PR diff and profiles the repository language, architecture, and integration layers.",
    instruction=PROFILER_INSTRUCTION,
    tools=[get_pr_diff, get_pr_files, get_commit_diff, list_directory, read_file],
)
