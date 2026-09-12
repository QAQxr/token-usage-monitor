"""Compact PySide6 desktop window for the read-only monitor."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .gui import scope_values
from .monitor import SnapshotRefresher, latest_scope


class DragBar(QFrame):
    """Header surface that moves the frameless parent window."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._offset: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._offset = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._offset = None
        super().mouseReleaseEvent(event)


class UsageWindow(QMainWindow):
    """A draggable, always-on-top, independently closable usage window."""

    def __init__(self, root: str | Path, interval: float = 1.0) -> None:
        super().__init__()
        self._scope: Literal["session", "turn"] = "session"
        self._drag_offset: QPoint | None = None
        self._refresher = SnapshotRefresher(root)
        self._values: dict[str, QLabel] = {}
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(max(250, int(float(interval) * 1000)))
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def _build_ui(self) -> None:
        self.setWindowTitle("Token Usage Monitor")
        self.setMinimumSize(430, 310)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )

        root = QWidget(self)
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        header = DragBar(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        eyebrow = QLabel("CODEX OBSERVABILITY")
        eyebrow.setObjectName("eyebrow")
        eyebrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title = QLabel("Token Usage Monitor")
        title.setObjectName("title")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_box.addWidget(eyebrow)
        title_box.addWidget(title)
        header_layout.addLayout(title_box, 1)

        self._status = QLabel("Starting…")
        self._status.setObjectName("status")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self._status)

        self._scope_selector = QComboBox()
        self._scope_selector.addItems(["Session", "Current Turn"])
        self._scope_selector.setFixedWidth(106)
        self._scope_selector.currentTextChanged.connect(self._scope_changed)
        header_layout.addWidget(self._scope_selector)

        close = QPushButton("×")
        close.setObjectName("close")
        close.setFixedSize(28, 28)
        close.setToolTip("Close")
        close.clicked.connect(self.close)
        header_layout.addWidget(close)
        layout.addWidget(header)

        self._scope_label = QLabel("Waiting for rollout data")
        self._scope_label.setObjectName("scope")
        layout.addWidget(self._scope_label)

        cards = QGridLayout()
        cards.setSpacing(7)
        for index, (key, label) in enumerate(
            (
                ("total", "TOTAL TOKENS"),
                ("input", "INPUT"),
                ("cached", "CACHED"),
                ("output", "OUTPUT"),
                ("cache", "CACHE HIT"),
                ("ttft", "TTFT"),
                ("tps", "TPS"),
                ("latency", "LATENCY"),
                ("context", "CONTEXT"),
            )
        ):
            card = QFrame()
            card.setObjectName("card")
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 9)
            card_layout.setSpacing(2)
            caption = QLabel(label)
            caption.setObjectName("caption")
            value = QLabel("—")
            value.setObjectName("value")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card_layout.addWidget(caption)
            card_layout.addWidget(value)
            self._values[key] = value
            cards.addWidget(card, index // 3, index % 3)
        layout.addLayout(cards)

        self._source = QLabel("")
        self._source.setObjectName("source")
        self._source.setWordWrap(True)
        layout.addWidget(self._source)

        self.setStyleSheet(
            """
            QMainWindow, QWidget#root { background: #0c1117; color: #dce7f3; }
            QMainWindow { border: 1px solid #2b3a4a; border-radius: 12px; }
            QLabel#eyebrow, QLabel#caption { color: #8192a5; font-size: 9px; font-weight: 700; letter-spacing: 1px; }
            QLabel#title { color: #f4f8fb; font-size: 17px; font-weight: 700; }
            QLabel#status { padding: 5px 8px; border-radius: 7px; color: #9db0c3; background: #17212b; font-size: 10px; }
            QLabel#status[state="active"] { color: #8df0bc; background: #123326; }
            QLabel#status[state="idle"], QLabel#status[state="no_session"] { color: #ffd27e; background: #382d14; }
            QLabel#status[state="error"] { color: #ff9a9a; background: #3b1e25; }
            QLabel#status[state="no_data"] { color: #9db0c3; background: #17212b; }
            QLabel#scope { color: #9db0c3; font-size: 11px; }
            QLabel#source { color: #617386; font-size: 9px; }
            QFrame#card { background: #121a23; border: 1px solid #223141; border-radius: 8px; }
            QLabel#value { color: #f5f8fb; font-size: 16px; font-weight: 700; }
            QComboBox { color: #dce7f3; background: #17212b; border: 1px solid #304457; border-radius: 6px; padding: 5px 7px; font-size: 10px; }
            QComboBox QAbstractItemView { color: #dce7f3; background: #17212b; selection-background-color: #2b5678; }
            QPushButton#close { color: #9db0c3; background: transparent; border: 0; border-radius: 6px; font-size: 20px; }
            QPushButton#close:hover { color: #ffffff; background: #3b1e25; }
            """
        )

    def _scope_changed(self, value: str) -> None:
        self._scope = "turn" if value == "Current Turn" else "session"
        self.refresh()

    def refresh(self) -> None:
        state = self._refresher.refresh()
        self._status.setText(state.message)
        self._status.setProperty("state", state.status)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

        current = latest_scope(state.snapshot, self._scope)
        values = scope_values(state.snapshot, self._scope)
        for key, value in values.items():
            self._values[key].setText(value)

        if current:
            identifier = current.get("turn_id") if self._scope == "turn" else current.get("session_id")
            self._scope_label.setText(f"{self._scope.title()} · {str(identifier or 'unknown')[-18:]}")
        else:
            self._scope_label.setText(state.message)

        source = state.source_file.name if state.source_file else "No source file"
        error = f" · {state.error}" if state.error else ""
        self._source.setText(f"{source} · refreshed {state.refreshed_at.astimezone().strftime('%H:%M:%S')}{error}")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 48:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)


def run(root: str | Path, interval: float = 1.0) -> int:
    app = QApplication.instance() or QApplication([sys.argv[0]])
    window = UsageWindow(root, interval)
    window.show()
    return app.exec()
