import os
import re
import fnmatch
import yaml
from pathlib import Path

def match_glob_list(file_path: str, globs: list[str]) -> bool:
    """Helper to check if a file matches a list of glob patterns."""
    for glob in globs:
        # Standard fnmatch
        if fnmatch.fnmatch(file_path, glob):
            return True
            
        base_name = os.path.basename(file_path)
        if fnmatch.fnmatch(base_name, glob):
            return True
            
        # Support recursive wildcard **/ matching
        if glob.startswith("**/"):
            stripped_glob = glob[3:]
            if fnmatch.fnmatch(file_path, stripped_glob) or fnmatch.fnmatch(base_name, stripped_glob):
                return True
                
    return False


def parse_rules_file(rules_path: Path) -> dict:
    """Parses rules.yaml config file."""
    if not rules_path.is_file():
        return {"rules": []}
        
    try:
        with open(rules_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            
        if not data:
            return {"rules": []}
            
        rules = []
        # Flatten all categories: domain_rules, architecture_rules, integration_rules, infra_rules, custom_rules
        for key in ["domain_rules", "architecture_rules", "integration_rules", "infra_rules", "custom_rules", "rules"]:
            if key in data and isinstance(data[key], list):
                for r in data[key]:
                    r["category"] = key.replace("_rules", "").capitalize()
                    rules.append(r)
                    
        return {
            "project": data.get("project", {}),
            "rules": rules
        }
    except Exception:
        return {"rules": []}

def find_inline_annotations(file_content: str) -> dict:
    """Finds all inline comments (using # or //) of type crb:ignore and crb:rule in the content.
    Returns a dict mapping line numbers to lists of ignored rules or inline rules.
    """
    annotations = {
        "ignores": {},  # line_num -> list[rule_id]
        "rules": {}     # line_num -> list[rule_desc]
    }
    
    for line_num, line in enumerate(file_content.splitlines(), 1):
        # Match ignore annotations: // crb:ignore rule-id-1 or # crb:ignore rule-id-1
        ignore_match = re.search(r'(?://|#)\s*crb:ignore\s+([\w\-, ]+)', line)
        if ignore_match:
            rules_ignored = [r.strip() for r in re.split(r'[, ]+', ignore_match.group(1)) if r.strip()]
            annotations["ignores"][line_num] = rules_ignored
            
        # Match custom inline rules: // crb:rule "description" or # crb:rule "description"
        rule_match = re.search(r'(?://|#)\s*crb:rule\s+["\']([^"\']+)["\']', line)
        if rule_match:
            annotations["rules"][line_num] = rule_match.group(1)
            
    return annotations


def check_file_rules(file_path: str, content: str, rules_config: dict) -> list[dict]:
    """Check a single file's content against the parsed rules, respecting inline ignores."""
    findings = []
    lines = content.splitlines()
    annotations = find_inline_annotations(content)
    
    for rule in rules_config.get("rules", []):
        rule_id = rule.get("id")
        pattern = rule.get("pattern")
        must_have = rule.get("must_have")
        severity = rule.get("severity", "medium").upper()
        category = rule.get("category", "Custom")
        files_scope = rule.get("files", ["*"])
        exclude_files = rule.get("exclude_files", [])
        
        # 1. Check file scope matching
        if files_scope and not match_glob_list(file_path, files_scope):
            continue
        if exclude_files and match_glob_list(file_path, exclude_files):
            continue
            
        # 2. Check pattern matching
        if pattern:
            try:
                compiled_regex = re.compile(pattern)
                for line_num, line in enumerate(lines, 1):
                    # Skip if rule is ignored on this line
                    if line_num in annotations["ignores"] and rule_id in annotations["ignores"][line_num]:
                        continue
                        
                    if compiled_regex.search(line):
                        # Pattern found = violation (unless it was a must_have check)
                        findings.append({
                            "rule_id": rule_id,
                            "severity": severity,
                            "category": category,
                            "file": file_path,
                            "line": line_num,
                            "description": rule.get("description", "Rule pattern matched."),
                            "source": "config-file",
                            "suggestion": rule.get("suggestion", "Please verify and fix this pattern.")
                        })
            except Exception as e:
                # regex compile failure
                continue
                
        # 3. Check must_have conditions
        if must_have:
            # If the must_have pattern is missing from the entire file content
            if must_have not in content:
                findings.append({
                    "rule_id": rule_id,
                    "severity": severity,
                    "category": category,
                    "file": file_path,
                    "line": 1,
                    "description": f"Missing required pattern: '{must_have}'",
                    "source": "config-file",
                    "suggestion": rule.get("suggestion", f"Ensure '{must_have}' is added to this file.")
                })
                
    return findings
