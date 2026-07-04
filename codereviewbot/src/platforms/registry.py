"""Platform registry — detects stack and injects rules + agent hints into the core pipeline."""

from functools import lru_cache
from pathlib import Path

from src.platforms.base import PlatformAdapter, RepoProfile
from src.platforms import python_web, mobile, ai_agent, web_frontend, infra
from src.platforms._shared import INTEGRATION_DB_RULES, INTEGRATION_REDIS_RULES
from src.utils.paths import read_pyproject_name

ADAPTERS: list[PlatformAdapter] = [
    python_web.ADAPTER,
    mobile.ADAPTER,
    ai_agent.ADAPTER,
    web_frontend.ADAPTER,
    infra.ADAPTER,
]

ADAPTER_BY_ID = {a.id: a for a in ADAPTERS}

SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__", ".pytest_cache", "dist", "build"}


def _detect_languages(root: Path) -> list[str]:
    langs: set[str] = set()
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".swift": "swift",
        ".kt": "kotlin",
        ".dart": "dart",
        ".java": "java",
        ".go": "go",
        ".tf": "hcl",
    }
    for path in root.rglob("*"):
        if not path.is_file() or any(s in path.parts for s in SKIP_DIRS):
            continue
        lang = ext_map.get(path.suffix.lower())
        if lang:
            langs.add(lang)
    if (root / "requirements.txt").exists() or (root / "pyproject.toml").exists():
        langs.add("python")
    if (root / "package.json").exists():
        langs.update({"javascript", "typescript"})
    return sorted(langs)


def _detect_integrations(root: Path) -> dict:
    layers: dict = {}
    for path in root.rglob("*"):
        if not path.is_file() or any(s in path.parts for s in SKIP_DIRS):
            continue
        if path.name not in ("requirements.txt", "pyproject.toml", "package.json"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if "redis" in text:
            layers["cache"] = "redis"
        if any(x in text for x in ("psycopg2", "sqlalchemy", "django", "prisma", "pg")):
            layers["db"] = "postgresql"
        if "mongodb" in text or "mongoose" in text:
            layers["db"] = "mongodb"
    return layers


def _detect_infra(root: Path) -> list[str]:
    tools: list[str] = []
    if list(root.rglob("*.tf")):
        tools.append("terraform")
    if (root / "docker-compose.yml").exists() or list(root.rglob("Dockerfile")):
        tools.append("docker")
    if (root / ".github" / "workflows").is_dir():
        tools.append("github-actions")
    return tools


def _infer_repo_kind(active: list[PlatformAdapter]) -> str:
    ids = {a.id for a in active}
    if "ai_agent" in ids:
        return "ai-agent"
    if "mobile" in ids:
        return "mobile"
    if "infra" in ids and len(ids) == 1:
        return "infra"
    return "application"


def _infer_architecture(active: list[PlatformAdapter], languages: list[str]) -> str:
    ids = {a.id for a in active}
    if "mobile" in ids:
        return "mobile-app"
    if "ai_agent" in ids:
        return "ai-agent"
    if len(languages) > 2 or len(active) > 2:
        return "microservice"
    return "monolith"


def profile_repo(root: Path) -> RepoProfile:
    """Heuristic repo profiling used by init, benchmark, and review preamble.

    Cached per-process by resolved path — `profile_repo` walks the filesystem
    multiple times via rglob, and the review pipeline calls it more than once.
    The cache avoids re-walking for the duration of a single CLI invocation.
    """
    return _profile_repo_cached(root.resolve())


@lru_cache(maxsize=32)
def _profile_repo_cached(root: Path) -> RepoProfile:
    root = root.resolve() if not root.is_absolute() else root
    active = [a for a in ADAPTERS if a.detect(root)]
    languages = _detect_languages(root)
    for a in active:
        languages.extend(a.languages)
    languages = sorted(set(languages))

    frameworks: list[str] = []
    for a in active:
        frameworks.extend(a.frameworks)
    frameworks = sorted(set(frameworks))

    integration = _detect_integrations(root)
    infra_tools = _detect_infra(root)

    package_managers: list[str] = []
    if (root / "requirements.txt").exists() or (root / "pyproject.toml").exists():
        package_managers.append("pip")
    if (root / "package.json").exists():
        package_managers.append("npm")
    if (root / "pubspec.yaml").exists():
        package_managers.append("pub")

    has_tests = any(
        p.is_dir() and p.name in ("tests", "test", "__tests__")
        for p in root.rglob("*")
        if p.is_dir() and not any(s in p.parts for s in SKIP_DIRS)
    )

    return RepoProfile(
        project_name=read_pyproject_name(root) or root.name,
        languages=languages,
        frameworks=frameworks,
        platform_adapters=[a.id for a in active],
        repo_kind=_infer_repo_kind(active),
        architecture=_infer_architecture(active, languages),
        integration_layers=integration,
        infra_tools=infra_tools,
        package_managers=package_managers,
        has_tests=has_tests,
        has_ci_cd="github-actions" in infra_tools,
        monorepo=len(list(root.glob("apps/*"))) > 1 or len(list(root.glob("packages/*"))) > 1,
    )


def collect_rules(profile: RepoProfile | dict) -> list[dict]:
    """Merge rules from active platform adapters + integration layers."""
    if isinstance(profile, RepoProfile):
        data = profile.to_dict()
    else:
        data = profile

    adapter_ids = data.get("platform_adapters", [])
    seen_ids: set[str] = set()
    rules: list[dict] = []

    def add_rules(items: list[dict]) -> None:
        for rule in items:
            rid = rule.get("id")
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            rules.append(rule)

    for aid in adapter_ids:
        adapter = ADAPTER_BY_ID.get(aid)
        if adapter:
            add_rules(adapter.rules)

    integration = data.get("integration_layers", {})
    if integration.get("cache") == "redis":
        add_rules(INTEGRATION_REDIS_RULES)
    if integration.get("db"):
        add_rules(INTEGRATION_DB_RULES)

    if not rules:
        add_rules(python_web.ADAPTER.rules[:2])
        add_rules(web_frontend.ADAPTER.rules[:1])

    return rules


def build_review_preamble(profile: RepoProfile | dict) -> str:
    """Compact context injected into review query to save tokens vs re-scanning."""
    if isinstance(profile, RepoProfile):
        data = profile.to_dict()
    else:
        data = profile

    hints: list[str] = []
    for aid in data.get("platform_adapters", []):
        adapter = ADAPTER_BY_ID.get(aid)
        if adapter and adapter.agent_hints:
            hints.append(f"- **{adapter.name}**: {adapter.agent_hints}")

    lines = [
        "## PRELOADED_REPO_PROFILE (use this; do not re-scan entire repo)",
        f"- Languages: {', '.join(data.get('languages', [])) or 'unknown'}",
        f"- Frameworks: {', '.join(data.get('frameworks', [])) or 'none detected'}",
        f"- Platform adapters: {', '.join(data.get('platform_adapters', [])) or 'generic'}",
        f"- Architecture: {data.get('architecture', 'unknown')} | Kind: {data.get('repo_kind', 'application')}",
        f"- Integrations: {data.get('integration_layers', {})}",
        "",
        "## PLATFORM_REVIEW_HINTS",
        *hints,
        "",
        "Keep DIFF_SUMMARY to changed hunks only (±15 lines context). Do not paste unchanged files.",
    ]
    return "\n".join(lines)
