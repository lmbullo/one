"""Task-queue launcher that spawns ephemeral agent_worker processes.

Polls tasks.jsonl, runs one agent_worker.py subprocess per task under a hard
wall-clock timeout, writes each worker's summary into outputs/, and runs
silently: launcher diagnostics go to a per-run timestamped file under `.logs/`.
"""

import subprocess
import json
import time
import os
import sys
from pathlib import Path

# Run the worker with the interpreter that has axm-edit/httpx installed.
# Prefer the project venv, fall back to the interpreter running this file.
_VENV_PY = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
WORKER_PY = str(_VENV_PY) if _VENV_PY.exists() else sys.executable
WORKER_PY = os.environ.get("AGENT_WORKER_PY", WORKER_PY)

TASK_QUEUE = "tasks.jsonl"  # One task per line
OUTPUT_DIR = "outputs"
FAILURES_LOG = "failures.log"
AGENT_TIMEOUT = 1800  # 30 minutes hard kill

# Per-run log: one timestamped file per launcher process, under .logs/.
# Stopping and restarting the launcher starts a fresh log for that run.
_RUN_TS = time.strftime("%Y%m%d-%H%M%S")
LOG_DIR = Path(".logs")
LOG_PATH = LOG_DIR / f"launcher-{_RUN_TS}.log"


def _log(message: str) -> None:
    """Append a timestamped line to the current run's log under `.logs/`."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")

def ensure_workers():
    """Create supporting files/dirs if missing."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(TASK_QUEUE):
        with open(TASK_QUEUE, 'w') as f:
            f.write("")
    if not os.path.exists(FAILURES_LOG):
        with open(FAILURES_LOG, 'w') as f:
            f.write("")
    LOG_DIR.mkdir(parents=True, exist_ok=True)

def load_tasks():
    """Return tasks as a list of dicts. Tolerates blank/malformed lines."""
    tasks = []
    with open(TASK_QUEUE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                tasks.append(json.loads(line))
            except json.JSONDecodeError as e:
                _log(f"Skipping malformed task line: {e}")
    return tasks

def main():
    """Run the launcher loop: pop queued tasks and spawn a worker for each."""
    ensure_workers()
    _log(f"Launcher started (log: {LOG_PATH.name}, queue: {TASK_QUEUE})")
    while True:
        tasks = load_tasks()

        if not tasks:
            _log("No tasks. Sleeping...")
            time.sleep(60)
            continue

        # Pop the first task
        task = tasks.pop(0)
        # Write remaining tasks back to the queue
        with open(TASK_QUEUE, 'w') as f:
            for t in tasks:
                f.write(json.dumps(t) + "\n")

        # SPAWN THE EPHEMERAL AGENT
        _log(f"Launching agent for: {task.get('name', task)}")
        try:
            result = subprocess.run(
                [WORKER_PY, "agent_worker.py", json.dumps(task)],
                timeout=AGENT_TIMEOUT,
                capture_output=True,
                text=True
            )
            # Write the output summary
            summary = result.stdout
            if result.returncode != 0:
                summary += f"\n\n[launcher] worker exited with code {result.returncode}\n"
                summary += f"[stderr]\n{result.stderr}\n"
            with open(os.path.join(OUTPUT_DIR, f"{task['name']}_summary.md"), 'w') as f:
                f.write(summary)

        except subprocess.TimeoutExpired:
            _log(f"Task {task['name']} timed out. Killing...")
            # Log the failure, move to next task.
            with open(FAILURES_LOG, 'a') as f:
                f.write(f"{task['name']} timed out\n")
        except FileNotFoundError:
            _log("agent_worker.py not found. Exiting.")
            return

if __name__ == "__main__":
    main()