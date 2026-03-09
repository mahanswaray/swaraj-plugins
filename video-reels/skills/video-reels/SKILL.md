---
name: video-reels
description: >
  End-to-end pipeline for turning raw video clips into polished short-form reels
  (Instagram Reels, TikTok, YouTube Shorts). Handles the full workflow: scanning raw
  footage, filtering useful clips, AI-powered multimodal analysis (Gemini) for rich
  per-timestamp visual inventory, interactive storyboard creation, ffmpeg-based reel
  construction, iterative editing rounds with human feedback, frame-level inspection
  for nuanced adjustments, and final polish (text overlays, timing, audio). Use this
  skill whenever the user mentions reels, short-form video, video editing, cutting
  clips together, making a highlight reel, creating social media videos, or working
  with raw footage from events/jams/performances. Also trigger when users have
  multiple video files and want to combine them, or when they mention Instagram,
  TikTok, or YouTube Shorts in the context of video content.
---

# Video Reels Pipeline

A human-in-the-loop pipeline for transforming raw video footage into polished short-form reels. Every stage invites human review, preference, and override — this is a creative collaboration, not an automated assembly line.

## Philosophy

The best reels aren't just technically well-cut — they tell a micro-story. Every cut should have a **visual reason** ("cut TO the guitarist because he's smiling during the solo"), not just a timestamp. Think in **musical bars** or **emotional beats**, not arbitrary seconds. The human always knows best what "feels right" — your job is to surface options, explain tradeoffs, and execute their vision precisely.

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────┐
│  1. INGEST         Scan raw files, extract metadata     │
│  2. FILTER         Human selects useful clips, renames  │
│  3. ANALYZE        Gemini multimodal + audio analysis   │
│  4. STORYBOARD     Interactive HTML review dashboard    │
│  5. FIRST CUT      Build initial reels with ffmpeg      │
│  6. ITERATE        Human feedback → revise → repeat     │
│  7. INSPECT        Frame-level analysis for fine detail  │
│  8. POLISH         Text overlays, timing, final export  │
└─────────────────────────────────────────────────────────┘
         ↑ Human review & override at every stage ↑
```

Each stage is designed to be run, reviewed, and potentially re-run. Don't rush through — let the human see intermediate results before moving on.

---

## Stage 1: Ingest & Inventory

Scan the source directory for video files and build a manifest of what you're working with.

### What to capture per file
- Filename, size, duration
- Resolution and framerate (important: phone cameras often shoot 120fps or variable)
- Codec and audio channels
- A human-readable summary

### How to scan
```bash
ffprobe -v error -show_entries format=duration,size,bit_rate:stream=width,height,r_frame_rate,codec_name \
  -of json "INPUT.mov"
```

### Present as a review interface
Build a simple HTML page or table so the human can see all clips at a glance. Include embedded video players where possible — people need to *watch* footage before making decisions. Extract a thumbnail from each clip (frame at 2s):
```bash
ffmpeg -v error -ss 2 -i "INPUT.mov" -vframes 1 -q:v 2 "thumb.jpg"
```

**Human checkpoint**: "Here are your N clips. Which ones are useful? Any you want to rename?"

---

## Stage 2: Filter & Rename

The human tells you which clips to keep and what to call them. Create a `filtered/` directory with descriptively named copies.

Good naming follows the pattern: `H7_hook_riff_and_traveling.mov` — source identifier + content description. This makes everything downstream more readable.

Group clips by camera type if there are multiple angles (handheld vs POV vs tripod). Note the resolution and fps differences between camera types — you'll need to handle scaling later.

**Human checkpoint**: "Here are your filtered clips. Does this look right?"

---

## Stage 3: AI-Powered Analysis

This is the creative intelligence layer. Use Google's Gemini API (multimodal, video-capable) to build a rich per-timestamp inventory of what's happening in each clip.

### Why this matters
Without analysis, you're cutting blind. With a detailed inventory of who's visible, what expressions they're making, what the audio is doing, and what's notable at each moment, you can make *intentional* editing decisions instead of arbitrary ones.

### Compression for API upload
Raw footage is too large for API upload. Compress first:
```bash
ffmpeg -v error -i "INPUT.mov" \
  -vf "scale=320:-2" -r 24 -c:v libx264 -crf 30 \
  -c:a aac -b:a 64k "compressed.mp4"
