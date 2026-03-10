# session-viewer

SQLite-backed Claude Code session browser. Browse tool calls, recover old file versions, and analyze usage patterns across all your Claude Code sessions.

See [SKILL.md](skills/session-viewer/SKILL.md) for full docs.

## Quick Start

```bash
# Copy the script
mkdir -p ~/.claude
cp scripts/session-viewer.py ~/.claude/session-viewer.py
chmod +x ~/.claude/session-viewer.py

# Add shell alias (add to ~/.zshrc or ~/.bashrc)
echo 'alias csv="python3 ~/.claude/session-viewer.py"' >> ~/.zshrc
source ~/.zshrc

# Build the SQLite database from your sessions
csv db

# Explore
csv stats              # Usage dashboard
csv --recent 20        # Recent sessions
csv <session-id>       # Interactive tool call browser
csv recover <sid> <pattern>  # Recover old file content
```
