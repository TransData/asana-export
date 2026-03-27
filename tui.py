"""
Rich TUI for Asana Export.
Main menu, animated progress bars, pause/resume/stop controls.
"""

import re
import csv
import json
import sys
import signal
import threading
import time
import logging
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.progress import (
    Progress, BarColumn, TextColumn, SpinnerColumn,
    TimeElapsedColumn, MofNCompleteColumn, TaskProgressColumn,
)
from rich.style import Style
from rich.live import Live
from rich.layout import Layout
from rich.columns import Columns
from rich import box

import config
from config import MAX_SUBTASK_DEPTH
import state
import fetcher

console = Console()

# ═══════════════════════════════════════════════════════════════════════════════
#  PIP-STYLE PROGRESS BAR
# ═══════════════════════════════════════════════════════════════════════════════

class PipStyleColumn(BarColumn):
    """Progress bar mimicking pip's style: ━━━━━━━━━━━━━━━╸━━━━━━━━"""

    def __init__(self, bar_width=40, **kwargs):
        super().__init__(bar_width=bar_width, **kwargs)

    def render(self, task):
        completed = task.completed
        total = task.total or 1
        ratio = min(completed / total, 1.0)

        bar_width = self.bar_width or 40
        filled = int(bar_width * ratio)
        empty = bar_width - filled

        bar = Text()

        # Filled portion — bright green thick dash
        if filled > 0:
            bar.append("━" * filled, style=Style(color="#00e676"))

        # Leading edge — half-filled indicator
        if filled < bar_width:
            if filled > 0:
                bar.append("╸", style=Style(color="#00e676"))
                empty -= 1
            # Empty portion — dim dark dash
            if empty > 0:
                bar.append("━" * empty, style=Style(color="#333333"))

        return bar


# ═══════════════════════════════════════════════════════════════════════════════
#  LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════════════

log = logging.getLogger("asana_export")
log.setLevel(logging.DEBUG)

# Suppress logs to console (Rich handles display)
_null_handler = logging.NullHandler()
log.addHandler(_null_handler)


def setup_file_logging(export_dir: Path):
    """Add a file handler that writes to exports/<run_id>/export.log."""
    # Remove old file handlers
    for h in log.handlers[:]:
        if isinstance(h, logging.FileHandler):
            log.removeHandler(h)

    log_path = export_dir / "export.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    log.addHandler(fh)
    return log_path


# ═══════════════════════════════════════════════════════════════════════════════
#  BANNER
# ═══════════════════════════════════════════════════════════════════════════════

