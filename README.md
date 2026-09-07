# one — Autonomous Agent Task Runner

A minimal, queue-driven runner for an autonomous AI coding agent.
`launcher.py` polls `tasks.jsonl`, spawns an **ephemeral** DeepSeek agent
(`agent_worker.py`) per task under a hard wall-clock timeout, and writes each
agent's final summary to `outputs/<name>_summary.md`.

The agent works through the **axm-edit** toolset — `list_dir`, `read_file`,
`search_files`, `run_command`, `batch_edit`, `batch_rollback` — and applies all
of its file changes in a single atomic `batch_edit` call. With no API key it runs
an offline demo that exercises the integration end-to-end.

## Install

```bash
python -m venv .venv
.venv/bin/pip install axm-edit httpx
cp .env.example .env    # then set DEEPSEEK_API_KEY=sk-...
```

## Run

```bash
.venv/bin/python launcher.py
```

`launcher.py` loops forever: it pops the first task off `tasks.jsonl`, runs a
worker for it (up to 30 min), writes the summary to `outputs/`, and sleeps when
the queue is empty. Run it under `nohup` or a service manager for a long-running
queue.

## Add a task

Append one JSON object per line to `tasks.jsonl` (any repo can be targeted —
point `path` at it):

```json
{"name": "fix-bug", "goal": "Find and fix the bug in src/app.py, then summarize.", "path": "/home/you/project"}
```

Fields:

- `name` (required) — used for the summary filename in `outputs/`.
- `goal` — the task to run; falls back to `description`.
- `path` — the project root the agent works in (defaults to this repo).
