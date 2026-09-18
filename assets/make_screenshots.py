# -*- coding: utf-8 -*-
"""Regenerate the README screenshots (en.png / cn.png).

Renders the *real* main window offscreen in a first-launch state with a
realistic "server running" scene:

* a temporary HOME (``~/.llama-cpp-launcher``) — real user settings are
  never touched; first-launch defaults apply (1600×940 window, 400px left
  panel, the five default quick toggles)
* real ``llama-server --version`` / ``--help`` / ``--list-devices`` from
  the server binary (version label, live defaults, GPU-info row)
* a real model-directory scan (model browser + model-info rows + the GGUF
  quick-metadata row, parsed from the actual file header)
* a realistic startup log that the real parser turns into the runtime-info
  panel (lines mirror the parser's supported formats, values mirror the
  user's actual hardware/model)

Usage (from anywhere):
    python assets/make_screenshots.py --lang en --out en.png --tab log
    python assets/make_screenshots.py --lang zh --out cn.png --tab info
    python assets/make_screenshots.py --lang en --out en_light.png \
        --theme light --mode advanced --adv-tab 0 --tab log
    python assets/make_screenshots.py --lang zh --out cn_light.png \
        --theme light --mode advanced --adv-tab 0 --tab info
"""
import argparse
import html as html_mod
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Environment must be fixed BEFORE any app module is imported:
# core.config computes CONFIG_DIR from Path.home() at import time.
# ---------------------------------------------------------------------------
TMP_HOME = tempfile.mkdtemp(prefix="llcl_screenshots_")
os.environ["USERPROFILE"] = TMP_HOME          # Path.home() on Windows
os.environ["HOME"] = TMP_HOME
# Native platform: the offscreen QPA has an empty font database (no CJK /
# monospace glyphs → tofu), so screenshots must render on the real platform.
os.environ.setdefault("QT_QPA_PLATFORM", "windows")


