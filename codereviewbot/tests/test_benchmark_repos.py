import os
from pathlib import Path
from src.utils.rules_parser import parse_rules_file, check_file_rules

from src.utils.paths import get_workspace_root

WORKSPACE_ROOT = get_workspace_root()

def test_backend_service_rules():
    backend_dir = WORKSPACE_ROOT / "benchmark_repos" / "backend_service"
    rules_path = backend_dir / ".crb" / "rules.yaml"
    billing_file = backend_dir / "billing.py"
    
    assert rules_path.is_file()
    assert billing_file.is_file()
    
    config = parse_rules_file(rules_path)
    content = billing_file.read_text()
    
    findings = check_file_rules("billing.py", content, config)
    
    # Repo's custom rules.yaml has: no-float-for-money, redis-key-prefix,
    # no-direct-db-in-controllers. Only the first two apply to billing.py.
    # (legacy_charge = float(...) on line 15 is ignored via crb:ignore)
    assert len(findings) == 2
    
    rule_ids = [f["rule_id"] for f in findings]
    assert "no-float-for-money" in rule_ids
    assert "redis-key-prefix" in rule_ids
    
    float_finding = next(f for f in findings if f["rule_id"] == "no-float-for-money")
    assert float_finding["line"] == 7
    
    redis_finding = next(f for f in findings if f["rule_id"] == "redis-key-prefix")
    assert redis_finding["line"] == 11

def test_frontend_app_rules():
    frontend_dir = WORKSPACE_ROOT / "benchmark_repos" / "frontend_app"
    rules_path = frontend_dir / ".crb" / "rules.yaml"
    app_file = frontend_dir / "App.tsx"
    utils_file = frontend_dir / "utils.js"
    
    config = parse_rules_file(rules_path)
    
    # Check App.tsx findings
    app_findings = check_file_rules("App.tsx", app_file.read_text(), config)
    assert len(app_findings) == 1
    assert app_findings[0]["rule_id"] == "no-console-log"
    assert app_findings[0]["line"] == 5 # first console.log
    
    # Check utils.js findings
    utils_findings = check_file_rules("utils.js", utils_file.read_text(), config)
    assert len(utils_findings) == 1
    assert utils_findings[0]["rule_id"] == "strict-equality"
    assert utils_findings[0]["line"] == 3

def test_database_infra_rules():
    infra_dir = WORKSPACE_ROOT / "benchmark_repos" / "database_infra"
    rules_path = infra_dir / ".crb" / "rules.yaml"
    queries_file = infra_dir / "queries.py"
    tf_file = infra_dir / "main.tf"
    
    config = parse_rules_file(rules_path)
    
    # Check queries.py
    query_findings = check_file_rules("queries.py", queries_file.read_text(), config)
    assert len(query_findings) == 1
    assert query_findings[0]["rule_id"] == "no-raw-sql"
    assert query_findings[0]["line"] == 8
    
    # Check main.tf
    tf_findings = check_file_rules("main.tf", tf_file.read_text(), config)
    assert len(tf_findings) == 1
    assert tf_findings[0]["rule_id"] == "tf-no-hardcoded-region"
    assert tf_findings[0]["line"] == 3
