"""Shared base rules used across Python and JS stacks."""
from pathlib import Path

PYTHON_RULES = [
    {
        "id": "no-float-for-money",
        "description": "Never use float for monetary calculations. Always use Decimal.",
        "pattern": r"float\(",
        "files": ["**/payment*.py", "**/billing*.py", "**/invoice*.py", "**/finance*.py"],
        "severity": "critical",
        "suggestion": "Use `from decimal import Decimal` instead of float()",
    },
    {
        "id": "bare-except",
        "description": "Do not use bare except: clauses, always catch explicit Exceptions",
        "pattern": r"except\s*:",
        "files": ["**/*.py"],
        "severity": "medium",
        "suggestion": "Use `except Exception as e:` or catch specific error class",
    },
    {
        "id": "no-print-statements",
        "description": "Avoid using print() statements in production code. Use a logging framework.",
        "pattern": r"print\(",
        "files": ["**/*.py"],
        "exclude_files": ["**/tests/**", "**/test_*.py"],
        "severity": "medium",
        "suggestion": "Use logger.info() or logging.info() instead of print()",
    },
]

JAVASCRIPT_RULES = [
    {
        "id": "no-console-log",
        "description": "Do not leave console.log() statements in production files.",
        "pattern": r"console\.log\(",
        "files": ["**/*.js", "**/*.ts", "**/*.jsx", "**/*.tsx"],
        "exclude_files": ["**/*.test.*", "**/*.spec.*", "**/tests/**"],
        "severity": "medium",
        "suggestion": "Use a logger utility or remove console.log()",
    },
]

INTEGRATION_REDIS_RULES = [
    {
        "id": "redis-key-naming",
        "description": "Ensure Redis keys are prefixed correctly.",
        "pattern": r'redis\.(get|set|del)\("(?![\w\-]+:)',
        "files": ["**/*.py", "**/*.js", "**/*.ts"],
        "severity": "high",
        "suggestion": "Prefix keys with service/domain name (e.g. 'user:session_id')",
    },
]

INTEGRATION_DB_RULES = [
    {
        "id": "raw-sql-injection-risk",
        "description": "SQL queries must use parameter bindings instead of string interpolation.",
        "pattern": r"\.execute\(.*f['\"]|SELECT\s+.*%\s+|raw\s*\(",
        "files": ["**/*.py", "**/*.js", "**/*.ts", "**/*.java"],
        "severity": "critical",
        "suggestion": "Pass query parameters as tuple or list rather than using f-strings",
    },
]

TERRAFORM_RULES = [
    {
        "id": "tf-no-hardcoded-region",
        "description": "Terraform resources must use var.region, not hardcoded values",
        "pattern": r'region\s*=\s*"(us-|eu-|ap-)',
        "files": ["**/*.tf"],
        "severity": "high",
        "suggestion": "Use var.region instead of hardcoded region",
    },
]


def _file_contains(root: Path, pattern: str, content_check=None) -> bool:
    for path in root.rglob(pattern):
        if path.is_file() and ".venv" not in str(path) and "node_modules" not in str(path):
            if content_check is None:
                return True
            try:
                if content_check(path.read_text(encoding="utf-8", errors="replace")):
                    return True
            except OSError:
                continue
    return False


def _deps_contain(root: Path, *needles: str) -> bool:
    for name in ("requirements.txt", "pyproject.toml", "package.json", "pubspec.yaml"):
        for path in root.rglob(name):
            if not path.is_file() or ".venv" in str(path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace").lower()
                if any(n.lower() in text for n in needles):
                    return True
            except OSError:
                continue
    return False
