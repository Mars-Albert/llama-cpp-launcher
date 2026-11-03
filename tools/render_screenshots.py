# -*- coding: utf-8 -*-
"""Render the README / manual screenshots from the real widgets.

Why this exists
---------------
The screenshots used to be taken on a developer machine, and they leaked it:
the real ``llama-server`` path, the real model directory and file names, the
real preset names, the real ``llama.cpp`` version. Everything a public README
should not publish. This script renders the same four images from the real UI
with **synthetic data only**, so re-shooting after a UI change never publishes
someone's machine again.

How it renders without a window flashing on screen
--------------------------------------------------
The native Qt platform plugin is used (``windows`` — the offscreen platform has
no real font database, so CJK would rasterize to tofu), but every top level
gets ``WA_DontShowOnScreen``, so the window is laid out and painted without
ever being mapped.

What is synthetic (edit the constants below, nothing else touches the machine)
------------------------------------------------------------------------------
* ``llama-server`` is **never executed** — ``_StartupInfoWorker.run`` is
  stubbed and version / device results are injected, so no ``--version`` and no
  ``--list-devices`` (that is what publishes your GPUs).
* ``get_server_path()`` is stubbed: the command preview would otherwise print
  the binary this machine resolves via settings / PATH.
* ``USERPROFILE`` / ``HOME`` point at a throwaway directory, so the real
  ``~/.llama-cpp-launcher`` (settings, presets, launcher.log) is neither read
  nor written.
* Models are sparse fake ``.gguf`` files built with the repo's own
  ``tests/test_gguf.build_fake_gguf`` fixture: real GGUF headers (so the
  model-info rows come out of the real parser) with realistic sizes.
* GPU / CPU names, the version string, the log lines and every counter are
  invented in this file.

Usage
-----
    python tools/render_screenshots.py              # -> %TEMP%/launcher-shots/
    python tools/render_screenshots.py --inplace    # overwrite the repo PNGs
    python tools/render_screenshots.py --only cn_light.png
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHOTS = (
    # file,                    theme,   lang, advanced, right tab, adv tab, running
    ("cn_light.png", "light", "zh", True, 0, 3, False),
    ("en_light.png", "light", "en", True, 0, 3, False),
    ("cn.png", "dark", "zh", False, 2, None, True),
    ("en.png", "dark", "en", False, 2, None, True),
)
SERVER = "D:/llama.cpp/llama-server.exe"          # shown in the command preview
MODEL_DIR_NAME = "models"                          # displayed as D:/models/...

# ---------------------------------------------------------------- synthetic HW
GPUS = [
    {"index": "CUDA0", "name": "NVIDIA GeForce RTX 4090",
     "total_mib": 24564, "free_mib": 22012},
    {"index": "CUDA1", "name": "NVIDIA GeForce RTX 3060",
     "total_mib": 12288, "free_mib": 10412},
]
CPU = "AMD Ryzen 7 7700X 8-Core Processor"
VERSION = ("6131", "9f2b0c1aa", "version: 6131 (9f2b0c1aa)")

# name, size on disk, arch, general.name, context_length, blocks, embedding
MODELS = [
    ("qwen2.5-7b-instruct-q4_k_m.gguf", 4_680_000_000, "qwen2",
     "Qwen2.5-7B-Instruct", 32768, 28, 3584),
    ("qwen2.5-vl-7b-instruct-q4_k_m.gguf", 5_060_000_000, "qwen2vl",
     "Qwen2.5-VL-7B-Instruct", 32768, 28, 3584),
    ("llama-3.2-3b-instruct-ud-q4_k_m.gguf", 2_030_000_000, "llama",
     "Llama-3.2-3B-Instruct", 131072, 28, 3072),
    ("deepseek-r1-distill-qwen-7b-q4_k_m.gguf", 4_580_000_000, "qwen2",
     "DeepSeek-R1-Distill-Qwen-7B", 131072, 28, 3584),
    ("phi-3.5-mini-instruct-q4_k_s.gguf", 2_180_000_000, "phi3",
     "Phi-3.5-mini-instruct", 131072, 32, 3072),
]
SELECTED = MODELS[1]          # the vision model: exercises model + mmproj
MMPROJ = "mmproj-qwen2.5-vl-7b-instruct-f16.gguf"

# --------------------------------------------------- a plausible llama.cpp run
# Formats are the ones ui/log_parser.py understands (samples borrowed from the
# repo's own tests); the values are invented.
LOG = [
    "09:14:02: load_backend: loaded CPU backend",
    "09:14:02: load_backend: loaded CUDA backend",
    "09:14:02: ggml_cuda_init: found 2 CUDA devices:",
    "  Device 0: NVIDIA GeForce RTX 4090, compute capability 8.9, VMM: yes, VRAM: 24564 MiB",
    "  Device 1: NVIDIA GeForce RTX 3060, compute capability 8.6, VMM: yes, VRAM: 12288 MiB",
    "llama_model_loader: loaded meta info with 26 KV pairs",
    "llama_model_loader: - type  f32:  126 tensors",
    "llama_model_loader: - type q4_K:  240 tensors",
    "print_info: n_ctx   = 16384 (32768)",
    "print_info: n_batch = 2048, n_ubatch = 512",
    "print_info: n_gpu_layers = 999",
    "print_info: flash_attn   = 1",
    "print_info: n_expert              = 0",
    "print_info: rope scaling          = yarn, factor = 2.000000",
    "print_info: file type   = Q4_K_M",
    "llama_context: n_ctx_seq (16384) < n_ctx_train (32768) -- the full capacity of the model will not be utilized",
    "load_tensors:        CUDA0 model buffer size =  3986.42 MiB",
    "load_tensors:        CUDA1 model buffer size =  1042.18 MiB",
    "load_tensors:   CPU_Mapped model buffer size =    24.61 MiB",
    "llama_kv_cache:      CUDA0 KV buffer size =   232.50 MiB",
    "llama_kv_cache:      CUDA1 KV buffer size =    61.50 MiB",
    "llama_new_context_with_model: compute buffer total size =   318.25 MiB",
    "llama_prepare_model_devices: using device CUDA0 (NVIDIA GeForce RTX 4090) (0000:01:00.0) - 22012 MiB free",
    "llama_prepare_model_devices: using device CUDA1 (NVIDIA GeForce RTX 3060) (0000:02:00.0) - 10412 MiB free",
    "main: using device CPU (%s) (unknown id) - 45312 MiB free" % CPU,
    "cmn common_param: common_params_print_info: verbosity = 4 (adjust with the `-lv N` CLI arg)",
    "09:14:05: srv    load_model: initializing, n_slots = 4, parallel = 2",
    "09:14:05: srv    load_model: prompt cache is enabled, size limit: no limit",
    "09:14:05: srv init: chat template supports preserving reasoning, it is enabled by default",
    "09:14:05: srv  embedding: embedding endpoint is enabled",
    "09:14:05: srv  metrics:  metrics endpoint is enabled",
    "09:14:05: srv  update_slots: all slots are idle",
    "09:14:05: srv  HTTP server is listening on http://127.0.0.1:8080",
    "09:14:05: starting the main loop",
    "09:14:22: slot get_availabl: id  0 | task -1 | selected slot by LRU, t_last = -1",
    "09:14:22: slot launch_slot_: id  0 | task 0 | processing task, is_child = 0",
    "09:14:22: slot update_slots: id  0 | task 0 | new prompt, n_ctx_kv = 0, n_tokens = 61",
    "09:14:22: slot print_timing: id  0 | task 0 |",
    "prompt eval time =   184.32 ms /    61 tokens (    3.02 ms per token,   331.42 tokens per second)",
    "       eval time = 16211.06 ms /  2486 tokens (    6.52 ms per token,   153.33 tokens per second)",
    "      total time = 16395.38 ms /  2547 tokens",
    "09:14:38: slot release: id  0 | task 0 | stopped at end-of-text",
    "09:16:41: slot get_availabl: id  1 | task -1 | selected slot by LRU, t_last = 1760000201",
    "09:16:41: slot launch_slot_: id  1 | task 42 | processing task, is_child = 0",
    "09:16:41: slot update_slots: id  1 | task 42 | prompt cache hit, 512 tokens",
    "srv  slot   0 cmd (12 ms)",
    "09:16:44: slot update_slots: id  1 | task 42 | n_ctx_kv = 6881, n_decoded = 1204",
]

STATS = {
    "prefill_tps": 331.42,
    "decode_tps": 153.33,
    "ctx_frac": 6881 / 16384.0,
    "ctx_used": 6881,
    "ctx_total": 16384,
    "prompt_total": 184320,
    "prompt_cached_total": 147456,
    "predicted_total": 25856,
    "task_cache_hit": 0.88,
}
RUNTIME_TEXT = "\u23f1 04:22"      # \u23f1 stopwatch, same format the app prints


def _isolate_profile() -> str:
    """Point ~ at a throwaway dir BEFORE any app module resolves it.

    core/config.py resolves ~/.llama-cpp-launcher at import time, so this must
    run before the imports below; it also keeps the real settings.json,
    presets/ and launcher.log untouched.
    """
    home = tempfile.mkdtemp(prefix="launcher-shots-home-")
    drive, tail = os.path.splitdrive(home)
    os.environ["USERPROFILE"] = home
    os.environ["HOMEDRIVE"] = drive
    os.environ["HOMEPATH"] = tail
    os.environ["HOME"] = home
    os.environ.pop("QT_QPA_PLATFORM", None)   # native plugin = real font DB
    return home


def _build_model_files(model_dir: str) -> None:
    sys.path.insert(0, os.path.join(REPO, "tests"))
    from test_gguf import build_fake_gguf      # the repo's own GGUF fixture

    for name, size, arch, gname, ctx, blocks, emb in MODELS:
        meta = {
            "general.architecture": arch,
            "general.name": gname,
            "general.quantization_version": 1,
            "general.file_type": 15,
            f"{arch}.context_length": ctx,
            f"{arch}.block_count": blocks,
            f"{arch}.embedding_length": emb,
            f"{arch}.attention.head_count": 28,
            "tokenizer.ggml.model": "gpt2",
            "tokenizer.ggml.bos_token_id": 151643,
            "tokenizer.ggml.eos_token_id": 151645,
        }
        with open(os.path.join(model_dir, name), "wb") as fh:
            fh.write(build_fake_gguf(metadata=meta))
            fh.truncate(size)                  # sparse: real size, zero IO
    with open(os.path.join(model_dir, MMPROJ), "wb") as fh:
        fh.write(build_fake_gguf(metadata={"general.architecture": "clip",
                                           "clip.vit.patch_size": 14,
                                           "clip.projector_type": "mlp"}))
        fh.truncate(860_000_000)


def render(out_dir: str, only=None) -> list:
    home = _isolate_profile()
    sys.path.insert(0, REPO)
    os.chdir(REPO)

    import ui.main_window as mw
    import core.config as cfg
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtWidgets import QApplication
    from core.i18n import set_language, t
    from core.params_schema import fallback_defaults
    from ui.runtime_info import build_info_html
    import main as launcher_main

    # The machine must stay out of the picture: no subprocess, no PATH lookup.
    mw._StartupInfoWorker.run = lambda self: None
    cfg.get_server_path = lambda: SERVER
    mw.get_server_path = lambda: SERVER

    model_dir = tempfile.mkdtemp(prefix="launcher-shots-models-")
    _build_model_files(model_dir)
    os.makedirs(out_dir, exist_ok=True)
    set_language("zh")

    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setFont(launcher_main._pick_healthy_font(app))
    launcher_main._apply_app_icon(app)

    win = mw.MainWindow(work_dir=REPO, defaults=dict(fallback_defaults()))
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.resize(1600, 941)
    win.show()

    def settle(times=24):
        for _ in range(times):
            app.processEvents()
            time.sleep(0.03)

    settle()
    win._on_version_result(*VERSION)
    win._on_devices_ready(GPUS)

    model = os.path.join(model_dir, SELECTED[0])
    mmproj = os.path.join(model_dir, MMPROJ)
    win.params.update({
        "model": model, "mmproj": mmproj, "ctx_size": 16384,
        "n_gpu_layers": 999, "flash_attn": True, "host": "127.0.0.1",
        "port": 8080, "parallel": 2, "metrics": True, "threads": 8,
        "jinja": True, "reasoning": "auto", "no_webui": False,
    })
    win.basic_panel.set_values(win.params)
    win.advanced_panel.set_values(win.params)

    win.model_browser.set_search_dir(model_dir)
    for _ in range(60):
        app.processEvents()
        time.sleep(0.03)
        if win.model_browser.model_list.count():
            break
    win._on_model_selected(model)
    win._on_mmproj_selected(mmproj)
    for _ in range(80):
        app.processEvents()
        time.sleep(0.03)
        if win._model_meta is not None:
            break

    # The temp dirs carry this machine's user name, so swap the paths that get
    # *displayed / emitted*. _update_model_info() only runs from the two
    # selection handlers, which already fired above — the parsed model-info
    # rows (size / params / quant) therefore survive the swap untouched.
    win.basic_panel.model_combo.setCurrentText(f"D:/{MODEL_DIR_NAME}/{SELECTED[0]}")
    win.basic_panel.mmproj_combo.setCurrentText(f"D:/{MODEL_DIR_NAME}/{MMPROJ}")
    win.advanced_panel.adv_model.setText(f"D:/{MODEL_DIR_NAME}/{SELECTED[0]}")
    win.advanced_panel.adv_mmproj.setText(f"D:/{MODEL_DIR_NAME}/{MMPROJ}")
    win._update_cmd_preview()

    # Paint the row the user would have clicked (setCurrentRow does not emit
    # itemClicked, so nothing re-selects or re-parses here).
    rows = win.model_browser.model_list
    for i in range(rows.count()):
        if SELECTED[0] in rows.item(i).text():
            rows.setCurrentRow(i)
            break

    # Two presets so the preset group does not read as a fresh install — these
    # land in the throwaway HOME, never in the real presets/ directory.
    base = dict(fallback_defaults())
    win.config.save_preset("vision-8k", {**base, "ctx_size": 8192,
                                         "n_gpu_layers": 999,
                                         "flash_attn": True, "parallel": 2})
    win.config.save_preset("quick-cpu", {**base, "ctx_size": 4096,
                                         "n_gpu_layers": 0,
                                         "flash_attn": False})
    win._refresh_presets(select_name="vision-8k")

    written = []
    for name, theme, lang, advanced, right_tab, adv_tab, running in SHOTS:
        if only and name not in only:
            continue
        set_language(lang)
        win.theme = theme
        win._theme_action.setChecked(theme == "dark")
        win._apply_theme()
        win.mode_combo.setCurrentIndex(1 if advanced else 0)
        if advanced and adv_tab is not None:
            win.advanced_panel.tabs.setCurrentIndex(adv_tab)
        win.retranslate_ui()
        if running:
            win._on_state_changed("running")
            win.timer.stop()
            win.run_time_label.setText(RUNTIME_TEXT)
            win.live_metrics.set_running(True)
            win.live_metrics.set_slots_state("on")
            win.live_metrics.set_metrics_checked(True)
            win.live_metrics.set_metrics_state("available")
            win.live_metrics.update(STATS)
            for line in LOG:
                win._append_log(line + "\n", "out")
            win._flush_log_buffer()
            win.info_display.setHtml(build_info_html(win._runtime_info))
            win._update_run_indicator()
        win.tab_widget.setCurrentIndex(right_tab)
        settle()
        win.move(QPoint(200, 60))
        pm = win.grab()
        path = os.path.join(out_dir, name)
        pm.save(path)
        written.append(path)
        print(f"{name}: {pm.width()}x{pm.height()} @ dpr {pm.devicePixelRatio()}")

    # teardown in the order closeEvent expects (scanner thread first)
    win.live_metrics.set_running(False)
    win.model_browser.shutdown()
    win.close()
    app.processEvents()
    print("home used (throwaway):", home)
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None,
                    help="output directory (default: %%TEMP%%/launcher-shots)")
    ap.add_argument("--inplace", action="store_true",
                    help="write straight into the repo root (overwrites the PNGs)")
    ap.add_argument("--only", nargs="*", default=None,
                    help="subset of file names, e.g. --only cn_light.png")
    args = ap.parse_args()

    if args.inplace:
        out = REPO
    elif args.out:
        out = os.path.abspath(args.out)
    else:
        out = os.path.join(tempfile.gettempdir(), "launcher-shots")
    render(out, only=args.only)


if __name__ == "__main__":
    main()
