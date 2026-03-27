"""
Configuration module for Asana Export TUI.
Loads settings from .env, environment variables, or interactive prompt.
"""

import os
import sys
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
#  .env LOADER (no dependency required)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_dotenv(path: Path = None):
    """Load .env file into os.environ. Works without python-dotenv."""
    env_path = path or Path.cwd() / ".env"
    if not env_path.exists():
        return False
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            os.environ.setdefault(key, value)
    return True


# Load .env on import
_dotenv_found = _load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

BASE_URL             = "https://app.asana.com/api/1.0"
PAGE_LIMIT           = 100
RATE_LIMIT_SLEEP     = 0.35
MAX_SUBTASK_DEPTH    = 5
DOWNLOAD_ATTACHMENTS = os.getenv("ASANA_DOWNLOAD_ATTACHMENTS", "false").lower() == "true"
MAX_WORKERS          = int(os.getenv("ASANA_MAX_WORKERS", "4"))
WORKSPACE_FILTER     = os.getenv("ASANA_WORKSPACE_FILTER", "")
SKIP_ARCHIVED_PROJECTS = os.getenv("ASANA_SKIP_ARCHIVED", "false").lower() == "true"

EXPORTS_DIR          = Path.cwd() / "exports"
STATE_FILE           = Path.cwd() / "asana_export_state.json"

# Full opt_fields string for task fetches
TASK_OPT_FIELDS = ",".join([
    "gid", "name", "resource_type", "resource_subtype",
    "completed", "completed_at", "created_at", "modified_at",
    "due_on", "due_at", "start_on", "start_at",
    "assignee", "assignee.gid", "assignee.name", "assignee.email",
    "assignee_status",
    "parent", "parent.gid", "parent.name", "parent.resource_subtype",
    "notes",
    "num_hearts", "num_likes", "hearted", "liked",
    "actual_time_minutes",
    "permalink_url",
    "workspace", "workspace.gid", "workspace.name",
    "memberships", "memberships.project.gid", "memberships.project.name",
    "memberships.section.gid", "memberships.section.name",
    "followers", "followers.gid", "followers.name",
    "tags", "tags.gid", "tags.name",
    "num_subtasks",
    "projects", "projects.gid", "projects.name",
    "custom_fields",
    "custom_fields.gid", "custom_fields.name", "custom_fields.type",
    "custom_fields.resource_subtype", "custom_fields.display_value",
    "custom_fields.is_formula_field",
    "custom_fields.enum_value", "custom_fields.enum_value.gid",
    "custom_fields.enum_value.name", "custom_fields.enum_value.color",
    "custom_fields.multi_enum_values",
    "custom_fields.multi_enum_values.gid", "custom_fields.multi_enum_values.name",
    "custom_fields.number_value",
    "custom_fields.text_value",
    "custom_fields.date_value",
    "custom_fields.people_value", "custom_fields.people_value.name",
])

# ═══════════════════════════════════════════════════════════════════════════════
#  TOKEN MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def get_token() -> str:
    """Get Asana access token from env/.env or return empty string."""
    return os.getenv("ASANA_ACCESS_TOKEN", "").strip()


def save_token_to_env(token: str):
    """Save (or update) ASANA_ACCESS_TOKEN in .env file."""
    env_path = Path.cwd() / ".env"
    lines = []
    found = False
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                if line.strip().startswith("ASANA_ACCESS_TOKEN"):
                    lines.append(f"ASANA_ACCESS_TOKEN='{token}'\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"ASANA_ACCESS_TOKEN='{token}'\n")
    with open(env_path, "w") as f:
        f.writelines(lines)
    os.environ["ASANA_ACCESS_TOKEN"] = token


def dotenv_found() -> bool:
    return _dotenv_found
