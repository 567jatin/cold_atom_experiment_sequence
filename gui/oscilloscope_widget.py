"""
Oscilloscope & Live Analog Output/Input Monitor Widget
======================================================
Provides a laboratory-grade digital storage oscilloscope (DSO) interface
that monitors live analog outputs (AO0..AO7) generated during sequence execution,
streams real-time analog inputs (AI0..AI7) from an NI DAQ AI card, and executes
pulse-gated analog input captures with automated CSV exports.

Features:
- Phosphor dark LCD oscilloscope display with 10x8 major division grid.
- Adjustable Timebase (1 µs/div to 5 s/div) and Volts/Div (50 mV/div to 10 V/div).
- Horizontal Position/Offset panning and Auto-Scale (Horizontal & Vertical framing).
- Monotonic DSO time mapping with Peak-Detect min-max envelope (no modulo wrapping).
- Accurate waveform synthesis for Sine, Square, Ramp, and Constant wave types.
- Trigger system with Level Line, Auto/Normal/Single modes, and PXI trigger sync.
- 🎯 Pulse-Gated Analog Input Capture: Controls capture duration strictly while
  a digital pulse (e.g. DIO0..DIO20 or PXI trigger) is active, graphing Input 1 (AI0)
  in real time and automatically saving full-precision data as CSV.
- Automated CSV Export with metadata header (pulse source, duration, sampling rate).
- Open Captures folder in Windows Explorer with one click.
"""

from __future__ import annotations

import math
import os
import sys
import time
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QDoubleSpinBox, QCheckBox, QGroupBox,
    QFrame, QSplitter, QFileDialog, QMessageBox, QTabWidget,
    QScrollArea, QSizePolicy, QLineEdit,
)
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPainterPath,
    QLinearGradient, QMouseEvent, QWheelEvent,
)

from sequence_model import ExperimentSequence, AnalogEvent, FPGA_CLOCK_HZ
from ai_controller import AIController

# Oscilloscope Channel Color Palettes
AO_OSC_COLORS = [
    "#00e5ff",  # AO0 Cyan
    "#ffab00",  # AO1 Amber
    "#ff5252",  # AO2 Coral
    "#e040fb",  # AO3 Purple
    "#00e676",  # AO4 Spring Green
    "#2979ff",  # AO5 Neon Blue
    "#ff4081",  # AO6 Pink
    "#ffd600",  # AO7 Gold
]

AI_OSC_COLORS = [
    "#00ff66",  # AI0 Electric Green (Input 1)
    "#ffff00",  # AI1 Bright Yellow
    "#00f0ff",  # AI2 Aqua
    "#ff007f",  # AI3 Neon Magenta
    "#ff6600",  # AI4 Vibrant Orange
    "#9933ff",  # AI5 Violet
    "#33ccff",  # AI6 Sky Blue
    "#ff3366",  # AI7 Crimson
]


# ────────────────────────────────────────────────────────────────────────
#  Oscilloscope Screen Display (Canvas)
# ────────────────────────────────────────────────────────────────────────

