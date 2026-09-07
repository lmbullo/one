Done. All changes verified.

## Summary

**`launcher.py` — now silent, logs to project-root `logs` file**
- Replaced all console `print(...)` calls (worker-launch notices, sleep notices, timeout/fatal errors, malformed-task warnings) with a new `_log()` helper.
- `_log()` appends timestamped lines to `./logs` (project root, via `LOG_FILE = "logs"`), so the launcher emits nothing to stdout/stderr.
- `ensure_workers()` now also creates an empty `logs` file if missing, matching the pattern used for `tasks.jsonl` and `failures.log`.
- Updated the module docstring to describe the silent/log-to-file behavior.

**`.gitignore` — ignores the new log file**
- Added `/logs` (root-anchored) under the `# Logs` section, so `./logs` is never committed.

**Verification**
- `py_compile` passes.
- `git check-ignore -v logs` → matched by `.gitignore:15:/logs`.
- Smoke test: ran `.venv/bin/python launcher.py` for ~5s — produced **no console output** and wrote `2026-09-07 02:04:10 No tasks. Sleeping...` to `./logs`.

**Note / next steps**
- `README.md` already showed as modified in `git status` before my edits — I did not touch it. You may want to update its "Run" section to mention logs now go to `./logs` (e.g., under `nohup`).
- The `logs` file created by my smoke test is ignored by git, so no cleanup needed, but you can delete it if you want a fresh start.
