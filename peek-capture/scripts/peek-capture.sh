#!/bin/bash
# peek-capture.sh — PreToolUse hook for Claude Code
# Intercepts Read tool calls to /tmp/peek-*.png and captures fresh screenshots via Peekaboo.
#
# THE PATTERN: Encode capture args in the filename, hook runs peekaboo before Read executes.
# Result: single tool call (Read) = fresh screenshot returned as an image.
#
# Convention:
#   /tmp/peek-screen-0-001.png    → peekaboo image --mode screen --screen-index 0
#   /tmp/peek-screen-1-002.png    → peekaboo image --mode screen --screen-index 1
#   /tmp/peek-frontmost-003.png   → peekaboo image --mode frontmost
#   /tmp/peek-app-Chrome-004.png  → peekaboo image --app "Chrome"
#
# Bump the numeric suffix to keep history (each capture is a unique file).
#
# Requirements:
#   - peekaboo CLI: brew install steipete/tap/peekaboo
#   - Screen Recording permission for your terminal app
#
# Installation:
#   1. Copy this script to ~/.claude/hooks/peek-capture.sh
#   2. chmod +x ~/.claude/hooks/peek-capture.sh
#   3. Add to ~/.claude/settings.json under hooks.PreToolUse:
#      {
#        "matcher": "Read",
#        "hooks": [{ "type": "command", "command": "~/.claude/hooks/peek-capture.sh" }]
#      }

# Read tool input comes as JSON via stdin
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | grep -o '"file_path":"[^"]*"' | head -1 | sed 's/"file_path":"//;s/"$//')

# Only intercept /tmp/peek-*.png paths
if [[ ! "$FILE_PATH" =~ ^/tmp/peek-.+\.png$ ]]; then
  exit 0
fi

# Strip /tmp/peek- prefix and .png suffix, then strip trailing -NNN id
SPEC=$(echo "$FILE_PATH" | sed 's|^/tmp/peek-||;s|\.png$||;s|-[0-9]\{1,\}$||')

# Parse command
CMD=$(echo "$SPEC" | cut -d'-' -f1)

case "$CMD" in
  screen)
    INDEX=$(echo "$SPEC" | cut -d'-' -f2)
    peekaboo image --mode screen --screen-index "$INDEX" --path "$FILE_PATH" 2>/dev/null
    ;;
  frontmost)
    peekaboo image --mode frontmost --path "$FILE_PATH" 2>/dev/null
    ;;
  app)
    # Everything after "app-" is the app name (e.g., app-Chrome, app-Visual Studio Code)
    APP_NAME=$(echo "$SPEC" | sed 's|^app-||')
    peekaboo image --app "$APP_NAME" --path "$FILE_PATH" 2>/dev/null
    ;;
  *)
    # Unknown command, skip
    exit 0
    ;;
esac