class OscilloscopeScreen(QWidget):
    """Phosphor display canvas rendering grid divisions, triggers, and live signals."""

    trigger_level_changed = Signal(float)
    time_offset_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

        # Oscilloscope Settings
        self.timebase_s_div = 1.0e-3     # 1 ms / division default
        self.volts_div = 1.0             # 1.0 V / division default
        self.time_offset_s = 0.0         # 0.0 s horizontal time offset
        self.vertical_offset_v = 0.0     # 0.0 V offset
        self.trigger_level_v = 0.0       # 0.0 V trigger level
        self.trigger_slope = "RISING"    # RISING / FALLING

        # Channel Traces Data: {ch_name: {"times": array, "volts": array, "color": hex, "visible": bool}}
        self._traces: Dict[str, Dict[str, Any]] = {}
        self._cursor_pos: Optional[QPointF] = None
        self._dragging_trigger = False
        self._sweep_x_norm: Optional[float] = None  # Normalized sweep position (0.0 to 1.0)

    def set_timebase(self, s_per_div: float):
        self.timebase_s_div = max(1e-7, float(s_per_div))
        self.update()

    def set_volts_div(self, v_per_div: float):
        self.volts_div = max(0.01, float(v_per_div))
        self.update()

    def set_time_offset(self, s: float):
        self.time_offset_s = float(s)
        self.update()

    def set_trigger_level(self, level_v: float):
        self.trigger_level_v = float(level_v)
        self.update()

    def update_trace(self, ch_name: str, times: np.ndarray, volts: np.ndarray, color: str, visible: bool = True):
        self._traces[ch_name] = {
            "times": np.asarray(times, dtype=np.float64),
            "volts": np.asarray(volts, dtype=np.float64),
            "color": color,
            "visible": visible,
        }
        self.update()

    def append_ai_chunk(self, ch_name: str, times: np.ndarray, volts: np.ndarray, color: str, max_samples: int = 50000, visible: bool = True):
        t_arr = np.asarray(times, dtype=np.float64)
        v_arr = np.asarray(volts, dtype=np.float64)
        if ch_name in self._traces:
            old = self._traces[ch_name]
            comb_t = np.concatenate([old["times"], t_arr])
            comb_v = np.concatenate([old["volts"], v_arr])
            if len(comb_t) > max_samples:
                comb_t = comb_t[-max_samples:]
                comb_v = comb_v[-max_samples:]
            self._traces[ch_name]["times"] = comb_t
            self._traces[ch_name]["volts"] = comb_v
            self._traces[ch_name]["visible"] = visible
        else:
            self._traces[ch_name] = {
                "times": t_arr,
                "volts": v_arr,
                "color": color,
                "visible": visible,
            }

        # Auto-roll window during live streaming
        total_time_window_s = 10.0 * self.timebase_s_div
        latest_t = t_arr[-1] if len(t_arr) > 0 else 0.0
        if latest_t > (self.time_offset_s + total_time_window_s):
            self.time_offset_s = max(0.0, latest_t - total_time_window_s)
            self.time_offset_changed.emit(self.time_offset_s)

        self.update()

    def set_trace_visibility(self, ch_name: str, visible: bool):
        if ch_name in self._traces:
            self._traces[ch_name]["visible"] = visible
            self.update()

    def clear_traces(self):
        self._traces.clear()
        self.update()

    def set_sweep_progress(self, progress_norm: Optional[float]):
        self._sweep_x_norm = progress_norm
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())

        # 1. Dark phosphor CRT screen background
        painter.fillRect(QRectF(0, 0, w, h), QColor("#0d1117"))

        # Screen bezel inner gradient
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(0, 20, 15, 60))
        grad.setColorAt(0.5, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 20, 15, 60))
        painter.fillRect(QRectF(0, 0, w, h), grad)

        # 2. Oscilloscope Grid (10 horizontal div x 8 vertical div)
        grid_pen_major = QPen(QColor("#1f2d3d"), 1, Qt.PenStyle.SolidLine)
        grid_pen_center = QPen(QColor("#2d425a"), 1.2, Qt.PenStyle.DashLine)
        subdiv_pen = QPen(QColor("#182330"), 0.8, Qt.PenStyle.DotLine)

        num_div_x = 10
        num_div_y = 8
        dx = w / num_div_x
        dy = h / num_div_y

        # Draw vertical grid lines
        for i in range(num_div_x + 1):
            x = i * dx
            if i == num_div_x // 2:
                painter.setPen(grid_pen_center)
            else:
                painter.setPen(grid_pen_major)
            painter.drawLine(int(x), 0, int(x), int(h))

            # Sub-division tick marks along center horizontal line
            if i < num_div_x:
                painter.setPen(subdiv_pen)
                for s in range(1, 5):
                    sx = x + s * (dx / 5.0)
                    painter.drawLine(int(sx), int(h / 2 - 4), int(sx), int(h / 2 + 4))

        # Draw horizontal grid lines
        for j in range(num_div_y + 1):
            y = j * dy
            if j == num_div_y // 2:
                painter.setPen(grid_pen_center)
            else:
                painter.setPen(grid_pen_major)
            painter.drawLine(0, int(y), int(w), int(y))

            # Sub-division tick marks along center vertical line
            if j < num_div_y:
                painter.setPen(subdiv_pen)
                for s in range(1, 5):
                    sy = y + s * (dy / 5.0)
                    painter.drawLine(int(w / 2 - 4), int(sy), int(w / 2 + 4), int(sy))

        # 3. Voltage Zero Center Baseline (0.0 V)
        center_y = h / 2.0
        painter.setPen(QPen(QColor("#334466"), 1))
        painter.drawLine(0, int(center_y), int(w), int(center_y))

        # Ground reference indicator (left edge)
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QColor("#00d4ff"))
        painter.drawText(4, int(center_y - 2), "⏚ 0V")

        # 4. Trigger Level Line
        trig_y = center_y - (self.trigger_level_v / self.volts_div) * dy
        if 0 <= trig_y <= h:
            trig_pen = QPen(QColor("#ffaa00"), 1, Qt.PenStyle.DashDotLine)
            painter.setPen(trig_pen)
            painter.drawLine(0, int(trig_y), int(w), int(trig_y))
            # Trigger handle
            painter.setBrush(QColor("#ffaa00"))
            trig_arrow = QPainterPath()
            trig_arrow.moveTo(w - 1, trig_y)
            trig_arrow.lineTo(w - 10, trig_y - 5)
            trig_arrow.lineTo(w - 10, trig_y + 5)
            trig_arrow.closeSubpath()
            painter.drawPath(trig_arrow)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(int(w - 85), int(trig_y - 4), f"T: {self.trigger_level_v:+.2f}V")

        # 5. Render Waveform Traces (Monotonic left-to-right windowing & Peak-Detect)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        total_time_window_s = num_div_x * self.timebase_s_div
        t_start = self.time_offset_s
        t_end = t_start + total_time_window_s

        for ch_name, tr in self._traces.items():
            if not tr.get("visible", True):
                continue

            times = tr["times"]
            volts = tr["volts"]
            if len(times) == 0 or len(volts) == 0:
                continue

            # Binary search to find points in the visible time window
            idx_start = int(np.searchsorted(times, t_start, side="left"))
            idx_end = int(np.searchsorted(times, t_end, side="right"))

            # Include adjacent border samples so lines meet edges cleanly
            if idx_start > 0:
                idx_start -= 1
            if idx_end < len(times):
                idx_end += 1

            if idx_end <= idx_start:
                continue

            t_vis = times[idx_start:idx_end]
            v_vis = volts[idx_start:idx_end]
            n_vis = len(t_vis)
            if n_vis == 0:
                continue

            color = QColor(tr["color"])
            trace_pen = QPen(color, 1.8)
            painter.setPen(trace_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            if n_vis <= 2500:
                # Direct monotonic point-to-point drawing
                x_pts = ((t_vis - t_start) / total_time_window_s) * w
                y_pts = center_y - (v_vis / self.volts_div) * dy

                curve_path = QPainterPath()
                curve_path.moveTo(float(x_pts[0]), float(y_pts[0]))
                for k in range(1, n_vis):
                    curve_path.lineTo(float(x_pts[k]), float(y_pts[k]))
                painter.strokePath(curve_path, trace_pen)
            else:
                # Peak-Detect DSO envelope: min and max per pixel column to eliminate aliasing
                num_pixels = max(10, int(w))
                t_clip = np.clip(t_vis, t_start, t_end)
                x_norm = (t_clip - t_start) / total_time_window_s
                pixel_bins = np.clip((x_norm * num_pixels).astype(np.int32), 0, num_pixels - 1)
                bin_splits = np.searchsorted(pixel_bins, np.arange(num_pixels + 1))

                top_path = QPainterPath()
                bot_path = QPainterPath()
                started = False
                last_px: Optional[int] = None

                for px in range(num_pixels):
                    b_st = bin_splits[px]
                    b_en = bin_splits[px + 1]
                    if b_en <= b_st:
                        continue
                    v_col = v_vis[b_st:b_en]
                    v_col_min = float(np.min(v_col))
                    v_col_max = float(np.max(v_col))

                    y_top = center_y - (v_col_max / self.volts_div) * dy
                    y_bot = center_y - (v_col_min / self.volts_div) * dy

                    if not started:
                        top_path.moveTo(float(px), float(y_top))
                        bot_path.moveTo(float(px), float(y_bot))
                        started = True
                    else:
                        # Prevent diagonal lines across gaps
                        if last_px is not None and (px - last_px) > 1:
                            top_path.moveTo(float(px), float(y_top))
                            bot_path.moveTo(float(px), float(y_bot))
                        else:
                            top_path.lineTo(float(px), float(y_top))
                            bot_path.lineTo(float(px), float(y_bot))
                    last_px = px

                if started:
                    painter.strokePath(top_path, trace_pen)
                    painter.strokePath(bot_path, trace_pen)

        # 6. Active Channel Indicators (Top-Left)
        chan_x = 10
        chan_y = 18
        for ch_name, tr in self._traces.items():
            if tr.get("visible", True) and len(tr["volts"]) > 0:
                col = QColor(tr["color"])
                painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
                painter.setPen(col)
                painter.drawText(int(chan_x), int(chan_y), f"■ {ch_name}")
                chan_x += 65
                if chan_x > w - 280:
                    chan_x = 10
                    chan_y += 16

        # 7. Live Sweep Beam Cursor
        if self._sweep_x_norm is not None:
            sweep_x = self._sweep_x_norm * w
            beam_pen = QPen(QColor(0, 255, 136, 180), 2)
            painter.setPen(beam_pen)
            painter.drawLine(int(sweep_x), 0, int(sweep_x), int(h))

        # 8. On-Screen Scale Badges (Timebase & Volts/Div & Time Offset)
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        badge_w = 260
        badge_h = 26
        badge_rect = QRectF(w - badge_w - 8, 8, badge_w, badge_h)
        painter.fillRect(badge_rect, QColor(0, 0, 0, 200))
        painter.setPen(QPen(QColor("#00ff88"), 1))
        painter.drawRect(badge_rect)

        tb_str = (
            f"{self.timebase_s_div*1e6:.1f} µs/div" if self.timebase_s_div < 1e-3 else (
                f"{self.timebase_s_div*1e3:.2f} ms/div" if self.timebase_s_div < 1.0 else f"{self.timebase_s_div:.2f} s/div"
            )
        )
        v_str = f"{self.volts_div*1e3:.0f} mV/div" if self.volts_div < 1.0 else f"{self.volts_div:.1f} V/div"
        offset_str = f" | {self.time_offset_s*1e3:+.1f}ms" if abs(self.time_offset_s) > 1e-7 else ""
        painter.setPen(QColor("#ffffff"))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, f"{tb_str}  |  {v_str}{offset_str}")

        painter.end()

    # ── Mouse Interaction for Trigger Level ─────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            dy = float(self.height()) / 8.0
            center_y = float(self.height()) / 2.0
            trig_y = center_y - (self.trigger_level_v / self.volts_div) * dy

            if abs(event.position().y() - trig_y) <= 12.0:
                self._dragging_trigger = True

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        dy = float(self.height()) / 8.0
        center_y = float(self.height()) / 2.0

        if self._dragging_trigger:
            new_v = ((center_y - pos.y()) / dy) * self.volts_div
            self.trigger_level_v = max(-10.0, min(10.0, new_v))
            self.trigger_level_changed.emit(self.trigger_level_v)
            self.update()
        else:
            trig_y = center_y - (self.trigger_level_v / self.volts_div) * dy
            if abs(pos.y() - trig_y) <= 12.0:
                self.setCursor(Qt.CursorShape.SplitVCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging_trigger = False


# ────────────────────────────────────────────────────────────────────────
#  Oscilloscope Widget (Main Panel)
# ────────────────────────────────────────────────────────────────────────

class OscilloscopeWidget(QWidget):
    """Laboratory Oscilloscope and Live Output/Input Monitor widget."""

    def __init__(self, ai_controller: Optional[AIController] = None, parent=None):
        super().__init__(parent)
        self._ai_controller = ai_controller
        self._sequence: Optional[ExperimentSequence] = None
        self._is_running_sweep = True
        self._measurement_channel = "AO0"
        self._latest_pulse_data: Optional[Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, Any], str]] = None
        self._active_primary_freq: Optional[float] = None
        self._active_primary_st: float = 0.0
        self._active_primary_dur: float = 0.010
        self._setup_ui()

        # Connect AI data streams if controller supplied
        if self._ai_controller:
            self._ai_controller.data_received.connect(self._on_ai_data_chunk)
            self._ai_controller.pulse_captured.connect(self._on_pulse_captured)

        # Playback animation timer during sequence execution
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(25)  # 40 fps
        self._play_timer.timeout.connect(self._on_playback_tick)
        self._playback_time_s = 0.0

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(8)

        # Left / Center: Oscilloscope Screen & Measurements
        screen_layout = QVBoxLayout()
        screen_layout.setSpacing(6)

        # Oscilloscope Screen
        self._screen = OscilloscopeScreen(self)
        screen_layout.addWidget(self._screen, 1)

        # Measurement Banner (HUD)
        meas_group = QFrame()
        meas_group.setStyleSheet("background-color: #141420; border: 1px solid #2a2a3e; border-radius: 4px; padding: 4px;")
        meas_lay = QHBoxLayout(meas_group)
        meas_lay.setContentsMargins(8, 4, 8, 4)

        self._lbl_vpp = QLabel("Vpp: -- V")
        self._lbl_vpp.setStyleSheet("color: #00ff88; font-family: Consolas; font-weight: bold;")
        self._lbl_vmax = QLabel("Vmax: -- V")
        self._lbl_vmax.setStyleSheet("color: #00d4ff; font-family: Consolas;")
        self._lbl_vmin = QLabel("Vmin: -- V")
        self._lbl_vmin.setStyleSheet("color: #ffaa00; font-family: Consolas;")
        self._lbl_vrms = QLabel("Vrms: -- V")
        self._lbl_vrms.setStyleSheet("color: #e040fb; font-family: Consolas;")
        self._lbl_freq = QLabel("Freq: -- kHz")
        self._lbl_freq.setStyleSheet("color: #ffff00; font-family: Consolas;")

        meas_lay.addWidget(QLabel("MEASUREMENTS:"))
        meas_lay.addWidget(self._lbl_vpp)
        meas_lay.addWidget(self._lbl_vmax)
        meas_lay.addWidget(self._lbl_vmin)
        meas_lay.addWidget(self._lbl_vrms)
        meas_lay.addWidget(self._lbl_freq)
        meas_lay.addStretch()

        screen_layout.addWidget(meas_group)
        main_layout.addLayout(screen_layout, 3)

        # Right Panel: Oscilloscope Instrument Controls & Pulse Gating Tabs
        controls_panel = QFrame()
        controls_panel.setFixedWidth(360)
        controls_panel.setStyleSheet("background-color: #1a1a28; border: 1px solid #333348; border-radius: 6px;")
        cp_layout = QVBoxLayout(controls_panel)
        cp_layout.setContentsMargins(6, 6, 6, 6)
        cp_layout.setSpacing(6)

        # Instrument Tab Widget
        self._ctrl_tabs = QTabWidget()
        self._ctrl_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #333348; background-color: #1a1a28; }
            QTabBar::tab { background-color: #12121e; color: #a0a0c0; padding: 6px 10px; font-weight: bold; border-top-left-radius: 4px; border-top-right-radius: 4px; }
            QTabBar::tab:selected { background-color: #242438; color: #00d4ff; border-bottom: 2px solid #00d4ff; }
        """)

        # ═══════════════════════════════════════════════════════════════
        # Tab 1: Scope Controls & Toggles
        # ═══════════════════════════════════════════════════════════════
        scope_tab = QWidget()
        st_layout = QVBoxLayout(scope_tab)
        st_layout.setContentsMargins(4, 4, 4, 4)
        st_layout.setSpacing(6)

        # 1. Horizontal Timebase (µs/div, ms/div, s/div)
        tb_group = QGroupBox("Horizontal (Timebase)")
        tb_lay = QGridLayout(tb_group)

        tb_lay.addWidget(QLabel("Scale:"), 0, 0)
        self._timebase_combo = QComboBox()
        self._timebase_values = [
            1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 50e-6, 100e-6,
            200e-6, 500e-6, 1e-3, 2e-3, 5e-3, 10e-3, 20e-3,
            50e-3, 100e-3, 200e-3, 500e-3, 1.0, 2.0, 5.0
        ]
        self._timebase_combo.addItems([
            "1 µs/div", "2 µs/div", "5 µs/div", "10 µs/div", "20 µs/div", "50 µs/div", "100 µs/div",
            "200 µs/div", "500 µs/div", "1 ms/div", "2 ms/div", "5 ms/div", "10 ms/div", "20 ms/div",
            "50 ms/div", "100 ms/div", "200 ms/div", "500 ms/div", "1 s/div", "2 s/div", "5 s/div"
        ])
        self._timebase_combo.setCurrentIndex(9)  # 1 ms/div
        self._timebase_combo.currentIndexChanged.connect(self._on_timebase_changed)
        tb_lay.addWidget(self._timebase_combo, 0, 1)

        tb_lay.addWidget(QLabel("Offset:"), 1, 0)
        self._offset_spin = QDoubleSpinBox()
        self._offset_spin.setRange(-1000.0, 1000.0)
        self._offset_spin.setDecimals(4)
        self._offset_spin.setValue(0.0)
        self._offset_spin.setSuffix(" s")
        self._offset_spin.valueChanged.connect(self._on_time_offset_changed)
        self._screen.time_offset_changed.connect(self._offset_spin.setValue)
        tb_lay.addWidget(self._offset_spin, 1, 1)

        st_layout.addWidget(tb_group)

        # 2. Vertical Scale (Volts/Div)
        vert_group = QGroupBox("Vertical (Volts/Div)")
        v_lay = QGridLayout(vert_group)

        v_lay.addWidget(QLabel("Scale:"), 0, 0)
        self._volts_combo = QComboBox()
        self._volts_combo.addItems([
            "50 mV/div", "100 mV/div", "200 mV/div", "500 mV/div",
            "1.0 V/div", "2.0 V/div", "5.0 V/div", "10.0 V/div"
        ])
        self._volts_values = [0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]
        self._volts_combo.setCurrentIndex(4)  # 1.0 V/div
        self._volts_combo.currentIndexChanged.connect(self._on_volts_changed)
        v_lay.addWidget(self._volts_combo, 0, 1)

        st_layout.addWidget(vert_group)

        # 3. Trigger Configuration
        trig_group = QGroupBox("Trigger Control")
        t_lay = QGridLayout(trig_group)

        t_lay.addWidget(QLabel("Source:"), 0, 0)
        self._trig_src_combo = QComboBox()
        self._trig_src_combo.addItems(["Free Run (Auto)", "PXI_Trig0", "AO0 Trigger", "AI0 Edge"])
        t_lay.addWidget(self._trig_src_combo, 0, 1)

        t_lay.addWidget(QLabel("Slope:"), 1, 0)
        self._trig_slope_combo = QComboBox()
        self._trig_slope_combo.addItems(["Rising (↗)", "Falling (↘)"])
        t_lay.addWidget(self._trig_slope_combo, 1, 1)

        t_lay.addWidget(QLabel("Level:"), 2, 0)
        self._trig_level_spin = QDoubleSpinBox()
        self._trig_level_spin.setRange(-10.0, 10.0)
        self._trig_level_spin.setDecimals(2)
        self._trig_level_spin.setValue(0.0)
        self._trig_level_spin.setSuffix(" V")
        self._trig_level_spin.valueChanged.connect(self._screen.set_trigger_level)
        self._screen.trigger_level_changed.connect(self._trig_level_spin.setValue)
        t_lay.addWidget(self._trig_level_spin, 2, 1)

        st_layout.addWidget(trig_group)

        # 4. Channel Selection & Toggles
        chan_group = QGroupBox("Channels Visible")
        chan_lay = QVBoxLayout(chan_group)
        chan_lay.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(130)
        scroll_w = QWidget()
        sw_lay = QVBoxLayout(scroll_w)
        sw_lay.setContentsMargins(2, 2, 2, 2)
        sw_lay.setSpacing(3)

        self._chan_checkboxes: Dict[str, QCheckBox] = {}

        # Analog Output Channels (Generated Waveforms)
        sw_lay.addWidget(QLabel("<b>Analog Outputs (AO):</b>"))
        for i in range(8):
            name = f"AO{i}"
            chk = QCheckBox(f"{name} Waveform")
            color = AO_OSC_COLORS[i % len(AO_OSC_COLORS)]
            chk.setStyleSheet(f"QCheckBox {{ color: {color}; font-weight: bold; }}")
            chk.setChecked(i == 0)
            chk.toggled.connect(lambda state, n=name: self._screen.set_trace_visibility(n, state))
            sw_lay.addWidget(chk)
            self._chan_checkboxes[name] = chk

        # Analog Input Channels (Live DAQ Card)
        sw_lay.addWidget(QLabel("<b>Analog Inputs (AI):</b>"))
        for i in range(4):
            name = f"AI{i}"
            chk = QCheckBox(f"{name} Input")
            color = AI_OSC_COLORS[i % len(AI_OSC_COLORS)]
            chk.setStyleSheet(f"QCheckBox {{ color: {color}; font-weight: bold; }}")
            chk.setChecked(i == 0)
            chk.toggled.connect(lambda state, n=name: self._screen.set_trace_visibility(n, state))
            sw_lay.addWidget(chk)
            self._chan_checkboxes[name] = chk

        scroll.setWidget(scroll_w)
        chan_lay.addWidget(scroll)
        st_layout.addWidget(chan_group)

        # Action Buttons (Scope)
        btn_lay = QGridLayout()
        self._btn_run = QPushButton("▶ Run Sweep")
        self._btn_run.setStyleSheet("background-color: #00aa66; color: #ffffff; font-weight: bold;")
        self._btn_run.clicked.connect(self._toggle_run)
        btn_lay.addWidget(self._btn_run, 0, 0)

        self._btn_single = QPushButton("🎯 Single")
        self._btn_single.clicked.connect(self._single_sweep)
        btn_lay.addWidget(self._btn_single, 0, 1)

        btn_autoscale = QPushButton("📐 Auto-Scale")
        btn_autoscale.clicked.connect(self._auto_scale)
        btn_lay.addWidget(btn_autoscale, 1, 0)

        btn_export = QPushButton("💾 Export CSV")
        btn_export.clicked.connect(self._export_csv)
        btn_lay.addWidget(btn_export, 1, 1)

        st_layout.addLayout(btn_lay)
        st_layout.addStretch()

        self._ctrl_tabs.addTab(scope_tab, "📊 Scope")

        # ═══════════════════════════════════════════════════════════════
        # Tab 2: 🎯 Pulse-Gated Capture & CSV Export (User Feature)
        # ═══════════════════════════════════════════════════════════════
        pulse_tab = QWidget()
        pt_layout = QVBoxLayout(pulse_tab)
        pt_layout.setContentsMargins(6, 6, 6, 6)
        pt_layout.setSpacing(6)

        hdr_pulse = QLabel("<b>🎯 Input 1 Pulse-Gated Capture</b>")
        hdr_pulse.setStyleSheet("color: #00d4ff; font-size: 13px;")
        pt_layout.addWidget(hdr_pulse)

        info_lbl = QLabel(
            "Controls acquisition strictly while the digital pulse is active and automatically saves to CSV."
        )
        info_lbl.setStyleSheet("color: #a0a0c0; font-size: 10px;")
        info_lbl.setWordWrap(True)
        pt_layout.addWidget(info_lbl)

        # Pulse Gate Config Group
        gate_group = QGroupBox("Gate Configuration")
        gg_lay = QGridLayout(gate_group)
        gg_lay.setSpacing(6)

        # 1. Target Input
        gg_lay.addWidget(QLabel("Target Input:"), 0, 0)
        self._gate_target_chan_combo = QComboBox()
        self._gate_target_chan_combo.addItem("AI0 (Input 1)", ["PXI2Slot4/ai0"])
        self._gate_target_chan_combo.addItem("AI1 (Input 2)", ["PXI2Slot4/ai1"])
        self._gate_target_chan_combo.addItem("AI2 (Input 3)", ["PXI2Slot4/ai2"])
        self._gate_target_chan_combo.addItem("AI3 (Input 4)", ["PXI2Slot4/ai3"])
        self._gate_target_chan_combo.addItem("All Inputs (AI0-AI3)", ["PXI2Slot4/ai0", "PXI2Slot4/ai1", "PXI2Slot4/ai2", "PXI2Slot4/ai3"])
        gg_lay.addWidget(self._gate_target_chan_combo, 0, 1)

        # 2. Gate Pulse Source (lists DIO0..DIO20 pulses from sequence)
        gg_lay.addWidget(QLabel("Gate Pulse:"), 1, 0)
        self._gate_source_combo = QComboBox()
        self._gate_source_combo.addItem("DIO0: Laser Gate (20.00 ms)", {"channel": 0, "duration_ms": 20.0, "name": "Laser Gate"})
        self._gate_source_combo.addItem("Manual Pulse Duration", {"channel": -1, "duration_ms": 20.0, "name": "Manual"})
        self._gate_source_combo.addItem("PXI_Trig0 Hardware Line", {"channel": -2, "duration_ms": 20.0, "name": "PXI_Trig0"})
        self._gate_source_combo.currentIndexChanged.connect(self._on_gate_source_changed)
        gg_lay.addWidget(self._gate_source_combo, 1, 1)

        # 3. Gate Active Duration
        gg_lay.addWidget(QLabel("Duration:"), 2, 0)
        self._gate_duration_spin = QDoubleSpinBox()
        self._gate_duration_spin.setRange(0.001, 60000.0)
        self._gate_duration_spin.setDecimals(3)
        self._gate_duration_spin.setValue(20.0)
        self._gate_duration_spin.setSuffix(" ms")
        gg_lay.addWidget(self._gate_duration_spin, 2, 1)

        # 4. Sampling Rate
        gg_lay.addWidget(QLabel("Sample Rate:"), 3, 0)
        self._gate_rate_combo = QComboBox()
        self._gate_rate_combo.addItem("100 kS/s", 100000.0)
        self._gate_rate_combo.addItem("250 kS/s", 250000.0)
        self._gate_rate_combo.addItem("500 kS/s", 500000.0)
        self._gate_rate_combo.addItem("1.0 MS/s", 1000000.0)
        self._gate_rate_combo.addItem("2.0 MS/s", 2000000.0)
        self._gate_rate_combo.setCurrentIndex(2)  # 500 kS/s
        gg_lay.addWidget(self._gate_rate_combo, 3, 1)

        # 5. Checkboxes
        self._chk_auto_csv = QCheckBox("Auto-Export to CSV upon capture")
        self._chk_auto_csv.setChecked(True)
        self._chk_auto_csv.setStyleSheet("font-weight: bold; color: #00ff88;")
        gg_lay.addWidget(self._chk_auto_csv, 4, 0, 1, 2)

        self._chk_capture_on_run = QCheckBox("Auto-Capture on Experiment Run")
        self._chk_capture_on_run.setChecked(False)
        self._chk_capture_on_run.setStyleSheet("color: #00d4ff;")
        gg_lay.addWidget(self._chk_capture_on_run, 5, 0, 1, 2)

        pt_layout.addWidget(gate_group)

        # Main Capture Action Button
        self._btn_capture_pulse = QPushButton("▶ Capture Input 1 Gated Pulse")
        self._btn_capture_pulse.setStyleSheet(
            "background-color: #00aa66; font-size: 13px; font-weight: bold; padding: 8px; color: white; border-radius: 4px;"
        )
        self._btn_capture_pulse.clicked.connect(self._trigger_pulse_capture)
        pt_layout.addWidget(self._btn_capture_pulse)

        # Export Actions
        csv_btn_lay = QHBoxLayout()
        self._btn_save_csv_as = QPushButton("💾 Save CSV As...")
        self._btn_save_csv_as.setEnabled(False)
        self._btn_save_csv_as.clicked.connect(self._save_latest_csv_as)
        csv_btn_lay.addWidget(self._btn_save_csv_as)

        self._btn_open_folder = QPushButton("📁 Open Captures")
        self._btn_open_folder.clicked.connect(self._open_captures_folder)
        csv_btn_lay.addWidget(self._btn_open_folder)
        pt_layout.addLayout(csv_btn_lay)

        # Results & Status HUD Card
        card = QFrame()
        card.setStyleSheet("background-color: #12121e; border: 1px solid #2a2a3e; border-radius: 4px; padding: 6px;")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(6, 6, 6, 6)
        card_lay.setSpacing(4)

        self._lbl_capture_status = QLabel("Status: Ready to capture Input 1")
        self._lbl_capture_status.setStyleSheet("color: #00ff88; font-family: Consolas; font-weight: bold;")
        card_lay.addWidget(self._lbl_capture_status)

        self._lbl_capture_summary = QLabel("Samples: --  |  Duration: --")
        self._lbl_capture_summary.setStyleSheet("color: #a0a0c0; font-family: Consolas; font-size: 11px;")
        card_lay.addWidget(self._lbl_capture_summary)

        self._lbl_capture_file = QLabel("File: --")
        self._lbl_capture_file.setStyleSheet("color: #00d4ff; font-family: Consolas; font-size: 10px;")
        self._lbl_capture_file.setWordWrap(True)
        card_lay.addWidget(self._lbl_capture_file)

        pt_layout.addWidget(card)
        pt_layout.addStretch()

        self._ctrl_tabs.addTab(pulse_tab, "🎯 Pulse Capture")

        cp_layout.addWidget(self._ctrl_tabs)
        main_layout.addWidget(controls_panel, 0)

    # ── Signal Handlers ─────────────────────────────────────────────────

    def _on_timebase_changed(self, idx: int):
        if 0 <= idx < len(self._timebase_values):
            self._screen.set_timebase(self._timebase_values[idx])

    def _on_volts_changed(self, idx: int):
        if 0 <= idx < len(self._volts_values):
            self._screen.set_volts_div(self._volts_values[idx])

    def _on_time_offset_changed(self, val: float):
        self._screen.set_time_offset(val)

    def _toggle_run(self):
        self._is_running_sweep = not self._is_running_sweep
        if self._is_running_sweep:
            self._btn_run.setText("⏸ Pause")
            self._btn_run.setStyleSheet("background-color: #ffaa00; color: #000000; font-weight: bold;")
            if self._ai_controller and not self._ai_controller.is_running():
                self._ai_controller.start_acquisition()
        else:
            self._btn_run.setText("▶ Run Sweep")
            self._btn_run.setStyleSheet("background-color: #00aa66; color: #ffffff; font-weight: bold;")
            if self._ai_controller and self._ai_controller.is_running():
                self._ai_controller.stop_acquisition()

    def _single_sweep(self):
        self._is_running_sweep = True
        self._screen.set_sweep_progress(0.0)

    def _auto_scale(self):
        """Automatically adjust timebase and volts/div to cleanly frame the active signal."""
        active_traces = [
            tr for tr in self._screen._traces.values()
            if tr.get("visible", True) and len(tr["volts"]) > 0
        ]
        if not active_traces:
            return

        # 1. Horizontal Timebase auto-fit
        target_offset = 0.0
        if getattr(self, "_active_primary_freq", None) is not None and self._active_primary_freq >= 1.0:
            # For periodic signals (sine, square), target ~1 cycle per division (10 cycles on screen)
            target_tb = 1.0 / self._active_primary_freq
            tb_idx = min(
                range(len(self._timebase_values)),
                key=lambda i: abs(np.log10(self._timebase_values[i]) - np.log10(target_tb))
            )
            target_offset = getattr(self, "_active_primary_st", 0.0)
        elif getattr(self, "_active_primary_dur", 0.0) > 0.0:
            # Non-periodic active pulse (ramp, etc.): frame active duration across ~8 divisions
            target_tb = self._active_primary_dur / 8.0
            tb_idx = min(
                range(len(self._timebase_values)),
                key=lambda i: abs(np.log10(self._timebase_values[i]) - np.log10(target_tb))
            )
            target_offset = getattr(self, "_active_primary_st", 0.0)
        else:
            all_t_min = min(float(np.min(tr["times"])) for tr in active_traces)
            all_t_max = max(float(np.max(tr["times"])) for tr in active_traces)
            duration_s = max(1e-6, all_t_max - all_t_min)

            # Pick timebase so the active signal occupies ~8 to 10 divisions
            tb_idx = len(self._timebase_values) - 1
            for i, val in enumerate(self._timebase_values):
                if val * 10.0 >= duration_s:
                    tb_idx = i
                    break
            target_offset = all_t_min

        self._timebase_combo.setCurrentIndex(tb_idx)
        self._offset_spin.setValue(target_offset)
        self._screen.set_time_offset(target_offset)

        # 2. Vertical Volts/Div auto-fit
        all_v_max = max(float(np.max(np.abs(tr["volts"]))) for tr in active_traces)
        target_v_div = max(0.05, all_v_max / 3.0)
        closest_v_idx = min(
            range(len(self._volts_values)),
            key=lambda i: abs(self._volts_values[i] - target_v_div)
        )
        self._volts_combo.setCurrentIndex(closest_v_idx)

    def _export_csv(self):
        """Export visible oscilloscope traces to a CSV file."""
        if not self._screen._traces:
            QMessageBox.information(self, "Export", "No active oscilloscope waveform data to export.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Oscilloscope Waveforms", "oscilloscope_capture.csv", "CSV Files (*.csv)"
        )
        if not filepath:
            return

        try:
            import csv
            with open(filepath, "w", newline="") as f:
                writer = csv.writer(f)
                headers = ["Time_s"]
                cols = []
                base_times = None

                for name, tr in self._screen._traces.items():
                    if tr.get("visible", True) and len(tr["times"]) > 0:
                        headers.append(f"{name}_V")
                        cols.append(tr["volts"])
                        if base_times is None:
                            base_times = tr["times"]

                writer.writerow(headers)
                if base_times is not None:
                    min_len = min([len(base_times)] + [len(c) for c in cols])
                    for i in range(min_len):
                        row = [f"{base_times[i]:.9f}"] + [f"{c[i]:.6f}" for c in cols]
                        writer.writerow(row)

            QMessageBox.information(self, "Export Successful", f"Saved oscilloscope capture to:\n{filepath}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", f"Failed to save CSV: {exc}")

    # ── Pulse-Gated Capture & CSV Handlers ──────────────────────────────

    def _on_gate_source_changed(self, idx: int):
        data = self._gate_source_combo.itemData(idx)
        if data and "duration_ms" in data:
            self._gate_duration_spin.setValue(float(data["duration_ms"]))

    def _update_gate_combo(self, seq: ExperimentSequence):
        if not seq or not hasattr(self, "_gate_source_combo"):
            return
        curr_text = self._gate_source_combo.currentText()
        self._gate_source_combo.blockSignals(True)
        self._gate_source_combo.clear()

        clock = seq.clock_hz
        for dev in seq.digital_events:
            if dev.enabled and (dev.end_ticks > dev.start_ticks):
                dur_ms = ((dev.end_ticks - dev.start_ticks) / clock) * 1000.0
                tag = f"DIO{dev.channel}: {dev.name or 'Pulse'} ({dur_ms:.2f} ms)"
                self._gate_source_combo.addItem(tag, {"channel": dev.channel, "duration_ms": dur_ms, "name": dev.name or 'Pulse'})

        self._gate_source_combo.addItem("Manual Pulse Duration", {"channel": -1, "duration_ms": 20.0, "name": "Manual"})
        self._gate_source_combo.addItem("PXI_Trig0 Hardware Line", {"channel": -2, "duration_ms": 20.0, "name": "PXI_Trig0"})
        self._gate_source_combo.blockSignals(False)

        idx = self._gate_source_combo.findText(curr_text)
        if idx >= 0:
            self._gate_source_combo.setCurrentIndex(idx)
        elif self._gate_source_combo.count() > 0:
            self._gate_source_combo.setCurrentIndex(0)
            self._on_gate_source_changed(0)

    def _trigger_pulse_capture(self):
        """Initiate pulse-gated capture on selected Input channel."""
        dur_ms = self._gate_duration_spin.value()
        dur_s = max(1e-6, dur_ms / 1000.0)
        rate_hz = float(self._gate_rate_combo.currentData() or 500000.0)
        target_name = self._gate_target_chan_combo.currentText()
        chans = self._gate_target_chan_combo.currentData() or ["PXI2Slot4/ai0"]
        gate_name = self._gate_source_combo.currentText()
        auto_csv = self._chk_auto_csv.isChecked()

        self._lbl_capture_status.setText(f"⏳ Capturing Input 1 ({dur_ms:.2f} ms)...")
        self._lbl_capture_file.setText("Acquiring data...")

        captures_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")
        os.makedirs(captures_dir, exist_ok=True)

        if self._ai_controller:
            trig_src = "/PXI2Slot3/PXI_Trig0" if "PXI_Trig0" in gate_name else None
            self._ai_controller.start_pulse_capture(
                channels=chans,
                duration_s=dur_s,
                sample_rate_hz=rate_hz,
                trigger_source=trig_src,
                metadata={
                    "gate_source": gate_name,
                    "duration_ms": dur_ms,
                    "target_input": target_name,
                    "sample_rate": rate_hz,
                },
                auto_export_csv=auto_csv,
                csv_dir=captures_dir,
            )
        else:
            # Fallback direct simulation if ai_controller not supplied
            num_samples = max(2, int(round(dur_s * rate_hz)))
            times = np.linspace(0.0, dur_s, num_samples, endpoint=False)
            freq = 2500.0
            noise = np.random.normal(0.0, 0.02, num_samples)
            sig = 2.5 * np.sin(2.0 * np.pi * freq * times) + 2.5 + noise
            ch_data = {"PXI2Slot4/ai0": sig}
            meta = {"gate_source": gate_name, "duration_ms": dur_ms, "target_input": target_name, "sample_rate": rate_hz}
            csv_path = ""
            if auto_csv:
                from ai_controller import AIController
                t_str = time.strftime("%Y%m%d_%H%M%S")
                fpath = os.path.join(captures_dir, f"gated_capture_AI0_{t_str}.csv")
                csv_path = AIController.export_to_csv(fpath, times, ch_data, meta)
            self._on_pulse_captured(times, ch_data, meta, csv_path)

    def _on_pulse_captured(self, times: np.ndarray, channel_data: Dict[str, np.ndarray], metadata: dict, csv_path: str):
        """Callback when pulse-gated acquisition completes."""
        if not channel_data:
            return

        self._latest_pulse_data = (times, channel_data, metadata, csv_path)

        primary_key = list(channel_data.keys())[0]
        volts = channel_data[primary_key]
        short_name = primary_key.split("/")[-1].upper()
        if not short_name.startswith("AI"):
            short_name = "AI0"

        # Update trace on screen
        self._screen.update_trace(short_name, times, volts, "#00ff66", visible=True)
        chk = self._chan_checkboxes.get(short_name)
        if chk:
            chk.setChecked(True)

        # Update measurements HUD
        self._update_measurements(volts)

        # Update status banner
        dur_ms = metadata.get("duration_ms", (times[-1] - times[0]) * 1000.0 if len(times) > 0 else 0.0)
        self._lbl_capture_status.setText(f"[OK] Captured {len(times):,} samples ({dur_ms:.2f} ms)")
        self._lbl_capture_summary.setText(f"Vpp: {np.ptp(volts):.2f}V | Vmax: {np.max(volts):+.2f}V | Vmin: {np.min(volts):+.2f}V")
        if csv_path:
            self._lbl_capture_file.setText(f"Saved: {os.path.basename(csv_path)}")
            self._lbl_capture_file.setToolTip(csv_path)
        else:
            self._lbl_capture_file.setText("CSV Auto-Save: Disabled")

        self._btn_save_csv_as.setEnabled(True)

        # Auto scale to frame the captured pulse
        self._auto_scale()

    def _open_captures_folder(self):
        """Open the captures folder in Windows Explorer."""
        captures_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures")
        os.makedirs(captures_dir, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(captures_dir)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", captures_dir])
        except Exception as exc:
            QMessageBox.information(self, "Captures Folder", f"Captures directory:\n{captures_dir}")

    def _save_latest_csv_as(self):
        """Save the latest captured pulse data to a custom user file path."""
        if not self._latest_pulse_data:
            QMessageBox.information(self, "Save CSV", "No pulse capture data available to save.")
            return

        times, ch_data, meta, _ = self._latest_pulse_data
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Captured Pulse CSV", "captured_pulse_input1.csv", "CSV Files (*.csv)"
        )
        if not filepath:
            return

        try:
            from ai_controller import AIController
            saved = AIController.export_to_csv(filepath, times, ch_data, meta)
            QMessageBox.information(self, "Export Successful", f"Saved capture to:\n{saved}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", f"Failed to save CSV: {exc}")

    # ── Real-Time Streaming & Execution Link ────────────────────────────

    def load_sequence_waveforms(self, seq: ExperimentSequence):
        """Load and display the analog output waveforms generated by the sequence."""
        self._sequence = seq
        if not seq:
            return

        clock = seq.clock_hz
        total_s = max(1e-6, seq.sequence_duration_ticks / clock)

        # Clear existing AO traces and sync checkboxes before loading new ones
        for i in range(8):
            name = f"AO{i}"
            if name in self._screen._traces:
                del self._screen._traces[name]
            chk = self._chan_checkboxes.get(name)
            if chk:
                chk.blockSignals(True)
                chk.setChecked(False)
                chk.blockSignals(False)

        # Clear stale AI traces if AI controller is not actively streaming
        if not (self._ai_controller and hasattr(self._ai_controller, "is_running") and self._ai_controller.is_running()):
            for ai_idx in range(8):
                ai_name = f"AI{ai_idx}"
                if ai_name in self._screen._traces:
                    del self._screen._traces[ai_name]
                chk = self._chan_checkboxes.get(ai_name)
                if chk:
                    chk.blockSignals(True)
                    chk.setChecked(False)
                    chk.blockSignals(False)

        primary_volts = None
        primary_freq = None
        loaded_any = False

        for i, aev in enumerate(seq.analog_events):
            if i >= 8:
                break
            name = f"AO{i}"
            if not aev.enabled:
                continue

            # Determine waveform timing directly from analog event
            st_s = getattr(aev, "start_ms", 0.0) / 1000.0
            dur_ms = getattr(aev, "duration_ms", 10.0)
            end_s = getattr(aev, "end_ms", st_s * 1000.0 + dur_ms) / 1000.0

            dur_s = max(1e-9, end_s - st_s)
            wtype = aev.waveform_type.value if hasattr(aev.waveform_type, "value") else str(aev.waveform_type).lower()
            freq = max(0.1, getattr(aev, "frequency_hz", 10000.0))
            v_s = aev.start_voltage
            v_e = aev.end_voltage

            num_cycles = max(0.001, freq * dur_s)
            if "sine" in wtype or "square" in wtype:
                pts_needed = int(round(num_cycles * 50))
                n_active = int(np.clip(pts_needed, 1000, 100000))
            elif "ramp" in wtype:
                n_active = 2000
            elif "constant" in wtype:
                n_active = 100
            else:
                n_active = 2000

            t_list = []
            v_list = []

            # Pre-pulse quiet interval (0.0 V dense baseline)
            if st_s > 1e-9:
                n_pre = max(20, int(round((st_s / total_s) * 1000)))
                t_pre = np.linspace(0.0, st_s, n_pre, endpoint=False, dtype=np.float64)
                v_pre = np.zeros(n_pre, dtype=np.float64)
                t_list.append(t_pre)
                v_list.append(v_pre)

            # Active waveform window (endpoint=False prevents duplicate sample at end_s)
            t_active = np.linspace(st_s, end_s, n_active, endpoint=False, dtype=np.float64)
            t_rel = t_active - st_s

            if "ramp" in wtype:
                v_active = v_s + (v_e - v_s) * (t_rel / dur_s)
            elif "sine" in wtype:
                amp = (v_e - v_s) / 2.0
                offset = (v_e + v_s) / 2.0
                v_active = offset + amp * np.sin(2.0 * np.pi * freq * t_rel)
            elif "square" in wtype:
                phase = (t_rel * freq) % 1.0
                v_active = np.where(phase < 0.5, v_e, v_s)
            elif "constant" in wtype:
                v_active = np.full(n_active, v_s, dtype=np.float64)
            else:
                v_active = v_s + (v_e - v_s) * (t_rel / dur_s)

            t_list.append(t_active)
            v_list.append(v_active)

            # Post-pulse quiet interval (0.0 V dense baseline to total duration)
            if end_s < total_s:
                n_post = max(50, int(round(((total_s - end_s) / total_s) * 2000)))
                t_post = np.linspace(end_s, total_s, n_post, dtype=np.float64)
                v_post = np.zeros(n_post, dtype=np.float64)
                t_list.append(t_post)
                v_list.append(v_post)

            trace_times = np.concatenate(t_list)
            trace_volts = np.concatenate(v_list)

            vis = self._chan_checkboxes.get(name, None)
            if vis:
                vis.blockSignals(True)
                vis.setChecked(True)
                vis.blockSignals(False)
            self._screen.update_trace(name, trace_times, trace_volts, AO_OSC_COLORS[i % len(AO_OSC_COLORS)], visible=True)
            loaded_any = True

            is_periodic = ("sine" in wtype or "square" in wtype)
            if primary_volts is None or (is_periodic and self._active_primary_freq is None) or (name == self._measurement_channel):
                primary_volts = v_active
                primary_freq = freq
                self._active_primary_freq = freq if is_periodic else None
                self._active_primary_st = st_s
                self._active_primary_dur = dur_s

        if primary_volts is not None:
            self._update_measurements(primary_volts, primary_freq)

        # Update gate pulse combo with sequence digital events
        self._update_gate_combo(seq)

        if loaded_any:
            self._auto_scale()

    def start_execution_sweep(self):
        """Trigger live oscilloscope sweep during sequence execution."""
        self._playback_time_s = 0.0
        self._is_running_sweep = True
        self._play_timer.start()

        # If pulse-gated capture on experiment run is checked, automatically trigger capture of Input 1!
        if hasattr(self, "_chk_capture_on_run") and self._chk_capture_on_run.isChecked():
            # Clear previous capture trace before triggering new capture to prevent double-pulse overlay
            for ai_name in ["AI0", "AI1", "AI2", "AI3"]:
                if ai_name in self._screen._traces:
                    del self._screen._traces[ai_name]
            self._trigger_pulse_capture()
        elif self._ai_controller and not self._ai_controller.is_running():
            self._ai_controller.start_acquisition()

    def stop_execution_sweep(self):
        """Stop oscilloscope sweep when execution finishes."""
        self._play_timer.stop()
        self._screen.set_sweep_progress(None)
        if self._ai_controller and self._ai_controller.is_running():
            self._ai_controller.stop_acquisition()

    def _on_playback_tick(self):
        if not self._sequence:
            return
        total_s = max(0.01, self._sequence.sequence_duration_ticks / self._sequence.clock_hz)
        self._playback_time_s += 0.025
        if self._playback_time_s > total_s:
            self._playback_time_s = total_s
            self._play_timer.stop()
            self._screen.set_sweep_progress(None)
            return

        t_w_start = self._screen.time_offset_s
        t_w_len = 10.0 * self._screen.timebase_s_div
        norm = (self._playback_time_s - t_w_start) / t_w_len
        self._screen.set_sweep_progress(norm if (0.0 <= norm <= 1.0) else None)

    def _on_ai_data_chunk(self, times: np.ndarray, channel_data: Dict[str, np.ndarray]):
        """Callback receiving streaming Analog Input samples from AI card."""
        if not self._is_running_sweep:
            return

        for idx, (ch_name, volts) in enumerate(channel_data.items()):
            short_name = f"AI{idx}"
            vis = self._chan_checkboxes.get(short_name, None)
            is_vis = vis.isChecked() if vis else True
            color = AI_OSC_COLORS[idx % len(AI_OSC_COLORS)]
            self._screen.append_ai_chunk(short_name, times, volts, color, visible=is_vis)

            if short_name == "AI0":
                self._update_measurements(volts)

    def _update_measurements(self, volts: np.ndarray, freq_hz: Optional[float] = None):
        """Compute and display real-time oscilloscope measurements."""
        if len(volts) == 0:
            return
        v_max = float(np.max(volts))
        v_min = float(np.min(volts))
        v_pp = v_max - v_min
        v_rms = float(np.sqrt(np.mean(volts ** 2)))

        self._lbl_vpp.setText(f"Vpp: {v_pp:.2f} V")
        self._lbl_vmax.setText(f"Vmax: {v_max:+.2f} V")
        self._lbl_vmin.setText(f"Vmin: {v_min:+.2f} V")
        self._lbl_vrms.setText(f"Vrms: {v_rms:.2f} V")
        if freq_hz is not None and freq_hz > 0:
            if freq_hz >= 1e6:
                self._lbl_freq.setText(f"Freq: {freq_hz/1e6:.2f} MHz")
            elif freq_hz >= 1e3:
                self._lbl_freq.setText(f"Freq: {freq_hz/1e3:.2f} kHz")
            else:
                self._lbl_freq.setText(f"Freq: {freq_hz:.1f} Hz")
        else:
            self._lbl_freq.setText("Freq: -- kHz")
