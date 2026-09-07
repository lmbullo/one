"""axm-edit adapter for the agent loop.

Wraps the axm-edit MCP tools as (1) JSON schemas the model can call, and
(2) a ``call_tool`` dispatcher that executes them against a project root.

The whole point: the agent gathers context with read/search/list/run and then
applies ALL of its file modifications in a SINGLE atomic ``batch_edit`` call
instead of touching files one at a time.
"""
from __future__ import annotations

import json
from pathlib import Path

from axm_edit.tools.batch_edit import BatchEditTool
from axm_edit.tools.batch_rollback import BatchRollbackTool
from axm_edit.tools.list_dir import ListDirTool
from axm_edit.tools.read_file import ReadFileTool
from axm_edit.tools.run_command import RunCommandTool
from axm_edit.tools.search_files import SearchFilesTool

# --------------------------------------------------------------------------- #
# Tool definitions (JSON schema) handed to the model for function calling.
# --------------------------------------------------------------------------- #

def _json_schema(name: str, description: str, required: list[str], props: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOL_SCHEMAS = [
    _json_schema(
        "list_dir",
        "List files and directories with metadata.",
        ["path"],
        {
            "path": {"type": "string", "description": "Project root directory."},
            "max_depth": {"type": "integer", "description": "Recursion depth; 1 = immediate children.", "default": 1},
        },
    ),
    _json_schema(
        "read_file",
        "Read file content with optional line-range.",
        ["path", "file"],
        {
            "path": {"type": "string", "description": "Project root directory."},
            "file": {"type": "string", "description": "Path relative to project root."},
            "start_line": {"type": "integer", "description": "Optional 1-indexed start line (inclusive)."},
            "end_line": {"type": "integer", "description": "Optional 1-indexed end line (inclusive)."},
        },
    ),
    _json_schema(
        "search_files",
        "Grep-like search across project files.",
        ["path", "pattern"],
        {
            "path": {"type": "string", "description": "Project root directory."},
            "pattern": {"type": "string", "description": "Search string or regex."},
            "is_regex": {"type": "boolean", "description": "Treat pattern as regex.", "default": False},
            "include": {"type": "array", "items": {"type": "string"},
                        "description": "Glob filters, e.g. ['*.py']."},
        },
    ),
    _json_schema(
        "run_command",
        "Execute a shell command with timeout and output truncation.",
        ["path", "command"],
        {
            "path": {"type": "string", "description": "Project root directory."},
            "command": {"type": "string", "description": "Shell command string."},
            "cwd": {"type": "string", "description": "Working directory, relative to root."},
            "timeout": {"type": "integer", "description": "Timeout in seconds.", "default": 30},
        },
    ),
    _json_schema(
        "batch_edit",
        "Apply replace/create/delete file operations atomically. "
        "PREFER THIS: accumulate ALL edits and apply them in one call.",
        ["path"],
        {
            "path": {"type": "string", "description": "Project root directory."},
            "operations": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"type": "object",
                         "properties": {"op": {"const": "replace"},
                                        "file": {"type": "string"},
                                        "edits": {"type": "array", "items": {
                                            "type": "object",
                                            "properties": {"line": {"type": "integer", "description": "Optional 1-indexed line hint."},
                                                           "old": {"type": "string", "description": "Expected existing content."},
                                                           "new": {"type": "string", "description": "Replacement content."}},
                                            "required": ["old", "new"]}}},
                         "required": ["op", "file", "edits"]},
                        {"type": "object",
                         "properties": {"op": {"const": "create"},
                                        "file": {"type": "string"},
                                        "content": {"type": "string"},
                                        "overwrite": {"type": "boolean", "default": False}},
                         "required": ["op", "file", "content"]},
                        {"type": "object",
                         "properties": {"op": {"const": "delete"},
                                        "file": {"type": "string"}},
                         "required": ["op", "file"]},
                    ]
                },
            },
            "lint": {"type": "boolean", "description": "Run ruff --fix on changed Python files.", "default": True},
        },
    ),
    _json_schema(
        "batch_rollback",
        "Restore the exact paths a prior batch_edit touched, using its checkpoint.",
        ["path", "checkpoint"],
        {
            "path": {"type": "string", "description": "Project root directory."},
            "checkpoint": {"type": "string", "description": "Snapshot payload from the batch_edit response."},
        },
    ),
]

TOOLS_BY_NAME = {s["function"]["name"]: s for s in TOOL_SCHEMAS}


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #

class _WrappedTool:
    """Minimal adapter exposing .execute(**kw) -> (success, data_or_error)."""

    def __init__(self, tool):
        self._tool = tool

    def __call__(self, **kw) -> dict:
        try:
            result = self._tool.execute(**kw)
            if getattr(result, "success", False):
                return {"ok": True, "data": result.data}
            return {"ok": False, "error": getattr(result, "error", "unknown"),
                    "hint": getattr(result, "hint", None)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


_IMPLEMENTATIONS = {
    "list_dir": _WrappedTool(ListDirTool()),
    "read_file": _WrappedTool(ReadFileTool()),
    "search_files": _WrappedTool(SearchFilesTool()),
    "run_command": _WrappedTool(RunCommandTool()),
    "batch_edit": _WrappedTool(BatchEditTool()),
    "batch_rollback": _WrappedTool(BatchRollbackTool()),
}


def call_tool(name: str, arguments: dict, project_root: Path | str) -> dict:
    """Execute an axm-edit tool. Injects ``path`` if the model omitted it."""
    if name not in _IMPLEMENTATIONS:
        return {"ok": False, "error": f"Unknown tool: {name}"}
    kw = dict(arguments or {})
    kw.setdefault("path", str(project_root))
    return _IMPLEMENTATIONS[name](**kw)


def tool_definitions() -> list[dict]:
    """Return the JSON tool schemas the agent model is allowed to call."""
    return list(TOOL_SCHEMAS)