```
This gets a typical 1-minute clip down to ~2-5MB without losing the visual information Gemini needs.

### Analysis approach: Single combined pass
Send one prompt per clip that requests both inventory AND creative suggestions. The key lesson learned: **5-second windows** are the right granularity. 2-second windows generate too much data and cost too much; 10-second windows miss important moments.

#### Prompt structure
```
Analyze this video clip. For every 5-second window, provide:

INVENTORY (per window):
- people_visible: who's in frame, face visible?, expression, action
- audio: volume level, what's playing, any lyrics/speech, energy (1-5)
- camera: framing (wide/medium/closeup/pov), focus subject
- notable: anything standout (someone smiling, a dog walking in, crowd reaction)
- edit_quality: 1-5 rating of how usable this moment is for a reel

REEL SUGGESTIONS:
Based on the inventory, suggest cuts for:
- A ~30s tight reel (best moments only)
- A ~60s extended reel (fuller story arc)

For each suggested cut specify:
- source timestamp (start, duration)
- visual_subject: what to show
- visual_reason: WHY this cut (not just "interesting" — be specific)
- audio_description: what's happening in the audio
- transition_note: what comes before/after and why the transition works
```

### Audio amplitude extraction
Complement Gemini's analysis with quantitative audio data — RMS amplitude per 0.5-second window:
```bash
ffmpeg -v error -i "INPUT.mov" -ac 1 -ar 8000 -f s16le -acodec pcm_s16le pipe:1
```
Then compute RMS per window in Python. This gives you volume contours that help identify musical peaks, quiet moments, and natural phrase boundaries.

### Rate limiting and progress
Gemini API calls take 60-120 seconds per clip. Always:
- Run analysis in background with logging to a file
- Tail the log periodically to show progress
- Save results as JSON files immediately (don't lose work if something fails)
- Only analyze primary clips (the ones that will actually be used), not all of them

### Output structure
Save enriched analysis as `{clip_name}_enriched.json`:
```json
{
  "inventory": [
    {
      "time_window": "00:00-00:05",
      "people": [...],
      "audio": {"volume": "loud", "energy": 4, ...},
      "camera": {"framing": "medium", ...},
      "notable": "Guitarist smiling at bassist",
      "quality": 5
    }
  ],
  "reel_options": {
    "short_30s": {"concept": "...", "cuts": [...]},
    "long_60s": {"concept": "...", "cuts": [...]}
  }
}
```

**Human checkpoint**: "Here's what the AI found in your clips. Do these moments match what you remember? Anything it missed?"

---

## Stage 4: Storyboard

Build an interactive HTML dashboard that lets the human visualize the planned edit before any video processing happens.

### What the storyboard should show
For each proposed reel:
- **Overview**: concept, duration, number of cuts
- **Per-cut row**: thumbnail frame, source clip, timestamp, duration, visual reason, audio description, transition note
- **Embedded video player** for the reel once it's built
- **Notes/feedback field** per cut (for the human to annotate)
- **Copy Feedback button** to easily share notes

### Frame extraction for thumbnails
Extract a JPEG frame at each cut's start timestamp:
```bash
ffmpeg -v error -ss TIMESTAMP -i "SOURCE.mov" -vframes 1 -q:v 2 "frame.jpg"
```

### Highlight quality-5 moments
Give visual emphasis (colored border, star icon) to moments the AI rated as "must-use" quality. These are your anchors — build the reel around them.

### Storyboard updates
The storyboard is a living document. Update it every time you make changes to the reel structure. The human should always be able to open one file and see the current state of everything.

**Human checkpoint**: "Take a look at the storyboard. Does the flow make sense? Want to change the order, swap any cuts, or try different moments?"

---

## Stage 5: First Cut

Build the actual video reels using ffmpeg. This is where the storyboard becomes real.

### Instagram Reels format
- **Aspect ratio**: 9:16 vertical (1080x1920)
- **Duration**: 15-90 seconds (sweet spot: 30-60s)
- **Codec**: H.264/AAC
- **FPS**: 30

### Scaling for vertical format
Most source footage needs scaling + cropping to fit 9:16:
```bash
SCALE="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
```

### The segment-concat pattern
For each reel, the process is:
1. **Cut video segments** (no audio): extract each visual segment from its source, scale to 1080x1920
2. **Build concat list**: text file listing segments in order
3. **Concat video**: join all segments into one video track
4. **Extract audio backbone**: pull continuous audio from the primary source clip
5. **Merge**: combine concatenated video with continuous audio

This separation is important: **video hard-cuts while audio flows continuously**. The viewer experiences smooth music with intentional visual changes — much more professional than audio cutting with video.

```bash
# 1. Cut a segment (video only)
ffmpeg -v error -ss START -i "SOURCE.mov" -t DURATION \
  -vf "$SCALE" -an -c:v libx264 -preset fast -crf 23 -r 30 "segment.mp4" -y

