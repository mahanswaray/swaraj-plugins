#!/usr/bin/env python3
"""
Gemini Enriched Video Analysis — Template Script

Analyzes video clips using Google Gemini multimodal API to produce
per-5-second visual inventory + creative reel cut suggestions.

Usage:
    python gemini_analyze.py --clips clip1.mov clip2.mov --output-dir ./analysis/
    python gemini_analyze.py --clips-dir ./filtered/ --output-dir ./analysis/

Requires:
    pip install google-generativeai --break-system-packages
    GEMINI_API_KEY environment variable (or pass --api-key)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("gemini_analysis.log")]
)
log = logging.getLogger(__name__)


def compress_for_upload(src: str, dst: str) -> str:
    """Compress video for Gemini API upload (~2-5MB per minute)."""
    log.info(f"  Compressing {os.path.basename(src)}...")
    subprocess.run(
        f'ffmpeg -v error -i "{src}" -vf "scale=320:-2" -r 24 '
        f'-c:v libx264 -crf 30 -c:a aac -b:a 64k "{dst}" -y',
        shell=True, check=True
    )
    size_mb = os.path.getsize(dst) / 1024 / 1024
    log.info(f"  Compressed to {size_mb:.1f}MB")
    return dst


def extract_amplitude(src: str, dst: str, window_sec: float = 0.5):
    """Extract RMS amplitude per window as JSON."""
    import struct
    log.info(f"  Extracting amplitude from {os.path.basename(src)}...")

    result = subprocess.run(
        f'ffmpeg -v error -i "{src}" -ac 1 -ar 8000 -f s16le -acodec pcm_s16le pipe:1',
        shell=True, capture_output=True
    )
    pcm = result.stdout
    sample_rate = 8000
    window_samples = int(window_sec * sample_rate)
    samples = struct.unpack(f"<{len(pcm)//2}h", pcm)

    amplitudes = []
    max_rms = 0
    for i in range(0, len(samples), window_samples):
        chunk = samples[i:i + window_samples]
        if len(chunk) < window_samples // 2:
            break
        rms = (sum(s * s for s in chunk) / len(chunk)) ** 0.5
        max_rms = max(max_rms, rms)
        amplitudes.append({"time": round(i / sample_rate, 1), "rms": round(rms, 1)})

    # Normalize
    if max_rms > 0:
        for a in amplitudes:
            a["norm"] = round(a["rms"] / max_rms, 3)

    with open(dst, "w") as f:
        json.dump(amplitudes, f, indent=2)
    log.info(f"  Amplitude: {len(amplitudes)} windows saved")


def build_analysis_prompt(clip_name: str, duration_sec: float, content_hint: str = "") -> str:
    """Build the combined inventory + reel suggestion prompt."""
    hint = f"\nContent context: {content_hint}" if content_hint else ""

    return f"""Analyze this video clip: "{clip_name}" (duration: {duration_sec:.0f}s).{hint}

TASK 1 — VISUAL INVENTORY
For every 5-second window (00:00-00:05, 00:05-00:10, etc.), provide:

- time_window: "MM:SS-MM:SS"
- people: array of {{role, face_visible, expression, action}}
- audio: {{volume (quiet/medium/loud/peak), sound, lyrics_or_speech, energy (1-5)}}
- camera: {{framing (wide/medium/closeup/pov), focus_on}}
- notable: standout moments (smiles, reactions, unexpected elements, crowd energy)
- quality: 1-5 rating for reel usability (5 = must-use moment)

TASK 2 — REEL CUT SUGGESTIONS
Based on the inventory, suggest cuts for two reel options:

Option A: ~30 second tight reel (best moments, strong hook)
Option B: ~60 second extended reel (story arc, more breathing room)

For each cut specify:
- start: timestamp in seconds
- duration: length in seconds (minimum 5s, prefer 6-12s — think in musical bars)
- source_clip: "{clip_name}"
- visual_subject: what the viewer sees
- visual_reason: WHY this cut — not "interesting" but specific (e.g., "guitarist smiling at bassist shows chemistry")
- audio_description: what's happening sonically
- energy: 1-5
- transition_note: why the transition from previous cut works

