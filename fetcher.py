"""
Concurrent data fetcher for Asana Export TUI.
All API calls live here. Uses ThreadPoolExecutor for parallel task enrichment.
"""

import re
import time
import threading
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    BASE_URL, PAGE_LIMIT, RATE_LIMIT_SLEEP, MAX_SUBTASK_DEPTH,
    MAX_WORKERS, DOWNLOAD_ATTACHMENTS, TASK_OPT_FIELDS, WORKSPACE_FILTER,
    SKIP_ARCHIVED_PROJECTS,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  THREAD-SAFE HTTP CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

_session_local = threading.local()
_rate_semaphore = threading.Semaphore(MAX_WORKERS)
_token = ""


def init_session(token: str):
    """Initialize the token (must be called before fetching)."""
    global _token
    _token = token


def _get_session() -> requests.Session:
    """Get a thread-local requests session."""
    if not hasattr(_session_local, "session"):
        _session_local.session = requests.Session()
        _session_local.session.headers.update({
            "Authorization": f"Bearer {_token}",
            "Accept": "application/json",
            "Asana-Enable": "new_user_task_lists",
        })
    return _session_local.session


def _get(endpoint: str, params: dict = None, retries: int = 5) -> dict:
    """Rate-limited, retrying GET request."""
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    session = _get_session()
    for attempt in range(1, retries + 1):
        _rate_semaphore.acquire()
        try:
            time.sleep(RATE_LIMIT_SLEEP)
            r = session.get(url, params=params or {}, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 60))
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
        finally:
            _rate_semaphore.release()
    return {}


def get_all_pages(endpoint: str, params: dict = None) -> list:
    """Fetch all pages of a paginated Asana endpoint."""
    params = {**(params or {}), "limit": PAGE_LIMIT}
    results = []
    while True:
        data = _get(endpoint, params)
        results.extend(data.get("data", []))
        nxt = data.get("next_page")
        if not nxt or not nxt.get("offset"):
            break
        params["offset"] = nxt["offset"]
    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  FETCH HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_workspaces() -> list:
    ws = get_all_pages("workspaces", {"opt_fields": "gid,name,resource_type"})
    if WORKSPACE_FILTER:
        ws = [w for w in ws if w["name"] == WORKSPACE_FILTER]
    return ws


def fetch_projects(workspace_gid: str) -> list:
    projects = get_all_pages("projects", {
        "workspace": workspace_gid,
        "opt_fields": (
            "gid,name,notes,color,archived,public,created_at,modified_at,"
            "permalink_url,due_date,start_on,"
            "owner,owner.gid,owner.name,owner.email,"
            "team,team.gid,team.name,"
            "members,members.gid,members.name,members.email,"
            "custom_field_settings,custom_field_settings.custom_field.gid,"
            "custom_field_settings.custom_field.name,"
            "current_status,current_status.text,current_status.color,"
            "current_status.author,current_status.author.name,"
            "workspace,workspace.gid,workspace.name"
        ),
    })
    
    if SKIP_ARCHIVED_PROJECTS:
        projects = [p for p in projects if not p.get("archived", False)]
        
    return projects


def fetch_sections(project_gid: str) -> list:
    return get_all_pages(f"projects/{project_gid}/sections", {
        "opt_fields": "gid,name,created_at"
    })


def fetch_project_tasks(project_gid: str) -> list:
    return get_all_pages("tasks", {
        "project": project_gid,
        "opt_fields": TASK_OPT_FIELDS,
    })


def fetch_subtasks(task_gid: str) -> list:
    return get_all_pages(f"tasks/{task_gid}/subtasks", {
        "opt_fields": TASK_OPT_FIELDS,
    })


def fetch_stories(task_gid: str) -> list:
    return get_all_pages(f"tasks/{task_gid}/stories", {
        "opt_fields": (
            "gid,type,resource_subtype,text,created_at,"
            "created_by,created_by.gid,created_by.name"
        )
    })


