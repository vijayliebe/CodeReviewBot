from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class PlatformAdapter:
    """Injectable stack support — detection + rules + compact agent hints."""

    id: str
    name: str
    rules: list[dict]
    detect: Callable[[Path], bool]
    agent_hints: str = ""
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)


@dataclass
class RepoProfile:
    project_name: str
    languages: list[str]
    frameworks: list[str]
    platform_adapters: list[str]
    repo_kind: str
    architecture: str
    integration_layers: dict
    infra_tools: list[str]
    package_managers: list[str] = field(default_factory=list)
    has_tests: bool = False
    has_ci_cd: bool = False
    monorepo: bool = False

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "languages": self.languages,
            "frameworks": self.frameworks,
            "platform_adapters": self.platform_adapters,
            "repo_kind": self.repo_kind,
            "architecture": self.architecture,
            "integration_layers": self.integration_layers,
            "infra_tools": self.infra_tools,
            "package_managers": self.package_managers,
            "has_tests": self.has_tests,
            "has_ci_cd": self.has_ci_cd,
            "monorepo": self.monorepo,
        }
