# Asana Full Export Tool (TUI Edition)

A powerful, high-speed asynchronous export tool for Asana with a beautiful terminal user interface (TUI). Features progress tracking, resume capabilities, and concurrent fetching.

![Asana Export TUI](https://raw.githubusercontent.com/TransData/asana-export/main/docs/tui_screenshot.png) *(Placeholder: Replace with actual screenshot)*

## Features

-   🚀 **High Speed:** Concurrent fetching of tasks and subtasks using thread pools.
-   💾 **Resume Support:** Automatically saves state; resume from the last completed project if interrupted.
-   📊 **Rich TUI:** Animated progress bars per component (Workspaces, Projects, Tasks, Subtasks).
-   ⏸️ **Interactive Controls:** Pause, Resume, or Stop the export at any time.
-   📂 **Structured Output:** Organized folder structure with JSON, CSV, and optional attachment downloads.
-   🔒 **Secure:** Load PAT from `.env` or enter interactively (optional save to `.env`).

## Getting Started

### 1. Prerequisites

-   Python 3.8+
-   An Asana Personal Access Token (PAT). [How to get a PAT](https://developers.asana.com/docs/personal-access-token).

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/TransData/asana-export.git
cd asana_export

# Create or use an existing virtual environment
python -m venv .vevn
source .vevn/bin/activate  # On Windows: .vevn\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Usage

Run the main script:

```bash
python main.py
```

-   **First Run:** You will be prompted for your Asana PAT if it's not in your `.env`.
-   **TUI Controls:**
    -   `p` : Pause the export.
    -   `r` : Resume the export.
    -   `s` : Stop gracefully (saves state).

## Configuration

Settings are managed via environment variables or a `.env` file in the project root.

| Environment Variable | Description | Default |
| :--- | :--- | :--- |
| `ASANA_ACCESS_TOKEN` | Your Asana Personal Access Token. | (Required) |
| `ASANA_MAX_WORKERS` | Number of concurrent threads for fetching. | `4` |
| `ASANA_SKIP_ARCHIVED` | Whether to skip archived projects. | `true` |
| `ASANA_DOWNLOAD_ATTACHMENTS` | Whether to download media/attachments. | `false` |
| `ASANA_WORKSPACE_FILTER` | Filter for specific workspace GID or name. | (All) |

### Example `.env`

```env
ASANA_ACCESS_TOKEN='your_token_here'
ASANA_SKIP_ARCHIVED='true'
ASANA_DOWNLOAD_ATTACHMENTS='false'
ASANA_MAX_WORKERS='4'
```

## Directory Structure

```text
exports/
└── <timestamp>/            # Each run gets its own folder
    ├── export.log          # Detailed activity logs
    ├── master_export.json  # Consolidated data
    ├── projects/           # Per-project JSON files
    ├── csv/                # Flattened CSV exports
    └── attachments/        # Downloaded media (if enabled)
```

## License

MIT