Return as JSON with keys "inventory" (array) and "reel_options" (object with "short_30s" and "long_60s", each having "concept", "hook", and "cuts" array).
"""


def analyze_clip(clip_path: str, output_dir: str, api_key: str, content_hint: str = ""):
    """Run full analysis on a single clip."""
    import google.generativeai as genai

    clip_name = os.path.splitext(os.path.basename(clip_path))[0]
    output_file = os.path.join(output_dir, f"{clip_name}_enriched.json")
    amp_file = os.path.join(output_dir, f"{clip_name}_amplitude.json")

    # Skip if already analyzed
    if os.path.exists(output_file):
        log.info(f"  {clip_name}: already analyzed, skipping")
        return output_file

    # Extract amplitude (local, fast)
    if not os.path.exists(amp_file):
        extract_amplitude(clip_path, amp_file)

    # Compress for upload
    compressed = os.path.join(output_dir, f"{clip_name}_compressed.mp4")
    if not os.path.exists(compressed):
        compress_for_upload(clip_path, compressed)

    # Get duration
    dur_result = subprocess.run(
        f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{clip_path}"',
        shell=True, capture_output=True, text=True
    )
    duration = float(dur_result.stdout.strip())

    # Configure Gemini
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")

    # Upload
    log.info(f"  Uploading {clip_name} to Gemini...")
    video_file = genai.upload_file(compressed)

    # Wait for processing
    while video_file.state.name == "PROCESSING":
        time.sleep(5)
        video_file = genai.get_file(video_file.name)
        log.info(f"  Processing... ({video_file.state.name})")

    if video_file.state.name != "ACTIVE":
        log.error(f"  Upload failed: {video_file.state.name}")
        return None

    # Analyze
    log.info(f"  Analyzing {clip_name} ({duration:.0f}s)...")
    prompt = build_analysis_prompt(clip_name, duration, content_hint)

    response = model.generate_content(
        [video_file, prompt],
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.7
        )
    )

    # Parse and save
    try:
        data = json.loads(response.text)
    except json.JSONDecodeError:
        # Sometimes Gemini wraps JSON in markdown code blocks
        text = response.text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        data = json.loads(text)

    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)

    size_kb = os.path.getsize(output_file) / 1024
    log.info(f"  {clip_name}: analysis complete ({size_kb:.0f}KB)")

    # Cleanup compressed file
    os.remove(compressed)

    return output_file


def main():
    parser = argparse.ArgumentParser(description="Gemini enriched video analysis")
    parser.add_argument("--clips", nargs="+", help="Individual clip paths")
    parser.add_argument("--clips-dir", help="Directory of clips to analyze")
    parser.add_argument("--output-dir", required=True, help="Output directory for JSON results")
    parser.add_argument("--api-key", help="Gemini API key (or set GEMINI_API_KEY env var)")
    parser.add_argument("--content-hint", default="", help="Content description (e.g., 'blues jam session')")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.error("No API key. Set GEMINI_API_KEY or pass --api-key")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    clips = args.clips or []
    if args.clips_dir:
        clips += sorted([
            os.path.join(args.clips_dir, f) for f in os.listdir(args.clips_dir)
            if f.lower().endswith(('.mov', '.mp4', '.avi', '.mkv'))
        ])

    if not clips:
        log.error("No clips found")
        sys.exit(1)

    log.info(f"Analyzing {len(clips)} clips...")
    for i, clip in enumerate(clips, 1):
        log.info(f"\n[{i}/{len(clips)}] {os.path.basename(clip)}")
        analyze_clip(clip, args.output_dir, api_key, args.content_hint)
        if i < len(clips):
            log.info("  Waiting 5s (rate limit)...")
            time.sleep(5)

    log.info("\nAll analysis complete!")


if __name__ == "__main__":
    main()
