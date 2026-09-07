# Security Policy

This project runs autonomous AI agents that can read files, search, execute shell
commands, and edit whatever project root each task points at. Treat it as a
remote-code-execution harness and apply the safe defaults below.

## Reporting vulnerabilities

Please do **not** open a public issue for security bugs. Report privately to the
maintainers (e.g. email or a private security-advisory channel), including:

- a description of the issue and its impact,
- steps to reproduce,
- any suggested fix.

We aim to acknowledge reports within a few business days and coordinate a
disclosure timeline with you.

## API key handling

- The DeepSeek key is read from `DEEPSEEK_API_KEY` (env var) or `.env`, which is
  **gitignored** — never commit it. `.env.example` documents the variable only.
- Precedence: explicit real environment variables win over `.env`; placeholder or
  stale-looking environment keys are replaced by `.env` values
  (see `_looks_placeholder` in `agent_worker.py`).
- Keep `.env` permissions tight (e.g. `chmod 600`) and rotate the key if it may
  have leaked. Scoped/limited keys are strongly recommended.
- Keys leave the machine only to the configured `DEEPSEEK_BASE_URL` over HTTPS;
  never log keys or echo `.env` contents.

## Safe defaults and operational guidance

- **No key, no network agent:** without `DEEPSEEK_API_KEY` the worker runs an
  offline demo only; it never calls the model API.
- **Bounded execution:** each agent is limited by `AGENT_MAX_STEPS` (default 25)
  and each HTTP call by `AGENT_HTTP_TIMEOUT` (default 120s); `launcher.py`
  hard-kills any worker exceeding its 30-minute budget and logs it to
  `failures.log`.
- **Scope to a trusted root:** workers operate inside the project root given in
  each task's `path`. Only queue tasks whose `goal` and `path` you trust.
- **Atomic edits:** the agent is instructed to apply all file modifications in a
  single `batch_edit`; `batch_rollback` restores the exact files a batch touched.
- **`run_command` executes code:** the agent can run shell commands with your
  user's access. Run this only on machines you control, and never feed it
  untrusted task definitions.
