"""Regression tests for ServerRunner readiness detection (B3 tail logic).

Background: current llama-server builds print exactly one readiness line,
``srv llama_server: listening on http://...``, immediately followed (same
burst, same readyRead chunk) by two NOTICE lines about the future default
port. The old implementation truncated the rolling tail to 200 chars BEFORE
scanning for the phrase, so the trailing NOTICE text pushed
``listening on http`` out of the window and the UI stayed in "starting"
forever even though the server was up.

The chunks below reproduce the exact lines from a real last_run.log.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.runner import ServerRunner

_app = None


def _qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


# Verbatim lines from a real 2026-era llama-server run (timestamps/levels
# included — they eat most of the 200-char window).
_LISTENING_BURST = (
    "0.11.871.965 I srv  llama_server: model loaded\n"
    "0.11.871.965 I srv  llama_server: listening on http://127.0.0.1:8080\n"
    "0.11.871.965 W srv  llama_server: NOTICE: server default port will be changed to :9931 in a future release\n"
    "0.11.871.965 W srv  llama_server:         ref: https://github.com/ggml-org/llama.cpp/pull/26508\n"
)

# Startup noise that must NOT trigger readiness.
_NOISE = (
    "0.00.052.508 I cmn  common_param: common_params_print_info: verbosity = 3 (adjust with the `-lv N` CLI arg)\n"
    "0.00.054.668 W srv  llama_server: CORS is set to allow all origins ('*') and no API key is set\n"
    "0.00.067.940 I srv    load_model: loading model 'G:\\llm\\Qwen3.8-27B-UD-Q5_K_XL.gguf'\n"
    "0.11.725.350 I srv    load_model: loaded multimodal model, 'G:\\llm\\Qwen3.8-mmproj-BF16.gguf'\n"
)


def _probe():
    """A ServerRunner with signal spies; never starts the QProcess."""
    app = _qapp()  # keep a live reference for the test duration
    runner = ServerRunner()
    events = {"ready": 0, "states": []}
    runner.server_ready.connect(lambda: events.__setitem__("ready", events["ready"] + 1))
    runner.state_changed.connect(lambda s: events["states"].append(s))
    return runner, events


def test_ready_phrase_truncated_out_of_window_same_chunk():
    """The exact regression: listening line + NOTICE lines in one chunk.

    The phrase sits >200 chars from the chunk end, so a check that runs on
    the truncated tail misses it. Must still fire.
    """
    runner, events = _probe()
    runner._check_ready(_NOISE)
    assert events["ready"] == 0
    runner._check_ready(_LISTENING_BURST)
    assert events["ready"] == 1
    assert events["states"] == ["running"]
    assert runner.is_ready


def test_phrase_split_across_chunk_boundary():
    """The phrase itself is cut by a chunk boundary; the retained tail must
    keep the first half so the second chunk completes it."""
    runner, events = _probe()
    runner._check_ready("0.11.871.965 I srv  llama_server: list")
    assert events["ready"] == 0
    runner._check_ready("ening on http://127.0.0.1:8080\n")
    assert events["ready"] == 1


def test_old_format_main_loop_still_detected():
    runner, events = _probe()
    runner._check_ready("main: llama_server.cpp: starting the main loop\n")
    assert events["ready"] == 1
    assert events["states"] == ["running"]


def test_legacy_server_is_listening_still_detected():
    runner, events = _probe()
    runner._check_ready("llama_http_server: server is listening on http://127.0.0.1:58980\n")
    assert events["ready"] == 1


def test_startup_noise_does_not_trigger_ready():
    runner, events = _probe()
    runner._check_ready(_NOISE)
    assert events["ready"] == 0
    assert events["states"] == []


def test_noise_after_ready_is_ignored():
    runner, events = _probe()
    runner._check_ready(_LISTENING_BURST)
    assert events["ready"] == 1
    # Post-ready traffic must not re-emit or touch the tail.
    runner._check_ready("1.09.588.041 I slot get_availabl: id  0 | task -1 | selected slot by LRU, t_last = -1\n" * 5)
    assert events["ready"] == 1
    assert len(events["states"]) == 1
