from pathlib import Path

from src.platforms._shared import PYTHON_RULES, _deps_contain, _file_contains
from src.platforms.base import PlatformAdapter

PYTHON_WEB_RULES = [
    {
        "id": "py-web-no-debug-true",
        "description": "Ensure DEBUG is disabled in production Django/Flask/Zango settings.",
        "pattern": r"DEBUG\s*=\s*(True|1)",
        "files": ["**/settings.py", "**/config.py", "**/app.py"],
        "severity": "critical",
        "suggestion": "Load DEBUG from environment variables, default False in production.",
    },
    {
        "id": "py-web-secret-key-leak",
        "description": "Do not hardcode SECRET_KEY in Django/Flask/Zango configs.",
        "pattern": r"SECRET_KEY\s*=\s*['\"][^'\"]{10,}['\"]",
        "files": ["**/settings.py", "**/config.py", "**/app.py"],
        "severity": "critical",
        "suggestion": "Load SECRET_KEY from environment variables.",
    },
    {
        "id": "py-web-csrf-exempt",
        "description": "Avoid @csrf_exempt on API views without documented justification.",
        "pattern": r"@csrf_exempt",
        "files": ["**/*.py"],
        "severity": "high",
        "suggestion": "Use CSRF protection or document why exemption is safe.",
    },
]


def detect_python_web(root: Path) -> bool:
    if _file_contains(root, "manage.py"):
        return True
    if _deps_contain(root, "django", "flask", "fastapi", "zango"):
        return True
    return _file_contains(root, "app.py", lambda t: "Flask(" in t or "FastAPI(" in t)


ADAPTER = PlatformAdapter(
    id="python_web",
    name="Python Web (Django, Flask, FastAPI, Zango)",
    rules=PYTHON_RULES + PYTHON_WEB_RULES,
    detect=detect_python_web,
    languages=["python"],
    frameworks=["django", "flask", "fastapi", "zango"],
    agent_hints=(
        "Python web stack: check DEBUG/SECRET_KEY in settings, migration files when models change, "
        "CSRF on views, ORM vs raw SQL, and @login_required on sensitive endpoints."
    ),
)
