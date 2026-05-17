# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Project Overview

Llama CPP Launcher is a Python/PyQt6 GUI frontend for `llama-server` (llama.cpp). It does NOT bundle llama.cpp — it uses whatever `llama-server` binary is on the system PATH. Default parameters are dynamically extracted from `llama-server --help` at startup, never hardcoded.

**Tech stack:** Python 3.11+, PyQt6, single dependency (`requirements.txt` lists only `PyQt6`)

## Running the Application

First activate the venv in the project directory, then run:

```bash
source venv/bin/activate    # Linux/macOS
venv\Scripts\activate       # Windows
python main.py
```

Prerequisite: `llama-server` must be accessible on PATH (the app runs `llama-server --help` and `llama-server --version` at startup).

## Architecture

The codebase is ~4,600 lines across 8 Python files in two packages plus an entry point.

**Entry point:** `main.py` — calls `_refresh_defaults()` to fetch defaults from the installed `llama-server`, then creates `QApplication` and `MainWindow`.

**Core package (`core/`):**
- `defaults.py` — 180+ parameter fallback defaults, `_VALUE_FLAG_MAP` / `_FLAG_MAP` / `_NEG_FLAG_MAP` for CLI flag construction, `_parse_help_to_defaults()` extracts real defaults from `llama-server --help`, `get_chat_templates()` auto-discovers chat templates
- `runner.py` — `ServerRunner` class wraps `QProcess` to manage the `llama-server` lifecycle; emits signals (`log_output`, `state_changed`, `error_occurred`, `server_ready`); graceful shutdown with 3s timeout
- `config.py` — `ConfigManager` for preset CRUD (save/load/delete/list/import/export as JSON in `~/.llama-cpp-launcher/presets/`)

**UI package (`ui/`):**
- `main_window.py` (~2200 lines) — Main window with splitter layout (left: model browser + presets + model info; right: mode selector + parameter panels + command preview + server controls + log/info tabs). Contains the command-line argument builder `_build_args_from_values()`, real-time log parser `_parse_log_line()` extracting 40+ data points into 9 categories, undo system (debounced 800ms snapshots, max 20 entries), and embedded CSS stylesheet
- `basic_panel.py` — Simplified panel: model, mmproj, GPU layers, context size, sampling sliders, server host/port, quick toggles
- `advanced_panel.py` (~1500 lines) — 7 tabs exposing 100+ parameters: Model, Context, Sampling, GPU/Performance, Server, Chat/Reasoning, Advanced
- `model_browser.py` — `ModelScanner` runs in a background `QThread` to scan for `.gguf` files; auto-categorizes into models/mmprojs/LoRAs

## Key Design Patterns

- **Basic/Advanced mode sync:** Changing a parameter in basic mode updates the corresponding advanced panel field (and vice versa). When switching modes, panel state is preserved — never reset.
- **Command preview:** Only non-default values are emitted to the command line. The `_VALUE_FLAG_MAP` in `defaults.py` maps each parameter key to its CLI flag(s) and type parser.
- **Log parsing:** `_parse_log_line()` in `main_window.py` uses regex to extract structured data from `llama-server` stdout, rendered as an HTML info panel.

## No Build Step, No Tests, No Linting

This is a pure Python application with no build system, no test suite, no linting config, and no CI/CD. Run directly from source.
