#!/usr/bin/env python3
"""
Asana Full Export Tool — TUI Edition
═══════════════════════════════════════════════════════════════════════════════
Export ALL data from Asana workspaces with:
  • Concurrent fetching (ThreadPoolExecutor)
  • Resume capability (checkpoint state)
  • Rich TUI with animated progress bars
  • Pause / Resume / Stop controls
  • .env token loading

Run:
  python main.py

Requirements:
  pip install -r requirements.txt
═══════════════════════════════════════════════════════════════════════════════
"""

import sys

def main():
    try:
        from rich.console import Console
    except ImportError:
        print("\nMissing dependencies. Install them with:")
        print("  pip install -r requirements.txt\n")
        sys.exit(1)

    import tui
    tui.run()


if __name__ == "__main__":
    main()