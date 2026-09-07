"""Ephemeral agent process run by launcher.py.

Loads a task from argv and drives a depth-limited DeepSeek agent loop over the
axm-edit tools in axm_tools.py, then prints the final summary to stdout.
"""

import json
import os
import sys
import traceback
from pathlib import Path

import httpx

import axm_tools


# --------------------------------------------------------------------------- #
# Config loading: `.env` (gitignored) authoritatively overrides a stale shell
# DEEPSEEK_API_KEY. Explicit env vars still beat `.env`.
# --------------------------------------------------------------------------- #

def _load_dotenv():
    path = Path(__file__).resolve().parent / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        # explicit real env vars win; empty/placeholder env keys lose to .env
        if os.environ.get(key):
            if _looks_placeholder(os.environ[key]):
                os.environ[key] = val
            continue
        os.environ[key] = val


def _looks_placeholder(val: str) -> bool:
    val = val.strip()
    low = val.lower()
    return not val or "YOUR_" in low or "sk-99f" in low or "placeholder" in low or len(val) < 20


_load_dotenv()

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "25"))
TIMEOUT = float(os.environ.get("AGENT_HTTP_TIMEOUT", "120"))

# Static system prompt — providers cache on this string, so keep it / use it.
SYSTEM_PROMPT = """\
You are an autonomous engineer. You have a single goal, provided by the user.

Tools available to you: list_dir, read_file, search_files, run_command, batch_edit, batch_rollback.

WORKFLOW:
1. Investigate with list_dir / search_files / read_file, and run_command if needed.
2. Decide ALL file changes (replace / create / delete) needed to finish the goal.
3. Apply them in a SINGLE batch_edit call — never edit files one at a time.
   batch_edit is atomic: either everything applies or nothing does.
4. If batch_edit reports a failure, fix the offending operation and retry,
   or use batch_rollback with the returned checkpoint.
5. When done, reply with a concise Markdown summary of what you changed and next steps.

Always include exact existing text in the "old" field so batch_edit's validation matches.
"""


# --------------------------------------------------------------------------- #
# DeepSeek chat-completions client (OpenAI-compatible function calling)
# --------------------------------------------------------------------------- #

def chat(messages: list[dict], tools: list[dict]) -> dict:
    """Send one chat-completions request with tools; return the JSON response."""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 4096,
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


def run_agent(task: dict, project_root: Path) -> str:
    """Depth-limited agent loop. Returns the final summary string."""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    goal = task.get("goal", task.get("description", ""))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Goal: {goal}\n"
            f"Work in the project at: {project_root}\n"
            f"Task metadata: {json.dumps(task, default=str)}\n"
        )},
    ]

    for _step in range(1, MAX_STEPS + 1):
        reply = chat(messages, axm_tools.tool_definitions())
        choice = reply["choices"][0]
        msg = choice["message"]

        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": msg.get("tool_calls")})

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return msg.get("content") or "(no final content)"

        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            result = axm_tools.call_tool(name, args, project_root)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", name),
                "content": json.dumps(result, default=str),
            })

    return "# FAILED: reached MAX_STEPS without a final answer.\n"


# --------------------------------------------------------------------------- #
# Offline demo mode: verifies the axm-edit integration without an API key.
# --------------------------------------------------------------------------- #

def demo_mode(task: dict, project_root: Path) -> str:
    """Run a canned sequence through the axm-edit tools (no network)."""
    out = [f"# Summary for {task['name']}\n"]

    listing = axm_tools.call_tool("list_dir", {"max_depth": 1}, project_root)
    out.append(f"listed dir: {listing.get('data')}")

    created = axm_tools.call_tool(
        "batch_edit",
        {"operations": [
            {"op": "create", "file": "demo.md", "content": "# demo\n"},
            {"op": "create", "file": "src/gen.py", "content": "VALUE = 42\n"},
        ]},
        project_root,
    )
    out.append(f"batch_edit (atomic create x2): {created.get('data')}")

    if created.get("ok"):
        # Look at the authored file, then modify it in a SECOND single batch.
        _ = axm_tools.call_tool("read_file", {"file": "src/gen.py"}, project_root)
        second = axm_tools.call_tool(
            "batch_edit",
            {"operations": [
                {"op": "replace", "file": "src/gen.py",
                 "edits": [{"old": "VALUE = 42", "new": "VALUE = 43"}]},
            ]},
            project_root,
        )
        out.append(f"batch_edit (atomic replace): {second.get('data')}")

    out.append("\nDemo loop exercised axm-edit's atomic batch_edit end-to-end.")
    out.append("Run again with DEEPSEEK_API_KEY set to use the real agent loop.")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

def main():
    """Entrypoint: parse the task from argv and run demo or agent mode."""
    task = json.loads(sys.argv[1])
    project_root = Path(task.get("path", os.getcwd())).resolve()

    try:
        if os.environ.get("AGENT_DEMO") == "1" or not os.environ.get("DEEPSEEK_API_KEY"):
            print(demo_mode(task, project_root))
        else:
            print(run_agent(task, project_root))
    except Exception as e:
        print(f"# FAILED: {task.get('name', 'unknown')}\n")
        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)  # Killed immediately


if __name__ == "__main__":
    main()