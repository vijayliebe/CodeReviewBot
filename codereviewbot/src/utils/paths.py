import os
from pathlib import Path

# Product-level workspace config (registry, shared rules, vector index)
CRB_WORKSPACE_DIR = ".crb-workspace"

# Per-repo review rules (one rules.yaml per repository)
CRB_REPO_DIR = ".crb"


def get_project_root() -> Path:
    """codereviewbot package root (src/utils/paths.py -> parents[2])."""
    return Path(__file__).resolve().parents[2]


def get_workspace_root() -> Path:
    """Monorepo / review workspace root (parent of codereviewbot/)."""
    env = os.environ.get("CRB_WORKSPACE_ROOT")
    if env:
        return Path(env).resolve()
    return get_project_root().parent


def read_pyproject_name(root: Path) -> str | None:
    """Return [project].name from pyproject.toml when present."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        name = data.get("project", {}).get("name")
        return name if isinstance(name, str) and name.strip() else None
    except Exception:
        return None


def default_product_name() -> str:
    """Workspace product label — use package name, not the clone directory name."""
    return read_pyproject_name(get_project_root()) or "codereviewbot"


def workspace_dir(root: Path | None = None) -> Path:
    return (root or get_workspace_root()) / CRB_WORKSPACE_DIR


def workspace_config_path(root: Path | None = None) -> Path:
    return workspace_dir(root) / "workspace.yaml"


def shared_rules_path(root: Path | None = None) -> Path:
    return workspace_dir(root) / "shared_rules.yaml"


def workspace_chroma_path(root: Path | None = None) -> Path:
    return workspace_dir(root) / "chroma_db"


def repo_config_dir(repo_root: Path) -> Path:
    return repo_root / CRB_REPO_DIR


def repo_rules_path(repo_root: Path) -> Path:
    return repo_config_dir(repo_root) / "rules.yaml"


def is_reserved_init_root(path: Path) -> bool:
    """Paths where `init` must not write .crb (use benchmark_repos/* instead)."""
    resolved = path.resolve()
    return resolved in {get_workspace_root().resolve(), get_project_root().resolve()}


def find_rules_yaml(start: Path | None = None) -> Path | None:
    """Locate .crb/rules.yaml walking up from the repo under review only."""
    if start is None:
        return None
    root = start.resolve()
    workspace = get_workspace_root().resolve()
    for candidate in [root, *root.parents]:
        rules = repo_rules_path(candidate)
        if rules.is_file():
            return rules
        if candidate == workspace:
            break
    return None
