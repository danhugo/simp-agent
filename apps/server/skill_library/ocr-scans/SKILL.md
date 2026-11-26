---
name: ocr-scans
label: OCR scans & images
description: "Extract text from scanned PDFs, photos of documents, receipts, screenshots and images with Tesseract (English + Vietnamese); make searchable PDFs; pull tables and fields out of scans."
license: MIT
source: simp
version: 1
---

# OCR Scans & Images

Tesseract languages installed: `eng`, `vie` (use `-l vie+eng` for mixed text).

## 1. Is OCR needed?

```bash
pdffonts file.pdf | head; pdftotext -f 1 -l 2 file.pdf - | head -20
```
If text comes out, use it (see `pdf` skill). If empty or garbage → OCR. You can also simply **view** an image or a rendered page yourself (`read_file` on the PNG): for a few pages or a photo, reading it directly is often more accurate than Tesseract, especially for handwriting, tables and receipts.

## 2. Prepare images (biggest quality win)

```bash
pdftoppm -r 300 -png file.pdf /work/ocr/page          # PDF → page-1.png ...
magick in.jpg -auto-orient -colorspace Gray -resize 200% -normalize -sharpen 0x1 -threshold 60% clean.png
magick in.png -deskew 40% deskewed.png                 # fix slight rotation
```
Aim for ~300 DPI, dark text on white, upright. Crop margins/backgrounds for photos (`-trim`, `-crop`).

## 3. Run OCR

```bash
tesseract clean.png out -l vie+eng --psm 3            # out.txt; psm 6 = single block, 4 = columns/receipts
tesseract clean.png out -l vie+eng pdf                # searchable PDF page
tesseract clean.png out -l eng tsv                    # words with positions and confidence
```
Python: `pytesseract.image_to_string(img, lang="vie+eng")`, `image_to_data(..., output_type=Output.DATAFRAME)` for confidence filtering.

Whole PDF → searchable PDF: OCR each page to PDF, then `qpdf --empty --pages page-*.pdf -- searchable.pdf` (sort pages numerically).

## 4. Check and clean

- Look at low-confidence words (`conf < 60` in TSV) and compare with the image yourself.
- Fix common errors: broken Vietnamese diacritics, `0/O`, `1/l`, hyphenated line breaks, headers/footers repeated per page.
- Numbers matter (invoices, IDs): verify them by viewing the image, never guess.

## 5. Structured output

- Tables: use TSV word positions to cluster columns, or view the image and transcribe; export CSV/Excel (`xlsx` skill).
- Forms/receipts: return a JSON/table of fields (date, vendor, total, tax, items) with any unreadable field marked `null`.

Tell the user the output paths and the pages where quality was poor.
