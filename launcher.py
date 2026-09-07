"""Task-queue launcher that spawns ephemeral agent_worker processes.

Polls tasks.jsonl, runs one agent_worker.py subprocess per task under a hard
wall-clock timeout, and writes each worker's summary into outputs/.
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

def ensure_workers():
    """Create supporting files/dirs if missing."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(TASK_QUEUE):
        with open(TASK_QUEUE, 'w') as f:
            f.write("")
    if not os.path.exists(FAILURES_LOG):
        with open(FAILURES_LOG, 'w') as f:
            f.write("")

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
                print(f"Skipping malformed task line: {e}")
    return tasks

def main():
    """Run the launcher loop: pop queued tasks and spawn a worker for each."""
    ensure_workers()
    while True:
        tasks = load_tasks()

        if not tasks:
            print("No tasks. Sleeping...")
            time.sleep(60)
            continue

        # Pop the first task
        task = tasks.pop(0)
        # Write remaining tasks back to the queue
        with open(TASK_QUEUE, 'w') as f:
            for t in tasks:
                f.write(json.dumps(t) + "\n")

        # SPAWN THE EPHEMERAL AGENT
        print(f"Launching agent for: {task.get('name', task)}")
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
            print(f"Task {task['name']} timed out. Killing...")
            # Log the failure, move to next task.
            with open(FAILURES_LOG, 'a') as f:
                f.write(f"{task['name']} timed out\n")
        except FileNotFoundError:
            print("agent_worker.py not found. Exiting.")
            return

if __name__ == "__main__":
    main()