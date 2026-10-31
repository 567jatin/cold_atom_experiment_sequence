"""
Experiment data model for the FPGA TTL and Analog Waveform Sequence Controller.

Defines the full dataclass hierarchy for digital events, analog events,
trigger mappings, and experiment sequences, along with serialization,
deserialization, and validation helpers.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FPGA_CLOCK_HZ: int = 40_000_000
_UINT32_MAX: int = 0xFFFF_FFFF  # 4 294 967 295


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class TimeUnit(Enum):
    SECONDS = "s"
    MILLISECONDS = "ms"
    MICROSECONDS = "us"
    TICKS = "ticks"


class WaveformType(Enum):
    RAMP = "ramp"
    SQUARE = "square"
    SINE = "sine"
    CONSTANT = "constant"
    ARBITRARY = "arbitrary"


class TriggerEdge(Enum):
    RISING = "rising"
    FALLING = "falling"


class RepeatMode(Enum):
    SINGLE = "single"
    CONTINUOUS = "continuous"
    COUNT = "count"


# ---------------------------------------------------------------------------
# Event / mapping dataclasses
# ---------------------------------------------------------------------------
@dataclass
class DigitalEvent:
    name: str = "Untitled"
    channel: int = 0  # 0-20
    start_ticks: int = 0
    end_ticks: int = 0
    enabled: bool = True
    notes: str = ""
    label: str = ""  # e.g. "Pump AOM", "Probe AOM", "Shutter"


@dataclass
class AnalogEvent:
    name: str = "Untitled"
    channel: str = "PXI2Slot3/ao0"
    trigger_source: str = "/PXI2Slot3/PXI_Trig0"
    trigger_edge: TriggerEdge = TriggerEdge.RISING
    waveform_type: WaveformType = WaveformType.RAMP
    start_voltage: float = 0.0
    end_voltage: float = 5.0
    min_voltage: float = -10.0
    max_voltage: float = 10.0
    frequency_hz: float = 10000.0
    start_ms: float = 0.0
    end_ms: float = 42.5
    duration_ms: float = 42.5
    sample_rate_hz: float = 500000.0
    num_samples: Optional[int] = None  # computed from duration & sample_rate if None
    enabled: bool = True
    notes: str = ""
    generation_mode: str = "triggered"  # "triggered" or "continuous"
    arbitrary_data: Optional[list] = None  # stored as list for JSON serialization

    # Microsecond and second convenience properties
    @property
    def start_us(self) -> float:
        return self.start_ms * 1000.0

    @start_us.setter
    def start_us(self, val: float):
        self.start_ms = val / 1000.0

    @property
    def end_us(self) -> float:
        return self.end_ms * 1000.0

    @end_us.setter
    def end_us(self, val: float):
        self.end_ms = val / 1000.0

    @property
    def duration_us(self) -> float:
        return max(0.0, self.duration_ms * 1000.0)

    @duration_us.setter
    def duration_us(self, val: float):
        self.duration_ms = max(0.000001, val / 1000.0)

    @property
    def start_s(self) -> float:
        return self.start_ms / 1000.0

    @start_s.setter
    def start_s(self, val: float):
        self.start_ms = val * 1000.0

    @property
    def end_s(self) -> float:
        return self.end_ms / 1000.0

    @end_s.setter
    def end_s(self, val: float):
        self.end_ms = val * 1000.0

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0

    def start_ticks(self, clock_hz: int = FPGA_CLOCK_HZ) -> int:
        return max(0, int(round((self.start_ms / 1000.0) * clock_hz)))

    def end_ticks(self, clock_hz: int = FPGA_CLOCK_HZ) -> int:
        return max(self.start_ticks(clock_hz), int(round((self.end_ms / 1000.0) * clock_hz)))


@dataclass
class TriggerMapping:
    name: str = "Untitled"
    source_type: str = "digital"  # "digital" or "pxi_trigger"
    source_channel: str = ""
    target_type: str = "analog"  # "analog" or "external"
    target_channel: str = ""
    trigger_edge: TriggerEdge = TriggerEdge.RISING
    enabled: bool = True
    notes: str = ""


# ---------------------------------------------------------------------------
# Experiment sequence
# ---------------------------------------------------------------------------
@dataclass
class ExperimentSequence:
    name: str = "New Experiment"
    clock_hz: int = FPGA_CLOCK_HZ
    repeat_mode: RepeatMode = RepeatMode.SINGLE
    repeat_count: int = 1
    sequence_duration_ticks: int = FPGA_CLOCK_HZ  # Default 1 second
    digital_events: List[DigitalEvent] = field(default_factory=list)
    analog_events: List[AnalogEvent] = field(default_factory=list)
    trigger_mappings: List[TriggerMapping] = field(default_factory=list)
    safe_voltage: float = 0.0
    channel_labels: dict = field(
        default_factory=lambda: {i: f"DIO{i}" for i in range(21)}
    )

    # -- Time conversion helpers --------------------------------------------
    def time_to_ticks(self, time_value: float, unit: TimeUnit) -> int:
        """Convert a time value in the given *unit* to FPGA clock ticks."""
        if unit is TimeUnit.TICKS:
            return int(time_value)
        multipliers = {
            TimeUnit.SECONDS: 1.0,
            TimeUnit.MILLISECONDS: 1e-3,
            TimeUnit.MICROSECONDS: 1e-6,
        }
        seconds = time_value * multipliers[unit]
        return int(round(seconds * self.clock_hz))

    def ticks_to_time(self, ticks: int, unit: TimeUnit) -> float:
        """Convert FPGA clock ticks to a time value in the given *unit*."""
        if unit is TimeUnit.TICKS:
            return float(ticks)
        divisors = {
            TimeUnit.SECONDS: 1.0,
            TimeUnit.MILLISECONDS: 1e-3,
            TimeUnit.MICROSECONDS: 1e-6,
        }
        seconds = ticks / self.clock_hz
        return seconds / divisors[unit]

    def get_or_create_analog_event(self, channel_idx: int) -> AnalogEvent:
        """Get or initialize the AnalogEvent for channel ao{channel_idx}."""
        target_name = f"ao{channel_idx}"
        for ev in self.analog_events:
            if ev.channel.lower().endswith(target_name):
                return ev
        # Create default
        ev = AnalogEvent(
            name=f"AO{channel_idx}",
            channel=f"PXI2Slot3/ao{channel_idx}",
            trigger_source=f"/PXI2Slot3/PXI_Trig{channel_idx}",
            start_ms=0.0,
            end_ms=42.5,
            duration_ms=42.5,
            enabled=False,
        )
        self.analog_events.append(ev)
        return ev

    def get_or_create_digital_event(self, channel_idx: int) -> DigitalEvent:
        """Get or initialize the single DigitalEvent for DIO channel_idx."""
        for ev in self.digital_events:
            if ev.channel == channel_idx:
                return ev
        ev = DigitalEvent(
            name=f"DIO{channel_idx}",
            channel=channel_idx,
            label=self.channel_labels.get(channel_idx, f"DIO{channel_idx}"),
            start_ticks=0,
            end_ticks=0,
            enabled=False,
        )
        self.digital_events.append(ev)
        return ev

    # -- Serialization ------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Serialize the full sequence to a plain dict (JSON-safe)."""

        def _enum_val(obj: Any) -> Any:
            return obj.value if isinstance(obj, Enum) else obj

        def _event_dict(evt: Any) -> Dict[str, Any]:
            d: Dict[str, Any] = {}
            for k, v in evt.__dict__.items():
                if isinstance(v, np.ndarray):
                    d[k] = v.tolist()
                elif isinstance(v, Enum):
                    d[k] = v.value
                else:
                    d[k] = v
            return d

        return {
            "name": self.name,
            "clock_hz": self.clock_hz,
            "repeat_mode": _enum_val(self.repeat_mode),
            "repeat_count": self.repeat_count,
            "sequence_duration_ticks": self.sequence_duration_ticks,
            "digital_events": [_event_dict(e) for e in self.digital_events],
            "analog_events": [_event_dict(e) for e in self.analog_events],
            "trigger_mappings": [_event_dict(m) for m in self.trigger_mappings],
            "safe_voltage": self.safe_voltage,
            "channel_labels": {str(k): v for k, v in self.channel_labels.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperimentSequence":
        """Deserialize from a plain dict (as produced by :meth:`to_dict`)."""

        def _digital(d: Dict[str, Any]) -> DigitalEvent:
            return DigitalEvent(**d)

        def _analog(d: Dict[str, Any]) -> AnalogEvent:
            d = dict(d)  # shallow copy so we don't mutate the input
            if "start_ms" not in d:
                d["start_ms"] = 0.0
            if "end_ms" not in d:
                d["end_ms"] = float(d["start_ms"]) + float(d.get("duration_ms", 42.5))
            if "duration_ms" not in d:
                d["duration_ms"] = max(0.001, float(d["end_ms"]) - float(d["start_ms"]))
            if "trigger_edge" in d:
                d["trigger_edge"] = TriggerEdge(d["trigger_edge"])
            if "waveform_type" in d:
                d["waveform_type"] = WaveformType(d["waveform_type"])
            return AnalogEvent(**d)

        def _trigger(d: Dict[str, Any]) -> TriggerMapping:
            d = dict(d)
            if "trigger_edge" in d:
                d["trigger_edge"] = TriggerEdge(d["trigger_edge"])
            return TriggerMapping(**d)

        # Reconstruct channel_labels with int keys
        raw_labels = data.get("channel_labels", {})
        channel_labels = {}
        for k, v in raw_labels.items():
            try:
                channel_labels[int(k)] = v
            except (ValueError, TypeError):
                channel_labels[k] = v

        return cls(
            name=data.get("name", "New Experiment"),
            clock_hz=data.get("clock_hz", FPGA_CLOCK_HZ),
            repeat_mode=RepeatMode(data["repeat_mode"]) if "repeat_mode" in data else RepeatMode.SINGLE,
            repeat_count=data.get("repeat_count", 1),
            sequence_duration_ticks=data.get("sequence_duration_ticks", FPGA_CLOCK_HZ),
            digital_events=[_digital(e) for e in data.get("digital_events", [])],
            analog_events=[_analog(e) for e in data.get("analog_events", [])],
            trigger_mappings=[_trigger(m) for m in data.get("trigger_mappings", [])],
            safe_voltage=data.get("safe_voltage", 0.0),
            channel_labels=channel_labels,
        )

    # -- File I/O -----------------------------------------------------------
    def save_json(self, filepath: str) -> None:
        """Save the sequence to a JSON file."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load_json(cls, filepath: str) -> "ExperimentSequence":
        """Load a sequence from a JSON file."""
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_dict(data)

    # -- Duplication --------------------------------------------------------
    def duplicate(self) -> "ExperimentSequence":
        """Return an independent deep copy of this sequence."""
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
@dataclass
class ValidationMessage:
    level: str  # "error", "warning", "info"
    message: str
    source: str


def validate(sequence: ExperimentSequence) -> List[ValidationMessage]:
    """Validate an :class:`ExperimentSequence` and return a list of messages.

    Checks performed
    ----------------
    - Digital event start_ticks < end_ticks.
    - All tick values >= 0 and fit in a 32-bit unsigned integer.
    - sequence_duration_ticks covers all events (terminal count).
    - No digital pulse crosses the counter rollover boundary.
    - Analog voltage values within [min_voltage, max_voltage].
    - Analog sample_rate > 0 and duration > 0.
    - Analog waveform duration compatible with trigger schedule.
    - Digital channel indices in range 0-20.
    - Warnings for overlapping events on the same digital channel.
    """
    msgs: List[ValidationMessage] = []

    # -- Digital events -----------------------------------------------------
    # Collect per-channel intervals for overlap detection.
    channel_intervals: Dict[int, List[tuple]] = {}

    for idx, evt in enumerate(sequence.digital_events):
        src = f"digital_events[{idx}] ({evt.name})"

        # Channel index non-negative
        if evt.channel < 0:
            msgs.append(ValidationMessage("error", f"Channel index cannot be negative ({evt.channel}).", src))

        # Tick sign / size
        for tick_name in ("start_ticks", "end_ticks"):
            tick_val = getattr(evt, tick_name)
            if tick_val < 0:
                msgs.append(ValidationMessage("error", f"{tick_name} is negative ({tick_val}).", src))
            elif tick_val > _UINT32_MAX:
                msgs.append(ValidationMessage("error", f"{tick_name} ({tick_val}) exceeds 32-bit unsigned max.", src))

        # Ordering
        if evt.start_ticks >= evt.end_ticks:
            msgs.append(ValidationMessage("error", f"start_ticks ({evt.start_ticks}) must be < end_ticks ({evt.end_ticks}).", src))

        # Terminal count coverage
        if evt.end_ticks > sequence.sequence_duration_ticks:
            msgs.append(
                ValidationMessage(
                    "error",
                    f"end_ticks ({evt.end_ticks}) exceeds sequence_duration_ticks ({sequence.sequence_duration_ticks}).",
                    src,
                )
            )

        # Rollover boundary: pulse must not span past UINT32_MAX
        if evt.start_ticks <= _UINT32_MAX < evt.end_ticks:
            msgs.append(ValidationMessage("error", "Pulse crosses 32-bit counter rollover boundary.", src))

        # Collect for overlap detection
        if evt.enabled:
            channel_intervals.setdefault(evt.channel, []).append((evt.start_ticks, evt.end_ticks, idx))

    # Overlap and multiple pulses detection (per-channel)
    # FPGA hardware architecture provides only one start/end register per channel per cycle.
    for ch, intervals in channel_intervals.items():
        if len(intervals) > 1:
            msgs.append(
                ValidationMessage(
                    "error",
                    f"FPGA hardware architecture limitation: Channel DIO{ch} has {len(intervals)} pulses configured. "
                    f"The FPGA bitfile provides only one start/end register pair (dio{ch}start / dio{ch}end) per cycle.",
                    f"Channel DIO{ch}",
                )
            )
        sorted_ivs = sorted(intervals, key=lambda t: t[0])
        for i in range(len(sorted_ivs) - 1):
            _, end_a, idx_a = sorted_ivs[i]
            start_b, _, idx_b = sorted_ivs[i + 1]
            if start_b < end_a:
                evt_a = sequence.digital_events[idx_a]
                evt_b = sequence.digital_events[idx_b]
                msgs.append(
                    ValidationMessage(
                        "error",
                        f"Overlapping events on channel {ch}: "
                        f"'{evt_a.name}' [{evt_a.start_ticks}-{evt_a.end_ticks}] and "
                        f"'{evt_b.name}' [{evt_b.start_ticks}-{evt_b.end_ticks}].",
                        f"digital_events[{idx_a}] / digital_events[{idx_b}]",
                    )
                )

    # -- Analog events ------------------------------------------------------
    for idx, evt in enumerate(sequence.analog_events):
        src = f"analog_events[{idx}] ({evt.name})"

        # Voltage limits
        for v_name in ("start_voltage", "end_voltage"):
            v = getattr(evt, v_name)
            if v < evt.min_voltage or v > evt.max_voltage:
                msgs.append(
                    ValidationMessage(
                        "error",
                        f"{v_name} ({v} V) outside allowed range [{evt.min_voltage}, {evt.max_voltage}] V.",
                        src,
                    )
                )

        # Sample rate
        if evt.sample_rate_hz <= 0:
            msgs.append(ValidationMessage("error", f"sample_rate_hz ({evt.sample_rate_hz}) must be > 0.", src))

        # Duration
        if evt.duration_ms <= 0:
            msgs.append(ValidationMessage("error", f"duration_ms ({evt.duration_ms}) must be > 0.", src))

        # Waveform duration vs. trigger schedule compatibility
        # In triggered mode the waveform must complete within one sequence cycle.
        if evt.enabled and evt.generation_mode == "triggered":
            waveform_duration_s = evt.duration_ms / 1000.0
            sequence_duration_s = sequence.sequence_duration_ticks / sequence.clock_hz
            if waveform_duration_s > sequence_duration_s:
                msgs.append(
                    ValidationMessage(
                        "warning",
                        f"Waveform duration ({evt.duration_ms} ms) exceeds sequence duration "
                        f"({sequence_duration_s * 1000:.3f} ms). The waveform may be truncated.",
                        src,
                    )
                )

    return msgs
