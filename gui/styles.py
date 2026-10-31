"""
Dark laboratory-instrument theme stylesheet (QSS) for the GUI.

Provides a professional, dark-themed appearance reminiscent of
high-end lab instrumentation and measurement software.
"""

from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QBrush

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
COLORS = {
    "bg_dark": "#1e1e2e",
    "bg_panel": "#2a2a3a",
    "bg_input": "#1a1a28",
    "bg_hover": "#353548",
    "bg_pressed": "#404058",
    "border": "#3a3a4e",
    "border_light": "#50506a",
    "text": "#e0e0e8",
    "text_dim": "#8888a0",
    "text_bright": "#ffffff",
    "accent_cyan": "#00d4ff",
    "accent_green": "#00ff88",
    "accent_red": "#ff4444",
    "accent_yellow": "#ffaa00",
    "accent_blue": "#4488ff",
    "accent_purple": "#aa66ff",
    "table_alt_row": "#252538",
    "scrollbar_bg": "#1e1e2e",
    "scrollbar_handle": "#3a3a4e",
}

STATUS_COLORS = {
    "connected": "#00ff88",
    "disconnected": "#ff4444",
    "initialized": "#00ff88",
    "uninitialized": "#8888a0",
    "running": "#00d4ff",
    "stopped": "#8888a0",
    "error": "#ff4444",
    "warning": "#ffaa00",
    "idle": "#8888a0",
    "armed": "#ffaa00",
    "configuring": "#aa66ff",
    "ready": "#00d4ff",
    "safe": "#00ff88",
}


