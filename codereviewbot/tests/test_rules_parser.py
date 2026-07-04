import os
import tempfile
from pathlib import Path
import pytest
import yaml
from src.utils.rules_parser import (
    match_glob_list,
    parse_rules_file,
    find_inline_annotations,
    check_file_rules
)

def test_match_glob_list():
    assert match_glob_list("src/payment.py", ["**/payment.py"]) is True
    assert match_glob_list("payment.py", ["payment.py"]) is True
    assert match_glob_list("src/utils.py", ["**/payment.py"]) is False

def test_find_inline_annotations():
    content = """
    # crb:ignore no-float-for-money
    price = float(val)
    # crb:rule "Strict rate limiting on login"
    def login():
        pass
    """
    annotations = find_inline_annotations(content)
    
    # Check ignore mappings
    assert 2 in annotations["ignores"]
    assert "no-float-for-money" in annotations["ignores"][2]
    
    # Check custom inline rule mappings
    assert 4 in annotations["rules"]
    assert annotations["rules"][4] == "Strict rate limiting on login"

def test_check_file_rules():
    # Define a temporary rules configuration
    rules_config = {
        "rules": [
            {
                "id": "no-float-for-money",
                "description": "Do not use float for money.",
                "pattern": r"float\(",
                "severity": "critical",
                "category": "Domain",
                "files": ["*.py"]
            }
        ]
    }
    
    content_violated = "price = float(input)"
    findings = check_file_rules("payment.py", content_violated, rules_config)
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "no-float-for-money"
    assert findings[0]["severity"] == "CRITICAL"
    
    # Test with inline ignore annotation
    content_ignored = "price = float(input)  # crb:ignore no-float-for-money"
    findings_ignored = check_file_rules("payment.py", content_ignored, rules_config)
    assert len(findings_ignored) == 0

