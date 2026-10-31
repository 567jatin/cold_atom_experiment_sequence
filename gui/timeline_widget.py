"""
Interactive Drag-and-Drop Graphical Timeline Widget.

Provides full visual drag-and-drop sequence editing down to 25 ns (1 FPGA clock tick):
- Full support for Microseconds (µs), Nanoseconds / Clock Ticks (25 ns), Milliseconds (ms), and Seconds (s)
- Click and drag on any DIO lane to draw/create new pulses of any duration (from 25 ns upwards)
- Drag pulse body horizontally to reposition in time (or vertically between channels)
- Drag pulse left/right borders to resize pulse duration
- Double-click or right-click to open pulse inspector dialog with multi-unit support (µs/ms/s/ticks)
- Precision snap-to-grid alignment (25 ns tick, 0.1 µs, 1 µs, 5 µs, 10 µs, 50 µs, 100 µs, 1 ms, 5 ms)
- Live visual HUD during dragging showing exact start/end/duration in µs or ms with tick counts
- Delete with Delete/Backspace key
- Integrated toolbar with unit selector, microsecond quick presets, zoom, fit, and snap tools
"""

from __future__ import annotations

import sys
import os
import math
from typing import Optional, List, Dict, Any, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QDialog, QFormLayout, QLineEdit, QDoubleSpinBox,
    QCheckBox, QDialogButtonBox, QMenu, QToolTip, QSpinBox,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Signal, Qt, QRectF, QPointF, QPoint
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QMouseEvent,
    QWheelEvent, QPaintEvent, QKeyEvent, QAction, QCursor,
)

from sequence_model import (
    ExperimentSequence, DigitalEvent, AnalogEvent,
    TimeUnit, FPGA_CLOCK_HZ,
)
from .styles import COLORS


DIO_COLORS = [
    "#00d4ff", "#00ff88", "#ffaa00", "#ff4444", "#aa66ff",
    "#4488ff", "#ff88dd", "#88ffcc", "#ffcc00", "#44ddff",
    "#66ffaa", "#ff6666", "#cc88ff", "#55aaff", "#ffaacc",
    "#aaffdd", "#ffdd44", "#33bbff", "#88ff88", "#ff9955",
    "#e040fb",  # DIO20
]
NUM_DIO_CHANNELS = 21
AO_COLOR = "#ffaa00"


# ────────────────────────────────────────────────────────────────────────
#  Pulse Edit Inspector Dialog (Multi-Unit Aware: µs, ms, s, ticks)
# ────────────────────────────────────────────────────────────────────────

