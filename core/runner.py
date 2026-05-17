from PyQt6.QtCore import QObject, pyqtSignal, QProcess, QTimer
from core.i18n import t


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
        self._log_buffer = ""
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
        self._log_buffer = ""
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
            if not self.process.waitForFinished(3000):
                self.process.kill()
                self.process.waitForFinished(1000)
                if self.process.state() != QProcess.ProcessState.NotRunning:
                    self.process.terminate()
                    self.process.waitForFinished(1000)
            self._kill_timer.stop()
            self._is_running = False
            self._is_stopping = False
        else:
            self._kill_timer.start(3000)

    def _force_kill(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            if not self.process.waitForFinished(2000):
                self.process.terminate()
                self.process.waitForFinished(1000)
                if self.process.state() != QProcess.ProcessState.NotRunning:
                    self._is_running = False
                    self._is_stopping = False
                    self.state_changed.emit("stopped")

    def _check_ready(self, text):
        if not self._is_ready and not self._is_stopping:
            self._log_buffer += text
            if len(self._log_buffer) > self._max_log_buffer:
                self._log_buffer = self._log_buffer[-self._max_log_buffer:]
            lower = self._log_buffer.lower()
            if "starting the main loop" in lower or "server is listening" in lower:
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
        self._log_buffer = ""
        if self._was_stopped_intentionally:
            self.state_changed.emit("stopped")
        elif exit_code != 0:
            self.state_changed.emit("error")
        else:
            self.state_changed.emit("stopped")
