"""
Execution and monitoring panel.

Provides sequence execution controls, real-time status indicators,
deterministic phase tracking, validation results viewer, and event logging.
"""

from __future__ import annotations

import sys
import os
import datetime
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QGroupBox, QSplitter, QFrame,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QFont

from sequence_model import ValidationMessage
from .styles import StatusIndicator, STATUS_COLORS, COLORS


class ExecutionPanel(QWidget):
    """Panel for starting, stopping, and monitoring sequence execution."""

    validate_requested = Signal()
    configure_requested = Signal()
    arm_requested = Signal()
    start_requested = Signal()
    stop_requested = Signal()
    emergency_stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # ── 1. Top Control Buttons Row ──────────────────────────────────────
        controls_group = QGroupBox("Execution Controls")
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setSpacing(10)

        self._btn_validate = QPushButton("🔍 Validate Sequence")
        self._btn_validate.setStyleSheet(
            "QPushButton { border-color: #4488ff; color: #4488ff; font-weight: bold; min-height: 38px; }"
            "QPushButton:hover { background-color: rgba(68, 136, 255, 0.15); }"
        )
        self._btn_validate.clicked.connect(self.validate_requested)
        controls_layout.addWidget(self._btn_validate)

        self._btn_configure = QPushButton("⚙ Configure Hardware")
        self._btn_configure.setStyleSheet(
            "QPushButton { border-color: #aa66ff; color: #aa66ff; font-weight: bold; min-height: 38px; }"
            "QPushButton:hover { background-color: rgba(170, 102, 255, 0.15); }"
        )
        self._btn_configure.clicked.connect(self.configure_requested)
        controls_layout.addWidget(self._btn_configure)

        self._btn_arm = QPushButton("⏳ Arm Analog Tasks")
        self._btn_arm.setStyleSheet(
            "QPushButton { border-color: #ffaa00; color: #ffaa00; font-weight: bold; min-height: 38px; }"
            "QPushButton:hover { background-color: rgba(255, 170, 0, 0.15); }"
        )
        self._btn_arm.clicked.connect(self.arm_requested)
        controls_layout.addWidget(self._btn_arm)

        self._btn_start = QPushButton("▶ Start Experiment")
        self._btn_start.setStyleSheet(
            "QPushButton { background-color: #00aa55; border-color: #00ff88; color: #ffffff; "
            "font-size: 14px; font-weight: bold; min-height: 38px; padding: 0 16px; }"
            "QPushButton:hover { background-color: #00cc66; }"
            "QPushButton:pressed { background-color: #008844; }"
        )
        self._btn_start.clicked.connect(self.start_requested)
        controls_layout.addWidget(self._btn_start)

        self._btn_stop = QPushButton("⬛ Stop Experiment")
        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet(
            "QPushButton { border-color: #ff4444; color: #ff4444; font-weight: bold; min-height: 38px; }"
            "QPushButton:hover { background-color: rgba(255, 68, 68, 0.15); }"
            "QPushButton:disabled { color: #555566; border-color: #333344; }"
        )
        self._btn_stop.clicked.connect(self.stop_requested)
        controls_layout.addWidget(self._btn_stop)

        self._btn_emergency_stop = QPushButton("⚠ EMERGENCY STOP")
        self._btn_emergency_stop.setStyleSheet(
            "QPushButton { background-color: #cc1111; border: 2px solid #ff4444; color: #ffffff; "
            "font-size: 14px; font-weight: bold; min-height: 38px; padding: 0 16px; }"
            "QPushButton:hover { background-color: #ee2222; }"
            "QPushButton:pressed { background-color: #990000; }"
        )
        self._btn_emergency_stop.clicked.connect(self.emergency_stop_requested)
        controls_layout.addWidget(self._btn_emergency_stop)

        main_layout.addWidget(controls_group)

        # ── 2. Real-time Status Dashboards ──────────────────────────────────
        status_group = QGroupBox("Execution Status & Metrics")
        status_layout = QGridLayout(status_group)
        status_layout.setContentsMargins(16, 12, 16, 12)
        status_layout.setHorizontalSpacing(24)

        # Indicator + Phase
        phase_box = QHBoxLayout()
        self._indicator = StatusIndicator(STATUS_COLORS["idle"], size=16)
        self._phase_label = QLabel("Idle")
        self._phase_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #00d4ff;")
        phase_box.addWidget(self._indicator)
        phase_box.addWidget(self._phase_label)
        phase_box.addStretch()

        lbl_phase_title = QLabel("CURRENT PHASE:")
        lbl_phase_title.setStyleSheet("color: #8888a0; font-weight: bold; font-size: 11px;")
        status_layout.addWidget(lbl_phase_title, 0, 0)
        status_layout.addLayout(phase_box, 1, 0)

        # Elapsed Time
        lbl_elapsed_title = QLabel("ELAPSED TIME:")
        lbl_elapsed_title.setStyleSheet("color: #8888a0; font-weight: bold; font-size: 11px;")
        self._elapsed_label = QLabel("00:00:00.000")
        self._elapsed_label.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
        self._elapsed_label.setStyleSheet("color: #ffffff;")
        status_layout.addWidget(lbl_elapsed_title, 0, 1)
        status_layout.addWidget(self._elapsed_label, 1, 1)

        # Cycles
        lbl_cycle_title = QLabel("CYCLE COUNT:")
        lbl_cycle_title.setStyleSheet("color: #8888a0; font-weight: bold; font-size: 11px;")
        self._cycle_label = QLabel("0 / 1")
        self._cycle_label.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
        self._cycle_label.setStyleSheet("color: #00ff88;")
        status_layout.addWidget(lbl_cycle_title, 0, 2)
        status_layout.addWidget(self._cycle_label, 1, 2)

        # Triggers
        lbl_trigger_title = QLabel("ANALOG TRIGGERS:")
        lbl_trigger_title.setStyleSheet("color: #8888a0; font-weight: bold; font-size: 11px;")
        self._trigger_label = QLabel("0")
        self._trigger_label.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
        self._trigger_label.setStyleSheet("color: #ffaa00;")
        status_layout.addWidget(lbl_trigger_title, 0, 3)
        status_layout.addWidget(self._trigger_label, 1, 3)

        main_layout.addWidget(status_group)

        # ── 3. Splitter: Validation Results & Event Log ─────────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Validation Box
        val_group = QGroupBox("Sequence Validation Results")
        val_layout = QVBoxLayout(val_group)
        self._val_list = QListWidget()
        self._val_list.setAlternatingRowColors(True)
        val_layout.addWidget(self._val_list)
        splitter.addWidget(val_group)

        # Log Box
        log_group = QGroupBox("Hardware & Execution Event Log")
        log_layout = QVBoxLayout(log_group)
        
        log_header = QHBoxLayout()
        log_header.addStretch()
        btn_clear_log = QPushButton("Clear Log")
        btn_clear_log.setFixedWidth(90)
        btn_clear_log.clicked.connect(self.clear_log)
        log_header.addWidget(btn_clear_log)
        log_layout.addLayout(log_header)

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Consolas", 10))
        self._log_text.setStyleSheet("background-color: #14141e; border: 1px solid #3a3a4e;")
        log_layout.addWidget(self._log_text)
        splitter.addWidget(log_group)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter)

    # ── Public API ──────────────────────────────────────────────────────

    def set_phase(self, phase: str):
        """Update current execution phase text and indicator color."""
        self._phase_label.setText(phase)
        color_map = {
            "Validating": STATUS_COLORS["configuring"],
            "Initializing": STATUS_COLORS["configuring"],
            "Configuring FPGA": STATUS_COLORS["configuring"],
            "Configuring Analog": STATUS_COLORS["configuring"],
            "Arming Analog": STATUS_COLORS["armed"],
            "Running": STATUS_COLORS["running"],
            "Stopping": STATUS_COLORS["warning"],
            "Safe State": STATUS_COLORS["safe"],
            "Complete": STATUS_COLORS["safe"],
            "Idle": STATUS_COLORS["idle"],
        }
        color = color_map.get(phase, STATUS_COLORS["running"])
        self._indicator.set_color(color)
        self.append_log(f"Phase change: {phase}", "PHASE")

    def set_elapsed_time(self, seconds: float):
        """Display elapsed time in HH:MM:SS.mmm format."""
        total_ms = int(round(seconds * 1000.0))
        hrs = total_ms // 3600000
        mins = (total_ms % 3600000) // 60000
        secs = (total_ms % 60000) // 1000
        ms = total_ms % 1000
        self._elapsed_label.setText(f"{hrs:02d}:{mins:02d}:{secs:02d}.{ms:03d}")

    def set_progress(self, current: int, total: int):
        """Display current cycle and total cycles."""
        tot_str = "∞" if total <= 0 else str(total)
        self._cycle_label.setText(f"{current} / {tot_str}")

    def set_trigger_count(self, count: int):
        """Display received analog hardware trigger count."""
        self._trigger_label.setText(str(count))

    def set_running(self, running: bool):
        """Enable or disable buttons according to running state."""
        self._btn_start.setEnabled(not running)
        self._btn_validate.setEnabled(not running)
        self._btn_configure.setEnabled(not running)
        self._btn_arm.setEnabled(not running)
        self._btn_stop.setEnabled(running)

    def show_validation_results(self, messages: List[ValidationMessage]):
        """Populate the validation results list with color coding."""
        self._val_list.clear()
        if not messages:
            item = QListWidgetItem("✔ Validation passed with no issues detected.")
            item.setForeground(QColor(COLORS["accent_green"]))
            self._val_list.addItem(item)
            return

        for msg in messages:
            prefix = "[ERROR]" if msg.level == "error" else "[WARN]" if msg.level == "warning" else "[INFO]"
            item = QListWidgetItem(f"{prefix} ({msg.source}): {msg.message}")
            if msg.level == "error":
                item.setForeground(QColor(COLORS["accent_red"]))
            elif msg.level == "warning":
                item.setForeground(QColor(COLORS["accent_yellow"]))
            else:
                item.setForeground(QColor(COLORS["accent_blue"]))
            self._val_list.addItem(item)

    def append_log(self, message: str, level: str = "INFO"):
        """Append a timestamped message to the event log."""
        now = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        color = "#e0e0e8"
        if level in ("ERROR", "CRITICAL"):
            color = COLORS["accent_red"]
        elif level in ("WARNING", "WARN"):
            color = COLORS["accent_yellow"]
        elif level in ("SUCCESS", "SAFE"):
            color = COLORS["accent_green"]
        elif level in ("PHASE", "STEP"):
            color = COLORS["accent_cyan"]

        html_line = f"<span style='color: #666688;'>[{now}]</span> <b style='color: {color};'>[{level}]</b> {message}"
        self._log_text.append(html_line)
        # Scroll to bottom
        scrollbar = self._log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log(self):
        """Clear all event log entries."""
        self._log_text.clear()
