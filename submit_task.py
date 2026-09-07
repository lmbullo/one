#!/usr/bin/env python3
"""Interactive task submission for the tasks.jsonl queue.

First asks for the task `name`, then the `goal` (and optionally the project
`path`), then APPENDS one JSON task line to tasks.jsonl. Already-queued tasks
are never overwritten.

Task format follows README.md:

    {"name": "...", "goal": "...", "path": "/home/you/project"}

    - name  : required, used for the summary filename in .outputs/.
    - goal  : the task to run; falls back to description.
    - path  : the project root the agent works in (defaults to this repo).
"""

import json
import sys
from pathlib import Path

TASK_QUEUE = Path(__file__).resolve().parent / "tasks.jsonl"
REPO_ROOT = Path(__file__).resolve().parent


def load_task_names() -> set:
    """Return names of tasks already in the queue (to warn on duplicates)."""
    names = set()
    if not TASK_QUEUE.exists():
        return names
    with TASK_QUEUE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                task = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = task.get("name")
            if name:
                names.add(name)
    return names


def ask(question: str, *, required: bool = False, default: str = "") -> str:
    """Prompt until a non-empty (or defaulted) answer is given."""
    while True:
        try:
            answer = input(question).strip()
        except EOFError:
            # End of input: fall back to the default, or abort if none.
            if default:
                answer = default
            else:
                print("\nInput closed; no task added.", file=sys.stderr)
                sys.exit(1)
        if not answer and default:
            answer = default
        if answer or not required:
            return answer
        print("This field is required; please enter a value.")


def main() -> int:
    print("Submit a new task to tasks.jsonl")
    print("--------------------------------")

    existing = load_task_names()
    name = ask("Task name: ", required=True)
    if name in existing:
        print(f"Note: a task named '{name}' is already queued.", file=sys.stderr)

    goal = ask("Task goal: ", required=True)

    path_default = str(REPO_ROOT)
    path = ask(
        f"Project path (Enter for {path_default}): ", default=path_default
    )

    task = {"name": name, "goal": goal, "path": path}

    # Append-only: never rewrite the queue, so pending tasks stay intact.
    with TASK_QUEUE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(task, ensure_ascii=False) + "\n")

    print(f"\nAdded task '{name}' to {TASK_QUEUE.name}:")
    print(json.dumps(task, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
