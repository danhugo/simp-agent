---
name: image-editing
label: Image editing
description: "Edit images with ImageMagick and Pillow: resize, crop, convert formats, compress, rotate, add text or watermark, remove simple backgrounds, collages, batch processing, favicons, GIFs. No AI image generation."
license: MIT
source: simp
version: 1
---

# Image Editing

ImageMagick 7 (`magick`) and Pillow are available. There is **no image-generation model**: you edit existing images or draw with code. Always write to a new file; never overwrite the original. View the result (`read_file` on the output) before reporting.

## Inspect

```bash
magick identify -verbose in.jpg | head -30     # or: magick identify in.jpg
```

## Common recipes

| Task | Command |
|---|---|
| Resize to width 1200 (keep ratio) | `magick in.jpg -resize 1200x out.jpg` |
| Fit inside 1080×1080, pad white | `magick in.jpg -resize 1080x1080 -background white -gravity center -extent 1080x1080 out.jpg` |
| Crop W×H+X+Y | `magick in.png -crop 800x600+100+50 +repage out.png` |
| Auto-trim borders | `magick in.png -trim +repage out.png` |
| Rotate / fix EXIF orientation | `magick in.jpg -auto-orient -rotate 90 out.jpg` |
| Convert / compress JPEG | `magick in.png -strip -quality 82 out.jpg` |
| WebP | `magick in.jpg -quality 80 out.webp` |
| Grayscale / brightness-contrast | `magick in.jpg -colorspace Gray out.jpg` / `-brightness-contrast 10x15` |
| Text caption | `magick in.jpg -gravity south -fill white -undercolor '#00000080' -pointsize 48 -annotate +0+30 'Text' out.jpg` |
| Watermark logo 20% | `magick in.jpg \( logo.png -resize 20% \) -gravity southeast -geometry +30+30 -compose over -composite out.jpg` |
| Simple background removal (flat colour) | `magick in.png -fuzz 12% -transparent white out.png` |
| Rounded corners / border | `-bordercolor '#ddd' -border 4` |
| Side by side / grid | `magick montage a.jpg b.jpg c.jpg d.jpg -tile 2x2 -geometry +10+10 grid.jpg` |
| Append horizontally | `magick a.jpg b.jpg +append out.jpg` |
| Images → PDF | `magick *.jpg -quality 90 out.pdf` (or `img2pdf` if installed) |
| PDF page → PNG | `pdftoppm -r 150 -png -f 1 -l 1 in.pdf page` |
| Favicon | `magick logo.png -define icon:auto-resize=16,32,48,64 favicon.ico` |
| GIF from frames | `magick -delay 10 -loop 0 frame*.png anim.gif` |
| Strip metadata (privacy) | `magick in.jpg -strip out.jpg` |
| HEIC → JPG | `magick in.heic out.jpg` (if the HEIC delegate is missing, say so) |

Vietnamese text: pass a font with diacritics, e.g. `-font DejaVu-Sans` (list with `magick -list font | grep Font:`).

## Batch

```bash
mkdir -p /work/out && for f in /work/photos/*.jpg; do magick "$f" -auto-orient -resize 1600x -strip -quality 82 "/work/out/$(basename "$f")"; done
```
Report count processed and total size before/after (`du -sh`).

## Pillow (for logic-heavy edits)

Use Pillow for per-pixel work, drawing shapes/charts on images, or composing layouts with precise coordinates (`ImageDraw`, `ImageFont.truetype("DejaVuSans.ttf", 40)`).

## Limits

Complex background removal (hair, busy scenes), object removal, face edits or generating new pictures are not possible with these tools; say so and offer the closest workable option.
