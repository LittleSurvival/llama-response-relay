from __future__ import annotations

from datetime import datetime
import sys
import threading
import traceback
from types import TracebackType

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class CrashLogDialog(QDialog):
    def __init__(
        self,
        crash_log: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.crash_log = crash_log
        self.setWindowTitle("Llama.cpp Launcher — Application error")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(760, 480)
        self.setMinimumSize(560, 360)

        layout = QVBoxLayout(self)
        title = QLabel("The application encountered an unexpected error.")
        title.setProperty("role", "section")
        layout.addWidget(title)
        detail = QLabel(
            "The main window will remain open. Copy the crash log when "
            "reporting this problem, then close this dialog to continue."
        )
        detail.setWordWrap(True)
        detail.setProperty("role", "muted")
        layout.addWidget(detail)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlainText(crash_log)
        self.log_view.setAccessibleName("Crash log")
        layout.addWidget(self.log_view, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.copy_button = QPushButton("Copy crash log")
        buttons.addButton(
            self.copy_button,
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.copy_button.clicked.connect(
            lambda _checked=False: QApplication.clipboard().setText(
                self.crash_log
            )
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CrashHandler(QObject):
    report_requested = pyqtSignal(str)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        self._installed = False
        self._presenting = False
        self._dialogs: list[CrashLogDialog] = []
        self._previous_sys_hook = sys.excepthook
        self._previous_thread_hook = threading.excepthook
        self.report_requested.connect(
            self.present,
            Qt.ConnectionType.QueuedConnection,
        )

    def install(self) -> None:
        if self._installed:
            return
        self._installed = True
        sys.excepthook = self.handle_exception
        threading.excepthook = self.handle_thread_exception

    def uninstall(self) -> None:
        if not self._installed:
            return
        if sys.excepthook == self.handle_exception:
            sys.excepthook = self._previous_sys_hook
        if threading.excepthook == self.handle_thread_exception:
            threading.excepthook = self._previous_thread_hook
        self._installed = False

    def handle_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            self._previous_sys_hook(exc_type, exc_value, exc_traceback)
            return
        self.report_requested.emit(
            self._format_log(
                exc_type,
                exc_value,
                exc_traceback,
                thread_name=threading.current_thread().name,
            )
        )

    def handle_thread_exception(
        self,
        args: threading.ExceptHookArgs,
    ) -> None:
        if args.exc_type is SystemExit:
            return
        self.report_requested.emit(
            self._format_log(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
                thread_name=args.thread.name if args.thread else "Unknown",
            )
        )

    def present(self, crash_log: str) -> None:
        if self._presenting:
            self._stderr_fallback(crash_log, "Crash dialog re-entry blocked.")
            return
        self._presenting = True
        try:
            parent = self.app.activeWindow()
            dialog = CrashLogDialog(crash_log, parent)
            self._dialogs.append(dialog)
            dialog.finished.connect(
                lambda _result, current=dialog: self._forget(current)
            )
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception:
            self._stderr_fallback(crash_log, traceback.format_exc())
        finally:
            self._presenting = False

    def _forget(self, dialog: CrashLogDialog) -> None:
        if dialog in self._dialogs:
            self._dialogs.remove(dialog)
        dialog.deleteLater()

    @staticmethod
    def _format_log(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
        *,
        thread_name: str,
    ) -> str:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        formatted = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        )
        return (
            f"Timestamp: {timestamp}\n"
            f"Thread: {thread_name}\n\n"
            f"{formatted}"
        )

    @staticmethod
    def _stderr_fallback(crash_log: str, handler_error: str) -> None:
        try:
            sys.stderr.write(
                f"{crash_log}\n\nCrash handler failure:\n{handler_error}\n"
            )
            sys.stderr.flush()
        except Exception:
            pass
