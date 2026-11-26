---
name: security-best-practices
label: Security review
description: "Security best-practice review and secure-by-default coding for Python, JavaScript/TypeScript and Go web apps (Django, Flask, FastAPI, Express, Next.js, React, Vue, jQuery). Use when the user asks for a security review/report or secure coding help."
license: Apache-2.0 (see LICENSE.txt)
source: https://github.com/openai/skills/tree/main/skills/.curated/security-best-practices
version: 1
---

# Security Best Practices

## Workflow

1. Identify ALL languages and frameworks in scope (frontend and backend). If unclear, inspect the repo in `/work` (`rg`, package files) and list your evidence.
2. Read the matching files in this skill's `references/` folder. Names are `<language>-<framework>-<stack>-security.md`; also read `<language>-general-<stack>-security.md`. For a web app with an unspecified frontend, also read `javascript-general-web-frontend-security.md`.
   Available: golang-general-backend, javascript-express-web-server, javascript-general-web-frontend, javascript-jquery-web-frontend, javascript-typescript-nextjs-web-server, javascript-typescript-react-web-frontend, javascript-typescript-vue-web-frontend, python-django-web-server, python-fastapi-web-server, python-flask-web-server.
3. If nothing matches, use well-known practices for that stack (you may `web_search` official docs) and tell the user no concrete guidance was bundled.

Then work in one of three modes:
- **Secure by default:** follow the guidance in all code you write from now on.
- **Passive:** while doing other work, flag only critical / high-impact issues.
- **Report:** when asked, write a full report (below), then offer fixes.

## Overrides

Projects may knowingly bypass a practice. Respect documented project rules; you may mention the risk once, but do not fight the user. Suggest documenting the reason.

## Report format

Write `/work/security_best_practices_report.md` (or where the user asks):
- short executive summary at top;
- sections by severity (Critical, High, Medium, Low), most critical first;
- each finding has a numeric ID, file path **with line numbers**, and for critical ones a one-sentence impact statement.
Then summarize the findings in chat and give the report path.

## Fixes

- One finding at a time, with a short comment naming the practice and why.
- Check the fix will not break existing behaviour (insecure code is often relied on); run the project's tests if any.
- Separate commits per finding if committing; clear messages.

## General advice

- Do not use small incrementing IDs as public resource IDs; use UUID4 or random hex.
- Do not report missing TLS for dev setups; only set `Secure` cookies when the app really runs over TLS (make it a config flag). Avoid recommending HSTS without explaining its lasting effects.