def write_temp_settings(language: str, server_path: str, scan_path: str,
                        preset: dict | None, theme: str = "dark") -> None:
    cfg = Path(TMP_HOME) / ".llama-cpp-launcher"
    (cfg / "presets").mkdir(parents=True, exist_ok=True)
    data = {
        "server_path": server_path,
        "scan_path": scan_path,
        "language": language,
        "theme": theme,
    }
    (cfg / "settings.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    if preset is not None:
        (cfg / "presets" / f"{preset['name']}.json").write_text(
            json.dumps(preset, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lang", choices=("en", "zh"), required=True)
    ap.add_argument("--out", required=True, help="output PNG path")
    ap.add_argument("--tab", choices=("log", "info"), default="log",
                    help="bottom tab to show: log output or runtime info")
    ap.add_argument("--theme", choices=("dark", "light"), default="dark")
    ap.add_argument("--mode", choices=("basic", "advanced"), default="basic")
    ap.add_argument("--adv-tab", type=int, default=0,
                    help="advanced-mode tab index to show (0 = model)")
    ap.add_argument("--width", type=int, default=1600,
                    help="window width in px (default 1600)")
    ap.add_argument("--server-path",
                    default=r"G:\Projects\llama.cpp\build\bin\Release\llama-server.EXE",
                    help="llama-server binary used for version/help/devices")
    ap.add_argument("--models-dir", default="G:/llm")
    ap.add_argument("--model", default=r"G:\llm\Qwen3.8-27B-UD-Q5_K_XL.gguf")
    ap.add_argument("--mmproj", default=r"G:\llm\Qwen3.8-mmproj-BF16.gguf")
    args = ap.parse_args()

    if not Path(args.server_path).exists():
        sys.exit(f"llama-server not found: {args.server_path}")
    if not Path(args.model).exists():
        sys.exit(f"model file not found: {args.model}")

    # One preset entry so the left-panel combo isn't empty.
    preset = {
        "name": "Qwen3.8-27B",
        "version": 1,
        "created": "2026-08-21T17:35:00",
        "params": {"ctx_size": 200000, "spec_type": "draft-mtp", "draft_max": 4},
    }
    write_temp_settings(args.lang, args.server_path, args.models_dir, preset,
                        args.theme)

    sys.path.insert(0, str(REPO))
    from PyQt6.QtWidgets import QApplication, QStyleFactory
    from core.i18n import set_language, t
    from core.defaults import _FALLBACK_DEFAULTS
    import main as launcher_main
    from ui.main_window import MainWindow

    set_language(args.lang)
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    launcher_main._apply_app_icon(app)

    def spin_until(cond, timeout_s: float, what: str) -> None:
        deadline = time.monotonic() + timeout_s
        while not cond():
            if time.monotonic() > deadline:
                sys.exit(f"timeout waiting for: {what}")
            app.processEvents()
            time.sleep(0.05)

    win = MainWindow(work_dir=str(REPO), defaults=dict(_FALLBACK_DEFAULTS))
    win.show()

    # 1) wait for the real startup worker (--version / --help / --list-devices)
    done = {"ver": False, "defaults": False, "devices": False}
    w = win._startup_worker
    w.version_ready.connect(lambda *a: done.__setitem__("ver", True))
    w.version_failed.connect(lambda *a: done.__setitem__("ver", True))
    w.defaults_ready.connect(lambda *a: done.__setitem__("defaults", True))
    w.devices_ready.connect(lambda *a: done.__setitem__("devices", True))
    spin_until(lambda: done["ver"] and done["defaults"], 90, "startup worker")
    spin_until(lambda: done["devices"], 30, "device probe")
    w.wait(15000)  # thread fully done before we exit (delayed-GC crash guard)

    # 2) wait for the model scan of the real models directory
    mb = win.model_browser
    spin_until(lambda: len(mb.models) > 0, 90, "model scan")
    print(f"scanned: {len(mb.models)} models, {len(mb.mmprojs)} mmprojs")

    # 3) realistic parameter set (mirrors a typical Qwen-27B config)
    win.basic_panel.set_values({
        "model": args.model, "mmproj": args.mmproj,
        "n_gpu_layers": "auto", "ctx_size": 200000,
        "temp": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
        "repeat_penalty": 1.0,
        "host": "127.0.0.1", "port": 8080, "parallel": 1,
        "webui": True, "verbose": False,
        "flash_attn": "auto", "reasoning": "auto", "split_mode": "none",
        "spec_type": "draft-mtp", "draft_max": 4,
    })
    # 3b) optional mode switch — values are preserved across the switch via
    #     the panels' get_values/set_values contract
    if args.mode == "advanced":
        win.mode_combo.setCurrentIndex(1)
        if 0 <= args.adv_tab < win.advanced_panel.tabs.count():
            win.advanced_panel.tabs.setCurrentIndex(args.adv_tab)
    # highlight the matching entry in the model list
    for i in range(mb.model_list.count()):
        if os.path.normcase(mb.model_list.item(i).toolTip()) == os.path.normcase(args.model):
            mb.model_list.setCurrentRow(i)
            break

    # 4) wait for the GGUF quick-metadata worker (real file header parse)
    spin_until(lambda: win._model_meta is not None, 30, "model meta parse")

    # 5) launcher banner + a realistic startup log (real parser formats)
    from core.config import get_server_path
    from ui.command_builder import quote_arg
    cmd_path = quote_arg(get_server_path())
    cmd_args = " ".join(quote_arg(a) for a in win._build_args_from_params())
    cmd_str = cmd_path + (" " + cmd_args if cmd_args else "")
    ts = datetime.now().strftime("%H:%M:%S")
    win._open_run_log(cmd_str)
    win._log_banner(f'<span style="color: #89b4fa;">[{ts}] {t("启动命令:")}</span>')
    win._log_banner(f'<span style="color: #a6e3a1;">  {html_mod.escape(cmd_str)}</span>')
    win._log_banner("")

    model_b = args.model.replace("\\", "\\\\")
    mmproj_b = args.mmproj.replace("\\", "\\\\")
    log_lines = [
        "0.031 I main: build = 10991 (930e2fa59)",
        "0.031 I system_info: n_threads = 16 / 20",
        "0.032 I srv  main: using 16 threads for HTTP",
        "0.033 I srv  main: initializing, n_slots = 1",
        "0.033 I srv  main: server is listening on http://127.0.0.1:8080",
        "0.034 I srv  main: prompt cache is enabled, size limit: no limit",
        "0.041 I system_info: verbosity = 4",
        "0.052 I srv  main: speculative decoding: type = draft-mtp, draft max = 4",
        "0.180 I   Device 0: NVIDIA GeForce RTX 5090, compute capability 9.0, VMM: yes, VRAM: 32579 MiB",
        "0.180 I   Device 1: NVIDIA GeForce RTX 2080, compute capability 7.5, VMM: no, VRAM: 8191 MiB",
        "0.181 I main: using device CPU (12th Gen Intel(R) Core(TM) i7-12700K) (unknown id) - 53243 MiB free",
        "0.181 I llama threadpool init: cpu - n_threads = 16 / 20",
        "0.410 I llama_prepare_model_devices: using device CUDA0 (NVIDIA GeForce RTX 5090) (0000:01:00.0) - 30991 MiB free",
        "0.410 I llama_prepare_model_devices: using device CUDA1 (NVIDIA GeForce RTX 2080) (0000:08:00.0) - 7989 MiB free",
        "0.411 I main: using device CPU (12th Gen Intel(R) Core(TM) i7-12700K) (unknown id) - 53243 MiB free",
        "0.412 I llama_context: n_ctx_seq = 200000",
        "0.412 I llama_context: n_batch = 2048",
        "0.412 I llama_context: n_ubatch = 512",
        "0.412 I llama_context: freq_base = 500000",
        "0.413 I llama_context: flash_attn = enabled (auto)",
        "0.420 I srv  load_model: loading model '" + model_b + "'",
        "0.431 I llama_model_loader: - file format = GGUF V3 (v3 + align 16)",
        "0.431 I llama_model_loader: - file size = 19.44 GiB",
        "0.437 I print_info: general.name = Qwen3.8-27B-UD-Q5_K_XL",
        "0.437 I print_info: arch 0 = qwen3",
        "0.437 I print_info: file type   = Q5_K_XL",
        "0.437 I print_info: file size   = 19.44 GiB",
        "0.437 I print_info: model params = 29.98 B",
        "0.437 I print_info: n_vocab = 151669",
        "0.437 I print_info: n_ctx_train = 262144",
        "0.438 I print_info: n_embd = 5120",
        "0.438 I print_info: n_layer = 64",
        "0.438 I print_info: n_ff = 17408",
        "0.438 I print_info: rope scaling = linear",
        "0.438 I print_info: vocab type = 9 (BPE)",
        "0.438 I print_info: BOS token = 151643 '<|begin_of_text|>'",
        "0.438 I print_info: EOS token = 151645 '<|endoftext|>'",
        "0.438 I print_info: freq_base_train = 500000",
        "1.120 I load_tensors: offloaded 64/64 layers to GPU (CUDA0: 40, CUDA1: 24)",
        "2.505 I loading multimodal model '" + mmproj_b + "'",
        "2.520 I load_hparams: model size: 885.16 MiB",
        "2.520 I load_hparams: image_size: 1344",
        "2.980 I load_tensors:        CUDA0 model buffer size = 11456.40 MiB",
        "2.981 I load_tensors:        CUDA1 model buffer size =  7448.29 MiB",
        "2.981 I load_tensors:   CPU_Mapped model buffer size =   551.85 MiB",
        "3.412 I llama_kv_cache:      CUDA0 KV buffer size =  6246.42 MiB",
        "3.412 I llama_kv_cache:      CUDA1 KV buffer size =   480.11 MiB",
        "3.905 I sched_reserve:       CUDA0 compute buffer size =  24.14 MiB",
        "3.905 I sched_reserve:       CUDA1 compute buffer size =   9.87 MiB",
        "3.920 I sched_reserve: graph nodes  = 4423",
        "3.920 I sched_reserve: graph splits = 2",
        "4.010 I llama_context: projected to use 15120.66 MiB (model + KV) vs. 40770.00 MiB total device memory",
        "4.100 I srv  main: model loaded",
        "4.110 I srv  main: adding speculative implementation 'draft-mtp'",
        "4.111 I srv  main: creating mtp draft context",
        "4.112 I srv  main: chat template supports preserving reasoning: enabled by default",
        "4.130 I srv  load_model: initializing, n_ctx_slot = 200000",
        "4.210 I srv  main: starting the main loop",
    ]
    win._append_log("\n".join(log_lines) + "\n")
    win._flush_log_buffer()

    # 6) flip to the "running" state
    win.runner._is_ready = True
    win._on_state_changed("running")
    win.timer.stop()
    win.run_time_label.setText(t("⏱ 运行: {mins}:{secs}", mins="00", secs="42"))

    # 7) left-panel preset combo
    win._refresh_presets(select_name="Qwen3.8-27B")

    # 8) bottom tab
    win.tab_widget.setCurrentIndex(0 if args.tab == "log" else 1)

    # 9) offscreen platform reports an 800×800 primary screen, so the
    #    first-launch default (1600×940) gets clamped down to the content
    #    minimum. Re-apply the intended width at the natural height.
    win.resize(args.width, max(940, win.minimumSize().height()))
    # settle layout / late labels (GPU info, model meta, panel minimums)
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)

    # keep the desktop tidy: hide before grabbing (grab renders the widget
    # tree regardless of visibility)
    win.hide()
    app.processEvents()

    img = win.grab()
    out = Path(args.out)
    img.save(str(out))
    print(f"saved {out} ({img.width()}x{img.height()})")

    # teardown: stop the model scanner thread cleanly, then hard-exit
    # (skip delayed GC — this PyQt6 build AVs when it runs late, see the
    # 2026-09 CI fix commits)
    mb.shutdown()
    w = win._startup_worker
    if w.isRunning():
        w.wait(5000)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