class PulseEditDialog(QDialog):
    """Modal dialog to inspect and edit a digital pulse in µs, ms, s, or ticks."""

    def __init__(self, event: DigitalEvent, sequence: ExperimentSequence, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Digital Pulse")
        self.setMinimumWidth(380)
        self._pulse_ev = event
        self.sequence = sequence
        self.clock = sequence.clock_hz or FPGA_CLOCK_HZ
        self.deleted = False

        # Current working unit: "us", "ms", "s", "ticks"
        dur_s = (event.end_ticks - event.start_ticks) / self.clock
        self._current_unit = "us" if dur_s < 0.001 else "ms"

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        # Name / Label
        self._name_edit = QLineEdit(self._pulse_ev.name or self._pulse_ev.label or "Pulse")
        form.addRow("Label / Name:", self._name_edit)

        # Channel
        self._chan_combo = QComboBox()
        num_ch = 21
        if self.sequence:
            max_ch = 20
            if self.sequence.digital_events:
                max_ch = max(max_ch, max(e.channel for e in self.sequence.digital_events))
            if self.sequence.channel_labels:
                for k in self.sequence.channel_labels.keys():
                    try:
                        max_ch = max(max_ch, int(k))
                    except Exception:
                        pass
            num_ch = max_ch + 1

        for i in range(num_ch):
            lbl = self.sequence.channel_labels.get(i, f"DIO{i}")
            self._chan_combo.addItem(f"Channel {i} ({lbl})", i)
        self._chan_combo.setCurrentIndex(max(0, min(num_ch - 1, self._pulse_ev.channel)))
        form.addRow("Channel:", self._chan_combo)

        # Unit Selector
        self._unit_combo = QComboBox()
        self._unit_combo.addItem("µs (Microseconds)", "us")
        self._unit_combo.addItem("ms (Milliseconds)", "ms")
        self._unit_combo.addItem("s (Seconds)", "s")
        self._unit_combo.addItem("ticks (25 ns FPGA Cycles)", "ticks")
        idx = {"us": 0, "ms": 1, "s": 2, "ticks": 3}.get(self._current_unit, 0)
        self._unit_combo.setCurrentIndex(idx)
        self._unit_combo.currentIndexChanged.connect(self._on_unit_switched)
        form.addRow("Time Unit:", self._unit_combo)

        # Spinboxes for Start, Duration, End
        self._start_spin = QDoubleSpinBox()
        self._start_spin.setRange(0.0, 1e9)
        self._start_spin.valueChanged.connect(self._on_start_changed)
        form.addRow("Start Time:", self._start_spin)

        self._dur_spin = QDoubleSpinBox()
        self._dur_spin.setRange(0.0, 1e9)
        self._dur_spin.valueChanged.connect(self._on_dur_changed)
        form.addRow("Duration:", self._dur_spin)

        self._end_spin = QDoubleSpinBox()
        self._end_spin.setRange(0.0, 1e9)
        self._end_spin.valueChanged.connect(self._on_end_changed)
        form.addRow("End Time:", self._end_spin)

        # Hardware Tick Info Label
        self._ticks_lbl = QLabel()
        self._ticks_lbl.setStyleSheet("color: #00d4ff; font-family: Consolas; font-size: 11px;")
        form.addRow("Hardware Ticks:", self._ticks_lbl)

        # Enabled
        self._enable_chk = QCheckBox("Enabled")
        self._enable_chk.setChecked(self._pulse_ev.enabled)
        form.addRow("", self._enable_chk)

        layout.addLayout(form)

        # Buttons
        btn_box = QHBoxLayout()
        del_btn = QPushButton("🗑 Delete Pulse")
        del_btn.setStyleSheet("color: #ff4444; border-color: #ff4444;")
        del_btn.clicked.connect(self._on_delete)
        btn_box.addWidget(del_btn)

        btn_box.addStretch()

        ok_btn = QPushButton("Save")
        ok_btn.setStyleSheet("background-color: #00aa55; color: #ffffff; font-weight: bold;")
        ok_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        btn_box.addWidget(cancel_btn)
        btn_box.addWidget(ok_btn)
        layout.addLayout(btn_box)

        self._update_spin_units_and_values()

    def _update_spin_units_and_values(self):
        """Update spinboxes according to the selected unit."""
        u = self._unit_combo.currentData()
        self._current_unit = u

        st_s = self._pulse_ev.start_ticks / self.clock
        dur_s = max(1.0 / self.clock, (self._pulse_ev.end_ticks - self._pulse_ev.start_ticks) / self.clock)
        end_s = st_s + dur_s

        if u == "us":
            mult = 1e6
            suf = " µs"
            dec = 3  # 0.025 µs step = 1 tick at 40MHz
            step = 1.0  # 1 µs step
        elif u == "ms":
            mult = 1e3
            suf = " ms"
            dec = 6
            step = 0.1
        elif u == "s":
            mult = 1.0
            suf = " s"
            dec = 8
            step = 0.001
        else:  # ticks
            mult = self.clock
            suf = " ticks"
            dec = 0
            step = 1.0

        for sp in (self._start_spin, self._dur_spin, self._end_spin):
            sp.blockSignals(True)
            sp.setDecimals(dec)
            sp.setSuffix(suf)
            sp.setSingleStep(step)

        self._start_spin.setValue(st_s * mult)
        self._dur_spin.setValue(dur_s * mult)
        self._end_spin.setValue(end_s * mult)

        for sp in (self._start_spin, self._dur_spin, self._end_spin):
            sp.blockSignals(False)

        self._update_ticks_label()

    def _on_unit_switched(self):
        self._update_spin_units_and_values()

    def _get_multiplier(self) -> float:
        u = self._current_unit
        if u == "us":
            return 1e-6
        elif u == "ms":
            return 1e-3
        elif u == "s":
            return 1.0
        else:
            return 1.0 / self.clock

    def _update_ticks_label(self):
        mult = self._get_multiplier()
        st_ticks = int(round((self._start_spin.value() * mult) * self.clock))
        dur_ticks = max(1, int(round((self._dur_spin.value() * mult) * self.clock)))
        end_ticks = st_ticks + dur_ticks
        ns_dur = (dur_ticks / self.clock) * 1e9
        self._ticks_lbl.setText(
            f"{st_ticks:,} → {end_ticks:,} ticks ({dur_ticks:,} ticks = {ns_dur:,.1f} ns)"
        )

    def _on_start_changed(self, val):
        self._end_spin.blockSignals(True)
        self._end_spin.setValue(val + self._dur_spin.value())
        self._end_spin.blockSignals(False)
        self._update_ticks_label()

    def _on_dur_changed(self, val):
        self._end_spin.blockSignals(True)
        self._end_spin.setValue(self._start_spin.value() + val)
        self._end_spin.blockSignals(False)
        self._update_ticks_label()

    def _on_end_changed(self, val):
        st = self._start_spin.value()
        if val > st:
            self._dur_spin.blockSignals(True)
            self._dur_spin.setValue(val - st)
            self._dur_spin.blockSignals(False)
        self._update_ticks_label()

    def _on_save(self):
        mult = self._get_multiplier()
        st_s = self._start_spin.value() * mult
        dur_s = max(1.0 / self.clock, self._dur_spin.value() * mult)

        self._pulse_ev.name = self._name_edit.text()
        self._pulse_ev.label = self._name_edit.text()
        self._pulse_ev.channel = self._chan_combo.currentData()
        self._pulse_ev.start_ticks = int(round(st_s * self.clock))
        self._pulse_ev.end_ticks = self._pulse_ev.start_ticks + int(round(dur_s * self.clock))
        self._pulse_ev.enabled = self._enable_chk.isChecked()
        self.accept()

    def _on_delete(self):
        self.deleted = True
        self.accept()


# ────────────────────────────────────────────────────────────────────────
#  Interactive Canvas Widget (Precision Drag-and-Drop)
# ────────────────────────────────────────────────────────────────────────

class TimelineCanvas(QWidget):
    """Custom-painted timeline canvas with precision microsecond drag-and-drop."""

    sequence_modified = Signal()
    event_selected = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(560)

        self._sequence: Optional[ExperimentSequence] = None
        self._time_unit: TimeUnit = TimeUnit.MILLISECONDS
        self._zoom: float = 1.0
        self._pan_offset_x: float = 0.0

        # Snap setting in seconds (default 10 µs)
        self.snap_step_s: float = 0.000010

        # Layout dimensions
        self._label_width = 120.0
        self._ruler_height = 36.0
        self._lane_height = 24.0
        self._lane_spacing = 3.0
        self._edge_grab_threshold = 8.0

        # Interaction state machine
        self._mode = "IDLE"
        self._active_event: Optional[DigitalEvent] = None
        self._selected_event: Optional[DigitalEvent] = None
        self._drag_start_pos = QPointF()
        self._drag_start_time_s = 0.0
        self._drag_event_orig_start = 0
        self._drag_event_orig_end = 0
        self._drag_event_orig_chan = 0
        self._drag_pan_orig_offset = 0.0

        # Hover tracking
        self._hover_channel: Optional[int] = None
        self._hover_event: Optional[DigitalEvent] = None
        self._hover_mode: str = "IDLE"
        self.num_dio_channels: int = 21

    # ── Public Configuration ────────────────────────────────────────────

    def set_sequence(self, sequence: ExperimentSequence):
        self._sequence = sequence
        if sequence:
            max_ch = 20
            if sequence.digital_events:
                max_ch = max(max_ch, max(e.channel for e in sequence.digital_events))
            if sequence.channel_labels:
                for k in sequence.channel_labels.keys():
                    try:
                        max_ch = max(max_ch, int(k))
                    except Exception:
                        pass
            self.num_dio_channels = max_ch + 1
        self.update()

    def set_time_unit(self, unit: TimeUnit):
        self._time_unit = unit
        self.update()

    def set_zoom(self, factor: float):
        self._zoom = max(0.01, min(factor, 500.0))
        self.update()

    def fit_sequence(self):
        self._zoom = 1.0
        self._pan_offset_x = 0.0
        self.update()

    def delete_selected_event(self):
        if self._selected_event and self._sequence:
            if self._selected_event in self._sequence.digital_events:
                self._sequence.digital_events.remove(self._selected_event)
                self._selected_event = None
                self.sequence_modified.emit()
                self.update()

    # ── Coordinate Conversions & Snapping ───────────────────────────────

    def _get_total_duration_s(self) -> float:
        if self._sequence and self._sequence.sequence_duration_ticks > 0:
            return self._sequence.sequence_duration_ticks / self._sequence.clock_hz
        return 0.1

    def _snap_time_s(self, t_s: float) -> float:
        clock = self._sequence.clock_hz if self._sequence else FPGA_CLOCK_HZ
        min_tick_s = 1.0 / clock  # 25 ns
        if self.snap_step_s <= min_tick_s:
            return max(0.0, round(t_s / min_tick_s) * min_tick_s)
        return max(0.0, round(t_s / self.snap_step_s) * self.snap_step_s)

    def _time_s_to_unit(self, seconds: float) -> float:
        if self._time_unit == TimeUnit.MICROSECONDS:
            return seconds * 1e6
        elif self._time_unit == TimeUnit.MILLISECONDS:
            return seconds * 1e3
        elif self._time_unit == TimeUnit.SECONDS:
            return seconds
        else:
            clock = self._sequence.clock_hz if self._sequence else FPGA_CLOCK_HZ
            return seconds * clock

    def _time_s_to_x(self, seconds: float, timeline_width: float) -> float:
        total_s = self._get_total_duration_s()
        if total_s <= 0:
            return self._label_width
        return self._label_width + (seconds / total_s) * timeline_width * self._zoom - self._pan_offset_x

    def _x_to_time_s(self, x: float, timeline_width: float) -> float:
        total_s = self._get_total_duration_s()
        eff_x = x - self._label_width + self._pan_offset_x
        if timeline_width * self._zoom <= 0:
            return 0.0
        return max(0.0, (eff_x / (timeline_width * self._zoom)) * total_s)

    def _get_lane_rect(self, lane_idx: int) -> QRectF:
        y = self._ruler_height + 5.0 + lane_idx * (self._lane_height + self._lane_spacing)
        w = max(10.0, float(self.width()) - self._label_width)
        return QRectF(self._label_width, y, w, self._lane_height)

    def _y_to_lane_idx(self, y: float) -> int:
        top = self._ruler_height + 5.0
        if y < top:
            return -1
        return int((y - top) // (self._lane_height + self._lane_spacing))

    # ── Painting ────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        timeline_width = max(10.0, w - self._label_width)
        total_s = self._get_total_duration_s()
        clock = self._sequence.clock_hz if self._sequence else FPGA_CLOCK_HZ

        # Background
        painter.fillRect(QRectF(0, 0, w, h), QColor(COLORS["bg_dark"]))

        num_dio = self.num_dio_channels
        num_ao = len(self._sequence.analog_events) if self._sequence else 1
        num_lanes = num_dio + num_ao

        req_height = self._ruler_height + num_lanes * (self._lane_height + self._lane_spacing) + 30.0
        if self.minimumHeight() != int(req_height):
            self.setMinimumHeight(int(req_height))

        # 1. Ruler & Grid
        self._paint_ruler_and_grid(painter, timeline_width, total_s, h)

        # 2. DIO Channels
        dio_events_by_chan: Dict[int, List[DigitalEvent]] = {}
        if self._sequence:
            for dev in self._sequence.digital_events:
                if 0 <= dev.channel < self.num_dio_channels:
                    dio_events_by_chan.setdefault(dev.channel, []).append(dev)

        for ch in range(num_dio):
            lane_rect = self._get_lane_rect(ch)
            bg_color = QColor(COLORS["bg_panel"])
            if self._hover_channel == ch and self._mode == "CREATING":
                bg_color = QColor("#303046")
            painter.fillRect(lane_rect, bg_color)
            painter.setPen(QPen(QColor(COLORS["border"]), 1))
            painter.drawRect(lane_rect)

            color = DIO_COLORS[ch % len(DIO_COLORS)]
            for ev in dio_events_by_chan.get(ch, []):
                self._paint_pulse_rect(painter, ev, lane_rect.top(), timeline_width, clock, color)

        # 3. Analog Channels
        for ao_idx in range(num_ao):
            lane_idx = num_dio + ao_idx
            lane_rect = self._get_lane_rect(lane_idx)
            painter.fillRect(lane_rect, QColor(COLORS["bg_panel"]))
            painter.setPen(QPen(QColor(COLORS["border"]), 1))
            painter.drawRect(lane_rect)

            if self._sequence and ao_idx < len(self._sequence.analog_events):
                aev = self._sequence.analog_events[ao_idx]
                self._paint_analog_block(painter, aev, lane_rect.top(), timeline_width, ao_idx=ao_idx)

        # 4. Left Gutter
        self._paint_left_gutter(painter, num_dio, num_ao, h)

        # 5. Live HUD
        if self._mode in ("CREATING", "MOVING", "RESIZE_START", "RESIZE_END") and self._active_event:
            self._paint_interaction_hud(painter, clock)

        painter.end()

    def _paint_ruler_and_grid(self, painter: QPainter, timeline_width: float, total_s: float, h: float):
        painter.fillRect(QRectF(0, 0, self.width(), self._ruler_height), QColor("#1c1c28"))
        painter.setPen(QPen(QColor(COLORS["border"]), 1))
        painter.drawLine(0, int(self._ruler_height), self.width(), int(self._ruler_height))

        visible_time_s = total_s / self._zoom
        if visible_time_s <= 0:
            return

        order = math.floor(math.log10(max(1e-12, visible_time_s)))
        nice_steps = [1, 2, 5, 10]
        step_s = 1.0 * (10 ** order)
        for s in nice_steps:
            cand = s * (10 ** (order - 1))
            if cand > 0 and 5 <= (visible_time_s / cand) <= 18:
                step_s = cand
                break

        unit_str = self._time_unit.value
        painter.setFont(QFont("Consolas", 8))

        t = 0.0
        while t <= total_s:
            x = self._time_s_to_x(t, timeline_width)
            if self._label_width <= x <= self.width():
                painter.setPen(QPen(QColor(COLORS["border"]), 1, Qt.PenStyle.DotLine))
                painter.drawLine(int(x), int(self._ruler_height), int(x), int(h))

                painter.setPen(QPen(QColor(COLORS["text_dim"]), 1))
                painter.drawLine(int(x), int(self._ruler_height - 8), int(x), int(self._ruler_height))

                t_unit = self._time_s_to_unit(t)
                text = f"{t_unit:.3g} {unit_str}" if t_unit != 0 else "0"
                painter.drawText(QRectF(x - 45, 6, 90, 18), Qt.AlignmentFlag.AlignCenter, text)
            t += step_s

    def _paint_pulse_rect(
        self, painter: QPainter, ev: DigitalEvent, lane_y: float,
        timeline_width: float, clock: int, color_hex: str
    ):
        start_s = ev.start_ticks / clock
        end_s = ev.end_ticks / clock
        x_start = self._time_s_to_x(start_s, timeline_width)
        x_end = self._time_s_to_x(end_s, timeline_width)
        # Always at least 4px visible width on display
        rect_w = max(4.0, x_end - x_start)

        rect = QRectF(x_start, lane_y + 2, rect_w, self._lane_height - 4)

        base_color = QColor(color_hex)
        if not ev.enabled:
            base_color = QColor("#555566")
        painter.fillRect(rect, base_color)

        border_pen = QPen(QColor("#ffffff"), 1)
        if ev == self._selected_event:
            border_pen = QPen(QColor("#ffffff"), 2)
        elif ev == self._hover_event:
            border_pen = QPen(QColor("#00d4ff"), 2)
        painter.setPen(border_pen)
        painter.drawRect(rect)

        # Draw handles
        if ev == self._selected_event or ev == self._hover_event:
            painter.fillRect(QRectF(rect.left(), rect.top(), 3, rect.height()), QColor("#ffffff"))
            painter.fillRect(QRectF(rect.right() - 3, rect.top(), 3, rect.height()), QColor("#ffffff"))

        if rect_w > 32:
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.setPen(QColor("#000000"))
            painter.drawText(
                rect.adjusted(4, 0, -4, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                ev.name or ev.label or "Pulse",
            )

    def _paint_analog_block(self, painter: QPainter, aev: AnalogEvent, lane_y: float, timeline_width: float, ao_idx: int = 0):
        start_s = getattr(aev, "start_ms", 0.0) / 1000.0
        dur_s = max(0.000025, getattr(aev, "duration_ms", 10.0) / 1000.0)
        end_s = getattr(aev, "end_ms", (start_s * 1000.0 + dur_s * 1000.0)) / 1000.0
        is_enabled = getattr(aev, "enabled", False)

        x_start = self._time_s_to_x(start_s, timeline_width)
        x_end = self._time_s_to_x(end_s, timeline_width)
        rect_w = max(6.0, x_end - x_start)

        rect = QRectF(x_start, lane_y + 2, rect_w, self._lane_height - 4)
        ao_palette = ["#00e5ff", "#ffab00", "#ff5252", "#e040fb", "#00e676", "#2979ff", "#ff4081", "#ffd600"]
        color_hex = ao_palette[ao_idx % len(ao_palette)] if is_enabled else "#252533"

        painter.fillRect(rect, QColor(color_hex))
        pen = QPen(QColor("#ffffff") if is_enabled else QColor("#444455"), 1)
        if not is_enabled:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(rect)

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#000000") if is_enabled else QColor("#777788"))
        wtype = getattr(aev, "waveform_type", "Ramp")
        if hasattr(wtype, "value"):
            wtype = wtype.value
        if is_enabled:
            text = f"∿ {aev.name or wtype} [{aev.start_voltage:.1f}V→{aev.end_voltage:.1f}V]"
        else:
            text = f"∿ {aev.name or wtype} (Disabled)"
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_left_gutter(self, painter: QPainter, num_dio: int, num_ao: int, h: float):
        painter.fillRect(QRectF(0, 0, self._label_width, h), QColor(COLORS["bg_panel"]))
        painter.setPen(QPen(QColor(COLORS["border"]), 1))
        painter.drawLine(int(self._label_width), 0, int(self._label_width), int(h))

        painter.setFont(QFont("Segoe UI", 9))
        for ch in range(num_dio):
            lane_rect = self._get_lane_rect(ch)
            lbl = f"DIO{ch}"
            if self._sequence and ch in self._sequence.channel_labels:
                lbl = self._sequence.channel_labels[ch]
            painter.setPen(QColor(COLORS["text"]))
            painter.drawText(
                QRectF(8, lane_rect.top(), self._label_width - 16, self._lane_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                lbl,
            )

        for ao_idx in range(num_ao):
            lane_rect = self._get_lane_rect(num_dio + ao_idx)
            lbl = f"AO{ao_idx}"
            if self._sequence and ao_idx < len(self._sequence.analog_events):
                lbl = self._sequence.analog_events[ao_idx].name or f"AO{ao_idx}"
            painter.setPen(QColor(COLORS["accent_yellow"]))
            painter.drawText(
                QRectF(8, lane_rect.top(), self._label_width - 16, self._lane_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                lbl,
            )

    def _paint_interaction_hud(self, painter: QPainter, clock: int):
        ev = self._active_event
        if not ev:
            return

        st_s = ev.start_ticks / clock
        dur_s = max(1.0 / clock, (ev.end_ticks - ev.start_ticks) / clock)
        end_s = st_s + dur_s
        ticks = int(round(dur_s * clock))

        if dur_s < 0.001:  # Microsecond display
            hud_text = (
                f"DIO{ev.channel}: Start {st_s*1e6:.2f} µs | End {end_s*1e6:.2f} µs | "
                f"Width {dur_s*1e6:.2f} µs ({ticks:,} ticks @ 25ns)"
            )
        else:  # Millisecond display
            hud_text = (
                f"DIO{ev.channel}: Start {st_s*1000:.3f} ms | End {end_s*1000:.3f} ms | "
                f"Width {dur_s*1000:.3f} ms ({ticks:,} ticks)"
            )

        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        hud_rect = QRectF(self._label_width + 10, 6, 520, 24)
        painter.fillRect(hud_rect, QColor(0, 0, 0, 230))
        painter.setPen(QPen(QColor("#00d4ff"), 1))
        painter.drawRect(hud_rect)
        painter.drawText(hud_rect, Qt.AlignmentFlag.AlignCenter, hud_text)

    # ── Interactive Mouse Handlers ──────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if not self._sequence:
            return

        pos = event.position()
        timeline_width = max(10.0, float(self.width()) - self._label_width)
        clock = self._sequence.clock_hz

        if pos.y() < self._ruler_height or event.button() == Qt.MouseButton.MiddleButton:
            self._mode = "PANNING"
            self._drag_start_pos = pos
            self._drag_pan_orig_offset = self._pan_offset_x
            return

        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            lane_idx = self._y_to_lane_idx(pos.y())
            t_s = self._x_to_time_s(pos.x(), timeline_width)
            snapped_s = self._snap_time_s(t_s)

            hit_ev, hit_mode = self._hit_test_pulse(pos.x(), lane_idx, timeline_width, clock)

            if hit_ev is not None:
                self._active_event = hit_ev
                self._selected_event = hit_ev
                self._mode = hit_mode
                self._drag_start_pos = pos
                self._drag_start_time_s = snapped_s
                self._drag_event_orig_start = hit_ev.start_ticks
                self._drag_event_orig_end = hit_ev.end_ticks
                self._drag_event_orig_chan = hit_ev.channel
                self.event_selected.emit("digital", hit_ev.channel)
                self.update()
                return

            # Check if clicked on empty spot in a DIO lane
            if 0 <= lane_idx < self.num_dio_channels:
                target_dio = lane_idx
                # ENFORCE FPGA 1-PULSE-PER-CHANNEL RULE:
                # If a pulse already exists on this channel, select and reposition it to the clicked time!
                existing = next((e for e in self._sequence.digital_events if e.channel == target_dio), None)
                if existing is not None:
                    orig_dur = max(1, existing.end_ticks - existing.start_ticks)
                    new_st = max(0, int(round(snapped_s * clock)))
                    existing.start_ticks = new_st
                    existing.end_ticks = new_st + orig_dur
                    existing.enabled = True

                    self._active_event = existing
                    self._selected_event = existing
                    self._mode = "MOVING"
                    self._drag_start_pos = pos
                    self._drag_start_time_s = snapped_s
                    self._drag_event_orig_start = new_st
                    self._drag_event_orig_end = new_st + orig_dur
                    self._drag_event_orig_chan = existing.channel
                    self.event_selected.emit("digital", existing.channel)

                    self.sequence_modified.emit()
                    self.update()
                    return

                # Create the single pulse for this channel
                self._mode = "CREATING"
                self._drag_start_pos = pos
                self._drag_start_time_s = snapped_s
                start_ticks = int(round(snapped_s * clock))

                min_step_s = max(self.snap_step_s, 1.0 / clock)
                end_ticks = start_ticks + max(1, int(round(min_step_s * clock)))

                new_event = DigitalEvent(
                    name=f"DIO{target_dio}",
                    channel=target_dio,
                    label=self._sequence.channel_labels.get(target_dio, f"DIO{target_dio}"),
                    start_ticks=start_ticks,
                    end_ticks=end_ticks,
                    enabled=True,
                )
                self._sequence.digital_events.append(new_event)
                self._active_event = new_event
                self._selected_event = new_event
                self.event_selected.emit("digital", target_dio)
                self.sequence_modified.emit()
                self.update()
                return
            elif lane_idx >= self.num_dio_channels and self._sequence:
                ao_idx = lane_idx - self.num_dio_channels
                if 0 <= ao_idx < len(self._sequence.analog_events):
                    self.event_selected.emit("analog", ao_idx)
                    self.update()
                    return

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()
        timeline_width = max(10.0, float(self.width()) - self._label_width)
        clock = self._sequence.clock_hz if self._sequence else FPGA_CLOCK_HZ
        min_tick_s = 1.0 / clock  # 25 ns

        if self._mode == "PANNING":
            dx = pos.x() - self._drag_start_pos.x()
            self._pan_offset_x = max(0.0, self._drag_pan_orig_offset - dx)
            self.update()
            return

        if self._mode == "CREATING" and self._active_event:
            t_s = self._x_to_time_s(pos.x(), timeline_width)
            snapped_s = self._snap_time_s(t_s)
            st_s = min(self._drag_start_time_s, snapped_s)
            end_s = max(self._drag_start_time_s, snapped_s)
            if end_s - st_s < min_tick_s:
                end_s = st_s + max(self.snap_step_s, min_tick_s)

            self._active_event.start_ticks = int(round(st_s * clock))
            self._active_event.end_ticks = max(
                self._active_event.start_ticks + 1, int(round(end_s * clock))
            )
            self.update()
            return

        if self._mode == "MOVING" and self._active_event:
            t_s = self._x_to_time_s(pos.x(), timeline_width)
            snapped_s = self._snap_time_s(t_s)
            delta_s = snapped_s - self._drag_start_time_s
            delta_ticks = int(round(delta_s * clock))

            orig_dur = max(1, self._drag_event_orig_end - self._drag_event_orig_start)
            new_st = max(0, self._drag_event_orig_start + delta_ticks)
            self._active_event.start_ticks = new_st
            self._active_event.end_ticks = new_st + orig_dur

            lane_idx = self._y_to_lane_idx(pos.y())
            if 0 <= lane_idx < self.num_dio_channels and lane_idx != self._active_event.channel:
                target_occupied = any(e.channel == lane_idx and e != self._active_event for e in self._sequence.digital_events)
                if not target_occupied:
                    self._active_event.channel = lane_idx

            self.update()
            return

        if self._mode == "RESIZE_START" and self._active_event:
            t_s = self._x_to_time_s(pos.x(), timeline_width)
            snapped_s = self._snap_time_s(t_s)
            new_st = int(round(snapped_s * clock))
            if 0 <= new_st < self._active_event.end_ticks:
                self._active_event.start_ticks = new_st
            self.update()
            return

        if self._mode == "RESIZE_END" and self._active_event:
            t_s = self._x_to_time_s(pos.x(), timeline_width)
            snapped_s = self._snap_time_s(t_s)
            new_end = int(round(snapped_s * clock))
            if new_end > self._active_event.start_ticks:
                self._active_event.end_ticks = new_end
            self.update()
            return

        lane_idx = self._y_to_lane_idx(pos.y())
        self._hover_channel = lane_idx
        hit_ev, hit_mode = self._hit_test_pulse(pos.x(), lane_idx, timeline_width, clock)
        self._hover_event = hit_ev
        self._hover_mode = hit_mode

        if hit_mode in ("RESIZE_START", "RESIZE_END"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif hit_mode == "MOVING":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        elif ((0 <= lane_idx < self.num_dio_channels) or (self.num_dio_channels <= lane_idx < self.num_dio_channels + 8)) and pos.x() > self._label_width:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._mode in ("CREATING", "MOVING", "RESIZE_START", "RESIZE_END"):
            self._mode = "IDLE"
            self._active_event = None
            self.sequence_modified.emit()
            self.update()
        self._mode = "IDLE"

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        pos = event.position()
        timeline_width = max(10.0, float(self.width()) - self._label_width)
        clock = self._sequence.clock_hz if self._sequence else FPGA_CLOCK_HZ
        lane_idx = self._y_to_lane_idx(pos.y())

        hit_ev, _ = self._hit_test_pulse(pos.x(), lane_idx, timeline_width, clock)
        if hit_ev and self._sequence:
            dlg = PulseEditDialog(hit_ev, self._sequence, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                if dlg.deleted:
                    if hit_ev in self._sequence.digital_events:
                        self._sequence.digital_events.remove(hit_ev)
                    self._selected_event = None
                self.sequence_modified.emit()
                self.update()
        elif 0 <= lane_idx < self.num_dio_channels and self._sequence:
            # Check if channel already has an event
            ch_ev = next((e for e in self._sequence.digital_events if e.channel == lane_idx), None)
            if not ch_ev:
                t_s = self._snap_time_s(self._x_to_time_s(pos.x(), timeline_width))
                st_ticks = int(round(t_s * clock))
                dur_ticks = max(1, int(round(self.snap_step_s * clock)))
                ch_ev = DigitalEvent(
                    name=f"DIO{lane_idx}",
                    channel=lane_idx,
                    label=self._sequence.channel_labels.get(lane_idx, f"DIO{lane_idx}"),
                    start_ticks=st_ticks,
                    end_ticks=st_ticks + dur_ticks,
                    enabled=True,
                )
                self._sequence.digital_events.append(ch_ev)
            dlg = PulseEditDialog(ch_ev, self._sequence, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                if dlg.deleted:
                    if ch_ev in self._sequence.digital_events:
                        self._sequence.digital_events.remove(ch_ev)
                self.sequence_modified.emit()
                self.update()
        elif lane_idx >= self.num_dio_channels and self._sequence:
            ao_idx = lane_idx - self.num_dio_channels
            if ao_idx < len(self._sequence.analog_events):
                from .analog_editor import AnalogChannelConfigDialog
                u_str = "µs" if self._time_unit == TimeUnit.MICROSECONDS else "ms"
                dlg = AnalogChannelConfigDialog(self._sequence.analog_events[ao_idx], ao_idx, initial_unit=u_str, parent=self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    self.sequence_modified.emit()
                    self.update()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected_event()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = 1.2 if delta > 0 else 0.8
        self.set_zoom(self._zoom * factor)

    # ── Hit Testing Helper ──────────────────────────────────────────────

    def _hit_test_pulse(
        self, x: float, lane_idx: int, timeline_width: float, clock: int
    ) -> Tuple[Optional[DigitalEvent], str]:
        if not self._sequence:
            return None, "IDLE"

        target_chan = lane_idx
        if lane_idx >= self.num_dio_channels:
            ao_idx = lane_idx - self.num_dio_channels
            if 0 <= ao_idx < 8:
                target_chan = ao_idx
            else:
                return None, "IDLE"
        elif not (0 <= lane_idx < self.num_dio_channels):
            return None, "IDLE"

        for ev in self._sequence.digital_events:
            if ev.channel != target_chan:
                continue
            st_x = self._time_s_to_x(ev.start_ticks / clock, timeline_width)
            end_x = self._time_s_to_x(ev.end_ticks / clock, timeline_width)
            eff_end_x = max(st_x + 8.0, end_x)
            pulse_w = eff_end_x - st_x

            # Hit margin of 6 pixels around the pulse
            if (st_x - 6.0) <= x <= (eff_end_x + 6.0):
                # When pulse is visually narrow on screen (< 28 px), entire pulse is a MOVE handle
                if pulse_w < 28.0:
                    return ev, "MOVING"
                # For wide pulses, outer edges resize, inner body moves
                edge_threshold = min(6.0, pulse_w * 0.2)
                if abs(x - st_x) <= edge_threshold:
                    return ev, "RESIZE_START"
                if abs(x - eff_end_x) <= edge_threshold:
                    return ev, "RESIZE_END"
                return ev, "MOVING"
        return None, "IDLE"

    def _show_context_menu(self, event: QMouseEvent):
        pos = event.position()
        timeline_width = max(10.0, float(self.width()) - self._label_width)
        clock = self._sequence.clock_hz if self._sequence else FPGA_CLOCK_HZ
        lane_idx = self._y_to_lane_idx(pos.y())
        hit_ev, _ = self._hit_test_pulse(pos.x(), lane_idx, timeline_width, clock)

        menu = QMenu(self)

        if hit_ev:
            action_edit = menu.addAction("✏ Edit Pulse Details…")
            action_toggle = menu.addAction("Disable Pulse" if hit_ev.enabled else "Enable Pulse")
            action_del = menu.addAction("🗑 Delete Pulse")

            act = menu.exec(QCursor.pos())
            ch = hit_ev.channel
            if act == action_edit:
                dlg = PulseEditDialog(hit_ev, self._sequence, parent=self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    if dlg.deleted:
                        if 0 <= ch < 8 and ch < len(self._sequence.analog_events):
                            self._sequence.analog_events[ch].enabled = False
                        if hit_ev in self._sequence.digital_events:
                            self._sequence.digital_events.remove(hit_ev)
                        self._selected_event = None
                    else:
                        if 0 <= ch < 8 and ch < len(self._sequence.analog_events):
                            self._sequence.analog_events[ch].enabled = hit_ev.enabled and (hit_ev.end_ticks > hit_ev.start_ticks)
                    self.sequence_modified.emit()
                    self.update()
            elif act == action_toggle:
                hit_ev.enabled = not hit_ev.enabled
                if 0 <= ch < 8 and ch < len(self._sequence.analog_events):
                    self._sequence.analog_events[ch].enabled = hit_ev.enabled and (hit_ev.end_ticks > hit_ev.start_ticks)
                self.sequence_modified.emit()
                self.update()
            elif act == action_del:
                if 0 <= ch < 8 and ch < len(self._sequence.analog_events):
                    self._sequence.analog_events[ch].enabled = False
                if hit_ev in self._sequence.digital_events:
                    self._sequence.digital_events.remove(hit_ev)
                self._selected_event = None
                self.sequence_modified.emit()
                self.update()
        elif 0 <= lane_idx < self.num_dio_channels:
            t_s = self._snap_time_s(self._x_to_time_s(pos.x(), timeline_width))
            act_1us = menu.addAction(f"+ Add 1 µs Pulse at {t_s*1e6:.1f} µs")
            act_10us = menu.addAction(f"+ Add 10 µs Pulse at {t_s*1e6:.1f} µs")
            act_100us = menu.addAction(f"+ Add 100 µs Pulse at {t_s*1e6:.1f} µs")
            act_1ms = menu.addAction(f"+ Add 1 ms Pulse at {t_s*1000:.2f} ms")

            act = menu.exec(QCursor.pos())
            dur_s = 0.0
            if act == act_1us:
                dur_s = 1e-6
            elif act == act_10us:
                dur_s = 10e-6
            elif act == act_100us:
                dur_s = 100e-6
            elif act == act_1ms:
                dur_s = 1e-3

            if dur_s > 0 and self._sequence:
                new_ev = DigitalEvent(
                    name=f"DIO{lane_idx} Pulse",
                    channel=lane_idx,
                    label=self._sequence.channel_labels.get(lane_idx, f"DIO{lane_idx}"),
                    start_ticks=int(round(t_s * clock)),
                    end_ticks=int(round((t_s + dur_s) * clock)),
                    enabled=True,
                )
                self._sequence.digital_events.append(new_ev)
                self.sequence_modified.emit()
                self.update()


# ────────────────────────────────────────────────────────────────────────
#  Integrated Timeline Container with Precision Toolbar
# ────────────────────────────────────────────────────────────────────────

class TimelineWidget(QWidget):
    """Complete Timeline container with interactive canvas and UX toolbar."""

    sequence_modified = Signal()
    time_clicked = Signal(float)
    event_selected = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Quick-Palette Toolbar ──
        tb = QHBoxLayout()
        tb.setContentsMargins(8, 6, 8, 0)
        tb.setSpacing(8)

        lbl_hint = QLabel("💡 <b>Draw & Drop:</b> Click-drag on any lane to draw (down to 25ns) • Drag edges to resize • Double-click to edit")
        lbl_hint.setStyleSheet("color: #8888a8; font-size: 11px;")
        tb.addWidget(lbl_hint)
        tb.addStretch()

        # Display Unit Selector (µs, ms, s, ticks)
        tb.addWidget(QLabel("⏱ Display:"))
        self._unit_combo = QComboBox()
        self._unit_combo.addItem("µs (Microseconds)", TimeUnit.MICROSECONDS)
        self._unit_combo.addItem("ms (Milliseconds)", TimeUnit.MILLISECONDS)
        self._unit_combo.addItem("s (Seconds)", TimeUnit.SECONDS)
        self._unit_combo.addItem("ticks (25 ns Cycles)", TimeUnit.TICKS)
        self._unit_combo.setCurrentIndex(1)  # default ms
        self._unit_combo.currentIndexChanged.connect(self._on_display_unit_changed)
        tb.addWidget(self._unit_combo)

        # Snap to grid dropdown (microsecond & nanosecond precision)
        tb.addWidget(QLabel("🧲 Snap:"))
        self._snap_combo = QComboBox()
        self._snap_combo.addItem("25 ns (1 Tick)", 25e-9)
        self._snap_combo.addItem("0.1 µs (100 ns)", 100e-9)
        self._snap_combo.addItem("1.0 µs (40 ticks)", 1e-6)
        self._snap_combo.addItem("5.0 µs (200 ticks)", 5e-6)
        self._snap_combo.addItem("10 µs (400 ticks)", 10e-6)
        self._snap_combo.addItem("50 µs", 50e-6)
        self._snap_combo.addItem("100 µs (0.1 ms)", 100e-6)
        self._snap_combo.addItem("0.5 ms", 0.0005)
        self._snap_combo.addItem("1.0 ms", 0.001)
        self._snap_combo.addItem("5.0 ms", 0.005)
        self._snap_combo.addItem("None (1 Tick)", 25e-9)
        self._snap_combo.setCurrentIndex(4)  # default 10 µs
        self._snap_combo.currentIndexChanged.connect(self._on_snap_changed)
        tb.addWidget(self._snap_combo)

        # Quick Pulse Presets
        btn_10us = QPushButton("+ 10 µs")
        btn_10us.setStyleSheet("background-color: #2b3b55; color: #00d4ff; font-weight: bold;")
        btn_10us.clicked.connect(lambda: self._add_preset_pulse_s(10e-6, "10µs Pulse"))
        tb.addWidget(btn_10us)

        btn_100us = QPushButton("+ 100 µs")
        btn_100us.setStyleSheet("background-color: #2b3b55; color: #00d4ff; font-weight: bold;")
        btn_100us.clicked.connect(lambda: self._add_preset_pulse_s(100e-6, "100µs Pulse"))
        tb.addWidget(btn_100us)

        btn_1ms = QPushButton("+ 1 ms")
        btn_1ms.setStyleSheet("background-color: #2b3b55; color: #00d4ff; font-weight: bold;")
        btn_1ms.clicked.connect(lambda: self._add_preset_pulse_s(1e-3, "1ms Pulse"))
        tb.addWidget(btn_1ms)

        # Delete Button
        btn_del = QPushButton("🗑 Delete")
        btn_del.setStyleSheet("color: #ff6666;")
        btn_del.clicked.connect(lambda: self._canvas.delete_selected_event())
        tb.addWidget(btn_del)

        # Zoom Controls
        btn_zoom_in = QPushButton("Zoom In (+)")
        btn_zoom_in.clicked.connect(lambda: self._canvas.set_zoom(self._canvas._zoom * 1.35))
        tb.addWidget(btn_zoom_in)

        btn_zoom_out = QPushButton("Zoom Out (−)")
        btn_zoom_out.clicked.connect(lambda: self._canvas.set_zoom(self._canvas._zoom * 0.75))
        tb.addWidget(btn_zoom_out)

        btn_fit = QPushButton("Fit Sequence")
        btn_fit.clicked.connect(lambda: self._canvas.fit_sequence())
        tb.addWidget(btn_fit)

        layout.addLayout(tb)

        # ── Interactive Canvas inside ScrollArea ──
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { border: 1px solid #28283c; background-color: #12121e; }")

        self._canvas = TimelineCanvas()
        self._canvas.sequence_modified.connect(self.sequence_modified.emit)
        self._canvas.event_selected.connect(self.event_selected.emit)
        self._scroll.setWidget(self._canvas)
        layout.addWidget(self._scroll, 1)

        self.setMinimumHeight(180)

    def _on_display_unit_changed(self):
        unit = self._unit_combo.currentData()
        if unit:
            self._canvas.set_time_unit(unit)

    def _on_snap_changed(self):
        val = self._snap_combo.currentData()
        self._canvas.snap_step_s = float(val) if val is not None else 10e-6

    def _add_preset_pulse_s(self, duration_s: float, label: str):
        """Add a preset pulse to the first available digital channel (1 pulse max per channel)."""
        seq = self._canvas._sequence
        if not seq:
            return
        clock = seq.clock_hz
        dur_ticks = max(1, int(round(duration_s * clock)))

        # Find first channel not yet having an event
        occupied_chans = {e.channel for e in seq.digital_events}
        target_ch = 0
        for ch in range(self._canvas.num_dio_channels):
            if ch not in occupied_chans:
                target_ch = ch
                break
        else:
            # All channels occupied: replace channel 0 pulse
            target_ch = 0
            seq.digital_events = [e for e in seq.digital_events if e.channel != 0]

        new_ev = DigitalEvent(
            name=label,
            channel=target_ch,
            label=seq.channel_labels.get(target_ch, f"DIO{target_ch}"),
            start_ticks=0,
            end_ticks=dur_ticks,
            enabled=True,
        )
        seq.digital_events.append(new_ev)

        if target_ch < 8 and target_ch < len(seq.analog_events):
            aev = seq.analog_events[target_ch]
            aev.enabled = True
            aev.start_ms = 0.0
            aev.end_ms = duration_s * 1000.0
            aev.duration_ms = max(0.000025, duration_s * 1000.0)

        self._canvas.sequence_modified.emit()
        self._canvas.update()

    # ── Proxy methods for MainWindow & Editors ──
    def set_sequence(self, sequence: ExperimentSequence):
        self._canvas.set_sequence(sequence)

    def set_time_unit(self, unit: TimeUnit):
        self._canvas.set_time_unit(unit)
        for i in range(self._unit_combo.count()):
            if self._unit_combo.itemData(i) == unit:
                self._unit_combo.blockSignals(True)
                self._unit_combo.setCurrentIndex(i)
                self._unit_combo.blockSignals(False)
                break

    def set_zoom(self, factor: float):
        self._canvas.set_zoom(factor)

    def reset_view(self):
        self._canvas.fit_sequence()

    def refresh(self):
        self._canvas.update()
