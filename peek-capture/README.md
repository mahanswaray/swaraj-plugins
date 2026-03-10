# peek-capture

Single-step screenshots for Claude Code. Uses a PreToolUse hook to capture your Mac screen when Claude reads a magic path — no extra tool calls needed.

See [SKILL.md](skills/peek-capture/SKILL.md) for full docs.

## Quick Start

```bash
brew install steipete/tap/peekaboo
mkdir -p ~/.claude/hooks
cp scripts/peek-capture.sh ~/.claude/hooks/peek-capture.sh
chmod +x ~/.claude/hooks/peek-capture.sh
```

Add to `~/.claude/settings.json`:
```json
"PreToolUse": [{
  "matcher": "Read",
  "hooks": [{ "type": "command", "command": "~/.claude/hooks/peek-capture.sh" }]
}]
```

Then in Claude Code: `Read("/tmp/peek-screen-0-001.png")` → instant screenshot.
