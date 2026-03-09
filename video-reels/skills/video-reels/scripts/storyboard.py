#!/usr/bin/env python3
"""
Storyboard HTML Generator — Template Script

Generates an interactive HTML dashboard showing planned reel cuts
with thumbnails, metadata, video players, and feedback fields.

Usage:
    python storyboard.py --reels reel_config.json --output storyboard.html

reel_config.json structure:
{
  "reels": [
    {
      "name": "Reel 1: Traveling",
      "output_path": "reels/reel1.mp4",
      "audio_source": "H7_hook_riff_and_traveling.mov",
      "segments": [
        {
          "source": "H7_hook_riff_and_traveling.mov",
          "start": 0.0,
          "duration": 6.0,
          "name": "vocalist_passion",
          "visual_reason": "Vocalist reaching out — HOOK",
          "audio_desc": "Full band intro, loud energy",
          "transition_note": "Opens the reel with energy"
        }
      ]
    }
  ]
}
"""

import argparse
import json
import os
import subprocess
import sys


def extract_frame(source_path: str, timestamp: float, output_path: str):
    """Extract a single JPEG frame at the given timestamp."""
    subprocess.run(
        f'ffmpeg -v error -ss {timestamp} -i "{source_path}" '
        f'-vframes 1 -q:v 2 "{output_path}" -y',
        shell=True, check=True
    )


def generate_storyboard(config: dict, output_html: str, frames_dir: str, source_dir: str):
    """Generate the storyboard HTML from a reel configuration."""

    os.makedirs(frames_dir, exist_ok=True)

    # Extract frames for each segment
    for ri, reel in enumerate(config["reels"]):
        for si, seg in enumerate(reel["segments"]):
            frame_name = f"r{ri+1}_{si:02d}_{seg['name']}.jpg"
            frame_path = os.path.join(frames_dir, frame_name)
            seg["_frame"] = frame_name

            if not os.path.exists(frame_path):
                src = os.path.join(source_dir, seg["source"])
                if os.path.exists(src):
                    extract_frame(src, seg["start"], frame_path)

    # Build HTML
    html = _build_html(config, frames_dir)

    with open(output_html, "w") as f:
        f.write(html)

    print(f"Storyboard written to {output_html}")
    return output_html


def _build_html(config: dict, frames_dir: str) -> str:
    """Generate the full HTML string."""

    reel_sections = []
    for ri, reel in enumerate(config["reels"]):
        rows = []
        cumulative = 0.0
        for si, seg in enumerate(reel["segments"]):
            quality = seg.get("quality", 0)
            border = "border-left:4px solid #4CAF50;" if quality >= 5 else ""
            frame_src = f"storyboard_frames/{seg.get('_frame', '')}"

            rows.append(f"""
            <div class="cut-row" style="{border}">
              <div class="cut-thumb">
                <img src="{frame_src}" alt="{seg['name']}"
                     onerror="this.style.background='#333';this.alt='no frame'">
              </div>
              <div class="cut-details">
                <div class="cut-header">
                  <span class="cut-num">#{si+1}</span>
                  <span class="cut-name">{seg['name']}</span>
                  <span class="cut-timing">{cumulative:.0f}s → {cumulative+seg['duration']:.0f}s ({seg['duration']:.0f}s)</span>
                </div>
                <div class="cut-meta">
                  <span class="source">{seg['source']}</span> @ {seg['start']:.1f}s
                </div>
                <div class="cut-reason"><strong>Visual:</strong> {seg.get('visual_reason', '')}</div>
                <div class="cut-audio"><strong>Audio:</strong> {seg.get('audio_desc', '')}</div>
                <div class="cut-transition"><strong>Transition:</strong> {seg.get('transition_note', '')}</div>
              </div>
              <div class="cut-notes">
                <textarea placeholder="Notes..." id="note_r{ri}s{si}"></textarea>
              </div>
            </div>
            """)
            cumulative += seg["duration"]

        total = cumulative
        video_path = reel.get("output_path", "")
        video_player = f"""
        <div class="video-player">
          <video controls width="320">
            <source src="{video_path}" type="video/mp4">
          </video>
          <span class="duration">{total:.0f}s total, {len(reel['segments'])} cuts</span>
        </div>
        """ if video_path else ""

        reel_sections.append(f"""
        <div class="reel-section">
          <h2>{reel['name']}</h2>
          {video_player}
          <div class="cuts-container">
            {''.join(rows)}
          </div>
        </div>
        """)

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Reel Storyboard</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, sans-serif; background:#1a1a1a; color:#eee; padding:20px; }}
  h1 {{ margin-bottom:20px; color:#fff; }}
  .reel-section {{ margin-bottom:40px; background:#222; border-radius:12px; padding:20px; }}
  .reel-section h2 {{ margin-bottom:15px; color:#4CAF50; }}
  .video-player {{ margin-bottom:20px; display:flex; align-items:center; gap:15px; }}
  .video-player video {{ border-radius:8px; }}
  .duration {{ color:#aaa; font-size:14px; }}
  .cuts-container {{ display:flex; flex-direction:column; gap:10px; }}
  .cut-row {{ display:flex; gap:15px; background:#2a2a2a; border-radius:8px; padding:12px; align-items:flex-start; }}
  .cut-thumb img {{ width:120px; height:213px; object-fit:cover; border-radius:6px; }}
  .cut-details {{ flex:1; font-size:14px; }}
  .cut-header {{ display:flex; gap:10px; align-items:center; margin-bottom:8px; }}
  .cut-num {{ background:#4CAF50; color:#fff; border-radius:50%; width:28px; height:28px;
              display:flex; align-items:center; justify-content:center; font-weight:bold; font-size:13px; }}
  .cut-name {{ font-weight:bold; font-size:16px; }}
  .cut-timing {{ color:#aaa; font-size:13px; margin-left:auto; }}
  .cut-meta {{ color:#888; font-size:12px; margin-bottom:6px; }}
  .cut-reason, .cut-audio, .cut-transition {{ margin-bottom:4px; font-size:13px; }}
  .cut-notes textarea {{ width:100%; min-height:50px; background:#333; border:1px solid #444;
                          color:#eee; border-radius:6px; padding:8px; font-size:13px; resize:vertical; }}
  .feedback-btn {{ position:fixed; bottom:20px; right:20px; background:#4CAF50; color:#fff;
                    border:none; padding:12px 24px; border-radius:8px; cursor:pointer; font-size:16px; }}
  .feedback-btn:hover {{ background:#45a049; }}
</style>
</head>
<body>
<h1>Reel Storyboard</h1>
{''.join(reel_sections)}
<button class="feedback-btn" onclick="copyFeedback()">Copy Feedback</button>
<script>
function copyFeedback() {{
  const notes = [];
  document.querySelectorAll('textarea').forEach(t => {{
    if (t.value.trim()) notes.push(t.id + ': ' + t.value.trim());
  }});
  if (notes.length === 0) {{ alert('No notes to copy!'); return; }}
  navigator.clipboard.writeText(notes.join('\\n')).then(() => alert('Feedback copied!'));
}}
</script>
</body></html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Reel config JSON")
    parser.add_argument("--output", default="storyboard.html", help="Output HTML path")
    parser.add_argument("--frames-dir", default="storyboard_frames", help="Frame output dir")
    parser.add_argument("--source-dir", default="filtered", help="Source clips directory")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    generate_storyboard(config, args.output, args.frames_dir, args.source_dir)
