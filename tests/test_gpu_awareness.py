"""Tests for E8: GPU awareness (device probe + runtime log facts)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication

from core.defaults import parse_device_list
from ui.log_parser import parse_log_line
from ui.runtime_info import build_info_html

DUAL_OUTPUT = """Available devices:
  CUDA0: NVIDIA GeForce RTX 5090 (32579 MiB, 30819 MiB free)
  CUDA1: NVIDIA GeForce RTX 2080 (8191 MiB, 7121 MiB free)
"""

DEVS = [
    {"index": "CUDA0", "name": "NVIDIA GeForce RTX 5090", "total_mib": 32579, "free_mib": 30819},
    {"index": "CUDA1", "name": "NVIDIA GeForce RTX 2080", "total_mib": 8191, "free_mib": 7121},
]


def test_parse_device_list_dual_gpu():
    devs = parse_device_list(DUAL_OUTPUT)
    assert len(devs) == 2
    assert devs[0]["index"] == "CUDA0"
    assert devs[0]["name"] == "NVIDIA GeForce RTX 5090"
    assert devs[0]["total_mib"] == 32579
    assert devs[0]["free_mib"] == 30819
    assert devs[1]["name"] == "NVIDIA GeForce RTX 2080"


def test_parse_device_list_cpu_only():
    assert parse_device_list("Available devices:\n  (none)\n") == []


def test_parse_device_list_empty_and_junk():
    assert parse_device_list("") == []
    assert parse_device_list("garbage without the expected format") == []


def test_log_offload_new_prefix():
    # newer builds: `load_all_data: offloaded 33/38 layers to GPU`
    info = {}
    parse_log_line("load_all_data: offloaded 33/38 layers to GPU", info)
    assert "33/38" in info.get("gpu_offload", "")


def test_log_offload_old_prefix():
    info = {}
    parse_log_line("load_tensors: offloaded 29/29 layers to GPU", info)
    assert "29/29" in info.get("gpu_offload", "")


def test_log_using_device_line():
    info = {}
    parse_log_line(
        "main: using device CUDA1 (NVIDIA GeForce RTX 2080) (CUDA1) - 7121 MiB free", info)
    assert info.get("gpu1_name") == "NVIDIA GeForce RTX 2080"
    assert info.get("gpu_name") == "NVIDIA GeForce RTX 2080"


def test_runtime_info_gpu_summary_line():
    info = {
        "gpu0_name": "NVIDIA GeForce RTX 5090", "gpu0_vram": "32579 MiB",
        "gpu1_name": "NVIDIA GeForce RTX 2080", "gpu1_vram": "8191 MiB",
        "gpu_offload": "33/38 \u5c42",
    }
    html = build_info_html(info)
    assert "GPU\uff08\u672c\u6b21\u8fd0\u884c\uff09" in html  # GPU（本次运行）
    assert "RTX 5090" in html and "RTX 2080" in html
    assert "33/38" in html


def test_runtime_info_summary_omitted_without_gpus():
    html = build_info_html({"cpu_name": "Intel CPU"})
    assert "GPU\uff08\u672c\u6b21\u8fd0\u884c\uff09" not in html


_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def test_basic_panel_gpu_info_dual():
    from ui.basic_panel import BasicPanel
    app = _qapp()  # keep a live reference
    panel = BasicPanel()
    panel.set_gpu_info(parse_device_list(DUAL_OUTPUT))
    assert "RTX 5090" in panel.gpu_info_label.text()
    assert "RTX 2080" in panel.gpu_info_label.text()
    assert "32GB" in panel.gpu_info_label.text()
    assert panel.gpu_info_label.isHidden() is False
    assert "CUDA1: NVIDIA GeForce RTX 2080" in panel.gpu_info_label.toolTip()
    panel.close()


def test_basic_panel_gpu_info_cpu_only():
    from ui.basic_panel import BasicPanel
    app = _qapp()
    panel = BasicPanel()
    panel.set_gpu_info([])
    assert "CPU" in panel.gpu_info_label.text()
    panel.close()


def test_worker_devices_probe(tmp_path, monkeypatch):
    """_emit_defaults runs --list-devices only when the flag is in the help text."""
    import core.defaults as CD
    import ui.main_window as MW
    app = _qapp()

    captured = {"devices": None}
    worker = MW._StartupInfoWorker()
    worker.server_path = "fake-server"
    worker.devices_ready.connect(lambda devs: captured.update(devices=devs))

    fake_help = "usage: llama-server\n  --ngl\n  --list-devices  list devices\n"

    class _Result:
        returncode = 0
        stdout = DUAL_OUTPUT
        stderr = ""

    monkeypatch.setattr(CD, "fetch_help_text", lambda server_path=None: fake_help)
    monkeypatch.setattr(MW.subprocess, "run", lambda *a, **kw: _Result())
    worker._emit_defaults()
    assert captured["devices"] == DEVS

    # no --list-devices in help -> no probe, no devices_ready
    captured["devices"] = None
    monkeypatch.setattr(CD, "fetch_help_text", lambda server_path=None: "usage: llama-server\n")
    worker._emit_defaults()
    assert captured["devices"] is None
