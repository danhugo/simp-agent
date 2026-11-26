---
name: research-citations
label: Research with citations
description: "Research a question on the web and write a sourced answer or report with inline citations: facts, market/competitor scans, literature overviews, fact-checking. Use when the user needs up-to-date or verifiable information."
license: MIT
source: simp
version: 1
---

# Research with Citations

## Plan (keep it short)

Break the question into 2–5 sub-questions. Decide what counts as a good source: official sites, primary data (government statistics, company filings, papers), reputable media; avoid content farms and SEO listicles.

## Search budget

- One round of parallel `web_search` calls (2–4 targeted queries, use site:, dates, exact phrases, local language when relevant, e.g. Vietnamese queries for Vietnamese topics).
- Then one round of parallel `web_fetch(url, prompt="extract ... with figures, dates and the exact sentences")` on the 2–5 best results.
- A second round only if a key sub-question is still unanswered. Never fetch search-engine result pages; don't retry failed fetches; move on to another source.

## Evaluate

- Prefer the primary source over articles about it.
- Check the date; note when data is old.
- Cross-check important numbers in two independent sources; if they disagree, report both.
- Separate fact, estimate and opinion.

## Write

- Lead with the direct answer (2–4 sentences), then supporting sections.
- Cite inline with numbered references `[1]` right after the claim; list sources at the end:
  `[1] Title — Publisher, date. URL`
- Quote exact wording for sensitive claims; otherwise paraphrase.
- Mark uncertainty ("≈", "estimates vary", "no reliable data found for …").
- Never invent sources, URLs, quotes or numbers. If you couldn't verify, say so.
- End with "Limitations" when coverage was thin.

## Longer reports

Structure: summary, background, findings by sub-question, comparison table if several options, conclusion/recommendation, sources. Deliver as Markdown in chat for short work, or a .docx (`docx` skill) for formal reports. Save the source list in `/work/research/<topic>-sources.md` so it can be reused.

## Academic style

If asked for APA/MLA/IEEE, format references in that style; use DOIs when available. Only cite papers you actually opened or whose abstract you read.
