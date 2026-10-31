"""
Sequence Simulation & Multi-Channel Oscilloscope Viewer.

Simulates the generated experimental sequence across time, rendering
Signal vs. Time for all analog and digital channels with distinct vibrant
colors, interactive multi-lane oscilloscope view, crosshair inspection,
and timing measurement tools.
"""

from __future__ import annotations

import math
import sys
import os
from typing import List, Dict, Any, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QRadioButton, QButtonGroup, QScrollArea,
    QFrame, QSizePolicy, QToolTip,
)
from PySide6.QtCore import Signal, Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPainterPath,
    QMouseEvent, QWheelEvent, QLinearGradient,
)

from sequence_model import (
    ExperimentSequence, DigitalEvent, AnalogEvent,
    WaveformType, TimeUnit, FPGA_CLOCK_HZ,
)
from waveform_generator import (
    generate_ramp, generate_sine, generate_square, generate_constant,
)
from .styles import COLORS

# Distinct color palette for channels
AO_COLORS = [
    "#00e5ff",  # AO0 Cyan
    "#ffab00",  # AO1 Amber
    "#ff5252",  # AO2 Coral
    "#e040fb",  # AO3 Purple
    "#00e676",  # AO4 Spring Green
    "#2979ff",  # AO5 Neon Blue
    "#ff4081",  # AO6 Hot Pink
    "#ffd600",  # AO7 Gold
]

DIO_COLORS = [
    "#00ffcc", "#76ff03", "#ff9100", "#ff1744", "#d500f9",
    "#3d5afe", "#f50057", "#00e676", "#ffea00", "#00b0ff",
    "#00e5ff", "#c6ff00", "#ff6d00", "#ff3d00", "#aa00ff",
    "#2979ff", "#ff80ab", "#b9f6ca", "#ffe57f", "#80d8ff",
]


# ────────────────────────────────────────────────────────────────────────
#  Simulation Canvas Widget (Custom QPainter)
# ────────────────────────────────────────────────────────────────────────

