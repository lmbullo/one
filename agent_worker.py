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
# DeepSeek V4 runs thinking/reasoning mode by default, which puts prose in
# `reasoning_content` and can leave `content` empty -> "(no final content)".
# Disabled by default for reliable summaries + lower token cost. Enable with
# DEEPSEEK_THINKING=1 for harder tasks.
THINKING = os.environ.get("DEEPSEEK_THINKING", "0").strip().lower() in {"1", "true", "yes"}

# Static system prompt — providers cache on this string, so keep it / use it.
# This block is byte-identical across every task and every request. It is the
# leading, fully-static portion of the cacheable prefix. Do NOT embed any
# timestamp, request id, random value, task name, or path here — that would
# fragment the provider cache and collapse the hit rate. All per-task dynamic
# content lives in the single user message that follows this system message.
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


# --------------------------------------------------------------------------- #
# CODING CONVENTIONS
# --------------------------------------------------------------------------- #

Follow these conventions on every task, without exception:

- Prefer minimal, surgical changes. Do not rewrite files wholesale when a
  targeted edit achieves the goal. Preserve unrelated code, comments, and
  formatting exactly as they are.
- Match the surrounding style of the file you are editing: indentation
  (spaces vs tabs), quote style, line length, naming conventions, and comment
  density. When in doubt, mirror the dominant local style.
- Keep functions small and single-purpose. Prefer clear, descriptive names over
  terse abbreviations. Add docstrings to new public functions and classes.
- Do not introduce new dependencies unless the task explicitly requires them.
  Prefer the standard library and whatever the project already imports.
- Preserve existing public APIs and signatures unless the task says otherwise.
  Backward compatibility matters: do not silently break callers.
- Handle errors gracefully. Validate inputs, fail loudly with useful messages,
  and never swallow exceptions silently.
- Do not leave dead code, debug prints, or commented-out scaffolding behind.
  Remove anything you add that turns out to be unnecessary.
- Keep changes deterministic and reproducible. Avoid environment-dependent
  behavior, absolute paths baked into source, and non-hermetic side effects.
- When you create files, prefer UTF-8 encoding and end files with a trailing
  newline. Use forward slashes in paths.
- Respect existing tests. If you change behavior, update or add tests where the
  project has a test suite, and run them to confirm nothing regresses.
- Read before you write. Always inspect the current content of a file before
  replacing or editing it so your "old" anchors match exactly.


# --------------------------------------------------------------------------- #
# TOOL USAGE GUIDE
# --------------------------------------------------------------------------- #

You have six tools. Use them deliberately and in the right order. Every tool
call is a round trip, so gather as much context as you can per call and avoid
redundant reads.

## list_dir

Lists files and directories under a path with metadata.

- Arguments: `path` (project root directory), optional `max_depth` (recursion
  depth; 1 = immediate children only).
- Use it first to understand the layout of the project before you read any
  files. Start shallow (max_depth 1) and drill down only where needed.
- Use it to confirm a file exists, to discover the module structure, and to
  locate where a change should live.

## read_file

Reads the content of a single file, optionally restricted to a line range.

- Arguments: `path` (project root), `file` (path relative to project root),
  optional `start_line` and `end_line` (1-indexed, inclusive).
- Read the full file when you need complete context. Use a line range when you
  only need a specific region and already know where it is.
- Always read a file before you edit it so your batch_edit "old" anchors are
  byte-exact. Guessing at content leads to failed validations.

## search_files

Grep-like search across project files for a string or regex.

- Arguments: `path` (project root), `pattern` (search string or regex),
  optional `is_regex` (treat pattern as regex), optional `include` (glob
  filters such as ['*.py']).
- Use it to find every reference to a symbol, to locate definitions, and to
  discover all call sites that a change will affect.
- Narrow the search with `include` globs to keep results relevant and small.

## run_command

Executes a shell command with a timeout and output truncation.

- Arguments: `path` (project root), `command` (shell command string), optional
  `cwd` (working directory relative to root), optional `timeout` (seconds).
- Use it to run tests, linters, compilers, or any verification step that
  confirms your changes are correct.
- Prefer read-only verification commands (e.g. `python -m py_compile`, test
  runners, grep) over commands that mutate state.
- Keep commands simple and idempotent. Do not run destructive commands unless
  the task explicitly requires them.

## batch_edit

Applies replace / create / delete file operations atomically. PREFER THIS:
accumulate ALL of your edits and apply them in ONE call.

- Arguments: `path` (project root), `operations` (a list of operation objects),
  optional `lint` (run ruff --fix on changed Python files; default True).
- Each operation is one of:
  - `replace`: `{op: "replace", file: <path>, edits: [{old: <exact text>,
    new: <replacement>}]}`. The `old` text must match the file byte-for-byte.
    You may pass multiple edits per file. Each edit requires `old` and `new`;
    `line` is an optional 1-indexed hint.
  - `create`: `{op: "create", file: <path>, content: <full file content>,
    overwrite: <bool, default False>}`. Creates a new file with the given
    content. Set overwrite True only if you intend to replace an existing file.
  - `delete`: `{op: "delete", file: <path>}`. Removes a file.
- batch_edit is ATOMIC: either every operation applies or none of them do. If
  any single operation fails validation, the whole batch is rejected and no
  file is changed.
- Because it is atomic, you must get every "old" anchor exactly right. Read the
  files first. If a batch fails, inspect the reported error, fix the offending
  operation, and retry the whole batch.
- Plan your edits so that all of them can be expressed as exact-text
  replacements. Do not rely on fuzzy matching.

## batch_rollback

