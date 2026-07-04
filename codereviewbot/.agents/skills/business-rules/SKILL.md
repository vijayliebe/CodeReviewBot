---
name: business-rules
description: Validates code changes against custom repo-specific configurations, inline instructions, and auto-discovered rules.
---

# Skill: Business Rules Checker

## Instructions
When checking project-specific conventions:
1. Locate and parse `.crb/rules.yaml` if available using `read_file`. Match code hunks against regex patterns defined under domains, architecture, integration, and infra rules.
2. Check for inline code annotations:
   - `# crb:ignore <rule_id>`: Skip reporting rules on marked lines.
   - `# crb:rule "<description>"`: Validate the code against the inline instruction.
3. Track pattern frequencies across the codebase with `get_pattern_frequency` to propose auto-discovered rules.

## Output Format
All findings must be presented under the header `📏 BUSINESS RULES FINDINGS` in the following format:
* **Rule ID**: `id`
  * *Severity*: CRITICAL | HIGH | MEDIUM | LOW
  * *File*: `path/to/file:line_num`
  * *Description*: Details of the rule violation.
  * *Source*: `config-file | auto-discovered | inline-rule`
  * *Suggestion*: Actionable correction.
