"""
Digital sequence editor for configuring FPGA TTL outputs.

Enforces physical FPGA architecture of 1 pulse window per channel per cycle.
Generically discovers and gives control for all channels that have matching start
and end registers in the FPGA bitfile, supporting dynamic channel addition,
microsecond/millisecond/second/tick units, and dedicated configuration settings.
"""

from __future__ import annotations

import sys
import os
import re
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QLineEdit, QComboBox, QDoubleSpinBox,
    QSpinBox, QPushButton, QCheckBox, QDialog, QFormLayout,
    QDialogButtonBox, QAbstractItemView, QGroupBox, QMessageBox,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QFont

from sequence_model import (
    DigitalEvent, RepeatMode, TimeUnit, FPGA_CLOCK_HZ,
)
from .styles import COLORS

DIO_COLORS = [
    "#00d4ff", "#00ff88", "#ffaa00", "#ff4444", "#aa66ff",
    "#4488ff", "#ff88dd", "#88ffcc", "#ffcc00", "#44ddff",
    "#66ffaa", "#ff6666", "#cc88ff", "#55aaff", "#ffaacc",
    "#aaffdd", "#ffdd44", "#33bbff", "#88ff88", "#ff9955",
    "#e040fb",  # DIO20
]


def get_channel_color(idx: int) -> str:
    """Return a distinct, high-contrast hex color for any channel index."""
    if 0 <= idx < len(DIO_COLORS):
        return DIO_COLORS[idx]
    hue = int(((idx * 0.618033988749895) % 1.0) * 360)
    return QColor.fromHsv(hue, 220, 255).name()


COL_ENABLE = 0
COL_CHANNEL = 1
COL_LABEL = 2
COL_START = 3
COL_END = 4
COL_DURATION = 5
COL_TICKS = 6
COL_CONFIGURE = 7
NUM_COLS = 8

HEADERS = [
    "Enable", "Channel (FPGA Registers)", "Label", "Start Time",
    "End Time", "Duration", "FPGA Ticks (40MHz)", "Settings",
]


# ────────────────────────────────────────────────────────────────────────
#  Digital Channel Configuration Dialog Window
# ────────────────────────────────────────────────────────────────────────

