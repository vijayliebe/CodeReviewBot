from pathlib import Path

from src.platforms._shared import JAVASCRIPT_RULES, _deps_contain, _file_contains
from src.platforms.base import PlatformAdapter

WEB_FRONTEND_RULES = JAVASCRIPT_RULES + [
    {
        "id": "strict-equality",
        "description": "Prefer === and !== over == and != for comparison.",
        "pattern": r"\s==\s|\s!=\s",
        "files": ["**/*.js", "**/*.ts", "**/*.jsx", "**/*.tsx"],
        "severity": "low",
        "suggestion": "Use === or !== to prevent unexpected JS coercion issues",
    },
]


def detect_web_frontend(root: Path) -> bool:
    if _deps_contain(root, "react", "vue", "angular", "next"):
        return True
    return _file_contains(root, "next.config.js") or _file_contains(root, "angular.json")


ADAPTER = PlatformAdapter(
    id="web_frontend",
    name="Web Frontend (React, Vue, Angular, Next.js)",
    rules=WEB_FRONTEND_RULES,
    detect=detect_web_frontend,
    languages=["javascript", "typescript"],
    frameworks=["react", "vue", "angular", "next.js"],
    agent_hints="Web frontend: XSS in dangerouslySetInnerHTML, console.log in prod, API contract breaks with backend.",
)
