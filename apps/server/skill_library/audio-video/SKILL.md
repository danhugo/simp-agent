---
name: audio-video
label: Audio & video (ffmpeg)
description: "Trim, cut, merge, convert, compress, resize audio and video with ffmpeg; extract audio or frames; add or burn subtitles; make GIFs; change speed or volume. Use for any media file task."
license: MIT
source: simp
version: 1
---

# Audio & Video with ffmpeg

Always write new files; inspect first; report output size and duration. There is no speech-to-text model: you cannot transcribe audio, but you can work with subtitle files the user provides or that you write.

## Inspect

```bash
ffprobe -v error -show_entries format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,r_frame_rate -of compact in.mp4
```

## Recipes

| Task | Command |
|---|---|
| Trim (fast, keyframe-accurate-ish) | `ffmpeg -ss 00:01:05 -to 00:02:30 -i in.mp4 -c copy out.mp4` |
| Trim (frame-accurate, re-encode) | `ffmpeg -i in.mp4 -ss 65 -to 150 -c:v libx264 -crf 20 -c:a aac out.mp4` |
| Convert to MP4 (H.264/AAC, web-safe) | `ffmpeg -i in.mov -c:v libx264 -crf 23 -preset medium -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart out.mp4` |
| Compress more | raise `-crf` (28 ≈ small); scale down: `-vf scale=-2:720` |
| Extract audio MP3 | `ffmpeg -i in.mp4 -vn -c:a libmp3lame -q:a 2 out.mp3` |
| Audio convert / trim | `ffmpeg -i in.m4a -ss 10 -t 60 out.wav` |
| Remove audio | `ffmpeg -i in.mp4 -an -c:v copy out.mp4` |
| Replace audio | `ffmpeg -i v.mp4 -i a.mp3 -map 0:v -map 1:a -c:v copy -shortest out.mp4` |
| Volume / normalize | `-af volume=1.5` / `-af loudnorm` |
| Speed ×2 | `-vf setpts=0.5*PTS -af atempo=2.0` |
| Concatenate same-format clips | list file `file 'a.mp4'` lines → `ffmpeg -f concat -safe 0 -i list.txt -c copy out.mp4` |
| Thumbnail at 5 s | `ffmpeg -ss 5 -i in.mp4 -frames:v 1 thumb.jpg` |
| One frame per 10 s | `ffmpeg -i in.mp4 -vf fps=1/10 frames/f_%04d.jpg` |
| GIF (good palette) | `ffmpeg -ss 3 -t 4 -i in.mp4 -vf "fps=12,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" out.gif` |
| Crop / rotate | `-vf crop=w:h:x:y` / `-vf transpose=1` |
| Vertical 9:16 from 16:9 | `-vf "crop=ih*9/16:ih,scale=1080:1920"` |
| Watermark | `-i logo.png -filter_complex "overlay=W-w-20:H-h-20"` |
| Images → slideshow | `ffmpeg -framerate 1/3 -i img%03d.jpg -c:v libx264 -r 30 -pix_fmt yuv420p out.mp4` |

## Subtitles

- Soft (selectable) in MP4: `ffmpeg -i in.mp4 -i subs.srt -c copy -c:s mov_text out.mp4`
- Burned in: `ffmpeg -i in.mp4 -vf "subtitles=subs.srt:force_style='FontName=DejaVu Sans,FontSize=22'" -c:a copy out.mp4`
- Convert: `ffmpeg -i subs.vtt subs.srt`
- Writing/translating SRT: keep numbering and `HH:MM:SS,mmm --> HH:MM:SS,mmm`; ≤ 42 chars/line, ≤ 2 lines. To shift timing, parse the timestamps in a short Python script and add the offset.

## Checks

- Long jobs: add `-y -loglevel error -stats`; run big encodes in one `bash` call and wait.
- After writing, `ffprobe` the output and, for visual edits, grab one frame and view it.
- `-c copy` cuts snap to keyframes; if the start is off, re-encode.
