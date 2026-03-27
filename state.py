"""
State persistence module for Asana Export TUI.
Saves/loads checkpoint state to enable resume after interruption.
"""

import json
import os
from pathlib import Path
from datetime import datetime

from config import STATE_FILE

# ═══════════════════════════════════════════════════════════════════════════════
#  STATE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════
#
# {
#   "version": 1,
#   "run_id": "20260327_181916",
#   "export_dir": "exports/20260327_181916",
#   "started_at": "2026-03-27T18:19:16Z",
#   "updated_at": "2026-03-27T18:25:00Z",
#   "status": "in_progress",            # in_progress | paused | completed
#   "phase": "tasks",                   # workspaces | projects | tasks
#   "completed_workspaces": ["gid1"],
#   "completed_projects": ["gid2", "gid3"],
#   "completed_tasks": ["gid4"],
#   "current_workspace_gid": "gid1",
#   "current_project_gid": "gid2",
#   "master_data": { ... },             # partial accumulated export
#   "stats": {
#       "workspaces_total": 2,
#       "projects_total": 10,
#       "tasks_total": 200,
#       "tasks_done": 50
#   }
# }


def new_state(run_id: str, export_dir: str) -> dict:
    """Create a fresh state dict."""
    return {
        "version": 1,
        "run_id": run_id,
        "export_dir": export_dir,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "status": "in_progress",
        "phase": "workspaces",
        "completed_workspaces": [],
        "completed_projects": [],
        "completed_tasks": [],
        "current_workspace_gid": None,
        "current_project_gid": None,
        "master_data": None,
        "stats": {
            "workspaces_total": 0,
            "projects_total": 0,
            "tasks_total": 0,
            "tasks_done": 0,
            "subtasks_done": 0,
        },
    }


def save_state(state: dict):
    """Atomically save state to disk (write .tmp then rename)."""
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)
    tmp.rename(STATE_FILE)


def load_state() -> dict | None:
    """Load state from disk, or None if no state file exists."""
    if not STATE_FILE.exists():
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != 1:
            return None
        return data
    except (json.JSONDecodeError, KeyError):
        return None


def clear_state():
    """Remove state file for fresh start."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def has_resumable_state() -> bool:
    """Check if there's a valid in-progress/paused state to resume."""
    state = load_state()
    if state is None:
        return False
    return state.get("status") in ("in_progress", "paused")


def get_state_summary() -> dict | None:
    """Return a brief summary of the state for display."""
    state = load_state()
    if state is None:
        return None
    return {
        "run_id": state.get("run_id", "?"),
        "started_at": state.get("started_at", "?"),
        "updated_at": state.get("updated_at", "?"),
        "status": state.get("status", "?"),
        "phase": state.get("phase", "?"),
        "stats": state.get("stats", {}),
    }
