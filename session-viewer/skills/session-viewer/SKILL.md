# Claude Session Viewer

SQLite-backed tool for browsing Claude Code session data, recovering file contents, and analyzing usage patterns.

## Location

- **Script**: `~/.claude/session-viewer.py`
- **SQLite DB**: `~/.claude/sessions.db` (built from all session JSONL files)
- **Alias**: `csv` (add to `~/.zshrc` or `~/.bashrc`)
- **Source data**: `~/.claude/projects/-Users-*-Documents-code-*/*.jsonl`

## DB Schema (4 tables)

| Table | Key columns | Use for |
|---|---|---|
| `sessions` | id, project, mtime, first_user_message | Finding sessions by project/date/prompt |
| `tool_calls` | session_id, tool_name, file_path, command, input_json, result_text | File recovery, tool analysis |
| `user_messages` | session_id, msg_type (prompt/interrupt/rejection), text | User behavior analysis |
| `assistant_thinking` | session_id, thinking, following_text | Reasoning chain analysis |

## Installation

### 1. Copy the script

```bash
mkdir -p ~/.claude
cp scripts/session-viewer.py ~/.claude/session-viewer.py
chmod +x ~/.claude/session-viewer.py
```

### 2. Add shell alias

Add to `~/.zshrc` or `~/.bashrc`:

```bash
alias csv="python3 ~/.claude/session-viewer.py"
```

Then `source ~/.zshrc`.

### 3. Build the database

```bash
csv db                    # Full build (all sessions → SQLite)
csv db --incremental      # Subsequent runs: only new/changed sessions
```

## CLI Commands

```bash
csv db                        # Full rebuild (all sessions → SQLite)
csv db --incremental          # Only new/changed sessions
csv stats                     # Dashboard: projects, tool freq, top files, sessions/day
csv sql "SELECT ..."          # Raw SQL
csv <session-id>              # Interactive browser (filter by tool type, search, copy to clipboard)
csv recover <sid> <pattern>   # Find old file versions, copy to clipboard
csv files <sid>               # List all files touched in a session
csv --recent 20               # Recent sessions across all projects
csv --list                    # All projects
```

## Common Queries

```sql
-- Find old versions of a file
SELECT session_id, tool_name, result_size, seq FROM tool_calls
WHERE file_path LIKE '%agent-manager%' AND tool_name='Read' ORDER BY ROWID;

-- Search your prompts
SELECT session_id, text FROM user_messages WHERE msg_type='prompt' AND text LIKE '%inngest%';

-- All rejections with your feedback
SELECT session_id, text FROM user_messages WHERE msg_type='rejection';

-- Thinking that mentions a topic
SELECT session_id, SUBSTR(thinking,1,200) FROM assistant_thinking WHERE thinking LIKE '%orchestrator%';

-- Sessions with most interrupts (frustration signal)
SELECT session_id, COUNT(*) as n FROM user_messages WHERE msg_type='interrupt' GROUP BY session_id ORDER BY n DESC LIMIT 10;

-- Most touched files
SELECT file_path, COUNT(*) as n FROM tool_calls WHERE tool_name IN ('Read','Write','Edit') GROUP BY file_path ORDER BY n DESC LIMIT 20;
```

## Interactive Browser

When you run `csv <session-id>`, you get an interactive session with these commands:

| Command | Action |
|---------|--------|
| `all` | List all tool calls |
| `r` / `read` | List Read calls only |
| `w` / `write` | List Write calls only |
| `e` / `edit` | List Edit calls only |
| `b` / `bash` | List Bash calls only |
| `f <name>` | Filter by tool name |
| `s <text>` | Search file paths & commands |
| `<number>` | Show full result of tool call #N |
| `c <number>` | Copy result to clipboard |
| `q` | Quit |

## When to use

- **File recovery**: `csv recover <session-id> <filename-pattern>` — finds Read/Write calls, copies old content to clipboard
- **Session archaeology**: `csv sql` with joins across tables to understand what happened in a session
- **Usage analytics**: `csv stats` or custom SQL for patterns across all sessions
- **Rebuild after new sessions**: `csv db --incremental`

## Requirements

- Python 3.6+
- macOS `pbcopy` for clipboard support (optional — everything else works without it)
- Claude Code sessions in `~/.claude/projects/`

## How it works

Claude Code stores session transcripts as JSONL files in `~/.claude/projects/`. Each line is a message (user, assistant, or system). The session viewer parses these files and indexes them into a SQLite database for fast querying.

Key data extracted:
- **Tool calls**: every Read, Write, Edit, Bash, Grep, Glob, Agent call with inputs and results
- **User messages**: prompts, interruptions, and tool rejections (with user feedback)
- **Assistant thinking**: reasoning blocks and what action followed them
- **Session metadata**: project, timestamps, size, message/tool counts
