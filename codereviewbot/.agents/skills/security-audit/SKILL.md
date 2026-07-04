---
name: security-audit
description: Scans code changes and diffs for secrets, hallucinated packages, SQL injection, XSS, and vulnerable dependencies.
---

# Skill: Security Audit

## Instructions
When performing a security audit on code changes:
1. Scan for hardcoded credentials, authorization tokens, passwords, and private keys.
2. Identify imports of third-party libraries and call the `verify_package_exists` tool to ensure they are real packages on PyPI or npm registries (preventing dependency hallucinations).
3. Check for SQL Injection risks in query strings. Ensure parameters are passed dynamically and not formatted using raw string templates or concatenation.
4. Verify XSS risks when template rendering or raw HTML output is generated.
5. Check file and system execution commands for command injection vulnerabilities.

## Output Format
All findings must be presented under the header `🔒 SECURITY FINDINGS` in the following format:
* **[SEVERITY]** File: `path/to/file:line_num`
  * *Description*: Details of the vulnerability.
  * *Fix*: Suggested correction.
