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


def find_rules_yaml(start: Path | None = None) -> Path | None:
    """Locate .crb/rules.yaml walking up from start or workspace root."""
    root = (start or get_workspace_root()).resolve()
    for candidate in [root, *root.parents]:
        rules = repo_rules_path(candidate)
        if rules.is_file():
            return rules
        if candidate == get_project_root():
            break
    project_rules = repo_rules_path(get_project_root())
    return project_rules if project_rules.is_file() else None
