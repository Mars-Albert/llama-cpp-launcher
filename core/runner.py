import logging

from PyQt6.QtCore import QObject, pyqtSignal, QProcess, QTimer
from core.i18n import t

logger = logging.getLogger(__name__)


class ServerRunner(QObject):
    log_output = pyqtSignal(str)
    state_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    server_ready = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._on_finished)
        self._is_running = False
        self._is_ready = False
        self._was_stopped_intentionally = False
        self._log_parts: list[str] = []
        self._log_buffer_len = 0
        self._max_log_buffer = 8000
        self._is_stopping = False
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._force_kill)

    @property
    def is_running(self):
        return self._is_running

    @property
    def is_ready(self):
        return self._is_ready

    def start(self, args, work_dir=None):
        if self._is_running or self._is_stopping:
            return
        cmd = "llama-server"
        self.process.setProgram(cmd)
        self.process.setArguments(args)
        if work_dir:
            self.process.setWorkingDirectory(work_dir)
        self._log_parts.clear()
        self._log_buffer_len = 0
        self._is_running = True
        self._is_ready = False
        self._was_stopped_intentionally = False
        self.process.start()
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._is_running = False
            self.error_occurred.emit(t("启动 llama-server 失败。请确保它在系统 PATH 中。"))
        else:
            self.state_changed.emit("starting")

    def stop(self, blocking=False):
        if not self._is_running or self._is_stopping:
            return
        self._was_stopped_intentionally = True
        self._is_stopping = True
        self._is_ready = False
        self.process.terminate()
        if blocking:
            # 关闭应用时允许阻塞等待
            if not self.process.waitForFinished(8000):
                self._do_force_kill()
            self._kill_timer.stop()
            self._is_running = False
            self._is_stopping = False
        else:
            # 非阻塞路径：定时器到期后执行 kill，不阻塞主线程
            self._kill_timer.start(5000)

    def _do_force_kill(self):
        logger.info("Force killing llama-server process")
        self.process.kill()
        if not self.process.waitForFinished(15000):
            logger.warning("llama-server process did not terminate after force kill")
            if self.process.state() != QProcess.ProcessState.NotRunning:
                self.error_occurred.emit(t("llama-server 进程无法终止，可能需要手动结束。"))

    def _force_kill(self):
        self._kill_timer.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            # 3 秒后异步检查，避免 waitForFinished 阻塞导致界面无响应
            QTimer.singleShot(3000, self._check_force_kill_result)

    def _check_force_kill_result(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            logger.warning("llama-server process still running after force kill")
            self.error_occurred.emit(t("llama-server 进程无法终止，可能需要手动结束。"))

    def _check_ready(self, text):
        if not self._is_ready and not self._is_stopping:
            self._log_parts.append(text)
            self._log_buffer_len += len(text)
            if self._log_buffer_len > self._max_log_buffer:
                while self._log_buffer_len > self._max_log_buffer and len(self._log_parts) > 1:
                    removed = self._log_parts.pop(0)
                    self._log_buffer_len -= len(removed)
            lower = "".join(self._log_parts).lower()
            if "starting the main loop" in lower or "server is listening" in lower or "listening on http" in lower:
                self._is_ready = True
                self.server_ready.emit()
                self.state_changed.emit("running")

    def _read_stream(self, read_method):
        data = read_method().data()
        text = data.decode("utf-8", errors="replace")
        self._check_ready(text)
        self.log_output.emit(text)

    def _read_stdout(self):
        self._read_stream(self.process.readAllStandardOutput)

    def _read_stderr(self):
        self._read_stream(self.process.readAllStandardError)

    def _on_finished(self, exit_code, exit_status):
        self._kill_timer.stop()
        self._is_running = False
        self._is_ready = False
        self._is_stopping = False
        self._log_parts.clear()
        self._log_buffer_len = 0
        if self._was_stopped_intentionally:
            self.state_changed.emit("stopped")
        elif exit_code != 0:
            self.state_changed.emit("error")
        else:
            self.state_changed.emit("stopped")
