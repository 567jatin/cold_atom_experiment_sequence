"""
Analog waveform editor for configuring NI PXI-6733 8-channel analog output.

Presents all 8 analog channels (AO0 to AO7) directly with editable start and end
timing, waveform types, voltage ranges, and an in-depth channel configuration
dialog window with real-time waveform preview.
"""

from __future__ import annotations

import math
import sys
import os
from typing import List, Optional, Dict, Any

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QLineEdit, QComboBox, QDoubleSpinBox,
    QPushButton, QCheckBox, QDialog, QFormLayout, QDialogButtonBox,
    QGroupBox, QAbstractItemView, QMessageBox, QFileDialog,
)
from PySide6.QtCore import Signal, Qt, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPainterPath

from sequence_model import (
    AnalogEvent, WaveformType, TriggerEdge, TimeUnit,
)
from waveform_generator import (
    generate_waveform, generate_ramp, generate_sine,
    generate_square, generate_constant, load_arbitrary,
)
from .styles import COLORS

AO_COLORS = [
    "#00e5ff",  # AO0 Cyan
    "#ffab00",  # AO1 Amber
    "#ff5252",  # AO2 Coral
    "#e040fb",  # AO3 Purple
    "#00e676",  # AO4 Spring Green
    "#2979ff",  # AO5 Blue
    "#ff4081",  # AO6 Magenta
    "#ffd600",  # AO7 Gold
]

# Table column indices
COL_ENABLE = 0
COL_CHANNEL = 1
COL_LABEL = 2
COL_START = 3
COL_END = 4
COL_DURATION = 5
COL_WAVEFORM = 6
COL_VOLTAGES = 7
COL_CONFIGURE = 8
NUM_COLS = 9

HEADERS = [
    "Enable", "Channel", "Label", "Start Time",
    "End Time", "Duration", "Waveform", "Voltages", "Settings",
]


# ────────────────────────────────────────────────────────────────────────
#  Waveform Preview Widget (QPainter)
# ────────────────────────────────────────────────────────────────────────

