from pathlib import Path

from src.platforms._shared import INTEGRATION_DB_RULES, INTEGRATION_REDIS_RULES, TERRAFORM_RULES, _file_contains
from src.platforms.base import PlatformAdapter


def detect_infra(root: Path) -> bool:
    return (
        _file_contains(root, "*.tf")
        or _file_contains(root, "docker-compose.yml")
        or _file_contains(root, "Dockerfile")
    )


ADAPTER = PlatformAdapter(
    id="infra",
    name="Infrastructure (Terraform, Docker, K8s)",
    rules=TERRAFORM_RULES + INTEGRATION_DB_RULES,
    detect=detect_infra,
    languages=["hcl", "yaml"],
    frameworks=["terraform", "docker", "kubernetes"],
    agent_hints="Infra: hardcoded regions/credentials, open 0.0.0.0/0 ingress, missing variable usage in Terraform.",
)

# Redis rules attached when cache layer detected separately in registry
INTEGRATION_REDIS = INTEGRATION_REDIS_RULES
