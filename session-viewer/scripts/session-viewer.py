#!/usr/bin/env python3
"""
Claude Session Viewer — SQLite-backed tool call browser & file recovery.

Usage:
  csv db                           # Build/rebuild SQLite DB from all sessions
  csv db --incremental             # Only ingest new/changed sessions
  csv sql "SELECT ..."             # Run raw SQL query
  csv stats                        # Aggregate stats dashboard
  csv files <session-id>           # Show all files touched in a session
  csv recover <session-id> <path>  # Find & copy old file content to clipboard
  csv <session-id>                 # Interactive browser (original mode)
  csv --recent [N]                 # Show N most recent sessions
  csv --list                       # List all projects
"""

import json
import os
import sys
import re
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
DB_PATH = CLAUDE_DIR / "sessions.db"
CODE_PREFIX = f"-Users-{os.environ.get('USER', 'user')}-Documents-code-"


# ─── SQLite Schema & Ingestion ──────────────────────────────────────────────

def get_db(readonly=False):
    """Get a connection to the SQLite DB."""
    if readonly and not DB_PATH.exists():
        print(f"No database found. Run: csv db")
        sys.exit(1)
    uri = f"file:{DB_PATH}"
    if readonly:
        uri += "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn):
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            project_dir TEXT NOT NULL,
            mtime REAL NOT NULL,
            size_bytes INTEGER NOT NULL,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            first_user_message TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS tool_calls (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            file_path TEXT,
            command TEXT,
            input_json TEXT,
            result_text TEXT,
            result_size INTEGER DEFAULT 0,
            line_num INTEGER,
            seq INTEGER,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS user_messages (
            session_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            line_num INTEGER,
            msg_type TEXT NOT NULL,
            text TEXT NOT NULL,
            char_count INTEGER DEFAULT 0,
            PRIMARY KEY (session_id, seq),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS assistant_thinking (
            session_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            line_num INTEGER,
            thinking TEXT NOT NULL,
            char_count INTEGER DEFAULT 0,
            following_text TEXT,
            PRIMARY KEY (session_id, seq),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_tc_session ON tool_calls(session_id);
        CREATE INDEX IF NOT EXISTS idx_tc_tool ON tool_calls(tool_name);
        CREATE INDEX IF NOT EXISTS idx_tc_file ON tool_calls(file_path);
        CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
        CREATE INDEX IF NOT EXISTS idx_sessions_mtime ON sessions(mtime DESC);
        CREATE INDEX IF NOT EXISTS idx_um_session ON user_messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_um_type ON user_messages(msg_type);
        CREATE INDEX IF NOT EXISTS idx_at_session ON assistant_thinking(session_id);
    """)
    conn.commit()


def result_to_text(result):
    """Serialize a tool result to plain text."""
    if result is None:
        return None
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts = []
        for block in result:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                else:
                    parts.append(json.dumps(block, indent=2))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return json.dumps(result, indent=2)


def ingest_session(conn, jsonl_path, project_name, project_dir, incremental=False):
    """Parse one session JSONL and insert into DB."""
    sid = jsonl_path.stem
    stat = jsonl_path.stat()

    if incremental:
        existing = conn.execute(
            "SELECT mtime FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        if existing and abs(existing["mtime"] - stat.st_mtime) < 0.01:
            return False  # unchanged

    # Parse JSONL
    messages = []
    with open(jsonl_path) as f:
        for i, line in enumerate(f):
            try:
                obj = json.loads(line.strip())
                obj["_line"] = i
                messages.append(obj)
            except json.JSONDecodeError:
                continue

    # Extract first user text message and timestamp
    first_user_msg = None
    created_at = None
    for msg in messages:
        if msg.get("type") == "user":
            content = msg.get("message", {}).get("content", [])
            if isinstance(content, str) and content.strip():
                first_user_msg = content[:500]
                break
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text and not text.startswith("<"):
                            first_user_msg = text[:500]
                            break
                    elif isinstance(block, str) and block.strip():
                        first_user_msg = block[:500]
                        break
                if first_user_msg:
                    break

    # Try to get created_at from first message timestamp
    for msg in messages:
        ts = msg.get("timestamp")
        if ts:
            created_at = ts
            break

    # Extract tool calls
    results_map = {}
    for msg in messages:
        if msg.get("type") == "user":
            content = msg.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        results_map[block.get("tool_use_id", "")] = block.get("content", "")

    tool_calls = []
    seq = 0
    for msg in messages:
        if msg.get("type") == "assistant":
            content = msg.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_id = block.get("id", "")
                        tool_name = block.get("name", "?")
                        tool_input = block.get("input", {})
                        result = results_map.get(tool_id)
                        result_text = result_to_text(result)

                        # Extract file_path for file tools
                        file_path = None
                        if tool_name in ("Read", "Write", "Edit"):
                            file_path = tool_input.get("file_path")
                        elif tool_name == "Glob":
                            file_path = tool_input.get("pattern")
                        elif tool_name == "Grep":
                            file_path = tool_input.get("path")

                        # Extract command for Bash
                        command = None
                        if tool_name == "Bash":
                            command = tool_input.get("command")

                        tool_calls.append((
                            tool_id, sid, tool_name, file_path, command,
                            json.dumps(tool_input), result_text,
                            len(result_text) if result_text else 0,
                            msg["_line"], seq
                        ))
                        seq += 1

    # Extract user messages and tool rejections
    REJECTION_MARKER = "The user doesn't want to proceed"
    user_messages = []
    um_seq = 0
    for msg in messages:
        if msg.get("type") != "user":
            continue
        content = msg.get("message", {}).get("content", [])

        # Raw string content = direct user message
        if isinstance(content, str):
            text = content.strip()
            if text and not text.startswith("<system-reminder>"):
                user_messages.append((sid, um_seq, msg["_line"], "prompt", text, len(text)))
                um_seq += 1
            continue

        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")

            # User typed text
            if btype == "text":
                text = block.get("text", "").strip()
                if not text:
                    continue
                # Skip system-reminder injections
                if text.startswith("<system-reminder>"):
                    continue
                # Interruptions are useful signal
                if text == "[Request interrupted by user]":
                    user_messages.append((sid, um_seq, msg["_line"], "interrupt", text, len(text)))
                    um_seq += 1
                    continue
                user_messages.append((sid, um_seq, msg["_line"], "prompt", text, len(text)))
                um_seq += 1

            # Tool rejections — user clicked deny with feedback
            elif btype == "tool_result":
                rc = str(block.get("content", ""))
                if REJECTION_MARKER in rc:
                    # Extract user's reason after "the user said:\n"
                    reason = rc
                    user_messages.append((sid, um_seq, msg["_line"], "rejection", reason, len(reason)))
                    um_seq += 1

    # Extract assistant thinking blocks
    thinking_blocks = []
    th_seq = 0
    for msg in messages:
        if msg.get("type") != "assistant":
            continue
        content = msg.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for j, block in enumerate(content):
            if not isinstance(block, dict) or block.get("type") != "thinking":
                continue
            thinking = block.get("thinking", "").strip()
            if not thinking:
                continue
            # Grab the next text block as context for what the thinking led to
            following_text = None
            for k in range(j + 1, len(content)):
                nxt = content[k]
                if isinstance(nxt, dict) and nxt.get("type") == "text":
                    following_text = nxt.get("text", "")[:500]
                    break
                elif isinstance(nxt, dict) and nxt.get("type") == "tool_use":
                    following_text = f"[tool_use: {nxt.get('name', '?')}]"
                    break
            thinking_blocks.append((sid, th_seq, msg["_line"], thinking, len(thinking), following_text))
            th_seq += 1

    # Upsert session
    conn.execute("""
        INSERT OR REPLACE INTO sessions
        (id, project, project_dir, mtime, size_bytes, message_count, tool_call_count, first_user_message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sid, project_name, str(project_dir), stat.st_mtime, stat.st_size,
          len(messages), len(tool_calls), first_user_msg, created_at))

    # Delete old data for this session then insert new
    conn.execute("DELETE FROM tool_calls WHERE session_id = ?", (sid,))
    conn.executemany("""
        INSERT INTO tool_calls (id, session_id, tool_name, file_path, command, input_json, result_text, result_size, line_num, seq)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, tool_calls)

    conn.execute("DELETE FROM user_messages WHERE session_id = ?", (sid,))
    conn.executemany("""
        INSERT INTO user_messages (session_id, seq, line_num, msg_type, text, char_count)
        VALUES (?, ?, ?, ?, ?, ?)
    """, user_messages)

    conn.execute("DELETE FROM assistant_thinking WHERE session_id = ?", (sid,))
    conn.executemany("""
        INSERT INTO assistant_thinking (session_id, seq, line_num, thinking, char_count, following_text)
        VALUES (?, ?, ?, ?, ?, ?)
    """, thinking_blocks)

    return True


def build_db(incremental=False):
    """Ingest all sessions into SQLite."""
    conn = get_db()
    init_db(conn)

    total = 0
    ingested = 0
    skipped = 0

    for d in sorted(PROJECTS_DIR.iterdir()):
        if not d.name.startswith(CODE_PREFIX):
            continue
        project_name = d.name[len(CODE_PREFIX):].replace("-", "/")
        jsonls = list(d.glob("*.jsonl"))
        for jsonl_path in jsonls:
            total += 1
            try:
                changed = ingest_session(conn, jsonl_path, project_name, d, incremental)
                if changed:
                    ingested += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"  WARN: {jsonl_path.name}: {e}")
                skipped += 1

        if jsonls:
            conn.commit()

    conn.commit()

    # Final stats
    row = conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()
    tc_row = conn.execute("SELECT COUNT(*) as c FROM tool_calls").fetchone()
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)

    print(f"\nDB built: {DB_PATH}")
    print(f"  Sessions: {row['c']} total ({ingested} ingested, {skipped} skipped)")
    print(f"  Tool calls: {tc_row['c']}")
    print(f"  DB size: {size_mb:.1f} MB")
    conn.close()


# ─── Query Commands ──────────────────────────────────────────────────────────

def run_sql(query):
    """Run raw SQL and print results."""
    conn = get_db(readonly=True)
    try:
        cur = conn.execute(query)
        rows = cur.fetchall()
        if not rows:
            print("(no results)")
            return

        keys = rows[0].keys()
        # Calculate column widths
        widths = {k: len(k) for k in keys}
        str_rows = []
        for row in rows:
            sr = {}
            for k in keys:
                val = str(row[k]) if row[k] is not None else "NULL"
                # Truncate long values for display
                if len(val) > 120:
                    val = val[:117] + "..."
                sr[k] = val
                widths[k] = max(widths[k], len(val))
            str_rows.append(sr)

        # Print header
        header = "  ".join(k.ljust(widths[k]) for k in keys)
        print(header)
        print("  ".join("─" * widths[k] for k in keys))
        for sr in str_rows:
            print("  ".join(sr[k].ljust(widths[k]) for k in keys))
        print(f"\n({len(rows)} rows)")
    except sqlite3.OperationalError as e:
        print(f"SQL error: {e}")
    finally:
        conn.close()


def show_stats():
    """Show aggregate stats dashboard."""
    conn = get_db(readonly=True)

    print("\n" + "=" * 70)
    print("CLAUDE SESSION STATS")
    print("=" * 70)

    # Overview
    row = conn.execute("""
        SELECT COUNT(*) as sessions,
               SUM(tool_call_count) as total_tools,
               SUM(size_bytes) as total_bytes,
               MIN(mtime) as earliest,
               MAX(mtime) as latest
        FROM sessions
    """).fetchone()
    print(f"\n  Sessions:    {row['sessions']}")
    print(f"  Tool calls:  {row['total_tools']}")
    print(f"  Total data:  {(row['total_bytes'] or 0) / (1024*1024):.1f} MB")
    if row['earliest']:
        print(f"  Date range:  {datetime.fromtimestamp(row['earliest']).strftime('%Y-%m-%d')} → {datetime.fromtimestamp(row['latest']).strftime('%Y-%m-%d')}")

    # By project
    print(f"\n{'─'*70}")
    print("BY PROJECT:")
    for r in conn.execute("""
        SELECT project, COUNT(*) as sessions, SUM(tool_call_count) as tools,
               ROUND(SUM(size_bytes)/1024.0/1024.0, 1) as mb
        FROM sessions GROUP BY project ORDER BY sessions DESC
    """):
        print(f"  {r['project']:50s}  {r['sessions']:4d} sessions  {r['tools'] or 0:6d} tools  {r['mb']:.1f}MB")

    # Tool frequency
    print(f"\n{'─'*70}")
    print("TOOL FREQUENCY:")
    for r in conn.execute("""
        SELECT tool_name, COUNT(*) as cnt,
               ROUND(SUM(result_size)/1024.0/1024.0, 1) as result_mb
        FROM tool_calls GROUP BY tool_name ORDER BY cnt DESC LIMIT 20
    """):
        print(f"  {r['tool_name']:30s}  {r['cnt']:6d} calls  {r['result_mb']:.1f}MB results")

    # Most touched files
    print(f"\n{'─'*70}")
    print("MOST TOUCHED FILES (Read/Write/Edit):")
    for r in conn.execute("""
        SELECT file_path, COUNT(*) as cnt,
               GROUP_CONCAT(DISTINCT tool_name) as tools
        FROM tool_calls
        WHERE file_path IS NOT NULL
          AND tool_name IN ('Read', 'Write', 'Edit')
        GROUP BY file_path ORDER BY cnt DESC LIMIT 20
    """):
        fp = r['file_path']
        # Shorten path
        fp = fp.replace(str(Path.home()), "~")
        print(f"  {cnt_bar(r['cnt'])} {r['cnt']:4d}x  {r['tools']:15s}  {fp}")

    # Sessions by day (last 14 days)
    print(f"\n{'─'*70}")
    print("SESSIONS PER DAY (last 14 days):")
    for r in conn.execute("""
        SELECT DATE(mtime, 'unixepoch', 'localtime') as day, COUNT(*) as cnt
        FROM sessions
        WHERE mtime > unixepoch('now', '-14 days')
        GROUP BY day ORDER BY day DESC
    """):
        print(f"  {r['day']}  {'█' * min(r['cnt'], 50)} {r['cnt']}")

    # Biggest sessions
    print(f"\n{'─'*70}")
    print("BIGGEST SESSIONS:")
    for r in conn.execute("""
        SELECT id, project, tool_call_count as tools,
               ROUND(size_bytes/1024.0, 0) as kb,
               SUBSTR(first_user_message, 1, 60) as prompt
        FROM sessions ORDER BY size_bytes DESC LIMIT 10
    """):
        print(f"  {r['id'][:12]}...  {r['kb']:7.0f}KB  {r['tools']:4d} tools  {r['project']:30s}  {r['prompt'] or ''}")

    conn.close()


def cnt_bar(n, max_width=15):
    """Small bar chart character."""
    blocks = min(n, max_width)
    return "▓" * blocks + "░" * (max_width - blocks)


def show_session_files(session_id):
    """Show all files touched in a session, grouped by file."""
    conn = get_db(readonly=True)

    # Find session
    session = conn.execute(
        "SELECT * FROM sessions WHERE id LIKE ?", (f"{session_id}%",)
    ).fetchone()
    if not session:
        print(f"Session not found: {session_id}")
        return

    sid = session['id']
    print(f"\nSession: {sid}")
    print(f"Project: {session['project']}")
    print(f"Prompt:  {session['first_user_message'] or '(none)'}")
    print(f"Tools:   {session['tool_call_count']}")

    print(f"\n{'─'*70}")
    print("FILES TOUCHED:")
    for r in conn.execute("""
        SELECT file_path, tool_name, COUNT(*) as cnt, seq
        FROM tool_calls
        WHERE session_id = ? AND file_path IS NOT NULL
          AND tool_name IN ('Read', 'Write', 'Edit')
        GROUP BY file_path, tool_name
        ORDER BY MIN(seq)
    """, (sid,)):
        fp = r['file_path'].replace(str(Path.home()), "~")
        print(f"  {r['tool_name']:6s} x{r['cnt']:<3d}  {fp}")

    conn.close()


def recover_file(session_id, file_pattern):
    """Find file content from a session and copy to clipboard."""
    conn = get_db(readonly=True)

    session = conn.execute(
        "SELECT id FROM sessions WHERE id LIKE ?", (f"{session_id}%",)
    ).fetchone()
    if not session:
        print(f"Session not found: {session_id}")
        return

    sid = session['id']

    # Find matching Read/Write tool calls
    rows = conn.execute("""
        SELECT id, tool_name, file_path, result_text, result_size, seq
        FROM tool_calls
        WHERE session_id = ?
          AND tool_name IN ('Read', 'Write')
          AND file_path LIKE ?
        ORDER BY seq
    """, (sid, f"%{file_pattern}%")).fetchall()

    if not rows:
        print(f"No Read/Write calls matching '{file_pattern}' in session {sid[:12]}...")
        return

    print(f"\nFound {len(rows)} matching tool calls:")
    for i, r in enumerate(rows):
        fp = r['file_path'].replace(str(Path.home()), "~")
        size = r['result_size'] or 0
        print(f"  [{i}] {r['tool_name']:6s}  {size:7d} chars  {fp}")

    # If Write, show the input content instead of result
    try:
        pick = input("\nPick # to copy to clipboard (or Enter to quit): ").strip()
        if not pick:
            return
        idx = int(pick)
        r = rows[idx]

        if r['tool_name'] == 'Write':
            # For Write, the file content is in input_json
            tc = conn.execute("SELECT input_json FROM tool_calls WHERE id = ?", (r['id'],)).fetchone()
            inp = json.loads(tc['input_json'])
            text = inp.get('content', '')
        else:
            text = r['result_text'] or "(empty)"

        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode())
        print(f"Copied {len(text)} chars to clipboard.")
    except (ValueError, IndexError, EOFError, KeyboardInterrupt):
        return
    finally:
        conn.close()


# ─── Interactive Browser (original) ──────────────────────────────────────────

def get_code_projects():
    if not PROJECTS_DIR.exists():
        return []
    projects = []
    for d in sorted(PROJECTS_DIR.iterdir()):
        if d.name.startswith(CODE_PREFIX):
            short_name = d.name[len(CODE_PREFIX):].replace("-", "/")
            jsonls = list(d.glob("*.jsonl"))
            if jsonls:
                projects.append((short_name, d, len(jsonls)))
    return projects


def get_sessions(project_dir):
    sessions = []
    for f in project_dir.glob("*.jsonl"):
        sid = f.stem
        stat = f.stat()
        size_kb = stat.st_size / 1024
        mtime = datetime.fromtimestamp(stat.st_mtime)
        with open(f) as fh:
            line_count = sum(1 for _ in fh)
        sessions.append((sid, mtime, size_kb, line_count, f))
    sessions.sort(key=lambda x: x[1], reverse=True)
    return sessions


def parse_session(jsonl_path):
    messages = []
    with open(jsonl_path) as f:
        for i, line in enumerate(f):
            try:
                obj = json.loads(line.strip())
                obj["_line"] = i
                messages.append(obj)
            except json.JSONDecodeError:
                continue
    return messages


def extract_tool_calls(messages):
    tool_calls = []
    results_map = {}
    for msg in messages:
        if msg.get("type") == "user":
            content = msg.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        results_map[block.get("tool_use_id", "")] = block.get("content", "")
    for msg in messages:
        if msg.get("type") == "assistant":
            content = msg.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_id = block.get("id", "")
                        tool_calls.append({
                            "id": tool_id,
                            "name": block.get("name", "?"),
                            "input": block.get("input", {}),
                            "result": results_map.get(tool_id),
                            "line": msg["_line"],
                        })
    return tool_calls


def format_tool_summary(tc, idx):
    name = tc["name"]
    inp = tc["input"]
    context = ""
    if name == "Read":
        context = inp.get("file_path", "")
    elif name == "Write":
        fp = inp.get("file_path", "")
        content_len = len(inp.get("content", ""))
        context = f"{fp} ({content_len} chars)"
    elif name == "Edit":
        fp = inp.get("file_path", "")
        old = inp.get("old_string", "")[:40]
        context = f"{fp} old='{old}...'"
    elif name == "Bash":
        context = inp.get("command", "")[:80]
    elif name == "Grep":
        context = f"/{inp.get('pattern', '')}/"
    elif name == "Glob":
        context = inp.get("pattern", "")
    elif name == "Agent":
        context = inp.get("description", inp.get("prompt", "")[:60])
    else:
        for k, v in inp.items():
            if isinstance(v, str) and v:
                context = f"{k}={v[:60]}"
                break
    has_result = "+" if tc["result"] is not None else "-"
    return f"  [{idx:3d}] {has_result} {name:20s} {context}"


def show_tool_result(tc):
    result = tc["result"]
    if result is None:
        print("  (no result captured)")
        return
    if isinstance(result, str):
        if "<persisted-output>" in result:
            print(result)
            match = re.search(r"saved to: (.+?)(?:\n|$)", result)
            if match:
                path = match.group(1).strip()
                if os.path.exists(path):
                    print(f"\n--- Reading persisted output from {path} ---")
                    with open(path) as f:
                        print(f.read())
        else:
            print(result)
    elif isinstance(result, list):
        for block in result:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    print(block.get("text", ""))
                elif block.get("type") == "tool_reference":
                    print(f"  [tool_reference: {block.get('tool_name', '?')}]")
                else:
                    print(json.dumps(block, indent=2)[:2000])
            else:
                print(str(block)[:2000])
    else:
        print(json.dumps(result, indent=2)[:5000])


def find_session_across_projects(session_id):
    for d in PROJECTS_DIR.iterdir():
        if not d.name.startswith(CODE_PREFIX):
            continue
        candidate = d / f"{session_id}.jsonl"
        if candidate.exists():
            short = d.name[len(CODE_PREFIX):].replace("-", "/")
            return candidate, short
    for d in PROJECTS_DIR.iterdir():
        if not d.name.startswith(CODE_PREFIX):
            continue
        for f in d.glob("*.jsonl"):
            if session_id in f.stem:
                short = d.name[len(CODE_PREFIX):].replace("-", "/")
                return f, short
    return None, None


def pick_number(prompt, max_val):
    while True:
        try:
            val = input(prompt).strip()
            if val.lower() in ("q", "quit", "exit"):
                sys.exit(0)
            if val == "":
                return None
            n = int(val)
            if 0 <= n < max_val:
                return n
            print(f"  Pick 0-{max_val - 1}")
        except (ValueError, EOFError):
            return None


def interactive_session_browser(tool_calls):
    tool_names = sorted(set(tc["name"] for tc in tool_calls))
    while True:
        print(f"\n{'='*70}")
        print(f"Tool calls: {len(tool_calls)} total")
        print(f"Tool types: {', '.join(tool_names)}")
        print()
        print("Commands:")
        print("  all         — list all tool calls")
        print("  r/read      — list Read calls only")
        print("  w/write     — list Write calls only")
        print("  e/edit      — list Edit calls only")
        print("  b/bash      — list Bash calls only")
        print("  f <name>    — filter by tool name")
        print("  s <text>    — search file paths & commands for text")
        print("  <number>    — show full result of tool call #N")
        print("  c <number>  — copy result to clipboard (pbcopy)")
        print("  q           — quit")
        print()
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not cmd:
            continue
        if cmd in ("q", "quit", "exit"):
            break
        filtered = None
        if cmd in ("all", "a"):
            filtered = tool_calls
        elif cmd in ("r", "read"):
            filtered = [tc for tc in tool_calls if tc["name"] == "Read"]
        elif cmd in ("w", "write"):
            filtered = [tc for tc in tool_calls if tc["name"] == "Write"]
        elif cmd in ("e", "edit"):
            filtered = [tc for tc in tool_calls if tc["name"] == "Edit"]
        elif cmd in ("b", "bash"):
            filtered = [tc for tc in tool_calls if tc["name"] == "Bash"]
        elif cmd.startswith("f "):
            name = cmd[2:].strip()
            filtered = [tc for tc in tool_calls if name.lower() in tc["name"].lower()]
        elif cmd.startswith("s "):
            query = cmd[2:].strip().lower()
            filtered = [tc for tc in tool_calls if query in json.dumps(tc["input"]).lower()]
        if filtered is not None:
            if not filtered:
                print("  No matches.")
            else:
                for i, tc in enumerate(tool_calls):
                    if tc in filtered:
                        print(format_tool_summary(tc, i))
            continue
        if cmd.startswith("c "):
            try:
                idx = int(cmd[2:].strip())
                if 0 <= idx < len(tool_calls):
                    tc = tool_calls[idx]
                    result = tc["result"]
                    if result is None:
                        print("  No result to copy.")
                        continue
                    text = result_to_text(result) or ""
                    proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                    proc.communicate(text.encode())
                    print(f"  Copied {len(text)} chars to clipboard.")
                else:
                    print(f"  Index out of range (0-{len(tool_calls)-1})")
            except ValueError:
                print("  Usage: c <number>")
            continue
        try:
            idx = int(cmd)
            if 0 <= idx < len(tool_calls):
                tc = tool_calls[idx]
                print(f"\n{'─'*70}")
                print(f"Tool: {tc['name']}  (line {tc['line']}, id: {tc['id']})")
                print(f"Input: {json.dumps(tc['input'], indent=2)[:1000]}")
                print(f"{'─'*70}")
                print("Result:")
                show_tool_result(tc)
                print(f"{'─'*70}")
            else:
                print(f"  Index out of range (0-{len(tool_calls)-1})")
        except ValueError:
            print(f"  Unknown command: {cmd}")


def show_recent_sessions(n=20):
    all_sessions = []
    for d in PROJECTS_DIR.iterdir():
        if not d.name.startswith(CODE_PREFIX):
            continue
        short_name = d.name[len(CODE_PREFIX):].replace("-", "/")
        for f in d.glob("*.jsonl"):
            stat = f.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime)
            size_kb = stat.st_size / 1024
            all_sessions.append((f.stem, short_name, mtime, size_kb, f))
    all_sessions.sort(key=lambda x: x[2], reverse=True)
    print(f"\n{'='*80}")
    print(f"Most recent {n} sessions across all projects:")
    print(f"{'='*80}")
    for i, (sid, proj, mtime, size_kb, path) in enumerate(all_sessions[:n]):
        print(f"  [{i:2d}] {mtime.strftime('%Y-%m-%d %H:%M')}  {size_kb:7.0f}KB  {proj:30s}  {sid[:12]}...")
    return all_sessions[:n]


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args:
        # Default: interactive project/session picker
        projects = get_code_projects()
        if not projects:
            print("No Claude Code projects found under Documents/code/")
            sys.exit(1)
        print(f"\nClaude Code projects:")
        for i, (short, path, count) in enumerate(projects):
            print(f"  [{i:2d}] {short:50s}  {count} sessions")
        pick = pick_number("\nPick project #: ", len(projects))
        if pick is None:
            return
        short, project_dir, _ = projects[pick]
        sessions = get_sessions(project_dir)
        print(f"\nSessions in {short} (newest first):")
        for i, (sid, mtime, size_kb, lines, path) in enumerate(sessions[:30]):
            print(f"  [{i:2d}] {mtime.strftime('%Y-%m-%d %H:%M')}  {size_kb:7.0f}KB  {lines:5d} msgs  {sid[:12]}...")
        pick = pick_number("\nPick session #: ", min(30, len(sessions)))
        if pick is None:
            return
        sid, mtime, size_kb, lines, path = sessions[pick]
        print(f"\nLoading session {sid}...")
        messages = parse_session(path)
        tool_calls = extract_tool_calls(messages)
        print(f"Parsed {len(messages)} messages, {len(tool_calls)} tool calls")
        interactive_session_browser(tool_calls)
        return

    cmd = args[0]

    # csv db [--incremental]
    if cmd == "db":
        incremental = "--incremental" in args
        print(f"Building SQLite DB ({'incremental' if incremental else 'full rebuild'})...")
        build_db(incremental)
        return

    # csv sql "SELECT ..."
    if cmd == "sql":
        if len(args) < 2:
            print("Usage: csv sql \"SELECT ...\"")
            sys.exit(1)
        run_sql(" ".join(args[1:]))
        return

    # csv stats
    if cmd == "stats":
        show_stats()
        return

    # csv files <session-id>
    if cmd == "files":
        if len(args) < 2:
            print("Usage: csv files <session-id>")
            sys.exit(1)
        show_session_files(args[1])
        return

    # csv recover <session-id> <file-pattern>
    if cmd == "recover":
        if len(args) < 3:
            print("Usage: csv recover <session-id> <file-pattern>")
            sys.exit(1)
        recover_file(args[1], args[2])
        return

    # csv --list
    if cmd == "--list":
        projects = get_code_projects()
        print(f"\nClaude Code projects under Documents/code/:")
        for short, path, count in projects:
            print(f"  {short:50s}  {count} sessions")
        return

    # csv --recent [N]
    if cmd == "--recent":
        n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
        recent = show_recent_sessions(n)
        pick = pick_number("\nPick session # (or Enter to quit): ", len(recent))
        if pick is not None:
            sid, proj, mtime, size_kb, path = recent[pick]
            print(f"\nLoading session {sid} from {proj}...")
            messages = parse_session(path)
            tool_calls = extract_tool_calls(messages)
            print(f"Parsed {len(messages)} messages, {len(tool_calls)} tool calls")
            interactive_session_browser(tool_calls)
        return

    # csv <session-id> [--dump-reads]
    session_id = cmd
    dump_reads = "--dump-reads" in args
    path, proj = find_session_across_projects(session_id)
    if not path:
        print(f"Session {session_id} not found in any project.")
        sys.exit(1)
    print(f"Found in project: {proj}")
    print(f"File: {path}")
    messages = parse_session(path)
    tool_calls = extract_tool_calls(messages)
    print(f"Parsed {len(messages)} messages, {len(tool_calls)} tool calls")
    if dump_reads:
        reads = [tc for tc in tool_calls if tc["name"] in ("Read", "Write")]
        for tc in reads:
            fp = tc["input"].get("file_path", "?")
            print(f"\n{'='*70}")
            print(f"[{tc['name']}] {fp}")
            print(f"{'='*70}")
            show_tool_result(tc)
        return
    interactive_session_browser(tool_calls)


if __name__ == "__main__":
    main()
