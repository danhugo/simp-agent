---
name: resume-cover-letter
label: Resume & cover letter
description: "Write, tailor and review resumes/CVs, cover letters and LinkedIn profiles for a specific job; ATS-friendly formatting; interview prep from a job description."
license: MIT
source: simp
version: 1
---

# Resume & Cover Letter

## Inputs

The user's current CV (any format: read .docx/.pdf with `markitdown` or `pdftotext -layout`) or their background in chat, and the **target job description** (pasted, a file, or `web_fetch` of the posting). Ask for the JD if missing: tailoring is the main value. Never invent jobs, degrees, dates, employers or numbers; if a metric would help, ask the user for it or leave a clear `[add number]` placeholder.

## Tailor to the job

1. Extract from the JD: must-have skills, nice-to-haves, key responsibilities, keywords, seniority, tone.
2. Map the user's experience to each item; note gaps honestly and how to address them (transferable skills, projects, courses).
3. Mirror the JD's exact keywords where truthful (ATS match).

## Resume rules

- Length: 1 page (< 10 years experience), 2 max otherwise. Reverse chronological.
- Sections: Name + contact (city, phone, email, LinkedIn/portfolio), Summary (2–3 lines targeted to the role), Experience, Education, Skills, optional Projects / Certifications / Languages.
- Bullets: **action verb + what + measurable result** ("Cut month-end close from 8 to 5 days by automating reconciliations in Excel/Power Query"). 3–5 bullets per role, most relevant first.
- No photos, age, marital status, ID numbers, or full address unless the user's country/employer expects them (Vietnamese employers sometimes do: ask).
- ATS-friendly: single column, standard headings, real text (no text in images), consistent dates (`03/2022 – Present`), common fonts, no tables for layout.
- Consistent tense (past for past roles), no "I", no "responsible for".

## Cover letter (≤ 1 page, 3–4 paragraphs)

1. Hook: the role, and one specific reason you fit / care about this company (use a real fact from their site via `web_fetch`).
2. 2–3 achievements mapped to the job's top needs, with numbers.
3. Why this company/team; what you'd bring in the first months.
4. Call to action and thanks.
Match the company's tone; address a named person if known; don't repeat the CV line by line.

## Review mode

Score against the JD (must-haves covered?), then list fixes by impact: missing keywords, weak bullets rewritten, formatting/ATS issues, typos. Show before → after for the top bullets.

## Output

Markdown in chat for quick iterations; a clean .docx via the `docx` skill (simple, ATS-safe layout) and/or PDF when final. Name files `Firstname_Lastname_Resume_<Company>.docx`.

## Interview prep (optional)

From the JD: 8–10 likely questions (behavioural + role-specific) with STAR-structured answer outlines built from the user's real experience, and 3–5 smart questions to ask the interviewer.