def get_stylesheet() -> str:
    """Return the complete QSS stylesheet string for the application."""
    return f"""
    /* ------------------------------------------------------------------ */
    /* Global                                                             */
    /* ------------------------------------------------------------------ */
    QMainWindow, QDialog, QWidget {{
        background-color: {COLORS["bg_dark"]};
        color: {COLORS["text"]};
        font-family: "Segoe UI", "Consolas", sans-serif;
        font-size: 13px;
    }}

    /* ------------------------------------------------------------------ */
    /* Menu bar                                                           */
    /* ------------------------------------------------------------------ */
    QMenuBar {{
        background-color: {COLORS["bg_panel"]};
        color: {COLORS["text"]};
        border-bottom: 1px solid {COLORS["border"]};
        padding: 2px;
    }}
    QMenuBar::item:selected {{
        background-color: {COLORS["bg_hover"]};
        color: {COLORS["accent_cyan"]};
    }}
    QMenu {{
        background-color: {COLORS["bg_panel"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
    }}
    QMenu::item:selected {{
        background-color: {COLORS["bg_hover"]};
        color: {COLORS["accent_cyan"]};
    }}
    QMenu::separator {{
        height: 1px;
        background: {COLORS["border"]};
        margin: 4px 8px;
    }}

    /* ------------------------------------------------------------------ */
    /* Tab widget                                                         */
    /* ------------------------------------------------------------------ */
    QTabWidget::pane {{
        border: 1px solid {COLORS["border"]};
        background-color: {COLORS["bg_dark"]};
    }}
    QTabBar::tab {{
        background-color: {COLORS["bg_panel"]};
        color: {COLORS["text_dim"]};
        border: 1px solid {COLORS["border"]};
        border-bottom: none;
        padding: 8px 18px;
        margin-right: 2px;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }}
    QTabBar::tab:selected {{
        background-color: {COLORS["bg_dark"]};
        color: {COLORS["accent_cyan"]};
        border-bottom: 2px solid {COLORS["accent_cyan"]};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {COLORS["bg_hover"]};
        color: {COLORS["text"]};
    }}

    /* ------------------------------------------------------------------ */
    /* Group boxes                                                        */
    /* ------------------------------------------------------------------ */
    QGroupBox {{
        background-color: {COLORS["bg_panel"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 6px;
        margin-top: 14px;
        padding: 12px 8px 8px 8px;
        font-weight: bold;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 2px 10px;
        color: {COLORS["accent_cyan"]};
    }}

    /* ------------------------------------------------------------------ */
    /* Buttons                                                            */
    /* ------------------------------------------------------------------ */
    QPushButton {{
        background-color: {COLORS["bg_panel"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border_light"]};
        border-radius: 4px;
        padding: 6px 16px;
        min-height: 24px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: {COLORS["bg_hover"]};
        border-color: {COLORS["accent_cyan"]};
        color: {COLORS["accent_cyan"]};
    }}
    QPushButton:pressed {{
        background-color: {COLORS["bg_pressed"]};
        border-color: {COLORS["accent_cyan"]};
    }}
    QPushButton:disabled {{
        background-color: {COLORS["bg_dark"]};
        color: {COLORS["text_dim"]};
        border-color: {COLORS["border"]};
    }}

    /* Named button variants via object names */
    QPushButton#btn_start {{
        background-color: #1a3a2a;
        border-color: {COLORS["accent_green"]};
        color: {COLORS["accent_green"]};
        font-size: 15px;
        min-height: 36px;
    }}
    QPushButton#btn_start:hover {{
        background-color: #2a4a3a;
    }}
    QPushButton#btn_stop {{
        background-color: #3a1a1a;
        border-color: {COLORS["accent_red"]};
        color: {COLORS["accent_red"]};
        font-size: 15px;
        min-height: 36px;
    }}
    QPushButton#btn_stop:hover {{
        background-color: #4a2a2a;
    }}
    QPushButton#btn_emergency {{
        background-color: {COLORS["accent_red"]};
        color: #ffffff;
        border: 2px solid #ff0000;
        font-size: 14px;
        font-weight: bold;
        min-height: 36px;
    }}
    QPushButton#btn_emergency:hover {{
        background-color: #ff6666;
    }}
    QPushButton#btn_validate {{
        border-color: {COLORS["accent_blue"]};
        color: {COLORS["accent_blue"]};
    }}
    QPushButton#btn_configure {{
        border-color: {COLORS["accent_cyan"]};
        color: {COLORS["accent_cyan"]};
    }}
    QPushButton#btn_arm {{
        border-color: {COLORS["accent_yellow"]};
        color: {COLORS["accent_yellow"]};
    }}

    /* ------------------------------------------------------------------ */
    /* Inputs                                                             */
    /* ------------------------------------------------------------------ */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 3px;
        padding: 4px 8px;
        selection-background-color: {COLORS["accent_cyan"]};
        selection-color: {COLORS["bg_dark"]};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border-color: {COLORS["accent_cyan"]};
    }}
    QLineEdit:read-only {{
        background-color: {COLORS["bg_panel"]};
        color: {COLORS["text_dim"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {COLORS["bg_panel"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        selection-background-color: {COLORS["bg_hover"]};
        selection-color: {COLORS["accent_cyan"]};
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        background-color: {COLORS["bg_panel"]};
        border: 1px solid {COLORS["border"]};
        width: 16px;
    }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
        background-color: {COLORS["bg_hover"]};
    }}

    /* ------------------------------------------------------------------ */
    /* Tables                                                             */
    /* ------------------------------------------------------------------ */
    QTableWidget, QTableView {{
        background-color: {COLORS["bg_dark"]};
        alternate-background-color: {COLORS["table_alt_row"]};
        color: {COLORS["text"]};
        gridline-color: {COLORS["border"]};
        border: 1px solid {COLORS["border"]};
        selection-background-color: #2a3a5a;
        selection-color: {COLORS["accent_cyan"]};
    }}
    QHeaderView::section {{
        background-color: {COLORS["bg_panel"]};
        color: {COLORS["accent_cyan"]};
        border: 1px solid {COLORS["border"]};
        padding: 4px 8px;
        font-weight: bold;
    }}

    /* ------------------------------------------------------------------ */
    /* Text edits                                                         */
    /* ------------------------------------------------------------------ */
    QTextEdit, QPlainTextEdit {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 3px;
        font-family: "Consolas", "Courier New", monospace;
        font-size: 12px;
    }}

    /* ------------------------------------------------------------------ */
    /* Splitter                                                           */
    /* ------------------------------------------------------------------ */
    QSplitter::handle {{
        background-color: {COLORS["border"]};
    }}
    QSplitter::handle:horizontal {{
        width: 3px;
    }}
    QSplitter::handle:vertical {{
        height: 3px;
    }}

    /* ------------------------------------------------------------------ */
    /* Scroll bars                                                        */
    /* ------------------------------------------------------------------ */
    QScrollBar:vertical {{
        background-color: {COLORS["scrollbar_bg"]};
        width: 12px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: {COLORS["scrollbar_handle"]};
        border-radius: 4px;
        min-height: 30px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {COLORS["border_light"]};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background-color: {COLORS["scrollbar_bg"]};
        height: 12px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {COLORS["scrollbar_handle"]};
        border-radius: 4px;
        min-width: 30px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {COLORS["border_light"]};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ------------------------------------------------------------------ */
    /* Check boxes                                                        */
    /* ------------------------------------------------------------------ */
    QCheckBox {{
        spacing: 6px;
        color: {COLORS["text"]};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {COLORS["border_light"]};
        border-radius: 3px;
        background-color: {COLORS["bg_input"]};
    }}
    QCheckBox::indicator:checked {{
        background-color: {COLORS["accent_cyan"]};
        border-color: {COLORS["accent_cyan"]};
    }}

    /* ------------------------------------------------------------------ */
    /* Labels (monospace override)                                         */
    /* ------------------------------------------------------------------ */
    QLabel#lbl_mono {{
        font-family: "Consolas", "Courier New", monospace;
        font-size: 14px;
    }}
    QLabel#lbl_phase {{
        font-family: "Consolas", "Courier New", monospace;
        font-size: 18px;
        font-weight: bold;
        color: {COLORS["accent_cyan"]};
    }}

    /* ------------------------------------------------------------------ */
    /* Status bar                                                         */
    /* ------------------------------------------------------------------ */
    QStatusBar {{
        background-color: {COLORS["bg_panel"]};
        color: {COLORS["text_dim"]};
        border-top: 1px solid {COLORS["border"]};
    }}

    /* ------------------------------------------------------------------ */
    /* Tool tips                                                          */
    /* ------------------------------------------------------------------ */
    QToolTip {{
        background-color: {COLORS["bg_panel"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["accent_cyan"]};
        padding: 4px;
    }}

    /* ------------------------------------------------------------------ */
    /* List widgets                                                       */
    /* ------------------------------------------------------------------ */
    QListWidget {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 3px;
        outline: none;
    }}
    QListWidget::item:selected {{
        background-color: #2a3a5a;
        color: {COLORS["accent_cyan"]};
    }}
    QListWidget::item:hover {{
        background-color: {COLORS["bg_hover"]};
    }}

    /* ------------------------------------------------------------------ */
    /* Progress bar                                                       */
    /* ------------------------------------------------------------------ */
    QProgressBar {{
        background-color: {COLORS["bg_input"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 4px;
        text-align: center;
        color: {COLORS["text"]};
        height: 20px;
    }}
    QProgressBar::chunk {{
        background-color: {COLORS["accent_cyan"]};
        border-radius: 3px;
    }}
    """


# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------


class StatusIndicator(QWidget):
    """A small coloured dot used as a status indicator."""

    def __init__(self, color: str = "#8888a0", size: int = 12, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size + 4, size + 4)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color))
        x = (self.width() - self._size) // 2
        y = (self.height() - self._size) // 2
        painter.drawEllipse(x, y, self._size, self._size)
        painter.end()


def create_status_row(label_text: str, initial_color: str = "#8888a0",
                      initial_status: str = "Unknown") -> tuple:
    """Create a horizontal layout with a status dot and label.

    Returns ``(container_widget, indicator, status_label)`` so the caller
    can update them later.
    """
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    indicator = StatusIndicator(initial_color)
    status_label = QLabel(initial_status)
    status_label.setStyleSheet(f"color: {initial_color};")

    layout.addWidget(indicator)
    layout.addWidget(status_label)
    layout.addStretch()

    return container, indicator, status_label


def make_colored_button(text: str, color: str, object_name: str = "") -> None:
    """Return inline QSS for a button with the given accent *color*."""
    return (
        f"QPushButton {{ border-color: {color}; color: {color}; }}"
        f"QPushButton:hover {{ background-color: {color}22; }}"
    )
