---
name: algorithmic-art
label: Generative art
description: "Create original generative / algorithmic art with code (Python + numpy/matplotlib/Pillow, or SVG): flow fields, particles, noise, geometric patterns. Use when the user asks for code-made art, patterns, wallpapers or posters."
license: Apache-2.0 (see LICENSE.txt)
source: https://github.com/anthropics/skills/tree/main/skills/algorithmic-art
version: 1
---

# Algorithmic Art

Two steps: write an **algorithmic philosophy**, then express it in code. Make original work; never copy a living artist's style.

## 1. Algorithmic philosophy (4–6 short paragraphs, save as `/work/art/philosophy.md`)

Name the movement (1–2 words, e.g. "Organic Turbulence", "Quantum Harmonics"). Describe how it shows itself through:
- computational process and mathematical relationships;
- noise functions and randomness patterns;
- particle behaviour and field dynamics;
- temporal evolution / emergence;
- parametric variation and controlled chaos.

Stress craftsmanship: the result should feel meticulously tuned, refined through many iterations. Leave room for interpretive choices. If the user gave a subject, weave it in as a subtle conceptual seed, not a literal picture.

Example seeds: *Organic Turbulence* (flow field over layered noise, thousands of particles leaving fading trails); *Quantum Harmonics* (grid of particles with phase values interfering like waves); *Recursive Whispers* (L-system branching under golden-ratio constraints); *Stochastic Crystallization* (relaxed circle packing → Voronoi cells, coloured by neighbour count).

## 2. Implementation

Write `/work/art/art.py` with:
- a fixed `SEED` (and `np.random.default_rng(SEED)`) so the piece is reproducible; print the seed;
- a `PARAMS` dict at the top (counts, scales, palette, speeds) so the user can tweak;
- your own noise (e.g. value/Perlin noise in numpy) — do not assume extra pip packages;
- output PNG at high resolution (e.g. 3000×3000 via Pillow or `matplotlib` with `dpi`), and optionally SVG for line work (write SVG text directly).

Rendering tips: draw many low-alpha strokes for depth; use a 3–5 colour palette chosen for the philosophy; leave negative space; avoid default matplotlib axes (`ax.axis('off')`, figure facecolor set).

Run it with `bash` (`python /work/art/art.py`), then **view the PNG** with `read_file` and refine parameters 1–3 times. For variations, render 3–4 seeds side by side (`montage` from imagemagick) and let the user pick.

## Optional: interactive version

If the user wants an interactive piece, write a single self-contained `/work/art/index.html` using p5.js from a CDN (`https://cdnjs.cloudflare.com/ajax/libs/p5.js/1.9.4/p5.min.js`), with `randomSeed`/`noiseSeed`, sliders for the PARAMS, and "new seed" / "save PNG" buttons. You cannot preview it; keep logic identical to the Python version you already checked.

## Deliver

Give the user the PNG (and SVG/HTML) paths, the seed, and a one-paragraph summary of the philosophy.
