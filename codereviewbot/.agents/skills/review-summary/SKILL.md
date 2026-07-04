---
name: review-summary
description: Synthesizes findings from Security, Style, Impact, and Business Rules agents into a unified, consolidated report.
---

# Skill: Review Summary

## Instructions
When preparing the final consolidated report:
1. Extract the `RepoProfile` to show at the top of the report.
2. Calculate the overall risk rating:
   - **HIGH**: If there are any CRITICAL or HIGH findings in Security, Business Rules, or Impact.
   - **MEDIUM**: If there are only MEDIUM findings.
   - **LOW**: If there are only LOW findings.
3. List the findings from all other checking agents under clear headings.
4. Summarize the key issues in a concise paragraph with recommendations.

## Output Format
```
🔍 CodeReviewBot Report
═══════════════════════

📚 Repo Profile: <details>
📊 Overall Risk Rating: <rating>

🔒 Security
...
🎨 Style
...
📏 Business Rules
...
💥 Impact & Integration
...

📝 Summary
...
```
