All docstrings are in place and verified. Done.

## Summary

Added documentation-only changes (no behavior, imports, or logic touched) across the three files, applied in a **single atomic `batch_edit`** (6 operations):

**launcher.py**
- Added module-level docstring at the top describing the task-queue launcher role.
- Added docstring to `main()`.

**agent_worker.py**
- Added module-level docstring describing the ephemeral agent process.
- Added docstrings to `chat()` and `main()` (module already documented elsewhere had `run_agent`/`demo_mode` docstrings intact).

**axm_tools.py** (module docstring already present)
- Added a docstring to `tool_definitions()` — the only remaining public function lacking one. (`_json_schema` and `_WrappedTool` are private; the class already had a docstring.)

**Verification**
- Read back each edited region to confirm placement is correct (docstrings first, before imports/defs).
- `python3 -m py_compile` passed for all three.
- Real imports with the project venv (`.venv/bin/python`): `import launcher`, `import axm_tools`, and `import agent_worker` all succeed — the earlier system-`python3` failures were only due to missing third-party packages (`axm_edit`, `httpx`), which the venv provides.

Next steps: none required; the change is docs-only. You can run `.venv/bin/python launcher.py` or the agent demo as before.