BANNER = r"""
[bold #00e5ff]    ╔═══════════════════════════════════════════════════╗
    ║  [bold #2196f3]█▀▀█ █▀▀ █▀▀█ █▀▀▄ █▀▀█   ╔═╗ ╔╗╔ ╔═╗ ╔═╗[/]  ║
    ║  [bold #2196f3]█▄▄█ ▀▀█ █▄▄█ █  █ █▄▄█   ╠═╝ ║║║ ╠═╝ ╠═╝[/]  ║
    ║  [bold #2196f3]▀  ▀ ▀▀▀ ▀  ▀ ▀  ▀ ▀  ▀   ╩   ╝╚╝ ╩   ╩[/]    ║
    ║                                                   ║
    ║  [dim #81d4fa]Full Export Tool with Resume & TUI[/]              ║
    ╚═══════════════════════════════════════════════════╝[/]
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN MENU
# ═══════════════════════════════════════════════════════════════════════════════

def show_main_menu():
    """Display main menu and return user choice."""
    console.clear()
    console.print(BANNER)

    # Token status
    token = config.get_token()
    if token:
        masked = token[:8] + "..." + token[-4:]
        console.print(f"  [dim green]✓ Token loaded:[/] [dim]{masked}[/]\n")
    else:
        console.print("  [dim red]✗ No token found[/]\n")

    # Resume status
    summary = state.get_state_summary()
    resume_available = summary is not None and summary.get("status") in ("in_progress", "paused")

    table = Table(
        show_header=False, box=box.ROUNDED,
        border_style="#2196f3", width=50,
        padding=(0, 2),
    )
    table.add_column("key", style="bold #00e5ff", width=6, justify="center")
    table.add_column("action", style="white")

    table.add_row("1", "🚀  Fresh Start")
    if resume_available:
        stats = summary.get("stats", {})
        resume_desc = (
            f"📂  Resume Export  [dim]({stats.get('tasks_done', 0)}"
            f"/{stats.get('tasks_total', '?')} tasks done)[/]"
        )
        table.add_row("2", resume_desc)
    else:
        table.add_row("2", "[dim]📂  Resume Export  (no data)[/]")

    table.add_row("3", "⚙️   Configuration")
    table.add_row("4", "🚪  Exit")

    console.print(table)
    console.print()

    choice = Prompt.ask(
        "[bold #2196f3]Select option[/]",
        choices=["1", "2", "3", "4"],
        default="1",
    )
    return choice, resume_available


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION MENU
# ═══════════════════════════════════════════════════════════════════════════════

def show_config_menu():
    """Show configuration screen."""
    console.clear()
    console.print("\n[bold #2196f3]⚙️  Configuration[/]\n")

    token = config.get_token()
    if token:
        masked = token[:8] + "..." + token[-4:]
        console.print(f"  Current token: [dim]{masked}[/]")
    else:
        console.print("  [yellow]No token configured[/]")

    console.print(f"  .env file: [dim]{'found' if config.dotenv_found() else 'not found'}[/]")
    console.print(f"  Workers: [dim]{config.MAX_WORKERS}[/]")
    console.print(f"  Workspace filter: [dim]{config.WORKSPACE_FILTER or '(all)'}[/]\n")

    if Confirm.ask("[#2196f3]Set a new token?[/]", default=False):
        new_token = Prompt.ask("[#00e5ff]Enter Asana Personal Access Token[/]")
        if new_token.strip():
            config.save_token_to_env(new_token.strip())
            console.print("[green]✓ Token saved to .env[/]\n")
        else:
            console.print("[yellow]Skipped (empty)[/]\n")

    Prompt.ask("[dim]Press Enter to return to menu[/]", default="")


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def _write_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _write_csv(path: Path, rows: list, fieldnames: list = None):
    if not rows:
        return
    fieldnames = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _count_nested(tasks: list, key: str) -> int:
    total = 0
    for t in tasks:
        total += len(t.get(key, []))
        total += _count_nested(t.get("subtasks", []), key)
    return total


def run_export(resume: bool = False):
    """Run the export with Rich progress bars and controls."""
    token = config.get_token()
    if not token:
        console.print("[bold red]No Asana token configured![/]")
        console.print("Use option [bold]3[/] (Configuration) to set your token.\n")
        Prompt.ask("[dim]Press Enter to return[/]", default="")
        return

    fetcher.init_session(token)

    # ── State setup ──────────────────────────────────────────────────────
    if resume:
        st = state.load_state()
        if st is None:
            console.print("[yellow]No resumable state found. Starting fresh.[/]\n")
            resume = False

    if not resume:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = config.EXPORTS_DIR / run_id
        export_dir.mkdir(parents=True, exist_ok=True)
        st = state.new_state(run_id, str(export_dir))
    else:
        export_dir = Path(st["export_dir"])
        export_dir.mkdir(parents=True, exist_ok=True)
        run_id = st["run_id"]

    log_path = setup_file_logging(export_dir)
    log.info(f"Starting export run. Output dir: {export_dir}")
    log.debug(f"Configuration: Workers={config.MAX_WORKERS}, "
              f"Attachments={config.DOWNLOAD_ATTACHMENTS}, "
              f"Skip Archived={config.SKIP_ARCHIVED_PROJECTS}, "
              f"Resume={resume}")

    projects_dir = export_dir / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir = (export_dir / "attachments") if config.DOWNLOAD_ATTACHMENTS else None

    completed_projects = set(st.get("completed_projects", []))
    completed_workspaces = set(st.get("completed_workspaces", []))

    # ── Control events ───────────────────────────────────────────────────
    pause_event = threading.Event()
    pause_event.set()  # Not paused initially
    stop_event = threading.Event()
    paused = False

    # ── Progress bars ────────────────────────────────────────────────────
    progress = Progress(
        SpinnerColumn(spinner_name="dots", style="#00e5ff"),
        TextColumn("[bold #2196f3]{task.description}[/]", justify="left"),
        PipStyleColumn(bar_width=35),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        refresh_per_second=8,
    )

    ws_task = progress.add_task("🏢 Workspaces", total=0)
    proj_task = progress.add_task("📁 Projects", total=0)
    task_task = progress.add_task("📋 Tasks", total=0)
    sub_task = progress.add_task("🔄 Subtasks", total=0, visible=True)

    # Lock for thread-safe progress updates
    progress_lock = threading.Lock()

    def on_task_done(task_dict):
        with progress_lock:
            progress.advance(task_task)

    def on_subtask_done(count):
        with progress_lock:
            progress.update(sub_task, advance=count)

    # ── Signal handler ───────────────────────────────────────────────────
    def sig_handler(signum, frame):
        stop_event.set()
        st["status"] = "paused"
        state.save_state(st)

    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, sig_handler)

    # ── Keyboard listener (non-blocking) ─────────────────────────────────
    def key_listener():
        """Listen for p/r/s keys in a background thread."""
        nonlocal paused
        import sys, tty, termios
        fd = sys.stdin.fileno()
        try:
            old_settings = termios.tcgetattr(fd)
        except termios.error:
            return  # Not a terminal
        try:
            tty.setcbreak(fd)
            while not stop_event.is_set():
                import select
                if select.select([sys.stdin], [], [], 0.2)[0]:
                    ch = sys.stdin.read(1)
                    if ch == 'p' and not paused:
                        paused = True
                        pause_event.clear()
                        progress.console.print(
                            "\n[bold yellow]⏸  PAUSED[/] — press [bold]r[/] to resume, "
                            "[bold]s[/] to stop\n"
                        )
                    elif ch == 'r' and paused:
                        paused = False
                        pause_event.set()
                        progress.console.print("[bold green]▶  RESUMED[/]\n")
                    elif ch == 's':
                        stop_event.set()
                        st["status"] = "paused"
                        state.save_state(st)
                        progress.console.print(
                            "\n[bold red]⏹  STOPPING[/] — state saved, will exit after current batch.\n"
                        )
        except Exception:
            pass
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass

    key_thread = threading.Thread(target=key_listener, daemon=True)
    key_thread.start()

    # ── Header ───────────────────────────────────────────────────────────
    console.clear()
    console.print(BANNER)
    console.print(
        f"  [dim]Export → {export_dir}[/]\n"
        f"  [dim]Workers: {config.MAX_WORKERS} | Press [bold]p[/]=pause  "
        f"[bold]r[/]=resume  [bold]s[/]=stop[/]\n"
    )

    # ══════════════════════════════════════════════════════════════════════
    #  MAIN EXPORT LOOP
    # ══════════════════════════════════════════════════════════════════════
    try:
        with progress:
            # 1) Fetch workspaces
            log.info("Fetching workspaces...")
            progress.update(ws_task, description="🏢 Workspaces — fetching")
            workspaces = fetcher.fetch_workspaces()
            progress.update(ws_task, total=len(workspaces))

            if not workspaces:
                log.warning("No workspaces found.")
                progress.console.print("[red]No workspaces found![/]")
                return

            # Initialize master data
            if resume and st.get("master_data"):
                master = st["master_data"]
            else:
                master = {
                    "exported_at": datetime.utcnow().isoformat() + "Z",
                    "config": {
                        "download_attachments": config.DOWNLOAD_ATTACHMENTS,
                        "max_subtask_depth": MAX_SUBTASK_DEPTH,
                        "workers": config.MAX_WORKERS,
                    },
                    "workspaces": [],
                }

            st["stats"]["workspaces_total"] = len(workspaces)

            for ws_idx, ws in enumerate(workspaces):
                if stop_event.is_set():
                    break

                if ws["gid"] in completed_workspaces:
                    progress.advance(ws_task)
                    continue

                progress.update(ws_task, description=f"🏢 {ws['name'][:25]}")
                st["current_workspace_gid"] = ws["gid"]
                log.info(f"Processing workspace: {ws['name']} ({ws['gid']})")

                # 2) Fetch projects
                log.info(f"Fetching projects for workspace {ws['name']}...")
                progress.update(proj_task, description="📁 Projects — fetching")
                projects = fetcher.fetch_projects(ws["gid"])
                progress.update(proj_task, total=len(projects), completed=0)
                st["stats"]["projects_total"] += len(projects)

                # Check existing ws data or create new
                ws_data = None
                if resume:
                    for existing_ws in master.get("workspaces", []):
                        if existing_ws.get("gid") == ws["gid"]:
                            ws_data = existing_ws
                            break
                if ws_data is None:
                    ws_data = {**ws, "projects": []}
                    master["workspaces"].append(ws_data)

                for proj_idx, proj in enumerate(projects):
                    if stop_event.is_set():
                        break

                    if proj["gid"] in completed_projects:
                        progress.advance(proj_task)
                        continue

                    progress.update(
                        proj_task,
                        description=f"📁 {proj['name'][:25]}",
                    )
                    st["current_project_gid"] = proj["gid"]
                    log.info(f"  Processing project: {proj['name']} ({proj['gid']})")

                    # Sections
                    pause_event.wait()
                    log.debug(f"    Fetching sections for project {proj['gid']}")
                    proj["sections"] = fetcher.fetch_sections(proj["gid"])

                    # 3) Fetch tasks
                    log.debug(f"    Fetching tasks list for project {proj['name']}...")
                    progress.update(task_task, description="📋 Tasks — fetching list")
                    tasks_raw = fetcher.fetch_project_tasks(proj["gid"])
                    progress.update(task_task, total=len(tasks_raw), completed=0)
                    st["stats"]["tasks_total"] += len(tasks_raw)

                    progress.update(task_task, description=f"📋 Tasks — enriching")
                    progress.update(sub_task, total=0, completed=0, description="🔄 Subtasks")

                    # Count expected subtasks for the bar
                    total_subs = sum(t.get("num_subtasks", 0) for t in tasks_raw)
                    progress.update(sub_task, total=max(total_subs, 1))

                    # 4) Enrich tasks concurrently
                    log.info(f"    Enriching {len(tasks_raw)} tasks concurrently...")
                    enriched = fetcher.enrich_tasks_concurrent(
                        tasks_raw, attachments_dir,
                        pause_event, stop_event,
                        task_callback=on_task_done,
                        subtask_callback=on_subtask_done,
                    )

                    proj["tasks"] = enriched
                    st["stats"]["tasks_done"] += len(enriched)

                    # Write per-project JSON
                    safe_ws = re.sub(r"[^\w\-]", "_", ws["name"])[:30]
                    safe_proj = re.sub(r"[^\w\-]", "_", proj["name"])[:60]
                    proj_path = projects_dir / f"{safe_ws}__{safe_proj}.json"
                    _write_json(proj_path, {
                        "workspace": ws["name"],
                        "workspace_gid": ws["gid"],
                        "project": proj,
                    })

                    ws_data["projects"].append(proj)

                    # Mark project complete
                    log.debug(f"    Completed project {proj['name']}. Saving state & JSON.")
                    completed_projects.add(proj["gid"])
                    st["completed_projects"] = list(completed_projects)
                    st["master_data"] = master
                    state.save_state(st)

                    progress.advance(proj_task)

                if not stop_event.is_set():
                    completed_workspaces.add(ws["gid"])
                    st["completed_workspaces"] = list(completed_workspaces)
                    state.save_state(st)
                    progress.advance(ws_task)

    finally:
        signal.signal(signal.SIGINT, original_sigint)
        stop_event.set()  # ensure key listener exits

    # ══════════════════════════════════════════════════════════════════════
    #  OUTPUT PHASE
    # ══════════════════════════════════════════════════════════════════════

    if st.get("status") == "paused":
        console.print(
            Panel(
                f"[yellow]Export paused. Progress saved.[/]\n"
                f"[dim]Run again and choose Resume to continue.[/]",
                border_style="#ff9800", title="⏸ Paused",
            )
        )
        return

    # Write master JSON
    log.info("Writing master JSON file...")
    master_path = export_dir / "master_export.json"
    _write_json(master_path, master)

    # Write CSVs
    log.info("Generating CSV files...")
    _write_projects_csv(master, export_dir)
    _write_tasks_csvs(master, export_dir)

    # Mark complete
    log.info("Export completed successfully.")
    st["status"] = "completed"
    state.save_state(st)
    state.clear_state()

    # Summary
    all_tasks = [
        t for ws in master["workspaces"]
        for p in ws["projects"]
        for t in p.get("tasks", [])
    ]
    total_projects = sum(len(ws["projects"]) for ws in master["workspaces"])
    total_stories = _count_nested(all_tasks, "stories")
    total_attachments = _count_nested(all_tasks, "attachments")

    summary_table = Table(
        title="[bold #00e5ff]Export Complete[/]",
        box=box.DOUBLE_EDGE, border_style="#2196f3",
        show_header=False, width=55, padding=(0, 2),
    )
    summary_table.add_column("metric", style="dim")
    summary_table.add_column("value", style="bold white")

    summary_table.add_row("📂 Output", str(export_dir))
    summary_table.add_row("🏢 Workspaces", str(len(master["workspaces"])))
    summary_table.add_row("📁 Projects", str(total_projects))
    summary_table.add_row("📋 Tasks", str(len(all_tasks)))
    summary_table.add_row("💬 Stories", str(total_stories))
    summary_table.add_row("📎 Attachments", str(total_attachments))

    console.print()
    console.print(summary_table)
    console.print()


# ═══════════════════════════════════════════════════════════════════════════════
#  CSV WRITERS (moved from main.py)
# ═══════════════════════════════════════════════════════════════════════════════

def _write_projects_csv(master: dict, out_dir: Path):
    csv_dir = out_dir / "csv"
    csv_dir.mkdir(exist_ok=True)
    rows = []
    for ws in master["workspaces"]:
        for proj in ws["projects"]:
            members = "; ".join(m.get("name", "") for m in (proj.get("members") or []))
            rows.append({
                "workspace_name": ws["name"],
                "workspace_gid": ws["gid"],
                "project_gid": proj["gid"],
                "project_name": proj["name"],
                "archived": proj.get("archived"),
                "public": proj.get("public"),
                "color": proj.get("color"),
                "owner_name": (proj.get("owner") or {}).get("name", ""),
                "owner_email": (proj.get("owner") or {}).get("email", ""),
                "team_name": (proj.get("team") or {}).get("name", ""),
                "members": members,
                "created_at": proj.get("created_at", ""),
                "modified_at": proj.get("modified_at", ""),
                "due_date": proj.get("due_date", ""),
                "start_on": proj.get("start_on", ""),
                "section_count": len(proj.get("sections", [])),
                "task_count": len(proj.get("tasks", [])),
                "permalink_url": proj.get("permalink_url", ""),
                "notes_preview": (proj.get("notes") or "")[:300],
            })
    _write_csv(csv_dir / "projects_summary.csv", rows)


def _write_tasks_csvs(master: dict, out_dir: Path):
    csv_dir = out_dir / "csv"
    csv_dir.mkdir(exist_ok=True)

    all_cf_names: set[str] = set()
    for ws in master["workspaces"]:
        for proj in ws["projects"]:
            for task in proj.get("tasks", []):
                for cf in (task.get("custom_fields") or []):
                    all_cf_names.add(cf.get("name", ""))

    base_cols = [
        "workspace", "project_name", "project_gid",
        "task_gid", "task_name", "resource_subtype",
        "section", "completed",
        "assignee_name", "assignee_email",
        "due_on", "due_at", "start_on",
        "created_at", "modified_at", "completed_at",
        "actual_time_minutes",
        "followers", "tags",
        "subtask_count", "story_count",
        "attachment_count", "dependency_count", "dependent_count",
        "notes_preview", "permalink_url",
    ]
    cf_cols = sorted(all_cf_names)

    for ws in master["workspaces"]:
        for proj in ws["projects"]:
            safe_name = re.sub(r"[^\w\-]", "_", proj["name"])[:60]
            path = csv_dir / f"tasks__{safe_name}.csv"
            rows = []
            for task in proj.get("tasks", []):
                section = ""
                for m in (task.get("memberships") or []):
                    if (m.get("project") or {}).get("gid") == proj["gid"]:
                        section = (m.get("section") or {}).get("name", "")
                        break

                assignee = task.get("assignee") or {}
                followers = "; ".join(f.get("name", "") for f in (task.get("followers") or []))
                tags = "; ".join(t.get("name", "") for t in (task.get("tags") or []))
                cf_map = {
                    cf.get("name", ""): cf.get("display_value", "")
                    for cf in (task.get("custom_fields") or [])
                }

                row = {
                    "workspace": ws["name"],
                    "project_name": proj["name"],
                    "project_gid": proj["gid"],
                    "task_gid": task["gid"],
                    "task_name": task.get("name", ""),
                    "resource_subtype": task.get("resource_subtype", ""),
                    "section": section,
                    "completed": task.get("completed"),
                    "assignee_name": assignee.get("name", ""),
                    "assignee_email": assignee.get("email", ""),
                    "due_on": task.get("due_on", ""),
                    "due_at": task.get("due_at", ""),
                    "start_on": task.get("start_on", ""),
                    "created_at": task.get("created_at", ""),
                    "modified_at": task.get("modified_at", ""),
                    "completed_at": task.get("completed_at", ""),
                    "actual_time_minutes": task.get("actual_time_minutes", ""),
                    "followers": followers,
                    "tags": tags,
                    "subtask_count": len(task.get("subtasks", [])),
                    "story_count": len(task.get("stories", [])),
                    "attachment_count": len(task.get("attachments", [])),
                    "dependency_count": len(task.get("dependencies", [])),
                    "dependent_count": len(task.get("dependents", [])),
                    "notes_preview": (task.get("notes") or "")[:300],
                    "permalink_url": task.get("permalink_url", ""),
                }
                for cf_name in cf_cols:
                    row[cf_name] = cf_map.get(cf_name, "")
                rows.append(row)

            if rows:
                _write_csv(path, rows, fieldnames=base_cols + cf_cols)


# ═══════════════════════════════════════════════════════════════════════════════
#  APP LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    """Main TUI loop."""
    while True:
        choice, resume_available = show_main_menu()

        if choice == "1":
            # Fresh start — clear any old state
            state.clear_state()
            run_export(resume=False)
            Prompt.ask("[dim]Press Enter to continue[/]", default="")

        elif choice == "2":
            if resume_available:
                run_export(resume=True)
            else:
                console.print("[yellow]No resumable export found.[/]\n")
            Prompt.ask("[dim]Press Enter to continue[/]", default="")

        elif choice == "3":
            show_config_menu()

        elif choice == "4":
            console.print("[dim]Goodbye! 👋[/]\n")
            break
