import yaml
from pathlib import Path

from src.platforms.registry import collect_rules, profile_repo


def harvest_rules_for_repo(repo_profile: dict) -> dict:
    """Aggregate rules from active platform adapters for the given profile."""
    rules = collect_rules(repo_profile)
    return {
        "project": {
            "name": repo_profile.get("project_name", "my-service"),
            "type": repo_profile.get("architecture", "monolith"),
        },
        "rules": rules,
    }


def generate_default_rules_file(repo_profile: dict, output_dir: Path) -> Path:
    """Generates the .crb/rules.yaml file in the repo root."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rules_data = harvest_rules_for_repo(repo_profile)

    file_path = output_dir / "rules.yaml"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("# CodeReviewBot Repository Rules Configuration\n")
        f.write("# Customize this file to fit your team's unwritten conventions.\n\n")
        yaml.dump(rules_data, f, default_flow_style=False, sort_keys=False)

    return file_path


def profile_and_harvest(root: Path) -> tuple[dict, list[dict]]:
    """Profile a repo path and return (profile_dict, rules)."""
    profile = profile_repo(root)
    data = profile.to_dict()
    return data, collect_rules(data)
