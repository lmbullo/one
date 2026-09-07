Done. Both files were created at the repository root in a single atomic `batch_edit` (2 operations, no other file touched).

**What I changed**
- Created `README.md` — concise, to the point:
  - **What it is:** a queue-driven runner (`launcher.py` → ephemeral `agent_worker.py` per task) where the agent edits files via axm-edit tools in one atomic `batch_edit`; offline demo mode when no API key.
  - **Install:** `python -m venv .venv`, `.venv/bin/pip install axm-edit httpx`, `cp .env.example .env`.
  - **Run:** `.venv/bin/python launcher.py`.
  - **Add tasks:** append one JSON object per line to `tasks.jsonl`, with documented `name` / `goal` / `path` fields and an example.
- Created `SECURITY.md` — tailored to an AI agent project:
  - **Reporting vulnerabilities:** private reporting only (no public issues), with details to include and expected acknowledgment timeline.
  - **Key handling:** `DEEPSEEK_API_KEY` via env/`.env` only, `.env` gitignored, precedence/placeholder-replacement behavior, `chmod 600`, rotation, HTTPS-only egress, no key logging.
  - **Safe defaults:** offline demo when no key, step/timeout bounds (`AGENT_MAX_STEPS`, `AGENT_HTTP_TIMEOUT`, 30-min hard kill), scoping agents to trusted `path` roots, atomic `batch_edit`/`batch_rollback`, and a warning that `run_command` executes code.

**Next steps:** none required — docs-only change. You could optionally verify rendering with `.venv/bin/python -c` or a markdown viewer, and confirm `git status` shows only the two new files.
