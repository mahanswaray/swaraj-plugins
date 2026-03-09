---
description: Start or continue a video reels project
allowed-tools: Read, Write, Edit, Bash(ffmpeg:*), Bash(ffprobe:*), Bash(pip:*), Bash(python:*), Bash(ls:*), Bash(mkdir:*), Bash(cp:*), Bash(mv:*)
argument-hint: [start | analyze | storyboard | build | inspect]
---

Read the video-reels skill at `${CLAUDE_PLUGIN_ROOT}/skills/video-reels/SKILL.md` first. Follow the pipeline stages defined there.

If `$1` is empty or "start", begin at Stage 1 (Ingest): scan the user's workspace for video files (.mov, .mp4, .avi, .mkv), probe metadata, and present an inventory for human review.

If `$1` is "analyze", run Stage 3: use the Gemini analysis script at `${CLAUDE_PLUGIN_ROOT}/skills/video-reels/scripts/gemini_analyze.py` on the filtered clips. Requires GEMINI_API_KEY environment variable.

If `$1` is "storyboard", run Stage 4: use the storyboard script at `${CLAUDE_PLUGIN_ROOT}/skills/video-reels/scripts/storyboard.py` to generate an interactive HTML dashboard from the reel config.

If `$1` is "build", run Stage 5: construct reels using ffmpeg with the segment-concat pattern. Reference `${CLAUDE_PLUGIN_ROOT}/skills/video-reels/references/ffmpeg_patterns.md` for ffmpeg recipes.

If `$1` is "inspect", run Stage 7: extract and analyze individual frames for position verification, text placement, or element visibility checks.

For any subcommand, always present results to the human and wait for feedback before proceeding to the next stage.