# 2. Concat list
echo "file 'seg1.mp4'" > concat.txt
echo "file 'seg2.mp4'" >> concat.txt

# 3. Concat
ffmpeg -v error -f concat -safe 0 -i concat.txt -c copy video.mp4 -y

# 4. Audio backbone (continuous from primary source)
ffmpeg -v error -i "PRIMARY_SOURCE.mov" -ss 0 -t TOTAL_DURATION \
  -vn -c:a aac -b:a 128k audio.aac -y

# 5. Merge
ffmpeg -v error -i video.mp4 -i audio.aac \
  -c:v copy -c:a aac -shortest -movflags +faststart output.mp4 -y
```

### Cut design principles

These principles emerged from extensive iteration and are worth internalizing:

- **Hard cuts only.** No fades, no blinks, no dissolves. They look like buffering on phones. Hard cuts feel modern and professional.
- **Think in bars, not seconds.** For music content, cuts should land on musical phrase boundaries. At ~100 BPM blues, one bar ≈ 2.4s. Minimum cut length: 2 bars (≈5s). Comfortable length: 4 bars (≈10s).
- **Every cut has a visual reason.** Not "cut at 14s" but "cut TO the guitarist because he's smiling." Define what you're cutting TO and WHY.
- **Multi-angle variety.** If you have multiple camera angles, swap between them to keep visual energy up. Every ~6 seconds is a good rhythm for dynamic sections; hold longer for contemplative moments.
- **No color grading** unless specifically requested. Raw footage from modern phones usually looks better than amateur color grades, which tend to look heavy-handed.
- **Continuous audio backbone.** Pick one source's audio and let it play through. Video cuts, audio flows.

### Working directory
Create a `reel_work/` directory for intermediate files (segments, audio, concat lists). These can be large — plan for ~200MB per reel iteration.

**Human checkpoint**: "Here's the first cut. Watch all the reels and tell me what works and what doesn't."

---

## Stage 6: Iterative Editing

This is where the magic happens. The human watches the reels and gives feedback. Your job: interpret their notes, make precise changes, and show them the result.

### Common feedback patterns and how to handle them

| User says | What they mean | How to fix |
|-----------|---------------|------------|
| "The cuts are too fast" | Segments too short, feels choppy | Lengthen segments to 8-12s, think in bars |
| "You cut in the middle of a solo" | Cut doesn't respect musical phrases | Use Gemini/audio analysis to find phrase boundaries |
| "It looks like it's buffering" | Fade/blink transitions are janky | Switch to hard cuts, no transitions |
| "The color looks weird" | Color grading is too heavy | Remove grading, use raw footage |
| "The audio jumps" | Audio cutting with video | Use continuous audio backbone |
| "It's all the same angle" | Not enough camera variety | Swap angles every ~6s in dynamic sections |
| "This part is perfect, don't touch it" | Lock a section | Note exact timestamps, preserve in future versions |
| "It needs something but I don't know what" | Offer options | Generate 2-3 variants, show in storyboard |

### Version discipline
Name each iteration clearly: `build_reels_v2.py`, `build_reels_v3.py`, etc. Never modify a previous version — create a new one. This lets you go back if something was better before.

Keep old reel outputs too. The human might say "actually v2 was better for that part."

### Re-analysis when needed
Sometimes feedback reveals that you need richer data. If the human says things like "we need to think about what to transition to" or "analyze the faces," that's a signal to go back to Stage 3 and run a more targeted Gemini analysis. Don't resist this — the analysis is what makes intentional editing possible.

**Human checkpoint**: After every revision. Always. Let them watch the new version before moving on.

---

## Stage 7: Frame Inspection

For nuanced work — placing text overlays, verifying positions, checking if an element is visible — you need to look at individual frames.

### The inspection workflow
1. **Extract frames** at the specific timestamps of interest
2. **View them** (use the Read tool on JPEGs)
3. **Zoom into regions** by cropping quadrants or specific areas:
   ```bash
   # Top-left quadrant of a 1080x1920 frame
   ffmpeg -v error -i frame.jpg -vf "crop=540:960:0:0" zoomed.jpg -y
   ```
4. **Analyze** what you see: where is the subject? What's the background? Where's the dark area for text?
5. **Verify** after changes: extract the same frames from the modified video and compare

### Position verification
When placing text or identifying elements, always verify with zoomed crops. The full 1080x1920 frame is too small to judge precise placement. Split into quadrants or crop to the region of interest.

### Duration analysis
When adding timed overlays, check that the element is actually visible for the entire duration window. Extract frames at both the START and END of the overlay window. If the element leaves frame before the overlay ends, trim the duration.

**Human checkpoint**: "I've extracted and analyzed the frames. Here's what I see at each timestamp — does this match what you're seeing?"

---

## Stage 8: Final Polish

### Text overlays with ffmpeg drawtext
```bash
ffmpeg -v error -i input.mp4 \
  -vf "drawtext=text='your text':fontfile=/path/to/font.ttf:\
  fontsize=60:fontcolor=white:borderw=3:bordercolor=black@0.8:\
  x=X:y=Y:enable='between(t,START,END)'" \
  -c:a copy -movflags +faststart output.mp4 -y