class WaveformPreviewWidget(QWidget):
    """Custom-painted waveform preview widget."""

    def __init__(self, color: str = "#00e5ff", parent=None):
        super().__init__(parent)
        self._data: list[float] = []
        self._v_min = -10.0
        self._v_max = 10.0
        self._sample_rate = 1000.0
        self._trace_color = color
        self.setMinimumHeight(140)
        self.setMinimumWidth(240)

    def set_trace_color(self, color_hex: str):
        self._trace_color = color_hex
        self.update()

    def set_data(self, data: list[float] | Any, v_min: float = -10.0,
                 v_max: float = 10.0, sample_rate: float = 1000.0):
        self._data = list(data) if data is not None else []
        self._v_min = v_min
        self._v_max = v_max
        self._sample_rate = sample_rate
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        ml, mr, mt, mb = 45.0, 15.0, 15.0, 25.0
        plot_x = ml
        plot_y = mt
        plot_w = max(10.0, w - ml - mr)
        plot_h = max(10.0, h - mt - mb)

        # Background
        painter.fillRect(QRectF(0, 0, w, h), QColor("#161622"))
        painter.fillRect(QRectF(plot_x, plot_y, plot_w, plot_h), QColor("#0d0d16"))

        # Grid lines
        pen_grid = QPen(QColor("#222234"), 1, Qt.PenStyle.DotLine)
        painter.setPen(pen_grid)
        for i in range(5):
            gy = plot_y + (plot_h * i / 4.0)
            painter.drawLine(int(plot_x), int(gy), int(plot_x + plot_w), int(gy))

        # Zero volt reference line
        v_span = max(0.001, self._v_max - self._v_min)
        zero_frac = (0.0 - self._v_min) / v_span
        if 0.0 <= zero_frac <= 1.0:
            zero_y = plot_y + plot_h * (1.0 - zero_frac)
            painter.setPen(QPen(QColor("#3a3a55"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(plot_x), int(zero_y), int(plot_x + plot_w), int(zero_y))

        # Y axis text
        painter.setFont(QFont("Segoe UI", 7))
        painter.setPen(QColor("#808098"))
        painter.drawText(QRectF(2, plot_y - 2, ml - 6, 14), Qt.AlignmentFlag.AlignRight, f"{self._v_max:+.1f}V")
        painter.drawText(QRectF(2, plot_y + plot_h - 10, ml - 6, 14), Qt.AlignmentFlag.AlignRight, f"{self._v_min:+.1f}V")
        if 0.0 <= zero_frac <= 1.0:
            painter.drawText(QRectF(2, zero_y - 7, ml - 6, 14), Qt.AlignmentFlag.AlignRight, "0.0V")

        # Plot data
        if self._data and len(self._data) > 1:
            n_raw = len(self._data)
            max_screen_pts = int(plot_w * 2)

            if n_raw <= max_screen_pts:
                # Direct high-res path
                path = QPainterPath()
                for i, val in enumerate(self._data):
                    frac_y = (val - self._v_min) / v_span
                    px = plot_x + (plot_w * i / max(1, n_raw - 1))
                    py = plot_y + plot_h * (1.0 - min(1.0, max(0.0, frac_y)))
                    if i == 0:
                        path.moveTo(px, py)
                    else:
                        path.lineTo(px, py)
                painter.setPen(QPen(QColor(self._trace_color), 1.8))
                painter.drawPath(path)
            else:
                # Peak-Detect Min-Max Envelope (avoids digital aliasing and Moiré beats)
                n_bins = int(plot_w)
                data_arr = np.asarray(self._data, dtype=np.float64)
                chunks = np.array_split(data_arr, n_bins)
                path_top = QPainterPath()
                path_bot = QPainterPath()
                started = False

                for b_idx, chunk in enumerate(chunks):
                    if len(chunk) == 0:
                        continue
                    px = plot_x + (plot_w * b_idx / max(1, n_bins - 1))
                    c_min = float(chunk.min())
                    c_max = float(chunk.max())
                    py_top = plot_y + plot_h * (1.0 - min(1.0, max(0.0, (c_max - self._v_min) / v_span)))
                    py_bot = plot_y + plot_h * (1.0 - min(1.0, max(0.0, (c_min - self._v_min) / v_span)))

                    if not started:
                        path_top.moveTo(px, py_top)
                        path_bot.moveTo(px, py_bot)
                        started = True
                    else:
                        path_top.lineTo(px, py_top)
                        path_bot.lineTo(px, py_bot)

                    # Draw vertical min-max slice at this pixel
                    painter.setPen(QPen(QColor(self._trace_color), 1))
                    painter.drawLine(int(px), int(py_top), int(px), int(py_bot))

                painter.setPen(QPen(QColor(self._trace_color), 1.5))
                painter.drawPath(path_top)
                painter.drawPath(path_bot)

            # Info text
            painter.setFont(QFont("Consolas", 8))
            painter.setPen(QColor("#ffffff"))
            info = f"{len(self._data):,} pts | Range: [{min(self._data):.2f}V, {max(self._data):.2f}V]"
            painter.drawText(QRectF(plot_x + 6, plot_y + 4, plot_w - 12, 16), Qt.AlignmentFlag.AlignLeft, info)
        else:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#666680"))
            painter.drawText(QRectF(plot_x, plot_y, plot_w, plot_h), Qt.AlignmentFlag.AlignCenter, "No Waveform Data")


# ────────────────────────────────────────────────────────────────────────
#  Analog Channel Configuration Dialog Window
# ────────────────────────────────────────────────────────────────────────

class AnalogChannelConfigDialog(QDialog):
    """Configuration settings window for a single analog output channel."""

    def __init__(self, event: AnalogEvent, channel_idx: int, initial_unit: str = "ms", parent=None):
        super().__init__(parent)
        self._aev = event
        self.channel_idx = channel_idx
        self._current_unit = initial_unit if initial_unit in ("µs", "ms", "s") else "ms"
        color = AO_COLORS[channel_idx % len(AO_COLORS)]

        self.setWindowTitle(f"Configure Analog Channel AO{channel_idx} (PXI2Slot3/ao{channel_idx})")
        self.resize(540, 620)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; color: #ffffff; }
            QLabel { color: #d0d0e0; font-size: 11px; }
            QGroupBox { border: 1px solid #3d3d5c; border-radius: 6px; margin-top: 8px; padding-top: 14px; font-weight: bold; color: #00d4ff; }
            QLineEdit, QDoubleSpinBox, QComboBox { background-color: #2a2a3e; border: 1px solid #4d4d6e; color: #ffffff; border-radius: 4px; padding: 4px 6px; }
            QPushButton { background-color: #2b3b55; color: #ffffff; border: 1px solid #4a5a75; border-radius: 4px; padding: 6px 14px; }
            QPushButton:hover { background-color: #3b4b6b; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header Badge
        hdr = QHBoxLayout()
        badge = QLabel(f"  AO{channel_idx}  ")
        badge.setStyleSheet(f"background-color: {color}; color: #000000; font-weight: bold; font-size: 13px; border-radius: 4px; padding: 4px;")
        hdr.addWidget(badge)
        hdr_info = QLabel(f"Hardware: <b>PXI2Slot3/ao{channel_idx}</b> | Channel: <b>AO{channel_idx}</b>")
        hdr.addWidget(hdr_info)
        hdr.addStretch()
        layout.addLayout(hdr)

        # --- General Settings Group ---
        grp_gen = QGroupBox("General Channel Settings")
        form_gen = QFormLayout(grp_gen)

        self._enable_chk = QCheckBox("Enable this channel in sequence")
        self._enable_chk.setChecked(event.enabled)
        form_gen.addRow("Active State:", self._enable_chk)

        self._label_edit = QLineEdit(event.name or f"AO{channel_idx}")
        form_gen.addRow("Channel Label:", self._label_edit)
        layout.addWidget(grp_gen)

        # --- Waveform Parameters Group ---
        grp_wave = QGroupBox("Waveform Generator Parameters")
        form_wave = QFormLayout(grp_wave)

        self._wave_combo = QComboBox()
        self._wave_combo.addItems(["Ramp", "Sine", "Square", "Constant", "Arbitrary"])
        w_val = event.waveform_type.value if hasattr(event.waveform_type, "value") else str(event.waveform_type)
        self._wave_combo.setCurrentText(w_val.capitalize())
        self._wave_combo.currentTextChanged.connect(self._update_preview)
        form_wave.addRow("Waveform Shape:", self._wave_combo)

        self._start_v = QDoubleSpinBox()
        self._start_v.setRange(-10.0, 10.0)
        self._start_v.setDecimals(3)
        self._start_v.setSuffix(" V")
        self._start_v.setValue(event.start_voltage)
        self._start_v.valueChanged.connect(self._update_preview)
        form_wave.addRow("Start Voltage (V_start):", self._start_v)

        self._end_v = QDoubleSpinBox()
        self._end_v.setRange(-10.0, 10.0)
        self._end_v.setDecimals(3)
        self._end_v.setSuffix(" V")
        self._end_v.setValue(event.end_voltage)
        self._end_v.valueChanged.connect(self._update_preview)
        form_wave.addRow("End Voltage (V_end):", self._end_v)

        self._freq_spin = QDoubleSpinBox()
        self._freq_spin.setRange(0.1, 1000000.0)
        self._freq_spin.setDecimals(1)
        self._freq_spin.setSuffix(" Hz")
        self._freq_spin.setValue(event.frequency_hz)
        self._freq_spin.valueChanged.connect(self._on_freq_changed)
        form_wave.addRow("Frequency (Sine/Square/Ramp):", self._freq_spin)

        self._sample_rate_spin = QDoubleSpinBox()
        self._sample_rate_spin.setRange(1000.0, 2000000.0)
        self._sample_rate_spin.setDecimals(0)
        self._sample_rate_spin.setSuffix(" S/s")
        self._sample_rate_spin.setValue(event.sample_rate_hz)
        self._sample_rate_spin.valueChanged.connect(self._update_preview)
        form_wave.addRow("DAC Sample Rate:", self._sample_rate_spin)

        layout.addWidget(grp_wave)

        # --- Timing Group (Supports Microseconds) ---
        grp_time = QGroupBox("Waveform Active Window & Duration")
        form_time = QFormLayout(grp_time)

        self._unit_combo = QComboBox()
        self._unit_combo.addItems(["µs (Microseconds)", "ms (Milliseconds)", "s (Seconds)"])
        unit_map = {"µs": 0, "ms": 1, "s": 2}
        self._unit_combo.setCurrentIndex(unit_map.get(self._current_unit, 1))
        self._unit_combo.currentIndexChanged.connect(self._on_unit_switched)
        form_time.addRow("Time Unit:", self._unit_combo)

        mult = self._get_multiplier()  # displayed value * mult = ms

        self._start_time_spin = QDoubleSpinBox()
        self._start_time_spin.setRange(0.0, 10000000.0)
        self._start_time_spin.setDecimals(4 if self._current_unit == "µs" else 3)
        self._start_time_spin.setSuffix(f" {self._current_unit}")
        self._start_time_spin.setValue(getattr(event, "start_ms", 0.0) / mult)
        self._start_time_spin.valueChanged.connect(self._on_start_time_changed)
        form_time.addRow("Start Time (t_start):", self._start_time_spin)

        self._end_time_spin = QDoubleSpinBox()
        self._end_time_spin.setRange(0.0, 10000000.0)
        self._end_time_spin.setDecimals(4 if self._current_unit == "µs" else 3)
        self._end_time_spin.setSuffix(f" {self._current_unit}")
        self._end_time_spin.setValue(getattr(event, "end_ms", 42.5) / mult)
        self._end_time_spin.valueChanged.connect(self._on_end_time_changed)
        form_time.addRow("End Time (t_end):", self._end_time_spin)

        self._dur_lbl = QLabel()
        self._dur_lbl.setStyleSheet("color: #00ff88; font-weight: bold;")
        form_time.addRow("Active Duration:", self._dur_lbl)

        lbl_sync_info = QLabel(
            f"⚡ Hardware sync: Trigger DIO{channel_idx} will be asserted HIGH for this exact duration.\n"
            f"The analog signal runs strictly while its trigger is selected (active)."
        )
        lbl_sync_info.setStyleSheet("color: #00d4ff; font-size: 10px; font-style: italic;")
        form_time.addRow("", lbl_sync_info)

        layout.addWidget(grp_time)

        # --- Waveform Preview ---
        self._preview = WaveformPreviewWidget(color=color)
        layout.addWidget(self._preview)

        # Dialog Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._update_duration_display()
        self._update_preview()

    def _get_multiplier(self) -> float:
        """Multiplier to convert displayed time value to milliseconds."""
        if self._current_unit == "µs":
            return 1e-3
        elif self._current_unit == "s":
            return 1000.0
        return 1.0  # ms

    def _on_unit_switched(self, idx: int):
        units = ["µs", "ms", "s"]
        old_mult = self._get_multiplier()
        old_st_ms = self._start_time_spin.value() * old_mult
        old_end_ms = self._end_time_spin.value() * old_mult

        self._current_unit = units[idx]
        new_mult = self._get_multiplier()

        self._start_time_spin.blockSignals(True)
        self._end_time_spin.blockSignals(True)

        self._start_time_spin.setDecimals(4 if self._current_unit == "µs" else 3)
        self._end_time_spin.setDecimals(4 if self._current_unit == "µs" else 3)

        self._start_time_spin.setSuffix(f" {self._current_unit}")
        self._end_time_spin.setSuffix(f" {self._current_unit}")

        self._start_time_spin.setValue(old_st_ms / new_mult)
        self._end_time_spin.setValue(old_end_ms / new_mult)

        self._start_time_spin.blockSignals(False)
        self._end_time_spin.blockSignals(False)

        self._update_duration_display()
        self._update_preview()

    def _on_start_time_changed(self, val: float):
        if self._end_time_spin.value() <= val:
            step = 1.0 if self._current_unit == "µs" else 0.1
            self._end_time_spin.blockSignals(True)
            self._end_time_spin.setValue(val + step)
            self._end_time_spin.blockSignals(False)
        self._update_duration_display()
        self._update_preview()

    def _on_end_time_changed(self, val: float):
        st = self._start_time_spin.value()
        if val <= st:
            step = 1.0 if self._current_unit == "µs" else 0.1
            self._end_time_spin.setValue(st + step)
            return
        self._update_duration_display()
        self._update_preview()

    def _on_freq_changed(self, freq: float):
        # Auto-scale DAC sample rate to guarantee sufficient points per cycle (avoiding Nyquist aliasing)
        min_rec_sr = min(2000000.0, max(50000.0, freq * 5.0))
        if self._sample_rate_spin.value() < min_rec_sr:
            self._sample_rate_spin.blockSignals(True)
            self._sample_rate_spin.setValue(min_rec_sr)
            self._sample_rate_spin.blockSignals(False)
        self._update_preview()

    def _update_duration_display(self):
        dur = max(0.00001, self._end_time_spin.value() - self._start_time_spin.value())
        self._dur_lbl.setText(f"Duration: {dur:.4g} {self._current_unit}")

    def _update_preview(self):
        w_type_str = self._wave_combo.currentText().lower()
        v_start = self._start_v.value()
        v_end = self._end_v.value()
        freq = self._freq_spin.value()
        sr = self._sample_rate_spin.value()
        mult = self._get_multiplier()
        dur_ms = max(0.000025, (self._end_time_spin.value() - self._start_time_spin.value()) * mult)
        num_samps = max(2, int(round((dur_ms / 1000.0) * sr)))

        try:
            if w_type_str == "ramp":
                data = generate_ramp(v_start, v_end, num_samps)
            elif w_type_str == "sine":
                amp = (v_end - v_start) / 2.0
                offset = (v_end + v_start) / 2.0
                num_cycles = max(0.001, (dur_ms / 1000.0) * freq)
                data = generate_sine(amp, offset, num_samps, num_cycles=num_cycles)
            elif w_type_str == "square":
                num_cycles = max(0.001, (dur_ms / 1000.0) * freq)
                data = generate_square(v_start, v_end, num_samps, duty_cycle=0.5, num_cycles=num_cycles)
            elif w_type_str == "constant":
                data = generate_constant(v_start, num_samps)
            else:
                data = generate_ramp(v_start, v_end, num_samps)
            self._preview.set_data(data, v_min=-10.0, v_max=10.0, sample_rate=sr)
        except Exception:
            pass

    def _on_save(self):
        mult = self._get_multiplier()
        self._aev.name = self._label_edit.text().strip() or f"AO{self.channel_idx}"
        self._aev.enabled = self._enable_chk.isChecked()
        w_str = self._wave_combo.currentText().lower()
        try:
            self._aev.waveform_type = WaveformType(w_str)
        except Exception:
            self._aev.waveform_type = WaveformType.RAMP
        self._aev.start_voltage = self._start_v.value()
        self._aev.end_voltage = self._end_v.value()
        self._aev.frequency_hz = self._freq_spin.value()
        self._aev.sample_rate_hz = self._sample_rate_spin.value()
        self._aev.start_ms = self._start_time_spin.value() * mult
        self._aev.end_ms = self._end_time_spin.value() * mult
        self._aev.duration_ms = max(0.000025, self._aev.end_ms - self._aev.start_ms)
        self._aev.num_samples = max(2, int(round((self._aev.duration_ms / 1000.0) * self._aev.sample_rate_hz)))
        self.accept()


# ────────────────────────────────────────────────────────────────────────
#  Analog Waveform Editor Table Panel (8 Channels AO0 - AO7)
# ────────────────────────────────────────────────────────────────────────

class AnalogWaveformEditor(QWidget):
    """Direct 8-channel analog waveform editor table with settings dialog."""

    analog_events_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._events: List[AnalogEvent] = []
        self._display_unit: str = "ms"
        self._unit_multiplier: float = 1.0  # ms -> ms: 1.0; ms -> us: 1000.0; ms -> s: 0.001
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Top Control Toolbar
        tb = QHBoxLayout()
        tb.setSpacing(8)

        lbl_title = QLabel("Analog Output Channels (PXI-6733)")
        lbl_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #00d4ff;")
        tb.addWidget(lbl_title)

        tb.addSpacing(16)
        tb.addWidget(QLabel("Time Unit:"))
        self._unit_combo = QComboBox()
        self._unit_combo.addItems(["ms (Milliseconds)", "µs (Microseconds)", "s (Seconds)"])
        self._unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        tb.addWidget(self._unit_combo)

        tb.addSpacing(12)
        btn_enable_all = QPushButton("✔ Enable All")
        btn_enable_all.clicked.connect(lambda: self._set_all_enabled(True))
        tb.addWidget(btn_enable_all)

        btn_disable_all = QPushButton("✖ Disable All")
        btn_disable_all.clicked.connect(lambda: self._set_all_enabled(False))
        tb.addWidget(btn_disable_all)

        btn_ramp_preset = QPushButton("⚡ Default 10kHz Ramp on AO0")
        btn_ramp_preset.setStyleSheet("color: #00ff88; font-weight: bold;")
        btn_ramp_preset.clicked.connect(self._apply_default_ramp)
        tb.addWidget(btn_ramp_preset)

        tb.addStretch()
        layout.addLayout(tb)

        # 8-Channel Table
        self._table = QTableWidget(8, NUM_COLS)
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
        self._table.horizontalHeader().setSectionResizeMode(COL_WAVEFORM, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_VOLTAGES, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_CONFIGURE, QHeaderView.ResizeMode.ResizeToContents)
        self._table.cellDoubleClicked.connect(self._on_table_double_clicked)
        layout.addWidget(self._table, 1)

        self._init_default_channels()

    def _init_default_channels(self):
        """Ensure all 8 analog channels (AO0 to AO7) exist with default values."""
        self._events = []
        for i in range(8):
            trig_idx = i if i <= 5 else 0
            ev = AnalogEvent(
                name=f"AO{i}",
                channel=f"PXI2Slot3/ao{i}",
                trigger_source=f"/PXI2Slot3/PXI_Trig{trig_idx}",
                trigger_edge=TriggerEdge.RISING,
                waveform_type=WaveformType.RAMP if i == 0 else WaveformType.CONSTANT,
                start_voltage=0.0,
                end_voltage=5.0 if i == 0 else 0.0,
                start_ms=0.0,
                end_ms=42.5 if i == 0 else 10.0,
                duration_ms=42.5 if i == 0 else 10.0,
                frequency_hz=10000.0,
                sample_rate_hz=500000.0,
                enabled=(i == 0),
            )
            self._events.append(ev)
        self._populate_table()

    def _populate_table(self):
        """Populate the 8 table rows with channel data."""
        self._table.blockSignals(True)
        mult = self._get_time_mult()
        unit_lbl = self._display_unit

        for ch in range(8):
            ev = self._events[ch] if ch < len(self._events) else None
            if not ev:
                continue

            color = AO_COLORS[ch % len(AO_COLORS)]

            # 1. Enable Checkbox
            chk = QCheckBox()
            chk.setChecked(ev.enabled)
            chk.toggled.connect(lambda state, c=ch: self._on_enable_toggled(c, state))
            chk_w = QWidget()
            ch_lay = QHBoxLayout(chk_w)
            ch_lay.setContentsMargins(8, 2, 8, 2)
            ch_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ch_lay.addWidget(chk)
            self._table.setCellWidget(ch, COL_ENABLE, chk_w)

            # 2. Channel Badge
            badge_lbl = QLabel(f"  AO{ch}  ")
            badge_lbl.setStyleSheet(f"background-color: {color}; color: #000000; font-weight: bold; border-radius: 4px; padding: 2px;")
            badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setCellWidget(ch, COL_CHANNEL, badge_lbl)

            # 3. Label Edit
            lbl_edit = QLineEdit(ev.name or f"AO{ch}")
            lbl_edit.textChanged.connect(lambda txt, c=ch: self._on_label_changed(c, txt))
            self._table.setCellWidget(ch, COL_LABEL, lbl_edit)

            # 4. Start Time SpinBox
            st_spin = QDoubleSpinBox()
            st_spin.setRange(0.0, 100000000.0)
            st_spin.setDecimals(3)
            st_spin.setSingleStep(1.0 if unit_lbl == "µs" else 0.1)
            st_spin.setSuffix(f" {unit_lbl}")
            st_spin.setValue(getattr(ev, "start_ms", 0.0) * mult)
            st_spin.valueChanged.connect(lambda val, c=ch: self._on_start_changed(c, val))
            self._table.setCellWidget(ch, COL_START, st_spin)

            # 5. End Time SpinBox
            end_spin = QDoubleSpinBox()
            end_spin.setRange(0.0, 100000000.0)
            end_spin.setDecimals(3)
            end_spin.setSingleStep(1.0 if unit_lbl == "µs" else 0.1)
            end_spin.setSuffix(f" {unit_lbl}")
            end_spin.setValue(getattr(ev, "end_ms", 42.5) * mult)
            end_spin.valueChanged.connect(lambda val, c=ch: self._on_end_changed(c, val))
            self._table.setCellWidget(ch, COL_END, end_spin)

            # 6. Duration Label
            dur_ms = max(0.001, getattr(ev, "end_ms", 42.5) - getattr(ev, "start_ms", 0.0))
            dur_item = QTableWidgetItem(f"{dur_ms * mult:.3f} {unit_lbl}")
            dur_item.setFlags(dur_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            dur_item.setForeground(QColor("#00ff88"))
            self._table.setItem(ch, COL_DURATION, dur_item)

            # 7. Waveform Type Combo
            wave_combo = QComboBox()
            wave_combo.addItems(["Ramp", "Sine", "Square", "Constant", "Arbitrary"])
            w_str = ev.waveform_type.value if hasattr(ev.waveform_type, "value") else str(ev.waveform_type)
            wave_combo.setCurrentText(w_str.capitalize())
            wave_combo.currentTextChanged.connect(lambda txt, c=ch: self._on_waveform_changed(c, txt))
            self._table.setCellWidget(ch, COL_WAVEFORM, wave_combo)

            # 8. Voltages Display
            v_item = QTableWidgetItem(f"{ev.start_voltage:.1f}V → {ev.end_voltage:.1f}V")
            v_item.setFlags(v_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            v_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(ch, COL_VOLTAGES, v_item)

            # 9. Configure Button
            btn_cfg = QPushButton("⚙ Configure…")
            btn_cfg.setStyleSheet("background-color: #2b3b55; color: #00d4ff; font-weight: bold; padding: 2px 8px;")
            btn_cfg.clicked.connect(lambda _, c=ch: self._open_config_dialog(c))
            self._table.setCellWidget(ch, COL_CONFIGURE, btn_cfg)

        self._table.blockSignals(False)

    def _get_time_mult(self) -> float:
        """Multiplier from ms to currently displayed unit."""
        if self._display_unit == "µs":
            return 1000.0
        elif self._display_unit == "s":
            return 0.001
        return 1.0  # ms

    def _get_ms_from_display(self, val: float) -> float:
        """Convert displayed time to milliseconds."""
        if self._display_unit == "µs":
            return val / 1000.0
        elif self._display_unit == "s":
            return val * 1000.0
        return val

    def _on_unit_changed(self, idx: int):
        units = ["ms", "µs", "s"]
        self._display_unit = units[idx]
        self._populate_table()

    def _on_enable_toggled(self, ch: int, state: bool):
        if 0 <= ch < len(self._events):
            self._events[ch].enabled = state
            self.analog_events_changed.emit()

    def _on_label_changed(self, ch: int, text: str):
        if 0 <= ch < len(self._events):
            self._events[ch].name = text
            self.analog_events_changed.emit()

    def _on_start_changed(self, ch: int, val: float):
        if 0 <= ch < len(self._events):
            ev = self._events[ch]
            st_ms = self._get_ms_from_display(val)
            ev.start_ms = st_ms
            ev.duration_ms = max(0.001, ev.end_ms - ev.start_ms)
            self._update_row_duration(ch)
            self.analog_events_changed.emit()

    def _on_end_changed(self, ch: int, val: float):
        if 0 <= ch < len(self._events):
            ev = self._events[ch]
            end_ms = self._get_ms_from_display(val)
            if end_ms > ev.start_ms:
                ev.end_ms = end_ms
                ev.duration_ms = max(0.001, ev.end_ms - ev.start_ms)
                self._update_row_duration(ch)
                self.analog_events_changed.emit()

    def _on_waveform_changed(self, ch: int, text: str):
        if 0 <= ch < len(self._events):
            try:
                self._events[ch].waveform_type = WaveformType(text.lower())
            except Exception:
                pass
            self.analog_events_changed.emit()

    def _update_row_duration(self, ch: int):
        if 0 <= ch < len(self._events):
            ev = self._events[ch]
            dur_ms = max(0.001, ev.end_ms - ev.start_ms)
            mult = self._get_time_mult()
            item = self._table.item(ch, COL_DURATION)
            if item:
                item.setText(f"{dur_ms * mult:.3f} {self._display_unit}")

    def _on_table_double_clicked(self, row: int, col: int):
        self._open_config_dialog(row)

    def _open_config_dialog(self, ch: int):
        if 0 <= ch < len(self._events):
            dlg = AnalogChannelConfigDialog(self._events[ch], ch, initial_unit=self._display_unit, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._populate_table()
                self.analog_events_changed.emit()

    def set_channel_timing(self, ch: int, start_ms: float, end_ms: float, enabled: bool):
        """Update channel timing from linked digital trigger (DIO{ch})."""
        if 0 <= ch < len(self._events):
            ev = self._events[ch]
            ev.start_ms = start_ms
            ev.end_ms = end_ms
            ev.duration_ms = max(0.000025, end_ms - start_ms)
            ev.enabled = enabled

            self._table.blockSignals(True)
            mult = self._get_time_mult()
            chk_w = self._table.cellWidget(ch, COL_ENABLE)
            if chk_w:
                chk = chk_w.findChild(QCheckBox)
                if chk:
                    chk.blockSignals(True)
                    chk.setChecked(enabled)
                    chk.blockSignals(False)

            st_spin = self._table.cellWidget(ch, COL_START)
            if isinstance(st_spin, QDoubleSpinBox):
                st_spin.blockSignals(True)
                st_spin.setValue(start_ms * mult)
                st_spin.blockSignals(False)

            end_spin = self._table.cellWidget(ch, COL_END)
            if isinstance(end_spin, QDoubleSpinBox):
                end_spin.blockSignals(True)
                end_spin.setValue(end_ms * mult)
                end_spin.blockSignals(False)

            self._update_row_duration(ch)
            self._table.blockSignals(False)

    def _set_all_enabled(self, state: bool):
        for ev in self._events:
            ev.enabled = state
        self._populate_table()
        self.analog_events_changed.emit()

    def _apply_default_ramp(self):
        """Set up standard 10kHz ramp on AO0: 0V -> 5V for 42.5ms."""
        if len(self._events) > 0:
            ao0 = self._events[0]
            ao0.name = "10kHz Ramp"
            ao0.enabled = True
            ao0.start_voltage = 0.0
            ao0.end_voltage = 5.0
            ao0.start_ms = 0.0
            ao0.end_ms = 42.5
            ao0.duration_ms = 42.5
            ao0.frequency_hz = 10000.0
            ao0.sample_rate_hz = 500000.0
            ao0.waveform_type = WaveformType.RAMP
            self._populate_table()
            self.analog_events_changed.emit()

    # ── Public API ──────────────────────────────────────────────────────

    def set_available_channels(self, channels: List[str]):
        """Update available physical channel names if reported by DAQ hardware."""
        pass

    def get_analog_events(self) -> List[AnalogEvent]:
        """Return all configured analog events."""
        return list(self._events)

    def set_analog_events(self, events: List[AnalogEvent]):
        """Load analog events into the 8 channel slots."""
        # Ensure we have 8 events
        ch_map: Dict[int, AnalogEvent] = {}
        for ev in events:
            # Match ao0..ao7 or int channel
            if isinstance(ev.channel, int):
                ch_idx = ev.channel
                if 0 <= ch_idx < 8:
                    ch_map[ch_idx] = ev
            else:
                import re
                m = re.search(r"ao(\d+)", str(ev.channel), re.IGNORECASE)
                if m:
                    ch_idx = int(m.group(1))
                    if 0 <= ch_idx < 8:
                        ch_map[ch_idx] = ev

        new_events: List[AnalogEvent] = []
        for i in range(8):
            if i in ch_map:
                ev = ch_map[i]
                if not hasattr(ev, "start_ms"):
                    ev.start_ms = 0.0
                if not hasattr(ev, "end_ms"):
                    ev.end_ms = ev.start_ms + getattr(ev, "duration_ms", 42.5)
                new_events.append(ev)
            else:
                new_events.append(
                    AnalogEvent(
                        name=f"AO{i}",
                        channel=f"PXI2Slot3/ao{i}",
                        trigger_source=f"/PXI2Slot3/PXI_Trig{i if i <= 5 else 0}",
                        start_ms=0.0,
                        end_ms=42.5 if i == 0 else 10.0,
                        duration_ms=42.5 if i == 0 else 10.0,
                        enabled=(i == 0),
                    )
                )
        self._events = new_events
        self._populate_table()
