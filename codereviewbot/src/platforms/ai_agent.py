from pathlib import Path

from src.platforms._shared import PYTHON_RULES, _deps_contain, _file_contains
from src.platforms.base import PlatformAdapter

AI_AGENT_RULES = [
    {
        "id": "agent-no-hardcoded-api-key",
        "description": "Do not hardcode LLM/API keys in agent source code.",
        "pattern": r'(GOOGLE_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY)\s*=\s*["\'][^"\']+["\']',
        "files": ["**/*.py", "**/*.ts", "**/*.js"],
        "severity": "critical",
        "suggestion": "Load keys from environment variables or a secrets manager.",
    },
    {
        "id": "agent-inline-mega-prompt",
        "description": "Avoid large inline system prompts; use template files under prompts/ or .agents/.",
        "pattern": r'instruction\s*=\s*"""[\s\S]{500,}"""',
        "files": ["**/*.py"],
        "severity": "medium",
        "suggestion": "Extract prompts to a dedicated template file.",
    },
    {
        "id": "agent-unsandboxed-shell",
        "description": "Shell/subprocess tools must restrict working directory and validate commands.",
        "pattern": r"subprocess\.(run|call|Popen)\([^)]*shell\s*=\s*True",
        "files": ["**/*.py"],
        "severity": "high",
        "suggestion": "Avoid shell=True; whitelist commands and sandbox paths.",
    },
]


def detect_ai_agent(root: Path) -> bool:
    if _deps_contain(root, "google-adk", "langgraph", "crewai", "autogen", "semantic-kernel"):
        return True
    if _file_contains(root, "SKILL.md"):
        return True
    for path in root.rglob(".agents"):
        if path.is_dir():
            return True
    return _file_contains(root, "*_mcp_server.py") or _file_contains(root, "orchestrator.py")


ADAPTER = PlatformAdapter(
    id="ai_agent",
    name="AI Agent (ADK, LangGraph, CrewAI, MCP)",
    rules=PYTHON_RULES + AI_AGENT_RULES,
    detect=detect_ai_agent,
    languages=["python", "typescript"],
    frameworks=["google-adk", "langgraph", "crewai", "autogen"],
    agent_hints=(
        "AI-agent repo: no hardcoded API keys, prompt templates vs inline strings, agent/tool timeouts, "
        "MCP input validation, sandboxed filesystem tools, secrets not in .env.example."
    ),
)
