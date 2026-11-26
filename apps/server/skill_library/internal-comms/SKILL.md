---
name: internal-comms
label: Internal comms
description: "Write internal communications: status reports, leadership updates, 3P (progress/plans/problems) updates, newsletters, FAQs, incident and project updates."
license: Apache-2.0 (see LICENSE.txt)
source: https://github.com/anthropics/skills/tree/main/skills/internal-comms
version: 1
---

## When to use this skill
To write internal communications, use this skill for:
- 3P updates (Progress, Plans, Problems)
- Company newsletters
- FAQ responses
- Status reports
- Leadership updates
- Project updates
- Incident reports

## How to use this skill

To write any internal communication:

1. **Identify the communication type** from the request
2. **Load the appropriate guideline file** from this skill's `examples/` folder (read it with `read_file`):
    - `examples/3p-updates.md` - For Progress/Plans/Problems team updates
    - `examples/company-newsletter.md` - For company-wide newsletters
    - `examples/faq-answers.md` - For answering frequently asked questions
    - `examples/general-comms.md` - For anything else that doesn't explicitly match one of the above
3. **Follow the specific instructions** in that file for formatting, tone, and content gathering

If the communication type doesn't match any existing guideline, ask for clarification or more context about the desired format.

## Keywords
3P updates, company newsletter, company comms, weekly update, faqs, common questions, updates, internal comms

## Sources in Simp
The examples mention Slack and Drive. In Simp, gather facts from the portals the user connected (Gmail, Drive, Calendar, Notion, Linear, Atlassian, GitHub) or from files in `/work`; if none are connected, ask the user to paste the updates. Never invent metrics.
