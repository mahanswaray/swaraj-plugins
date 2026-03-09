# Video Reels Plugin

Turn raw video footage into polished short-form reels for Instagram, TikTok, and YouTube Shorts. A human-in-the-loop pipeline that combines AI-powered video analysis with precise ffmpeg editing.

## What it does

This plugin provides an 8-stage pipeline:

1. **Ingest** — Scan raw footage, extract metadata, build an inventory
2. **Filter** — Select and rename the clips you want to use
3. **Analyze** — AI multimodal analysis (Google Gemini) for rich per-timestamp visual inventory
4. **Storyboard** — Interactive HTML dashboard to visualize planned edits
5. **First Cut** — Build initial reels with ffmpeg (9:16 vertical, hard cuts, continuous audio)
6. **Iterate** — Watch, give feedback, revise, repeat
7. **Inspect** — Frame-level analysis for precise text placement and element verification
8. **Polish** — Text overlays, timing adjustments, final export

Every stage invites human review, preference, and override.

## Components

| Component | Name | Purpose |
|-----------|------|---------|
| Skill | video-reels | Core pipeline knowledge, cut design principles, ffmpeg patterns |
| Command | /reels | Quick-start any pipeline stage |

## Setup

### Required
- **ffmpeg** and **ffprobe** installed and on PATH

### Optional (for AI analysis)
- Google Gemini API key: set `GEMINI_API_KEY` environment variable
- Install the Python client: `pip install google-generativeai --break-system-packages`

## Usage

The skill triggers automatically when you mention reels, video editing, cutting clips, or short-form video.

You can also use the `/reels` command directly:

- `/reels start` — Scan workspace for video files and begin
- `/reels analyze` — Run Gemini AI analysis on filtered clips
- `/reels storyboard` — Generate interactive HTML storyboard
- `/reels build` — Construct reels with ffmpeg
- `/reels inspect` — Frame-level verification for overlays and positioning

## Key principles

- **Hard cuts only** — no fades or dissolves (they look like buffering on phones)
- **Think in musical bars** — cuts should land on phrase boundaries, not arbitrary timestamps
- **Every cut has a visual reason** — "cut TO the guitarist because he's smiling", not just "cut at 14s"
- **Continuous audio backbone** — video cuts, audio flows smoothly from one source
- **Human always decides** — the pipeline surfaces options, you make the creative calls
