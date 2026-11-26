---
name: mcp-builder
label: MCP server builder
description: "Build an MCP (Model Context Protocol) server that wraps an API or service as tools for LLMs, in Python (FastMCP) or TypeScript. Also good guidance for designing any LLM-facing API or tool set."
license: Apache-2.0 (see LICENSE.txt)
source: https://github.com/anthropics/skills/tree/main/skills/mcp-builder
version: 1
---

# MCP Server Development

An MCP server is judged by how well an LLM can get real tasks done with its tools. Work in four phases.

## 1. Research and plan

- **Coverage vs. workflow tools:** cover the API's main endpoints first; add higher-level workflow tools only for common multi-step jobs.
- **Naming:** consistent prefix + action (`github_create_issue`, `github_list_repos`).
- **Context:** concise descriptions; every list tool filters and paginates; return focused data.
- **Errors:** actionable messages that say what to change next.
- Read the protocol and SDK docs with `web_fetch` (one or two pages, not the whole site):
  - spec: `https://modelcontextprotocol.io/specification/draft.md` (sitemap: `https://modelcontextprotocol.io/sitemap.xml`)
  - Python SDK: `https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md`
  - TypeScript SDK: `https://raw.githubusercontent.com/modelcontextprotocol/typescript-sdk/main/README.md`
- Read this skill's `reference/mcp_best_practices.md` (naming, pagination, response formats, security) and the guide for your language: `reference/python_mcp_server.md` or `reference/node_mcp_server_v2.md`.
- List the endpoints, auth method and data models of the target API (`web_search` + `web_fetch` its docs). Write the tool list before coding.

Recommended stack: TypeScript or Python; **streamable HTTP** (stateless JSON) for remote servers, **stdio** for local ones.

## 2. Implement

- Shared pieces first: API client with auth (secrets from env vars, never hard-coded), error helper, response formatting (JSON and Markdown), pagination.
- Each tool: input schema (Pydantic / Zod) with constraints and examples in field descriptions; `outputSchema` / structured content where the SDK supports it; a short description; async I/O.
- Annotations: `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`.

## 3. Review and test

- No duplicated code, consistent errors, typed everywhere, clear descriptions.
- Python: `python -m py_compile server.py`; TypeScript: `npm run build`.
- Smoke-test in the sandbox: start the server (stdio or HTTP on localhost) and call `tools/list` and one read-only tool with a tiny client script from the SDK. Do not call destructive tools against real accounts while testing.

## 4. Evaluation questions (optional)

Write ~10 realistic, read-only, multi-step questions whose answers are single verifiable strings, as:

```xml
<evaluation>
  <qa_pair><question>...</question><answer>...</answer></qa_pair>
</evaluation>
```

Answers must be stable over time and checkable by string match. Hand the file to the user; running the evaluation needs an LLM API key, which the sandbox does not have.

## Deliver

Put the project in `/work/<name>-mcp/` with a README (install, env vars, run command, tool list) and tell the user how to connect it to their MCP client.
