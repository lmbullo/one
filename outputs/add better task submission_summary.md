Everything is complete and verified. Here's a summary:

## What I changed

**Created `submit_task.py`** — an interactive task submitter for the queue:

1. **Asks for the task `name` first** (required; empty input is rejected and it re-prompts).
2. **Asks for the `goal`** (required).
3. Optionally asks for the project **`path`**, defaulting to the repo root (matching README's format where `path` defaults to this repo; typing just Enter or ending input uses the default).
4. **Appends** one JSON line to `tasks.jsonl` in the exact README format — `{"name": ..., "goal": ..., "path": ...}` — via append-mode, so already-queued tasks are **never overwritten**.

Nice touches:
- Warns (to stderr, doesn't block) if a task with the same name is already queued.
- Tolerates a missing/empty `tasks.jsonl` and skips malformed existing lines when scanning for duplicate names.
- Aborts cleanly (exit 1, no partial write) if input is closed while a required field is still unanswered.
- Resolves `tasks.jsonl` relative to the script, so it works from any working directory and `ensure_ascii=False` keeps non-ASCII names readable.

**Updated `README.md`** — the "Add a task" section now documents the interactive submitter (`.venv/bin/python submit_task.py`) after the manual-append example and field list.

## Verification
Tested the script end-to-end (in temp dirs, never touching the real queue) and confirmed:
- fresh append writes the correct README-format line,
- appending preserves pre-existing queued tasks (append-only),
- duplicate-name warning fires on stderr while still appending,
- empty required answers retry instead of being accepted, and EOF on a required field aborts without writing.

`tasks.jsonl` remains empty/unmodified and no temporary files were left in the repo.

**Next step:** run `.venv/bin/python submit_task.py` (or `python3 submit_task.py`) and enter a name + goal when you want to queue a task.