def fetch_attachments_meta(task_gid: str) -> list:
    return get_all_pages(f"tasks/{task_gid}/attachments", {
        "opt_fields": "gid,name,created_at,host,size,download_url,view_url,resource_type"
    })


def fetch_dependencies(task_gid: str) -> list:
    return get_all_pages(f"tasks/{task_gid}/dependencies", {
        "opt_fields": "gid,name,resource_subtype,completed"
    })


def fetch_dependents(task_gid: str) -> list:
    return get_all_pages(f"tasks/{task_gid}/dependents", {
        "opt_fields": "gid,name,resource_subtype,completed"
    })


def download_attachment(att: dict, dest_dir: Path) -> str | None:
    """Download attachment binary to disk."""
    url = att.get("download_url")
    if not url:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-]", "_", att.get("name", att["gid"]))
    dest = dest_dir / safe
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
        return str(dest)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  TASK ENRICHMENT (with pause/stop support)
# ═══════════════════════════════════════════════════════════════════════════════

def enrich_task(
    task: dict,
    attachments_root: Path | None,
    depth: int = 0,
    pause_event: threading.Event = None,
    stop_event: threading.Event = None,
    subtask_callback=None,
) -> dict:
    """
    Fetch stories, attachments, dependencies, and subtasks for a task.
    pause_event: clear() to pause, set() to resume
    stop_event: set() to signal workers should stop
    subtask_callback: called with +1 for each subtask enriched
    """
    if stop_event and stop_event.is_set():
        return task

    # Honor pause
    if pause_event:
        pause_event.wait()

    gid = task["gid"]

    # Stories
    try:
        task["stories"] = fetch_stories(gid)
    except Exception:
        task["stories"] = []

    # Attachments
    try:
        atts = fetch_attachments_meta(gid)
        if DOWNLOAD_ATTACHMENTS and atts and attachments_root:
            task_dir = attachments_root / gid
            for att in atts:
                att["local_path"] = download_attachment(att, task_dir)
        task["attachments"] = atts
    except Exception:
        task["attachments"] = []

    # Dependencies / dependents
    try:
        task["dependencies"] = fetch_dependencies(gid)
        task["dependents"] = fetch_dependents(gid)
    except Exception:
        task["dependencies"] = []
        task["dependents"] = []

    # Subtasks (recursive)
    if task.get("num_subtasks", 0) > 0 and depth < MAX_SUBTASK_DEPTH:
        try:
            raw_subtasks = fetch_subtasks(gid)
            enriched_subs = []
            for st in raw_subtasks:
                if stop_event and stop_event.is_set():
                    break
                enriched_subs.append(
                    enrich_task(st, attachments_root, depth + 1,
                                pause_event, stop_event, subtask_callback)
                )
                if subtask_callback:
                    subtask_callback(1)
            task["subtasks"] = enriched_subs
        except Exception:
            task["subtasks"] = task.get("subtasks", [])
    else:
        task["subtasks"] = task.get("subtasks", [])

    return task


def enrich_tasks_concurrent(
    tasks: list,
    attachments_root: Path | None,
    pause_event: threading.Event,
    stop_event: threading.Event,
    task_callback=None,
    subtask_callback=None,
) -> list:
    """
    Enrich a list of tasks concurrently using ThreadPoolExecutor.
    task_callback: called with (task_dict) after each task completes
    subtask_callback: called with (count) for subtask progress
    """
    enriched = [None] * len(tasks)

    def _worker(idx, task):
        result = enrich_task(
            task, attachments_root, 0,
            pause_event, stop_event, subtask_callback,
        )
        if task_callback:
            task_callback(result)
        return idx, result

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_worker, i, t): i
            for i, t in enumerate(tasks)
        }
        for future in as_completed(futures):
            if stop_event.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
                break
            try:
                idx, result = future.result()
                enriched[idx] = result
            except Exception:
                idx = futures[future]
                enriched[idx] = tasks[idx]
                enriched[idx]["_enrichment_error"] = True

    return [t for t in enriched if t is not None]
