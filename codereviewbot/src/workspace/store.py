"""Workspace store — product-level shared rules, repo registry, and relationships.

A workspace groups related repos (frontend, backend, database, downstream services)
that belong to the same product. This enables:
  - Shared business rules inherited by all repos (deduped)
  - Repo relationship tracking (upstream/downstream contracts)
  - Cross-repo reference lookup and impact analysis

Layout (lives at workspace root, parent of codereviewbot/):

  workspace_root/
  ├── .crb-workspace/
  │   ├── workspace.yaml           # product name + repo registry
  │   ├── shared_rules.yaml        # product-level rules inherited by all repos
  │   └── chroma_db/               # multi-repo vector store (repo_id metadata)
  ├── codereviewbot/
  ├── benchmark_repos/
  └── <repo dirs>/
      └── .crb/
          └── rules.yaml           # repo-specific rules (override shared)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.utils.paths import (
    get_workspace_root,
    repo_rules_path,
    shared_rules_path,
    workspace_chroma_path,
    workspace_config_path,
    default_product_name,
)

# Re-export path helpers for callers that import from store.
# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RepoRecord:
    id: str
    path: str
    kind: str = "service"  # frontend | backend | database | service | library | infra | mobile | ai-agent
    consumes: list[str] = field(default_factory=list)   # repo ids this repo calls
    provides: list[str] = field(default_factory=list)   # repo ids that call this repo
    contracts: list[dict] = field(default_factory=list)  # API/queue/schema contracts


@dataclass
class WorkspaceConfig:
    product: str
    repos: dict[str, RepoRecord]

    def to_dict(self) -> dict:
        return {
            "product": self.product,
            "repos": {
                rid: {
                    "path": r.path,
                    "kind": r.kind,
                    "consumes": r.consumes,
                    "provides": r.provides,
                    "contracts": r.contracts,
                }
                for rid, r in self.repos.items()
            },
        }


# ---------------------------------------------------------------------------
# Workspace config load / save
# ---------------------------------------------------------------------------


def load_workspace(root: Path | None = None) -> WorkspaceConfig | None:
    path = workspace_config_path(root)
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    repos: dict[str, RepoRecord] = {}
    for rid, rdata in (data.get("repos") or {}).items():
        repos[rid] = RepoRecord(
            id=rid,
            path=rdata.get("path", ""),
            kind=rdata.get("kind", "service"),
            consumes=rdata.get("consumes", []),
            provides=rdata.get("provides", []),
            contracts=rdata.get("contracts", []),
        )
    return WorkspaceConfig(product=data.get("product", "default"), repos=repos)


def save_workspace(cfg: WorkspaceConfig, root: Path | None = None) -> Path:
    path = workspace_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# CodeReviewBot workspace config — product-level repo registry\n"
        "# Edit manually to add repos, contracts, and relationships.\n\n"
        + yaml.dump(cfg.to_dict(), default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return path


def init_workspace(product: str, root: Path | None = None) -> WorkspaceConfig:
    """Create or return a workspace config."""
    existing = load_workspace(root)
    if existing:
        return existing
    cfg = WorkspaceConfig(product=product, repos={})
    save_workspace(cfg, root)
    return cfg


def register_repo(
    repo_id: str,
    repo_path: str,
    kind: str = "service",
    root: Path | None = None,
) -> WorkspaceConfig:
    """Add or update a repo in the workspace registry."""
    cfg = load_workspace(root)
    if cfg is None:
        cfg = WorkspaceConfig(product=default_product_name(), repos={})
    cfg.repos[repo_id] = RepoRecord(id=repo_id, path=repo_path, kind=kind)
    save_workspace(cfg, root)
    return cfg


# ---------------------------------------------------------------------------
# Shared rules load / save
# ---------------------------------------------------------------------------


def load_shared_rules(root: Path | None = None) -> list[dict]:
    path = shared_rules_path(root)
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules: list[dict] = []
    for key in ("domain_rules", "architecture_rules", "integration_rules", "infra_rules", "custom_rules", "rules"):
        items = data.get(key)
        if isinstance(items, list):
            for r in items:
                r = dict(r)
                r["category"] = key.replace("_rules", "").capitalize()
                r["source"] = "workspace-shared"
                rules.append(r)
    return rules


def save_shared_rules(rules: list[dict], root: Path | None = None) -> Path:
    path = shared_rules_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"rules": rules}
    path.write_text(
        "# CodeReviewBot shared rules — inherited by ALL repos in this workspace.\n"
        "# Repo-level .crb/rules.yaml can override these by rule_id.\n\n"
        + yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Merged rules: shared (workspace) + repo-level + platform-injected
# ---------------------------------------------------------------------------


def merge_rules(shared: list[dict], repo_rules: list[dict]) -> list[dict]:
    """Merge shared workspace rules with repo-level rules. Repo overrides by rule_id."""
    by_id: dict[str, dict] = {}
    for r in shared:
        rid = r.get("id")
        if rid:
            by_id[rid] = r
    for r in repo_rules:
        rid = r.get("id")
        if rid:
            r = dict(r)
            r.setdefault("source", "repo-config")
            by_id[rid] = r  # override
        else:
            by_id[f"_{len(by_id)}"] = r
    return list(by_id.values())


def get_effective_rules(repo_path: Path, root: Path | None = None) -> list[dict]:
    """Return the full rule set that applies to a repo: shared + repo + platform."""
    from src.platforms.registry import profile_repo, collect_rules

    shared = load_shared_rules(root)
    rules_path = repo_rules_path(repo_path)
    repo_rules: list[dict] = []
    if rules_path.is_file():
        from src.utils.rules_parser import parse_rules_file

        repo_rules = parse_rules_file(rules_path).get("rules", [])

    profile = profile_repo(repo_path)
    platform_rules = collect_rules(profile.to_dict())

    # Merge: platform (lowest) → shared → repo (highest)
    merged: dict[str, dict] = {}
    for r in platform_rules:
        if r.get("id"):
            merged[r["id"]] = r
    for r in shared:
        if r.get("id"):
            merged[r["id"]] = r
    for r in repo_rules:
        if r.get("id"):
            merged[r["id"]] = r

    return list(merged.values())


# ---------------------------------------------------------------------------
# Repo relationships
# ---------------------------------------------------------------------------


def get_related_repos(repo_id: str, root: Path | None = None) -> dict:
    """Return upstream (who this repo consumes) and downstream (who consumes this)."""
    cfg = load_workspace(root)
    if not cfg or repo_id not in cfg.repos:
        return {"upstream": [], "downstream": []}

    record = cfg.repos[repo_id]
    upstream = [cfg.repos[u] for u in record.consumes if u in cfg.repos]
    downstream = [
        cfg.repos[r] for r, rec in cfg.repos.items()
        if repo_id in rec.consumes
    ]
    return {"upstream": upstream, "downstream": downstream}


def find_repo_id_for_path(repo_path: Path, root: Path | None = None) -> str | None:
    """Find the workspace repo_id for a given filesystem path."""
    cfg = load_workspace(root)
    if not cfg:
        return None
    resolved = repo_path.resolve()
    for rid, record in cfg.repos.items():
        rpath = (get_workspace_root() if root is None else root) / record.path
        if rpath.resolve() == resolved:
            return rid
    return None
