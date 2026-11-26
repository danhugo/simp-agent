---
name: summarize-documents
label: Summarize documents
description: "Summarize long documents, reports, papers, contracts, books, web pages or many files: executive summary, key points, per-section notes, or answers to specific questions with page references."
license: MIT
source: simp
version: 1
---

# Summarize Documents

## 1. Get the text

- PDF: `pdftotext -layout file.pdf out.txt` (keeps page breaks as `\f`); scanned PDF with no text → `ocr-scans` skill.
- Word/PowerPoint/Excel/HTML/EPUB: `markitdown file.docx > out.md` (or `pandoc file.epub -t plain`).
- Web page: `web_fetch(url, prompt="Return the full main text, keep headings")`.
- Drive/Notion/Atlassian docs: read via the connected portal.
- Check length: `wc -w out.txt`. Note page numbers (`\f` count) so you can cite them.

## 2. Long documents (more than ~30k words)

Don't read it all at once. Split by headings or pages (`csplit`, or Python on `\f`), summarize each part in 5–10 bullets with page refs into `/work/summary/notes.md`, then summarize the notes. Keep numbers, names, dates, definitions and obligations verbatim.

## 3. Choose the output (ask if unclear; default = executive summary)

- **TL;DR:** 1–3 sentences.
- **Executive summary:** purpose, 3–7 key findings/points, conclusions/recommendations, what it means for the reader. ≤ 1 page.
- **Structured notes:** per section/chapter, bullets.
- **Q&A / extraction:** answer specific questions, each with a quote and page reference.
- **Comparison** of several documents: table with rows = criteria, columns = documents.
- **Contract/policy:** parties, term, money, obligations of each side, deadlines, termination, penalties, unusual or risky clauses. Add: "Not legal advice."
- **Paper:** question, method, data, main results (with numbers), limitations, takeaway.

## Rules

- Faithful: no claims the source doesn't make; mark your own interpretation ("Implication:").
- Keep the author's hedging ("may", "suggests").
- Cite page/section for key facts (`p. 12`, `§3.2`).
- Say what you skipped (appendices, tables) and whether the text extraction was imperfect.
- Write in the user's language unless asked otherwise; keep technical terms in the original in parentheses when translating.