class DigitalChannelConfigDialog(QDialog):
    """Configuration settings window for a single digital TTL channel."""

    def __init__(
        self,
        event: DigitalEvent,
        channel_idx: int,
        clock_hz: int = FPGA_CLOCK_HZ,
        channel_info: Optional[Dict[str, Any]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._dev = event
        self.channel_idx = channel_idx
        self.clock = clock_hz
        self.channel_info = channel_info or {}
        color = get_channel_color(channel_idx)

        ch_name = self.channel_info.get("name", f"DIO{channel_idx}")
        start_reg = self.channel_info.get("start_reg", f"dio{channel_idx}start")
        end_reg = self.channel_info.get("end_reg", f"dio{channel_idx}end")

        self.setWindowTitle(f"Configure Digital Channel {ch_name}")
        self.resize(480, 440)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; color: #ffffff; }
            QLabel { color: #d0d0e0; font-size: 11px; }
            QGroupBox { border: 1px solid #3d3d5c; border-radius: 6px; margin-top: 8px; padding-top: 14px; font-weight: bold; color: #00d4ff; }
            QLineEdit, QDoubleSpinBox, QComboBox { background-color: #2a2a3e; border: 1px solid #4d4d6e; color: #ffffff; border-radius: 4px; padding: 4px 6px; }
            QPushButton { background-color: #2b3b55; color: #ffffff; border: 1px solid #4a5a75; border-radius: 4px; padding: 6px 14px; }
            QPushButton:hover { background-color: #3b4b6b; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header Badge
        hdr = QHBoxLayout()
        badge = QLabel(f"  {ch_name}  ")
        badge.setStyleSheet(f"background-color: {color}; color: #000000; font-weight: bold; font-size: 13px; border-radius: 4px; padding: 4px;")
        hdr.addWidget(badge)
        if channel_idx < 8:
            hdr_info = QLabel(f"Registers: <b>{start_reg}</b> / <b>{end_reg}</b> | Linked: <b>Trig {channel_idx} -> AO{channel_idx}</b>")
        else:
            hdr_info = QLabel(f"Registers: <b>{start_reg}</b> / <b>{end_reg}</b> (General Digital Output)")
        hdr.addWidget(hdr_info)
        hdr.addStretch()
        layout.addLayout(hdr)

        # General Settings Group
        grp_gen = QGroupBox("General Channel Settings")
        form_gen = QFormLayout(grp_gen)

        self._enable_chk = QCheckBox("Enable this channel in sequence")
        self._enable_chk.setChecked(event.enabled)
        form_gen.addRow("Active State:", self._enable_chk)

        self._label_edit = QLineEdit(event.name or event.label or ch_name)
        form_gen.addRow("Channel Label:", self._label_edit)

        self._notes_edit = QLineEdit(event.notes or "")
        form_gen.addRow("Notes / Function:", self._notes_edit)
        layout.addWidget(grp_gen)

        # Timing Group
        grp_time = QGroupBox("Pulse Timing (When to Start & When to End)")
        form_time = QFormLayout(grp_time)

        self._unit_combo = QComboBox()
        self._unit_combo.addItems(["µs (Microseconds)", "ms (Milliseconds)", "s (Seconds)", "ticks (25 ns)"])
        self._unit_combo.setCurrentIndex(0)  # default us
        self._unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        form_time.addRow("Time Unit:", self._unit_combo)

        # Start Time Control
        self._start_spin = QDoubleSpinBox()
        self._start_spin.setRange(0.0, 10000000.0)
        self._start_spin.setDecimals(4)
        self._start_spin.setSuffix(" µs")
        self._start_spin.valueChanged.connect(self._on_time_changed)
        form_time.addRow(f"Start Time ({start_reg}):", self._start_spin)

        # End Time Control
        self._end_spin = QDoubleSpinBox()
        self._end_spin.setRange(0.0, 10000000.0)
        self._end_spin.setDecimals(4)
        self._end_spin.setSuffix(" µs")
        self._end_spin.valueChanged.connect(self._on_time_changed)
        form_time.addRow(f"End Time ({end_reg}):", self._end_spin)

        # Computed Ticks & Duration
        self._ticks_lbl = QLabel()
        self._ticks_lbl.setStyleSheet("color: #00ff88; font-weight: bold; font-family: Consolas;")
        form_time.addRow("Computed Range:", self._ticks_lbl)
        layout.addWidget(grp_time)

        # Quick Preset Buttons
        btn_box = QHBoxLayout()
        btn_box.addWidget(QLabel("Quick Presets:"))
        for name, dur_us in [("+10 µs", 10.0), ("+50 µs", 50.0), ("+1 ms", 1000.0), ("+10 ms", 10000.0)]:
            pb = QPushButton(name)
            pb.clicked.connect(lambda _, d=dur_us: self._apply_duration(d))
            btn_box.addWidget(pb)
        btn_box.addStretch()
        layout.addLayout(btn_box)

        # Dialog Buttons
        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bbox.accepted.connect(self._on_save)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

        self._current_unit = "us"
        self._load_from_ticks()

    def _apply_duration(self, dur_us: float):
        """Add given duration to start time."""
        mult = self._get_multiplier()
        st_s = self._start_spin.value() * mult
        new_end_s = st_s + (dur_us * 1e-6)
        self._end_spin.setValue(new_end_s / mult)

    def _get_multiplier(self) -> float:
        """Multiplier from current unit to seconds."""
        if self._current_unit == "us":
            return 1e-6
        elif self._current_unit == "ms":
            return 1e-3
        elif self._current_unit == "s":
            return 1.0
        else:
            return 1.0 / self.clock

    def _load_from_ticks(self):
        st_s = self._dev.start_ticks / self.clock
        end_s = self._dev.end_ticks / self.clock
        mult = self._get_multiplier()

        self._start_spin.blockSignals(True)
        self._end_spin.blockSignals(True)
        self._start_spin.setValue(st_s / mult)
        self._end_spin.setValue(end_s / mult)
        self._start_spin.blockSignals(False)
        self._end_spin.blockSignals(False)
        self._update_ticks_label()

    def _on_unit_changed(self, idx: int):
        units = ["us", "ms", "s", "ticks"]
        self._current_unit = units[idx]
        unit_names = ["µs", "ms", "s", "ticks"]
        suffix = f" {unit_names[idx]}"
        self._start_spin.setSuffix(suffix)
        self._end_spin.setSuffix(suffix)
        self._start_spin.setDecimals(4 if idx != 3 else 0)
        self._end_spin.setDecimals(4 if idx != 3 else 0)
        self._load_from_ticks()

    def _on_time_changed(self):
        mult = self._get_multiplier()
        st_s = self._start_spin.value() * mult
        end_s = self._end_spin.value() * mult
        st_ticks = int(round(st_s * self.clock))
        end_ticks = int(round(end_s * self.clock))
        dur_ticks = max(0, end_ticks - st_ticks)
        dur_us = (dur_ticks / self.clock) * 1e6
        self._ticks_lbl.setText(f"{st_ticks:,} → {end_ticks:,} ticks (Width: {dur_ticks:,} ticks = {dur_us:.3f} µs)")

    def _update_ticks_label(self):
        st_ticks = self._dev.start_ticks
        end_ticks = self._dev.end_ticks
        dur_ticks = max(0, end_ticks - st_ticks)
        dur_us = (dur_ticks / self.clock) * 1e6
        self._ticks_lbl.setText(f"{st_ticks:,} → {end_ticks:,} ticks (Width: {dur_ticks:,} ticks = {dur_us:.3f} µs)")

    def _on_save(self):
        mult = self._get_multiplier()
        st_s = self._start_spin.value() * mult
        end_s = self._end_spin.value() * mult
        def_name = self.channel_info.get("name", f"DIO{self.channel_idx}")

        self._dev.name = self._label_edit.text().strip() or def_name
        self._dev.label = self._dev.name
        self._dev.notes = self._notes_edit.text().strip()
        self._dev.enabled = self._enable_chk.isChecked()
        self._dev.start_ticks = max(0, int(round(st_s * self.clock)))
        self._dev.end_ticks = max(self._dev.start_ticks, int(round(end_s * self.clock)))
        self.accept()


# ────────────────────────────────────────────────────────────────────────
#  Digital Sequence Editor Table Panel (General Start/End Channels)
# ────────────────────────────────────────────────────────────────────────

class DigitalSequenceEditor(QWidget):
    """Direct digital sequence editor table providing Start and End controls for every channel."""

    sequence_changed = Signal()
    duration_changed = Signal(int)
    auto_detect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._events: List[DigitalEvent] = []
        self._channels_info: List[Dict[str, Any]] = []
        self._clock_hz = FPGA_CLOCK_HZ
        self._sequence_duration_ticks = FPGA_CLOCK_HZ  # Default 1 second
        self._display_unit = "ms"
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Top Control Bar
        tb = QHBoxLayout()
        tb.setSpacing(8)

        lbl_title = QLabel("Digital TTL Channels (FPGA Target)")
        lbl_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #00d4ff;")
        tb.addWidget(lbl_title)

        tb.addSpacing(16)
        tb.addWidget(QLabel("Time Unit:"))
        self._unit_combo = QComboBox()
        self._unit_combo.addItems(["ms (Milliseconds)", "µs (Microseconds)", "s (Seconds)", "ticks (25 ns)"])
        self._unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        tb.addWidget(self._unit_combo)

        tb.addSpacing(12)
        tb.addWidget(QLabel("Duration (y):"))
        self._dur_spin = QDoubleSpinBox()
        self._dur_spin.setRange(0.0001, 1000000.0)
        self._dur_spin.setDecimals(4)
        self._dur_spin.setValue(1000.0)  # 1000 ms
        self._dur_spin.setSuffix(" ms")
        self._dur_spin.valueChanged.connect(self._on_sequence_duration_changed)
        tb.addWidget(self._dur_spin)

        tb.addSpacing(12)
        tb.addWidget(QLabel("Repeat Mode:"))
        self._repeat_combo = QComboBox()
        self._repeat_combo.addItems(["Single", "Continuous", "Count"])
        self._repeat_combo.currentIndexChanged.connect(self._on_repeat_mode_changed)
        tb.addWidget(self._repeat_combo)

        self._repeat_count_spin = QSpinBox()
        self._repeat_count_spin.setRange(1, 1000000)
        self._repeat_count_spin.setValue(1)
        self._repeat_count_spin.setEnabled(False)
        self._repeat_count_spin.valueChanged.connect(lambda _: self.sequence_changed.emit())
        tb.addWidget(self._repeat_count_spin)

        tb.addSpacing(8)
        btn_enable_all = QPushButton("✔ Enable All")
        btn_enable_all.clicked.connect(lambda: self._set_all_enabled(True))
        tb.addWidget(btn_enable_all)

        btn_disable_all = QPushButton("✖ Disable All")
        btn_disable_all.clicked.connect(lambda: self._set_all_enabled(False))
        tb.addWidget(btn_disable_all)

        # Dynamic channel management buttons
        btn_add_ch = QPushButton("➕ Add Channel")
        btn_add_ch.setStyleSheet("color: #00ff88; font-weight: bold;")
        btn_add_ch.clicked.connect(self._on_add_channel_clicked)
        tb.addWidget(btn_add_ch)

        btn_remove_ch = QPushButton("➖ Remove Channel")
        btn_remove_ch.clicked.connect(self._on_remove_channel_clicked)
        tb.addWidget(btn_remove_ch)

        btn_autodetect = QPushButton("🔄 Auto-Detect from Bitfile")
        btn_autodetect.setStyleSheet("color: #00d4ff; font-weight: bold;")
        btn_autodetect.setToolTip("Automatically discover all start/end register pairs from the active FPGA bitfile")
        btn_autodetect.clicked.connect(self.auto_detect_requested.emit)
        tb.addWidget(btn_autodetect)

        tb.addStretch()
        layout.addLayout(tb)

        # Dynamic Channel Table (Enforces Exactly 1 Pulse per Channel)
        self._table = QTableWidget(0, NUM_COLS)
        self._table.setHorizontalHeaderLabels(HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(COL_ENABLE, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_CHANNEL, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_LABEL, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(COL_START, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_END, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_DURATION, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_TICKS, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_CONFIGURE, QHeaderView.ResizeMode.ResizeToContents)
        self._table.cellDoubleClicked.connect(self._on_table_double_clicked)
        layout.addWidget(self._table, 1)

        # Initialize with default 21 channels
        self._init_default_channels(21)

    def _init_default_channels(self, count: int = 21):
        """Initialize channels and metadata."""
        channels = []
        for i in range(count):
            channels.append({
                "channel": i,
                "prefix": f"dio{i}",
                "name": f"DIO{i}",
                "start_reg": f"dio{i}start",
                "end_reg": "dio4end " if i == 4 else f"dio{i}end",
            })
        self.set_channels(channels)

    def set_channels(self, channels: List[Dict[str, Any]] | int):
        """Generally set channel configuration based on discovered or configured channels."""
        if isinstance(channels, int):
            ch_list = []
            for i in range(channels):
                ch_list.append({
                    "channel": i,
                    "prefix": f"dio{i}",
                    "name": f"DIO{i}",
                    "start_reg": f"dio{i}start",
                    "end_reg": "dio4end " if i == 4 else f"dio{i}end",
                })
            channels = ch_list

        self._channels_info = list(channels)
        num_channels = len(self._channels_info)

        # Preserve existing event values where matching
        old_map = {ev.channel: ev for ev in self._events}
        new_events: List[DigitalEvent] = []

        for ch_info in self._channels_info:
            ch_idx = ch_info["channel"]
            def_name = ch_info.get("name", f"DIO{ch_idx}")
            if ch_idx in old_map:
                ev = old_map[ch_idx]
                if not ev.name:
                    ev.name = def_name
                new_events.append(ev)
            else:
                ev = DigitalEvent(
                    name=def_name,
                    channel=ch_idx,
                    label=def_name,
                    start_ticks=0,
                    end_ticks=0,
                    enabled=False,
                )
                new_events.append(ev)

        self._events = new_events
        self._table.setRowCount(num_channels)
        self._populate_table()

    def _on_add_channel_clicked(self):
        """Add a new digital channel dynamically."""
        new_ch_idx = len(self._events)
        name = f"DIO{new_ch_idx}"
        ch_info = {
            "channel": new_ch_idx,
            "prefix": f"dio{new_ch_idx}",
            "name": name,
            "start_reg": f"dio{new_ch_idx}start",
            "end_reg": f"dio{new_ch_idx}end",
        }
        self._channels_info.append(ch_info)
        ev = DigitalEvent(
            name=name,
            channel=new_ch_idx,
            label=name,
            start_ticks=0,
            end_ticks=0,
            enabled=False,
        )
        self._events.append(ev)
        self._table.setRowCount(len(self._events))
        self._populate_table()
        self.sequence_changed.emit()

    def _on_remove_channel_clicked(self):
        """Remove the selected or last channel."""
        if len(self._events) <= 1:
            QMessageBox.information(self, "Remove Channel", "At least one digital channel must remain.")
            return

        selected_row = self._table.currentRow()
        if selected_row < 0 or selected_row >= len(self._events):
            selected_row = len(self._events) - 1

        self._events.pop(selected_row)
        if selected_row < len(self._channels_info):
            self._channels_info.pop(selected_row)

        self._table.setRowCount(len(self._events))
        self._populate_table()
        self.sequence_changed.emit()

    def _populate_table(self):
        """Populate table rows with Start and End controls for each channel."""
        self._table.blockSignals(True)
        mult = self._get_time_mult()
        unit_lbl = self._display_unit
        num_rows = len(self._events)

        for row in range(num_rows):
            ev = self._events[row]
            ch_idx = ev.channel
            color = get_channel_color(ch_idx)

            ch_info = self._channels_info[row] if row < len(self._channels_info) else {}
            start_reg = ch_info.get("start_reg", f"dio{ch_idx}start")
            end_reg = ch_info.get("end_reg", f"dio{ch_idx}end")
            ch_name = ch_info.get("name", f"DIO{ch_idx}")

            # 1. Enable Checkbox
            chk = QCheckBox()
            chk.setChecked(ev.enabled)
            chk.toggled.connect(lambda state, r=row: self._on_enable_toggled(r, state))
            chk_w = QWidget()
            ch_lay = QHBoxLayout(chk_w)
            ch_lay.setContentsMargins(8, 2, 8, 2)
            ch_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ch_lay.addWidget(chk)
            self._table.setCellWidget(row, COL_ENABLE, chk_w)

            # 2. Channel Badge with FPGA start/end register tooltip
            badge_text = f"  {ch_name}  "
            badge_lbl = QLabel(badge_text)
            badge_lbl.setStyleSheet(f"background-color: {color}; color: #000000; font-weight: bold; border-radius: 4px; padding: 2px;")
            badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge_lbl.setToolTip(f"FPGA Start Register: '{start_reg}'\nFPGA End Register: '{end_reg}'")
            self._table.setCellWidget(row, COL_CHANNEL, badge_lbl)

            # 3. Label Edit
            lbl_edit = QLineEdit(ev.name or ev.label or ch_name)
            lbl_edit.textChanged.connect(lambda txt, r=row: self._on_label_changed(r, txt))
            self._table.setCellWidget(row, COL_LABEL, lbl_edit)

            # 4. Start Time SpinBox -> DIRECT CONTROL FOR START
            st_s = ev.start_ticks / self._clock_hz
            st_spin = QDoubleSpinBox()
            st_spin.setRange(0.0, 10000000.0)
            st_spin.setDecimals(4 if unit_lbl != "ticks" else 0)
            st_spin.setSuffix(f" {unit_lbl}")
            st_spin.setValue(st_s / mult)
            st_spin.setToolTip(f"Start time written to FPGA register '{start_reg}'")
            st_spin.valueChanged.connect(lambda val, r=row: self._on_start_changed(r, val))
            self._table.setCellWidget(row, COL_START, st_spin)

            # 5. End Time SpinBox -> DIRECT CONTROL FOR END
            end_s = ev.end_ticks / self._clock_hz
            end_spin = QDoubleSpinBox()
            end_spin.setRange(0.0, 10000000.0)
            end_spin.setDecimals(4 if unit_lbl != "ticks" else 0)
            end_spin.setSuffix(f" {unit_lbl}")
            end_spin.setValue(end_s / mult)
            end_spin.setToolTip(f"End time written to FPGA register '{end_reg}'")
            end_spin.valueChanged.connect(lambda val, r=row: self._on_end_changed(r, val))
            self._table.setCellWidget(row, COL_END, end_spin)

            # 6. Duration Display
            dur_s = max(0.0, (ev.end_ticks - ev.start_ticks) / self._clock_hz)
            dur_val = dur_s / mult
            dur_item = QTableWidgetItem(f"{dur_val:.4g} {unit_lbl}")
            dur_item.setFlags(dur_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            dur_item.setForeground(QColor("#00ff88"))
            self._table.setItem(row, COL_DURATION, dur_item)

            # 7. Ticks Display
            ticks_item = QTableWidgetItem(f"{ev.start_ticks:,} → {ev.end_ticks:,}")
            ticks_item.setFlags(ticks_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            ticks_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            ticks_item.setFont(QFont("Consolas", 8))
            self._table.setItem(row, COL_TICKS, ticks_item)

            # 8. Configure Button
            btn_cfg = QPushButton("⚙ Configure…")
            btn_cfg.setStyleSheet("background-color: #2b3b55; color: #00d4ff; font-weight: bold; padding: 2px 8px;")
            btn_cfg.clicked.connect(lambda _, r=row: self._open_config_dialog(r))
            self._table.setCellWidget(row, COL_CONFIGURE, btn_cfg)

        self._table.blockSignals(False)

    def _get_time_mult(self) -> float:
        """Multiplier from unit to seconds."""
        if self._display_unit == "µs":
            return 1e-6
        elif self._display_unit == "ms":
            return 1e-3
        elif self._display_unit == "s":
            return 1.0
        else:  # ticks
            return 1.0 / self._clock_hz

    def _on_unit_changed(self, idx: int):
        units = ["ms", "µs", "s", "ticks"]
        self._display_unit = units[idx]
        mult = self._get_time_mult()
        total_s = self._sequence_duration_ticks / self._clock_hz
        self._dur_spin.blockSignals(True)
        self._dur_spin.setSuffix(f" {self._display_unit}")
        self._dur_spin.setValue(total_s / mult)
        self._dur_spin.blockSignals(False)
        self._populate_table()

    def _on_sequence_duration_changed(self, val: float):
        mult = self._get_time_mult()
        total_s = val * mult
        self._sequence_duration_ticks = max(1, int(round(total_s * self._clock_hz)))
        self.duration_changed.emit(self._sequence_duration_ticks)
        self.sequence_changed.emit()

    def _on_repeat_mode_changed(self, idx: int):
        self._repeat_count_spin.setEnabled(idx == 2)  # Count mode
        self.sequence_changed.emit()

    def _on_enable_toggled(self, row: int, state: bool):
        if 0 <= row < len(self._events):
            self._events[row].enabled = state
            self.sequence_changed.emit()

    def _on_label_changed(self, row: int, text: str):
        if 0 <= row < len(self._events):
            self._events[row].name = text
            self._events[row].label = text
            self.sequence_changed.emit()

    def _on_start_changed(self, row: int, val: float):
        if 0 <= row < len(self._events):
            mult = self._get_time_mult()
            st_s = val * mult
            ev = self._events[row]
            ev.start_ticks = max(0, int(round(st_s * self._clock_hz)))
            if ev.end_ticks < ev.start_ticks:
                ev.end_ticks = ev.start_ticks
            self._update_row_timing(row)
            self.sequence_changed.emit()

    def _on_end_changed(self, row: int, val: float):
        if 0 <= row < len(self._events):
            mult = self._get_time_mult()
            end_s = val * mult
            ev = self._events[row]
            ev.end_ticks = max(ev.start_ticks, int(round(end_s * self._clock_hz)))
            self._update_row_timing(row)
            self.sequence_changed.emit()

    def _update_row_timing(self, row: int):
        if 0 <= row < len(self._events):
            ev = self._events[row]
            dur_s = max(0.0, (ev.end_ticks - ev.start_ticks) / self._clock_hz)
            mult = self._get_time_mult()
            dur_item = self._table.item(row, COL_DURATION)
            if dur_item:
                dur_item.setText(f"{dur_s / mult:.4g} {self._display_unit}")
            ticks_item = self._table.item(row, COL_TICKS)
            if ticks_item:
                ticks_item.setText(f"{ev.start_ticks:,} → {ev.end_ticks:,}")

    def _on_table_double_clicked(self, row: int, col: int):
        self._open_config_dialog(row)

    def _open_config_dialog(self, row: int):
        if 0 <= row < len(self._events):
            ch_info = self._channels_info[row] if row < len(self._channels_info) else {}
            dlg = DigitalChannelConfigDialog(
                self._events[row],
                self._events[row].channel,
                clock_hz=self._clock_hz,
                channel_info=ch_info,
                parent=self,
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._populate_table()
                self.sequence_changed.emit()

    def _set_all_enabled(self, state: bool):
        for ev in self._events:
            ev.enabled = state
        self._populate_table()
        self.sequence_changed.emit()

    def set_channel_timing(self, ch: int, start_ticks: int, end_ticks: int, enabled: bool):
        """Update channel timing from linked analog channel (AO{ch})."""
        for row, ev in enumerate(self._events):
            if ev.channel == ch:
                ev.start_ticks = start_ticks
                ev.end_ticks = max(start_ticks, end_ticks)
                ev.enabled = enabled

                self._table.blockSignals(True)
                mult = self._get_time_mult()
                chk_w = self._table.cellWidget(row, COL_ENABLE)
                if chk_w:
                    chk = chk_w.findChild(QCheckBox)
                    if chk:
                        chk.blockSignals(True)
                        chk.setChecked(enabled)
                        chk.blockSignals(False)

                st_s = ev.start_ticks / self._clock_hz
                st_spin = self._table.cellWidget(row, COL_START)
                if isinstance(st_spin, QDoubleSpinBox):
                    st_spin.blockSignals(True)
                    st_spin.setValue(st_s / mult)
                    st_spin.blockSignals(False)

                end_s = ev.end_ticks / self._clock_hz
                end_spin = self._table.cellWidget(row, COL_END)
                if isinstance(end_spin, QDoubleSpinBox):
                    end_spin.blockSignals(True)
                    end_spin.setValue(end_s / mult)
                    end_spin.blockSignals(False)

                self._update_row_timing(row)
                self._table.blockSignals(False)
                break

    # ── Public API ──────────────────────────────────────────────────────

    def get_digital_events(self) -> List[DigitalEvent]:
        """Return the list of active/configured digital events (at most 1 per channel)."""
        return [ev for ev in self._events if ev.enabled]

    def get_all_digital_events(self) -> List[DigitalEvent]:
        """Return all digital events."""
        return list(self._events)

    def set_digital_events(self, events: List[DigitalEvent]):
        """Load events into channel slots (enforcing 1 pulse per channel)."""
        ch_map: Dict[int, DigitalEvent] = {}
        max_ch = max([e.channel for e in events] + [len(self._events) - 1, 20])

        for ev in events:
            if ev.channel not in ch_map:
                ch_map[ev.channel] = ev

        # Ensure channels list accommodates any channels present in the sequence
        if max_ch + 1 > len(self._channels_info):
            for i in range(len(self._channels_info), max_ch + 1):
                self._channels_info.append({
                    "channel": i,
                    "prefix": f"dio{i}",
                    "name": f"DIO{i}",
                    "start_reg": f"dio{i}start",
                    "end_reg": f"dio{i}end",
                })

        new_events: List[DigitalEvent] = []
        for i, ch_info in enumerate(self._channels_info):
            ch_idx = ch_info["channel"]
            def_name = ch_info.get("name", f"DIO{ch_idx}")
            if ch_idx in ch_map:
                ev = ch_map[ch_idx]
                if not ev.name:
                    ev.name = def_name
                new_events.append(ev)
            else:
                new_events.append(
                    DigitalEvent(
                        name=def_name,
                        channel=ch_idx,
                        label=def_name,
                        start_ticks=0,
                        end_ticks=0,
                        enabled=False,
                    )
                )

        self._events = new_events
        self._table.setRowCount(len(self._events))
        self._populate_table()

    def get_sequence_duration_ticks(self) -> int:
        return self._sequence_duration_ticks

    def set_sequence_duration_ticks(self, ticks: int):
        self._sequence_duration_ticks = max(1, ticks)
        mult = self._get_time_mult()
        total_s = self._sequence_duration_ticks / self._clock_hz
        self._dur_spin.blockSignals(True)
        self._dur_spin.setValue(total_s / mult)
        self._dur_spin.blockSignals(False)

    def get_repeat_mode(self) -> RepeatMode:
        idx = self._repeat_combo.currentIndex()
        if idx == 1:
            return RepeatMode.CONTINUOUS
        elif idx == 2:
            return RepeatMode.COUNT
        return RepeatMode.SINGLE

    def set_repeat_mode(self, mode: RepeatMode):
        if mode == RepeatMode.CONTINUOUS:
            self._repeat_combo.setCurrentIndex(1)
        elif mode == RepeatMode.COUNT:
            self._repeat_combo.setCurrentIndex(2)
        else:
            self._repeat_combo.setCurrentIndex(0)

    def get_repeat_count(self) -> int:
        return self._repeat_count_spin.value()

    def set_repeat_count(self, count: int):
        self._repeat_count_spin.setValue(max(1, count))

    def set_channel_labels(self, labels: dict):
        for k, v in labels.items():
            try:
                ch = int(k)
                for ev in self._events:
                    if ev.channel == ch:
                        ev.label = str(v)
                        if not ev.name or ev.name.startswith("DIO"):
                            ev.name = str(v)
            except Exception:
                pass
        self._populate_table()

    def get_channel_labels(self) -> dict:
        return {ev.channel: ev.label or ev.name or f"DIO{ev.channel}" for ev in self._events}
