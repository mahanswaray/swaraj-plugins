# peek-capture — Single-Step Screenshots for Claude Code

A PreToolUse hook that gives Claude Code instant visual access to your Mac screen in a single tool call.

## The Problem

Claude Code's `Read` tool can display images, but `Bash` can only return text. So getting a screenshot normally takes two steps:

1. `Bash("screencapture /tmp/shot.png")` → text output only
2. `Read("/tmp/shot.png")` → image displayed

This is slow and wastes a round-trip.

## The Solution

A `PreToolUse` hook intercepts `Read` calls to magic paths (`/tmp/peek-*.png`), runs a screen capture CLI **before** Read executes, then Read returns the fresh image. One tool call = one screenshot.

```
Read("/tmp/peek-screen-0-001.png")
       ↓ hook fires
       ↓ peekaboo image --mode screen --screen-index 0 --path /tmp/peek-screen-0-001.png
       ↓ Read returns the image
       → Claude sees your screen
```

## Conventions

Args are encoded in the filename. The hook parses them:

| Path | Captures |
|------|----------|
| `/tmp/peek-screen-0-001.png` | Display at index 0 (e.g., laptop) |
| `/tmp/peek-screen-1-002.png` | Display at index 1 (e.g., external monitor) |
| `/tmp/peek-frontmost-003.png` | Frontmost window |
| `/tmp/peek-app-Chrome-004.png` | Chrome windows specifically |

The trailing `-NNN` is a unique ID — bump it each time so captures don't overwrite.

## Installation

### Prerequisites

- **Peekaboo** (macOS-native screen capture via ScreenCaptureKit):
  ```bash
  brew install steipete/tap/peekaboo
  ```
- **Screen Recording permission**: System Settings → Privacy & Security → Screen & System Audio Recording → enable for your terminal

### Setup

1. Copy the hook script:
   ```bash
   mkdir -p ~/.claude/hooks
   cp scripts/peek-capture.sh ~/.claude/hooks/peek-capture.sh
   chmod +x ~/.claude/hooks/peek-capture.sh
   ```

2. Add to `~/.claude/settings.json`:
   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "Read",
           "hooks": [
             {
               "type": "command",
               "command": "~/.claude/hooks/peek-capture.sh"
             }
           ]
         }
       ]
     }
   }
   ```

3. Start a new Claude Code session. Ask it to read `/tmp/peek-screen-0-001.png` — it should capture and display your screen.

## Adapt It

This uses Peekaboo, but the **pattern** works with any CLI that captures screenshots:

- macOS `screencapture`: replace the `peekaboo image` calls with `screencapture -x` / `screencapture -l <windowid>`
- Linux `scrot` / `grim` (Wayland): same idea, different capture commands
- `ffmpeg` frame grab: capture from a video device

The hook is ~30 lines of bash. Fork it and swap in your preferred capture tool.

## How It Works (for tool authors)

Claude Code hooks fire shell commands at specific lifecycle points. `PreToolUse` runs before a tool executes, receiving the tool's input as JSON on stdin.

The key insight: **Read is the only built-in tool that returns images to the model.** By hooking into Read's pre-execution, you can make *any* CLI's visual output available to Claude in a single step. This pattern extends beyond screenshots — you could use it for:

- Chart rendering (generate SVG/PNG → Read displays it)
- Diagram generation (mermaid/graphviz → PNG → Read)
- Camera capture (webcam frame → Read)
- PDF rendering (specific page → PNG → Read)

Any "generate image then view it" workflow collapses to one tool call.