class SimulationCanvas(QWidget):
    """Custom oscilloscope canvas plotting Signal vs. Time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(450)
        self.setMinimumWidth(600)

        self._sequence: Optional[ExperimentSequence] = None
        self._display_mode = "STACKED"  # "STACKED" or "OVERLAY"
        self._time_unit = "ms"          # "ms", "µs", "s"
        self._zoom = 1.0
        self._pan_offset_x = 0.0

        # Synthesized trace data: list of dicts
        # { "name": str, "type": "analog"|"digital", "ch_idx": int, "color": str,
        #   "times": np.ndarray (s), "voltages": np.ndarray (V), "v_min": float, "v_max": float }
        self._traces: List[Dict[str, Any]] = []

        # Cursor inspection state
        self._cursor_x: Optional[float] = None
        self._hover_time_s: Optional[float] = None

        # Layout metrics
        self._gutter_width = 220.0
        self._ruler_height = 36.0
        self._lane_height = 54.0
        self._lane_spacing = 8.0

    def set_sequence(self, sequence: ExperimentSequence):
        self._sequence = sequence
        self.recompute_simulation()

    def set_display_mode(self, mode: str):
        self._display_mode = mode
        self.update()

    def set_time_unit(self, unit: str):
        self._time_unit = unit
        self.update()

    def set_zoom(self, zoom: float):
        self._zoom = max(0.1, min(zoom, 100.0))
        self.update()

    def fit_sequence(self):
        self._zoom = 1.0
        self._pan_offset_x = 0.0
        self.update()

    # ── Signal Synthesis Engine ─────────────────────────────────────────

    def recompute_simulation(self):
        """Synthesize continuous voltage signals V(t) for all active channels."""
        self._traces = []
        if not self._sequence:
            self.update()
            return

        clock = self._sequence.clock_hz
        total_ticks = max(1, self._sequence.sequence_duration_ticks)
        total_s = total_ticks / clock

        # 1. Analog Channels (AO0 to AO7)
        # Hardware rule: If a pulse is made in DIO0..DIO7, it starts the respective analog channel
        # with respect to its configured wave specifically for the part where the digital pulse is!
        for ao_idx in range(min(8, len(self._sequence.analog_events))):
            aev = self._sequence.analog_events[ao_idx]

            # Find matching digital trigger pulse on DIO{ao_idx}
            dio_match = [d for d in self._sequence.digital_events if d.channel == ao_idx]
            dev = dio_match[0] if dio_match else None

            # An analog channel runs if either DIO{ao_idx} pulse is active, OR aev is directly enabled
            dio_active = (dev is not None and dev.enabled and dev.end_ticks > dev.start_ticks)
            if not dio_active and not aev.enabled:
                continue

            color = AO_COLORS[ao_idx % len(AO_COLORS)]

            if dio_active:
                st_s = dev.start_ticks / clock
                end_s = dev.end_ticks / clock
            else:
                st_s = getattr(aev, "start_ms", 0.0) / 1000.0
                end_s = getattr(aev, "end_ms", 42.5) / 1000.0

            dur_s = max(1e-9, end_s - st_s)
            wtype = aev.waveform_type.value if hasattr(aev.waveform_type, "value") else str(aev.waveform_type).lower()
            freq = max(0.1, getattr(aev, "frequency_hz", 10000.0))
            v_s = aev.start_voltage
            v_e = aev.end_voltage

            num_cycles = max(0.001, freq * dur_s)

            # High-fidelity adaptive point count:
            # For sine/square waves, allocate at least 50 points per cycle (up to 100,000 pts)
            # so that high frequency signals have zero aliasing and crisp transitions!
            if wtype in ("sine", "square"):
                pts_needed = int(round(num_cycles * 50))
                n_active = int(np.clip(pts_needed, 1000, 100000))
            elif wtype == "ramp":
                n_active = 2000
            elif wtype == "constant":
                n_active = 50
            else:
                n_active = 2000

            t_list = []
            v_list = []

            # Pre-pulse quiet interval (0.0 V safe voltage)
            if st_s > 1e-9:
                t_list.append(np.array([0.0, max(0.0, st_s - 1e-9)], dtype=np.float64))
                v_list.append(np.array([0.0, 0.0], dtype=np.float64))

            # Active waveform window
            t_active = np.linspace(st_s, end_s, n_active, dtype=np.float64)
            t_rel = t_active - st_s

            if wtype == "ramp":
                v_active = v_s + (v_e - v_s) * (t_rel / dur_s)
            elif wtype == "sine":
                amp = (v_e - v_s) / 2.0
                offset = (v_e + v_s) / 2.0
                v_active = offset + amp * np.sin(2.0 * np.pi * freq * t_rel)
            elif wtype == "square":
                phase = (t_rel * freq) % 1.0
                v_active = np.where(phase < 0.5, v_e, v_s)
            elif wtype == "constant":
                v_active = np.full(n_active, v_s, dtype=np.float64)
            else:
                v_active = v_s + (v_e - v_s) * (t_rel / dur_s)

            t_list.append(t_active)
            v_list.append(v_active)

            # Post-pulse quiet interval (0.0 V safe voltage)
            if end_s < total_s - 1e-9:
                t_list.append(np.array([min(total_s, end_s + 1e-9), total_s], dtype=np.float64))
                v_list.append(np.array([0.0, 0.0], dtype=np.float64))

            trace_times = np.concatenate(t_list)
            trace_volts = np.concatenate(v_list)

            v_min_display = min(-1.0, float(np.min(trace_volts)) - 0.5)
            v_max_display = max(5.0, float(np.max(trace_volts)) + 0.5)
            dur_us = dur_s * 1e6

            self._traces.append({
                "name": f"AO{ao_idx} (Trig{ao_idx}): {aev.name or 'Waveform'} [{dur_us:.3g} µs]",
                "type": "analog",
                "ch_idx": ao_idx,
                "color": color,
                "times": trace_times,
                "voltages": trace_volts,
                "v_min": v_min_display,
                "v_max": v_max_display,
                "start_s": st_s,
                "end_s": end_s,
            })

        # 2. Digital Channels (DIO0 to DIO20)
        dio_channels_seen = set()
        for dev in self._sequence.digital_events:
            if not dev.enabled:
                continue
            dio_channels_seen.add(dev.channel)
            color = DIO_COLORS[dev.channel % len(DIO_COLORS)]
            st_s = dev.start_ticks / clock
            end_s = dev.end_ticks / clock
            dur_us = ((dev.end_ticks - dev.start_ticks) / clock) * 1e6

            t_list = []
            v_list = []
            if st_s > 1e-9:
                t_pre = np.linspace(0.0, max(0.0, st_s - 1e-9), 300)
                t_list.append(t_pre)
                v_list.append(np.zeros_like(t_pre))

            t_pulse = np.linspace(st_s, end_s, 200)
            t_list.append(t_pulse)
            v_list.append(np.full_like(t_pulse, 5.0))

            if end_s < total_s - 1e-9:
                t_post = np.linspace(min(total_s, end_s + 1e-9), total_s, 300)
                t_list.append(t_post)
                v_list.append(np.zeros_like(t_post))

            ch_tag = f"DIO{dev.channel} (Trig{dev.channel}->AO{dev.channel})" if dev.channel < 8 else f"DIO{dev.channel}"
            self._traces.append({
                "name": f"{ch_tag}: {dev.name or dev.label or 'Pulse'} [{dur_us:.3g} µs]",
                "type": "digital",
                "ch_idx": dev.channel,
                "color": color,
                "times": np.concatenate(t_list),
                "voltages": np.concatenate(v_list),
                "v_min": -0.5,
                "v_max": 5.5,
                "start_s": st_s,
                "end_s": end_s,
            })

        # Automatically display the trigger lines for active analog channels
        for ao_idx, aev in enumerate(self._sequence.analog_events):
            if aev.enabled and 0 <= ao_idx < 8 and ao_idx not in dio_channels_seen:
                color = DIO_COLORS[ao_idx % len(DIO_COLORS)]
                st_s = getattr(aev, "start_ms", 0.0) / 1000.0
                end_s = getattr(aev, "end_ms", 42.5) / 1000.0
                dur_us = max(0.0, end_s - st_s) * 1e6

                t_list = []
                v_list = []
                if st_s > 1e-9:
                    t_pre = np.linspace(0.0, max(0.0, st_s - 1e-9), 300)
                    t_list.append(t_pre)
                    v_list.append(np.zeros_like(t_pre))

                t_pulse = np.linspace(st_s, end_s, 200)
                t_list.append(t_pulse)
                v_list.append(np.full_like(t_pulse, 5.0))

                if end_s < total_s - 1e-9:
                    t_post = np.linspace(min(total_s, end_s + 1e-9), total_s, 300)
                    t_list.append(t_post)
                    v_list.append(np.zeros_like(t_post))

                self._traces.append({
                    "name": f"DIO{ao_idx} (Trig{ao_idx}->AO{ao_idx}): Hardware Trigger [{dur_us:.3g} µs]",
                    "type": "digital",
                    "ch_idx": ao_idx,
                    "color": color,
                    "times": np.concatenate(t_list),
                    "voltages": np.concatenate(v_list),
                    "v_min": -0.5,
                    "v_max": 5.5,
                    "start_s": st_s,
                    "end_s": end_s,
                })

        self.update()

    # ── Coordinate Conversions ──────────────────────────────────────────

    def _get_total_duration_s(self) -> float:
        if self._sequence and self._sequence.sequence_duration_ticks > 0:
            return self._sequence.sequence_duration_ticks / self._sequence.clock_hz
        return 0.1

    def _time_s_to_unit(self, seconds: float) -> float:
        if self._time_unit == "µs":
            return seconds * 1e6
        elif self._time_unit == "ms":
            return seconds * 1e3
        return seconds

    def _time_s_to_x(self, seconds: float, plot_width: float) -> float:
        total_s = self._get_total_duration_s()
        if total_s <= 0:
            return self._gutter_width
        return self._gutter_width + (seconds / total_s) * plot_width * self._zoom - self._pan_offset_x

    def _x_to_time_s(self, x: float, plot_width: float) -> float:
        total_s = self._get_total_duration_s()
        eff_x = x - self._gutter_width + self._pan_offset_x
        if plot_width * self._zoom <= 0:
            return 0.0
        return max(0.0, min(total_s, (eff_x / (plot_width * self._zoom)) * total_s))

    # ── Painting ────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        plot_w = max(10.0, w - self._gutter_width)
        total_s = self._get_total_duration_s()

        # Canvas Background
        painter.fillRect(QRectF(0, 0, w, h), QColor("#12121e"))

        num_traces = len(self._traces)
        if num_traces == 0:
            painter.setFont(QFont("Segoe UI", 12))
            painter.setPen(QColor("#808098"))
            painter.drawText(
                QRectF(self._gutter_width, 0, plot_w, h),
                Qt.AlignmentFlag.AlignCenter,
                "No channels enabled for simulation.\nEnable channels in the Sequence Builder and click '▶ Simulate Sequence'.",
            )
            return

        # Stacked vs Overlay Layout
        if self._display_mode == "STACKED":
            req_height = self._ruler_height + num_traces * (self._lane_height + self._lane_spacing) + 40.0
            if self.minimumHeight() != int(req_height):
                self.setMinimumHeight(int(req_height))

            # 1. Paint Ruler
            self._paint_time_ruler(painter, plot_w, total_s, h)

            # 2. Paint Each Channel Lane
            for idx, tr in enumerate(self._traces):
                lane_y = self._ruler_height + 8.0 + idx * (self._lane_height + self._lane_spacing)
                self._paint_stacked_lane(painter, tr, lane_y, plot_w, total_s)

        else:  # OVERLAY MODE
            self.setMinimumHeight(450)
            self._paint_time_ruler(painter, plot_w, total_s, h)
            self._paint_overlay_view(painter, plot_w, total_s, h)

        # 3. Paint Left Gutter (Channel Info Badges)
        self._paint_gutter(painter, h)

        # 4. Paint Crosshair Cursor & HUD Readout
        if self._cursor_x is not None and self._hover_time_s is not None:
            self._paint_crosshair_and_hud(painter, plot_w, h)

        painter.end()

    def _paint_time_ruler(self, painter: QPainter, plot_width: float, total_s: float, h: float):
        painter.fillRect(QRectF(0, 0, self.width(), self._ruler_height), QColor("#1a1a2a"))
        painter.setPen(QPen(QColor("#2d2d42"), 1))
        painter.drawLine(0, int(self._ruler_height), int(self.width()), int(self._ruler_height))

        # Determine tick interval based on zoom and total duration
        eff_dur = total_s / self._zoom
        raw_step = eff_dur / 8.0
        exp = math.floor(math.log10(max(1e-12, raw_step)))
        frac = raw_step / (10 ** exp)
        if frac < 1.5:
            step_base = 1.0
        elif frac < 3.5:
            step_base = 2.0
        elif frac < 7.5:
            step_base = 5.0
        else:
            step_base = 10.0
        step_s = step_base * (10 ** exp)

        t = 0.0
        painter.setFont(QFont("Consolas", 8))
        while t <= total_s:
            x = self._time_s_to_x(t, plot_width)
            if self._gutter_width <= x <= self.width():
                # Grid line
                painter.setPen(QPen(QColor("#1e1e30"), 1, Qt.PenStyle.DotLine))
                painter.drawLine(int(x), int(self._ruler_height), int(x), int(h))

                # Tick on ruler
                painter.setPen(QPen(QColor("#70708c"), 1))
                painter.drawLine(int(x), int(self._ruler_height - 8), int(x), int(self._ruler_height))

                t_unit = self._time_s_to_unit(t)
                text = f"{t_unit:.4g} {self._time_unit}" if t_unit != 0 else "0"
                painter.drawText(QRectF(x - 45, 6, 90, 18), Qt.AlignmentFlag.AlignCenter, text)
            t += step_s

    def _paint_stacked_lane(
        self, painter: QPainter, tr: Dict[str, Any], lane_y: float, plot_width: float, total_s: float
    ):
        lane_rect = QRectF(self._gutter_width, lane_y, plot_width, self._lane_height)

        # Lane background
        painter.fillRect(lane_rect, QColor("#161626"))
        painter.setPen(QPen(QColor("#252538"), 1))
        painter.drawRect(lane_rect)

        # Zero volt line
        v_min = tr["v_min"]
        v_max = tr["v_max"]
        v_span = max(0.001, v_max - v_min)
        zero_frac = (0.0 - v_min) / v_span
        zero_y = lane_y + self._lane_height * (1.0 - zero_frac)

        painter.setPen(QPen(QColor("#2d2d44"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(self._gutter_width), int(zero_y), int(self.width()), int(zero_y))

        times = tr["times"]
        voltages = tr["voltages"]
        n_pts = len(times)
        if n_pts < 2:
            return

        # Determine visible time window
        t_left = self._x_to_time_s(self._gutter_width, plot_width)
        t_right = self._x_to_time_s(float(self.width()), plot_width)
        if t_left > t_right:
            t_left, t_right = t_right, t_left

        i_start = max(0, int(np.searchsorted(times, t_left)) - 1)
        i_end = min(n_pts, int(np.searchsorted(times, t_right)) + 1)
        vis_times = times[i_start:i_end]
        vis_volts = voltages[i_start:i_end]
        n_vis = len(vis_times)
        if n_vis < 2:
            return

        vis_px_w = max(10, int(self.width() - self._gutter_width))
        color = QColor(tr["color"])

        if n_vis <= vis_px_w * 2:
            # Direct continuous path (smooth curves, no decimation artifacts)
            curve_path = QPainterPath()
            fill_path = QPainterPath()
            started = False

            for t_val, v_val in zip(vis_times, vis_volts):
                x = self._time_s_to_x(t_val, plot_width)
                frac = (v_val - v_min) / v_span
                y = lane_y + self._lane_height * (1.0 - min(1.0, max(0.0, frac)))
                if not started:
                    curve_path.moveTo(x, y)
                    fill_path.moveTo(x, zero_y)
                    fill_path.lineTo(x, y)
                    started = True
                else:
                    curve_path.lineTo(x, y)
                    fill_path.lineTo(x, y)

            if started:
                last_x = self._time_s_to_x(vis_times[-1], plot_width)
                fill_path.lineTo(min(last_x, self.width()), zero_y)
                fill_path.closeSubpath()

                grad = QLinearGradient(0, lane_y, 0, lane_y + self._lane_height)
                grad.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 50))
                grad.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
                painter.fillPath(fill_path, QBrush(grad))

                painter.setPen(QPen(color, 2))
                painter.drawPath(curve_path)
        else:
            # Peak-Detect Min-Max Envelope (hardware DSO algorithm for high frequency)
            # Guarantees zero aliasing and crisp peak-to-peak bands at high frequencies!
            n_bins = vis_px_w
            chunks_v = np.array_split(vis_volts, n_bins)
            chunks_t = np.array_split(vis_times, n_bins)

            top_path = QPainterPath()
            bot_path = QPainterPath()
            started = False

            for b_idx in range(n_bins):
                cv = chunks_v[b_idx]
                if len(cv) == 0:
                    continue
                ct = chunks_t[b_idx]
                t_mid = ct[len(ct) // 2]
                x = self._time_s_to_x(t_mid, plot_width)

                c_min = float(cv.min())
                c_max = float(cv.max())

                y_top = lane_y + self._lane_height * (1.0 - min(1.0, max(0.0, (c_max - v_min) / v_span)))
                y_bot = lane_y + self._lane_height * (1.0 - min(1.0, max(0.0, (c_min - v_min) / v_span)))

                # Draw crisp vertical column stroke for each pixel
                painter.setPen(QPen(color, 1.2))
                painter.drawLine(int(x), int(y_top), int(x), int(y_bot))

                if not started:
                    top_path.moveTo(x, y_top)
                    bot_path.moveTo(x, y_bot)
                    started = True
                else:
                    top_path.lineTo(x, y_top)
                    bot_path.lineTo(x, y_bot)

            if started:
                painter.setPen(QPen(color, 1.8))
                painter.drawPath(top_path)
                painter.drawPath(bot_path)

        # Voltage scale labels
        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QColor("#707090"))
        painter.drawText(QRectF(self._gutter_width + 4, lane_y + 2, 60, 12), Qt.AlignmentFlag.AlignLeft, f"{v_max:+.1f}V")
        painter.drawText(QRectF(self._gutter_width + 4, lane_y + self._lane_height - 14, 60, 12), Qt.AlignmentFlag.AlignLeft, f"{v_min:+.1f}V")

    def _paint_overlay_view(self, painter: QPainter, plot_width: float, total_s: float, h: float):
        main_h = h - self._ruler_height - 20.0
        main_rect = QRectF(self._gutter_width, self._ruler_height, plot_width, main_h)

        painter.fillRect(main_rect, QColor("#161626"))
        painter.setPen(QPen(QColor("#252538"), 1))
        painter.drawRect(main_rect)

        # Plot all traces overlaid
        v_min, v_max = -10.0, 10.0
        v_span = 20.0
        zero_y = self._ruler_height + main_h * 0.5

        painter.setPen(QPen(QColor("#3a3a55"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(self._gutter_width), int(zero_y), int(self.width()), int(zero_y))

        for tr in self._traces:
            times = tr["times"]
            voltages = tr["voltages"]
            n_pts = len(times)
            if n_pts < 2:
                continue

            t_left = self._x_to_time_s(self._gutter_width, plot_width)
            t_right = self._x_to_time_s(float(self.width()), plot_width)
            if t_left > t_right:
                t_left, t_right = t_right, t_left

            i_start = max(0, int(np.searchsorted(times, t_left)) - 1)
            i_end = min(n_pts, int(np.searchsorted(times, t_right)) + 1)
            vis_times = times[i_start:i_end]
            vis_volts = voltages[i_start:i_end]
            n_vis = len(vis_times)
            if n_vis < 2:
                continue

            vis_px_w = max(10, int(self.width() - self._gutter_width))
            color = QColor(tr["color"])

            if n_vis <= vis_px_w * 2:
                path = QPainterPath()
                started = False
                for t_val, v_val in zip(vis_times, vis_volts):
                    x = self._time_s_to_x(t_val, plot_width)
                    frac = (v_val - v_min) / v_span
                    y = self._ruler_height + main_h * (1.0 - min(1.0, max(0.0, frac)))
                    if not started:
                        path.moveTo(x, y)
                        started = True
                    else:
                        path.lineTo(x, y)
                painter.setPen(QPen(color, 2))
                painter.drawPath(path)
            else:
                n_bins = vis_px_w
                chunks_v = np.array_split(vis_volts, n_bins)
                chunks_t = np.array_split(vis_times, n_bins)
                top_path = QPainterPath()
                bot_path = QPainterPath()
                started = False

                for b_idx in range(n_bins):
                    cv = chunks_v[b_idx]
                    if len(cv) == 0:
                        continue
                    ct = chunks_t[b_idx]
                    t_mid = ct[len(ct) // 2]
                    x = self._time_s_to_x(t_mid, plot_width)

                    c_min = float(cv.min())
                    c_max = float(cv.max())

                    y_top = self._ruler_height + main_h * (1.0 - min(1.0, max(0.0, (c_max - v_min) / v_span)))
                    y_bot = self._ruler_height + main_h * (1.0 - min(1.0, max(0.0, (c_min - v_min) / v_span)))

                    painter.setPen(QPen(color, 1.2))
                    painter.drawLine(int(x), int(y_top), int(x), int(y_bot))

                    if not started:
                        top_path.moveTo(x, y_top)
                        bot_path.moveTo(x, y_bot)
                        started = True
                    else:
                        top_path.lineTo(x, y_top)
                        bot_path.lineTo(x, y_bot)

                if started:
                    painter.setPen(QPen(color, 1.8))
                    painter.drawPath(top_path)
                    painter.drawPath(bot_path)

    def _paint_gutter(self, painter: QPainter, h: float):
        painter.fillRect(QRectF(0, 0, self._gutter_width, h), QColor("#181826"))
        painter.setPen(QPen(QColor("#2d2d42"), 1))
        painter.drawLine(int(self._gutter_width), 0, int(self._gutter_width), int(h))

        if self._display_mode == "STACKED":
            for idx, tr in enumerate(self._traces):
                lane_y = self._ruler_height + 8.0 + idx * (self._lane_height + self._lane_spacing)

                # Channel Color Pill
                color = QColor(tr["color"])
                pill_rect = QRectF(8, lane_y + 4, 12, self._lane_height - 8)
                painter.fillRect(pill_rect, color)

                # Channel Name & Type
                painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(
                    QRectF(26, lane_y + 4, self._gutter_width - 32, 18),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    tr["name"],
                )

                # Subtitle (Timing Window)
                painter.setFont(QFont("Consolas", 8))
                painter.setPen(QColor("#8888a8"))
                st_u = self._time_s_to_unit(tr["start_s"])
                end_u = self._time_s_to_unit(tr["end_s"])
                painter.drawText(
                    QRectF(26, lane_y + 24, self._gutter_width - 32, 16),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    f"[{st_u:.2f} → {end_u:.2f} {self._time_unit}]",
                )
        else:
            # Overlay mode legend
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.setPen(QColor("#00d4ff"))
            painter.drawText(QRectF(10, 8, self._gutter_width - 20, 20), Qt.AlignmentFlag.AlignLeft, "Channels Legend")

            y_pos = self._ruler_height + 10
            for tr in self._traces:
                painter.fillRect(QRectF(10, y_pos + 2, 10, 10), QColor(tr["color"]))
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(QRectF(26, y_pos, self._gutter_width - 32, 16), Qt.AlignmentFlag.AlignLeft, tr["name"])
                y_pos += 20

    def _paint_crosshair_and_hud(self, painter: QPainter, plot_width: float, h: float):
        x = self._cursor_x
        if x is None or x < self._gutter_width or x > self.width():
            return

        t_s = self._hover_time_s
        if t_s is None:
            return

        # 1. Vertical Cursor Line
        painter.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(int(x), int(self._ruler_height), int(x), int(h))

        # 2. Time Tag on Ruler
        t_unit = self._time_s_to_unit(t_s)
        time_tag = f"{t_unit:.3f} {self._time_unit}"
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        tag_rect = QRectF(x - 40, self._ruler_height - 18, 80, 16)
        painter.fillRect(tag_rect, QColor("#00d4ff"))
        painter.setPen(QColor("#000000"))
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, time_tag)

        # 3. Readout HUD for all channels at this exact time
        hud_items = []
        clock = self._sequence.clock_hz if self._sequence else FPGA_CLOCK_HZ
        ticks = int(round(t_s * clock))

        hud_items.append(f"⏱ t = {t_unit:.3f} {self._time_unit} ({ticks:,} ticks)")
        for tr in self._traces:
            # Interpolate voltage at t_s
            times = tr["times"]
            volts = tr["voltages"]
            idx = np.searchsorted(times, t_s)
            idx = min(len(volts) - 1, max(0, idx))
            v = volts[idx]
            ch_badge = tr["name"].split(":")[0]
            if tr["type"] == "digital":
                state = "HIGH (5V)" if v > 2.5 else "LOW (0V)"
                hud_items.append(f"{ch_badge}: {state}")
            else:
                hud_items.append(f"{ch_badge}: {v:+.2f}V")

        hud_text = "  |  ".join(hud_items)

        # Draw HUD bar across top
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        hud_w = min(float(self.width()) - self._gutter_width - 20, max(380.0, float(len(hud_text) * 7 + 20)))
        hud_rect = QRectF(self._gutter_width + 10, 8, hud_w, 20)
        painter.fillRect(hud_rect, QColor(0, 0, 0, 220))
        painter.setPen(QPen(QColor("#00ff88"), 1))
        painter.drawRect(hud_rect)
        painter.drawText(hud_rect, Qt.AlignmentFlag.AlignCenter, hud_text)

    # ── Mouse Interaction ───────────────────────────────────────────────

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        plot_w = max(10.0, float(self.width()) - self._gutter_width)
        self._cursor_x = pos.x()
        self._hover_time_s = self._x_to_time_s(pos.x(), plot_w)
        self.update()

    def leaveEvent(self, event):
        self._cursor_x = None
        self._hover_time_s = None
        self.update()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = 1.25 if delta > 0 else 0.8
        self.set_zoom(self._zoom * factor)


# ────────────────────────────────────────────────────────────────────────
#  Main Simulation Viewer Panel (Tab 2)
# ────────────────────────────────────────────────────────────────────────

class SimulationViewerWidget(QWidget):
    """Complete sequence simulation viewer with oscilloscope graphs and controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sequence: Optional[ExperimentSequence] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Top Control Toolbar
        tb = QHBoxLayout()
        tb.setSpacing(8)

        btn_sim = QPushButton("▶ Run Simulation")
        btn_sim.setStyleSheet(
            "background-color: #00aa66; color: #ffffff; font-weight: bold; font-size: 12px; padding: 6px 16px; border-radius: 4px;"
        )
        btn_sim.clicked.connect(self.run_simulation)
        tb.addWidget(btn_sim)

        tb.addSpacing(16)
        tb.addWidget(QLabel("Display Mode:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Multi-Channel Stacked Lanes", "Single Overlay Grid"])
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        tb.addWidget(self._mode_combo)

        tb.addSpacing(12)
        tb.addWidget(QLabel("Time Unit:"))
        self._unit_combo = QComboBox()
        self._unit_combo.addItems(["ms (Milliseconds)", "µs (Microseconds)", "s (Seconds)"])
        self._unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        tb.addWidget(self._unit_combo)

        tb.addSpacing(16)
        btn_zoom_in = QPushButton("Zoom In (+)")
        btn_zoom_in.clicked.connect(lambda: self._canvas.set_zoom(self._canvas._zoom * 1.3))
        tb.addWidget(btn_zoom_in)

        btn_zoom_out = QPushButton("Zoom Out (−)")
        btn_zoom_out.clicked.connect(lambda: self._canvas.set_zoom(self._canvas._zoom * 0.75))
        tb.addWidget(btn_zoom_out)

        btn_fit = QPushButton("Fit Sequence")
        btn_fit.clicked.connect(lambda: self._canvas.fit_sequence())
        tb.addWidget(btn_fit)

        tb.addStretch()
        self._stats_lbl = QLabel("Ready to simulate")
        self._stats_lbl.setStyleSheet("color: #00d4ff; font-weight: bold;")
        tb.addWidget(self._stats_lbl)

        layout.addLayout(tb)

        # Scrollable Canvas
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._canvas = SimulationCanvas()
        scroll.setWidget(self._canvas)
        layout.addWidget(scroll, 1)

    def set_sequence(self, sequence: ExperimentSequence):
        self._sequence = sequence
        self._canvas.set_sequence(sequence)
        self._update_stats()

    def run_simulation(self):
        """Simulate and synthesize all channel waveforms."""
        self._canvas.recompute_simulation()
        self._update_stats()

    def _on_mode_changed(self, idx: int):
        mode = "STACKED" if idx == 0 else "OVERLAY"
        self._canvas.set_display_mode(mode)

    def _on_unit_changed(self, idx: int):
        units = ["ms", "µs", "s"]
        self._canvas.set_time_unit(units[idx])

    def _update_stats(self):
        if not self._sequence:
            return
        total_s = self._sequence.sequence_duration_ticks / self._sequence.clock_hz
        n_ao = sum(1 for a in self._sequence.analog_events if a.enabled)
        n_dio = sum(1 for d in self._sequence.digital_events if d.enabled)
        self._stats_lbl.setText(
            f"Duration: {total_s*1000:.2f} ms ({self._sequence.sequence_duration_ticks:,} ticks) | Active: {n_ao} AO, {n_dio} DIO"
        )
