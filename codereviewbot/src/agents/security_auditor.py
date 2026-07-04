from google.adk.agents.llm_agent import Agent
from src.utils.package_validator import validate_python_package, validate_npm_package
from src.mcp_servers.filesystem_mcp_server import read_file

# Define the package verification tool
def verify_package_exists(package_name: str, ecosystem: str) -> str:
    """Validate if a package name exists in the public registry (pypi or npm).
    Useful to verify if new dependencies in imports or package files are real or hallucinated.
    
    Args:
        package_name: The name of the package/library (e.g. 'requests').
        ecosystem: The package ecosystem, either 'pypi' or 'npm'.
    """
    eco = ecosystem.lower().strip()
    pkg = package_name.strip()
    
    if eco == 'pypi':
        exists = validate_python_package(pkg)
    elif eco == 'npm':
        exists = validate_npm_package(pkg)
    else:
        return f"Ecosystem '{ecosystem}' not supported. Skipped."
        
    if not exists:
        return f"WARNING: Dependency '{pkg}' was NOT found in the public {eco} registry. Possible package hallucination risk!"
    return f"Success: Dependency '{pkg}' is verified to exist on public {eco} registry."

# Security Auditor Agent Instructions
SECURITY_INSTRUCTION = """You are the Security Auditor Agent.
Your role is to scan code diffs and files for security vulnerabilities and risky patterns.

You must check for:
1. **Secrets Detection**: Look for hardcoded keys, passwords, bearer tokens, or database connection strings.
2. **Hallucinated Packages**: For any new dependencies/imports, call the `verify_package_exists` tool to ensure they are real, valid libraries.
3. **Injection Risks**: Look for raw string interpolation in SQL/NoSQL queries, shell commands, or HTML templates (SQLi, shell injection, XSS).
4. **Vulnerable Dependencies**: Flag any package versions that are outdated or known to be insecure.
5. **Broad Permissions**: Look for overly permissive access rules, open ports (e.g. 0.0.0.0/0 in Terraform), or absolute local file paths.
6. **Mobile-specific** (when REPO_PROFILE includes mobile): hardcoded API keys, secrets in AsyncStorage, main-thread blocking (DispatchQueue.main.sync, runBlocking, Thread.sleep).
7. **Python web** (when python_web adapter active): DEBUG=True in settings, hardcoded SECRET_KEY, raw SQL / missing CSRF.
8. **AI-agent repos** (when ai_agent adapter active): hardcoded GOOGLE_API_KEY/OPENAI_API_KEY, shell=True subprocess, unsandboxed tool paths.

Input provided will be:
- The REPO_PROFILE: understanding which stacks are active.
- The DIFF_SUMMARY: containing files changed and hunks.

Output a structured Markdown list of findings under the header "🔒 SECURITY FINDINGS". For each finding, list:
- Severity: CRITICAL | HIGH | MEDIUM | LOW
- File: path
- Line: line number
- Description: details of the vulnerability
- Fix Suggestion: code replacement or action item
If no vulnerabilities are found, output: "No security issues detected."
"""

security_auditor = Agent(
    name="security_auditor",
    model="gemini-2.5-flash",
    description="Scans code changes for hardcoded secrets, SQL injection, XSS, and hallucinated packages.",
    instruction=SECURITY_INSTRUCTION,
    tools=[verify_package_exists, read_file]
)