```

Key considerations:
- **Font**: Poppins Bold works well for Instagram text (check `fc-list` for available fonts)
- **Positioning**: Place text against dark backgrounds near the subject. Never guess — inspect frames first.
- **Duration**: Match exactly to when the subject is visible. No lingering after they leave frame.
- **Multiple overlays**: Chain drawtext filters with commas. Each gets its own `enable='between(t,START,END)'`.
- **Progression**: Text can escalate ("dog" → "DOG" → "so much DOG") for running gags or emphasis.

### Final export settings
```bash
ffmpeg -v error -i input.mp4 \
  -c:v libx264 -preset slow -crf 20 \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  output_final.mp4
```

### Deliverables
Save final reels to the user's workspace directory with clear names. Update the storyboard HTML to include the final versions.

**Human checkpoint**: "Here are the final reels. Give them a watch and let me know if anything needs tweaking."

---

## Ad-Hoc Analysis Tools

Sometimes you need specific analysis that doesn't fit neatly into the pipeline. Common patterns:

### Beat/onset detection
Extract audio as raw PCM, compute RMS energy in windows, find peaks:
```python
# 25ms windows, 12.5ms hop, 8kHz sample rate
window_size = 200  # 25ms * 8000
hop = 100          # 12.5ms * 8000
# Detect onsets where energy jump > threshold (0.15) with min gap (0.1s)
```
Useful for syncing cuts to musical beats in performance footage.

### Solo/phrase boundary detection
Ask Gemini to identify exact phrase boundaries in musical performances. This prevents the cardinal sin of cutting in the middle of a solo.

### Volume-based scene detection
Use amplitude data to find quiet→loud transitions (verse→chorus), which are natural cut points.

---

## Common Pitfalls

Things that seemed like good ideas but weren't:

1. **2-second analysis windows**: Way too granular. Generates massive JSON, costs more API calls, and doesn't add value over 5-second windows.
2. **Analyzing all clips**: Only analyze the ones you'll actually use (primary clips). Secondary/backup angles can be analyzed later if needed.
3. **Color grading everything**: Warm/orange grades on phone footage usually look amateurish. Raw footage from modern phones is already well-balanced.
4. **Fade transitions**: Blink fades, crossfades, and dissolves look like encoding artifacts on mobile. Hard cuts are cleaner.
5. **Not showing progress**: Long-running API calls (60-120s each) need progress logging. The human will cancel if they can't see what's happening.
6. **Cutting audio with video**: When video hard-cuts, the audio should flow continuously from one source. Audio jumps are jarring.

---

## Gemini API Setup

The pipeline uses `google-generativeai` Python package:

```bash
pip install google-generativeai --break-system-packages -q
```

```python
import google.generativeai as genai
genai.configure(api_key="YOUR_KEY")  # Or from environment

# Upload compressed video
video_file = genai.upload_file("compressed.mp4")

# Wait for processing
import time
while video_file.state.name == "PROCESSING":
    time.sleep(5)
    video_file = genai.get_file(video_file.name)

# Generate analysis
model = genai.GenerativeModel("gemini-2.5-flash")
response = model.generate_content([video_file, PROMPT])
```

Always handle the upload→processing→ready lifecycle. Videos take 30-60 seconds to process before you can query them.