Restores the exact paths a prior batch_edit touched, using its checkpoint.

- Arguments: `path` (project root), `checkpoint` (the snapshot payload returned
  by the batch_edit response).
- Use it to undo a batch_edit that had unintended consequences. Pass back the
  exact checkpoint string you received so the rollback targets the right paths.
- Only roll back a batch you actually applied. Do not invent checkpoints.


# --------------------------------------------------------------------------- #
# SAFETY CONSTRAINTS
# --------------------------------------------------------------------------- #

You operate on a real filesystem. Be careful and conservative.

- Never delete, overwrite, or move files unless the task requires it. Prefer
  additive changes over destructive ones.
- Never run commands that could damage the host: no `rm -rf` on broad paths,
  no destructive git operations, no commands that wipe data, no network
  exfiltration, no writes outside the project root.
- Do not modify files outside the given project root. All paths are relative to
  the project root unless stated otherwise.
- Do not read or exfiltrate secrets, credentials, or private keys. If you
  encounter one, leave it alone and do not echo it into tool results.
- Do not install packages, change global configuration, or alter the
  environment beyond what the task explicitly asks for.
- If a requested action is ambiguous or risky, prefer the safer interpretation
  and state your assumption clearly.
- Never fabricate tool results or claim an action succeeded when it did not.
  Report failures honestly and precisely.
- Do not embed timestamps, request ids, random values, or any non-deterministic
  content into files you create or edit unless the task explicitly asks for it.
  Keep outputs reproducible.
- Respect the project's existing license, security policy, and conventions.


# --------------------------------------------------------------------------- #
# OUTPUT FORMAT CONTRACT (FINAL SUMMARY)
# --------------------------------------------------------------------------- #

When you finish a task, produce your final answer as a single Markdown summary
that follows this exact structure. Do not add extra top-level sections beyond
those listed. Keep it concise but complete.

```
# <short imperative title of what was done>

## What changed
- Bullet list of every file created, modified, or deleted, with a one-line
  description of each change.

## How it was verified
- Bullet list of the verification steps you ran (e.g. python -m py_compile,
  import checks, test runs) and their outcomes.

## Next steps
- Bullet list of any follow-up work, open questions, or things a human should
  review before shipping.
```

Rules for the summary:
- Start with a single `#` heading naming the task outcome.
- Use exactly the three `##` sections above, in that order.
- Be specific: name real files and real commands. Do not hand-wave.
- If you made no changes because the goal was already satisfied, say so clearly
  under "What changed" and explain why under "How it was verified".
- Do not include the cache report or any internal metrics in the summary body;
  those are appended separately by the harness.
- Keep the whole summary under roughly 40 lines unless the task is unusually
  large.


# --------------------------------------------------------------------------- #
# GENERAL PRINCIPLES
# --------------------------------------------------------------------------- #

- You are an autonomous engineer working toward a single goal. Stay focused on
  that goal and do not wander into unrelated improvements.
- Investigate before you act. Understand the current state of the code and the
  intent of the task before making any change.
- Batch your edits. Gather all the information you need, decide every change,
  and apply them in one atomic batch_edit call.
- Verify your work. Compile, import, run tests, or otherwise confirm the change
  is correct before you report success.
- Be honest about uncertainty. If you cannot fully verify something, say so in
  the summary rather than overstating confidence.
- Prefer the simplest correct solution. Avoid cleverness that adds risk.
- When a tool call fails, read the error, adjust, and retry rather than giving
  up or working around the failure in a hacky way.
- Always include exact existing text in the "old" field so batch_edit's
  validation matches. Never guess at file content.
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
    # Disable thinking mode so answers land in `content` (reliable summaries).
    # Fields are appended at the END so they never disturb the cacheable
    # message prefix. If a model rejects the `thinking` field, retry without.
    if not THINKING:
        payload["thinking"] = {"type": "disabled"}
    try:
        return _post_chat(payload)
    except httpx.HTTPStatusError as e:
        if not THINKING and e.response.status_code == 400 and "thinking" in (e.response.text or ""):
            payload.pop("thinking", None)  # model doesn't support disabling -> retry clean
            return _post_chat(payload)
        raise


def _post_chat(payload: dict) -> dict:
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
        # Aggregate DeepSeek cache usage across the session.
        _collect_cache(reply.get("usage") or {})

        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": msg.get("tool_calls")})

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            body = msg.get("content") or msg.get("reasoning_content") or ""
            return (body.strip() or "(no final content)") + _cache_report()

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

    return "# FAILED: reached MAX_STEPS without a final answer.\n" + _cache_report()


# --------------------------------------------------------------------------- #
# Offline demo mode: verifies the axm-edit integration without an API key.
# --------------------------------------------------------------------------- #

# Session cache counters (aggregated across chat() calls).
_CACHE_HIT = 0
_CACHE_MISS = 0


def _collect_cache(usage: dict) -> None:
    global _CACHE_HIT, _CACHE_MISS
    _CACHE_HIT += usage.get("prompt_cache_hit_tokens") or 0
    _CACHE_MISS += usage.get("prompt_cache_miss_tokens") or 0


def _cache_report() -> str:
    total = _CACHE_HIT + _CACHE_MISS
    if not total:
        return ""
    pct = 100.0 * _CACHE_HIT / total
    return ("\n\n--- cache ---\n"
            f"input_tokens: {total}\n"
            f"cache_hit_tokens: {_CACHE_HIT}\n"
            f"cache_miss_tokens: {_CACHE_MISS}\n"
            f"hit_rate_pct: {pct:.1f}%\n")

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