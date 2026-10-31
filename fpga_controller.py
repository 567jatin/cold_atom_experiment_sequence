"""
FPGA Controller Module
======================
Manages the NI FPGA session for TTL digital output waveform generation.
Communicates with the FPGA via nifpga to configure digital timing registers
and control sequence execution.

Generally discovers all control channels that expose a matching 'start' and 'end'
register pair in the FPGA bitfile, without hardcoded channel count limitations.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional

from PySide6.QtCore import QObject, Signal
import nifpga

from sequence_model import (
    ExperimentSequence,
    DigitalEvent,
    FPGA_CLOCK_HZ,
)
from logging_utils import get_app_logger

logger = get_app_logger(__name__)


def parse_bitfile_registers(bitfile_path: str) -> List[str]:
    """Parse raw register names directly from a .lvbitx bitfile XML document.

    Allows discovering registers and channel architecture statically without
    requiring physical PXI hardware or the NI-RIO runtime kernel driver.
    """
    registers: List[str] = []
    if not bitfile_path or not os.path.exists(bitfile_path):
        return registers
    try:
        tree = ET.parse(bitfile_path)
        root = tree.getroot()
        for reg in root.iter():
            name_node = reg.find("Name")
            if name_node is not None and name_node.text:
                if reg.tag in ("Register", "Control", "Indicator"):
                    registers.append(name_node.text)
    except Exception as exc:
        logger.warning("Could not parse bitfile registers from XML (%s): %s", bitfile_path, exc)
    return registers


def discover_start_end_channels(registers: List[str]) -> List[Dict[str, Any]]:
    """Generally discover all channels that have both a 'start' and an 'end' register.

    Works for any prefix (dio0..dioN, ch0..chN, laser_start/laser_end, etc.).
    Preserves exact raw register names for bitfile compatibility (such as
    the trailing space in 'dio4end ').

    Returns a list of dicts:
        {
            "channel": int,            # Integer channel index
            "prefix": str,             # Common prefix, e.g. "dio0"
            "name": str,               # Display name, e.g. "DIO0"
            "start_reg": str,          # Exact raw start register name
            "end_reg": str,            # Exact raw end register name
        }
    """
    starts: Dict[str, str] = {}
    ends: Dict[str, str] = {}

    for raw in registers:
        s = raw.strip()
        s_lower = s.lower()
        if s_lower.endswith("start"):
            prefix = s[:-5]
            if prefix.endswith("_"):
                prefix = prefix[:-1]
            starts[prefix] = raw
        elif s_lower.endswith("end"):
            prefix = s[:-3]
            if prefix.endswith("_"):
                prefix = prefix[:-1]
            ends[prefix] = raw

    common_prefixes = set(starts.keys()) & set(ends.keys())

    # Natural sort order (e.g., dio0, dio1, ... dio9, dio10, dio20)
    def natural_sort_key(p: str):
        parts = re.split(r'(\d+)', p)
        return [int(text) if text.isdigit() else text.lower() for text in parts]

    sorted_prefixes = sorted(common_prefixes, key=natural_sort_key)

    channels: List[Dict[str, Any]] = []
    for idx, prefix in enumerate(sorted_prefixes):
        m = re.search(r'(\d+)$', prefix)
        ch_num = int(m.group(1)) if m else idx
        display_name = prefix.upper()

        channels.append({
            "channel": ch_num,
            "prefix": prefix,
            "name": display_name,
            "start_reg": starts[prefix],
            "end_reg": ends[prefix],
        })

    return channels


class VirtualRegister:
    """In-memory representation of an FPGA register for software simulation."""

    def __init__(self, name: str, datatype: str = "U32"):
        self.name = name
        self.datatype = datatype
        self.value = False if datatype == "Bool" else 0

    def write(self, val):
        self.value = val

    def read(self):
        return self.value


class VirtualFpgaSession:
    """Simulated FPGA session allowing complete sequence testing without physical hardware."""

    def __init__(self, bitfile: str = "", discovered_channels: Optional[List[Dict[str, Any]]] = None):
        self.registers: Dict[str, VirtualRegister] = {}
        self.registers["y"] = VirtualRegister("y", "U32")
        self.registers["stop 2"] = VirtualRegister("stop 2", "Bool")

        # Use discovered channels or auto-detect from bitfile
        channels = discovered_channels
        if not channels and bitfile and os.path.exists(bitfile):
            regs = parse_bitfile_registers(bitfile)
            channels = discover_start_end_channels(regs)

        if not channels:
            # Fallback default 21 channels
            channels = [
                {
                    "channel": i,
                    "prefix": f"dio{i}",
                    "name": f"DIO{i}",
                    "start_reg": f"dio{i}start",
                    "end_reg": "dio4end " if i == 4 else f"dio{i}end",
                }
                for i in range(21)
            ]

        for ch in channels:
            self.registers[ch["start_reg"]] = VirtualRegister(ch["start_reg"], "U32")
            self.registers[ch["end_reg"]] = VirtualRegister(ch["end_reg"], "U32")

        try:
            if bitfile and os.path.exists(bitfile):
                bf = nifpga.Bitfile(bitfile)
                for k, v in bf.registers.items():
                    self.registers[k] = VirtualRegister(k, getattr(v, "datatype", "U32"))
        except Exception:
            pass

    def run(self):
        pass

    def close(self):
        pass

    def abort(self):
        pass


class FPGAController(QObject):
    """Controller for an NI FPGA target that drives DIO TTL lines.

    Provides general, automated discovery of all registers with a start and end pair:
    - Automatically discovers start/end channels dynamically from any bitfile or session.
    - Preserves bitfile naming quirks (e.g. trailing space on 'dio4end ').
    - Exposes controls and registers for every pair discovered.
    - Handles master counter 'y' and boolean 'stop 2' flag.
    """

    # ── Qt Signals ──────────────────────────────────────────────────────
    connected = Signal()
    disconnected = Signal()
    error_occurred = Signal(str)
    status_changed = Signal(str)
    channels_discovered = Signal(list)  # Emits list of channel metadata dicts

    # ── Hardware defaults ───────────────────────────────────────────────
    DEFAULT_BITFILE = (
        r"C:\Users\nqm lab18b\Documents\FPGA Bitfiles"
        r"\untitledproject1_FPGATarget_Untitled_8Vy1IOyvoh0.lvbitx"
    )
    DEFAULT_RESOURCE = "RIO0"
    CLOCK_HZ = 40_000_000
    NUM_DIO_CHANNELS = 21

    # ── Construction ────────────────────────────────────────────────────
    def __init__(
        self,
        bitfile: str = DEFAULT_BITFILE,
        resource: str = DEFAULT_RESOURCE,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bitfile = bitfile
        self._resource = resource
        self._session = None
        self.simulation_mode = False
        self._is_simulation = False
        self._discovered_channels: List[Dict[str, Any]] = []
        self._configured_sequence: Optional[ExperimentSequence] = None

        logger.info(
            "FPGAController created  bitfile=%s  resource=%s",
            self._bitfile,
            self._resource,
        )
        # Initial discovery from bitfile
        self.refresh_channels()

    # ── Channel Discovery ───────────────────────────────────────────────
    def refresh_channels(self) -> List[Dict[str, Any]]:
        """Dynamically detect all registers that have a start and end pair.

        Scans the current FPGA session registers, or parses the bitfile directly
        if the session is not yet active.
        """
        regs: List[str] = []
        if self._session is not None:
            regs = self.get_register_names()
        if not regs and self._bitfile and os.path.exists(self._bitfile):
            regs = parse_bitfile_registers(self._bitfile)

        channels = discover_start_end_channels(regs) if regs else []
        if not channels:
            # Fallback default 21 channels
            channels = [
                {
                    "channel": i,
                    "prefix": f"dio{i}",
                    "name": f"DIO{i}",
                    "start_reg": f"dio{i}start",
                    "end_reg": "dio4end " if i == 4 else f"dio{i}end",
                }
                for i in range(21)
            ]

        self._discovered_channels = channels
        self.NUM_DIO_CHANNELS = len(channels)
        logger.info(
            "Discovered %d start/end channels in FPGA bitfile: %s",
            len(channels),
            [c["name"] for c in channels],
        )
        self.channels_discovered.emit(channels)
        return channels

    def get_discovered_channels(self) -> List[Dict[str, Any]]:
        """Return list of discovered start/end channel metadata."""
        if not self._discovered_channels:
            self.refresh_channels()
        return list(self._discovered_channels)

    # ── Connection management ───────────────────────────────────────────
    def connect(self, allow_simulation: bool = True) -> bool:
        """Open an FPGA session and run the VI."""
        if self.simulation_mode:
            self.refresh_channels()
            self._session = VirtualFpgaSession(self._bitfile, self._discovered_channels)
            self._is_simulation = True
            logger.info("FPGA connected in Simulated Mode.")
            self.status_changed.emit("FPGA connected (Simulated)")
            self.connected.emit()
            return True

        try:
            logger.info("Opening FPGA session on %s …", self._resource)
            self._session = nifpga.Session(self._bitfile, self._resource)
            self._session.run()
            self._is_simulation = False
            self.refresh_channels()
            logger.info("FPGA session opened and VI running.")
            self.status_changed.emit("FPGA connected")
            self.connected.emit()
            self.safe_state()
            return True
        except Exception as exc:
            if allow_simulation:
                logger.warning(
                    "Physical FPGA not accessible (%s). Falling back to Virtual Simulation Mode.",
                    exc,
                )
                self.refresh_channels()
                self._session = VirtualFpgaSession(self._bitfile, self._discovered_channels)
                self._is_simulation = True
                self.status_changed.emit("FPGA connected (Simulated)")
                self.connected.emit()
                return True

            msg = f"Failed to connect to FPGA: {exc}"
            logger.error(msg)
            self._session = None
            self.error_occurred.emit(msg)
            return False

    def disconnect(self) -> None:
        """Request a stop, then close the FPGA session."""
        if self._session is None:
            return
        try:
            logger.info("Disconnecting FPGA …")
            self._write_register("stop 2", True)
            self._session.close()
            logger.info("FPGA session closed.")
        except Exception as exc:
            msg = f"Error disconnecting FPGA: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)
        finally:
            self._session = None
            self.status_changed.emit("FPGA disconnected")
            self.disconnected.emit()

    def is_connected(self) -> bool:
        """Return whether an FPGA session is currently open."""
        return self._session is not None

    # ── Register introspection ──────────────────────────────────────────
    def get_register_names(self) -> List[str]:
        """Return a list of all register names exposed by the current session."""
        if self._session is None:
            if self._bitfile and os.path.exists(self._bitfile):
                return sorted(parse_bitfile_registers(self._bitfile))
            return []
        try:
            if hasattr(self._session.registers, "keys"):
                return sorted(list(self._session.registers.keys()))
            names = []
            for reg in self._session.registers:
                names.append(reg.name if hasattr(reg, "name") else str(reg))
            return sorted(names)
        except Exception as exc:
            msg = f"Failed to enumerate registers: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)
            return []

    # ── Sequence configuration ──────────────────────────────────────────
    def configure_sequence(self, sequence: ExperimentSequence) -> None:
        """Arm sequence timing and master counter duration.

        Pins remain actively held at 0.0 V LOW during configuration to eliminate
        spurious premature pulses while analog tasks are being armed. Active channel
        timings are applied directly upon sequence start.

        Parameters
        ----------
        sequence : ExperimentSequence
            The experiment sequence containing digital events.
        """
        if self._session is None:
            msg = "Cannot configure sequence: FPGA not connected."
            logger.error(msg)
            self.error_occurred.emit(msg)
            return

        try:
            logger.info("Configuring FPGA sequence …")
            self._configured_sequence = sequence

            # 1. Write the master counter terminal with sequence duration
            self._write_register("y", sequence.sequence_duration_ticks)
            logger.debug("  y = %d ticks", sequence.sequence_duration_ticks)

            # 2. Hold all start/end registers at 0 (active 0.0 V LOW) while configuring/arming
            channels_to_write = self._discovered_channels or self.refresh_channels()
            for ch_info in channels_to_write:
                self._write_register(ch_info["start_reg"], 0)
                self._write_register(ch_info["end_reg"], 0)

            self.status_changed.emit("FPGA sequence configured (armed)")
            logger.info(
                "FPGA sequence configured successfully (%d channels armed at 0.0 V).",
                len(channels_to_write),
            )
        except Exception as exc:
            msg = f"Failed to configure sequence: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)

    # ── Run control ─────────────────────────────────────────────────────
    def start(self) -> None:
        """Apply active timing registers and start the FPGA pulse generation."""
        if self._session is None:
            msg = "Cannot start: FPGA not connected."
            logger.error(msg)
            self.error_occurred.emit(msg)
            return
        try:
            logger.info("Starting FPGA sequence …")
            self._write_register("stop 2", False)
            if hasattr(self._session, "run"):
                try:
                    self._session.run()
                except Exception:
                    pass

            # Program channel timings now at exact sequence start
            if self._configured_sequence is not None:
                enabled_events: Dict[int, DigitalEvent] = {
                    event.channel: event
                    for event in self._configured_sequence.digital_events
                    if event.enabled
                }
                channels = self._discovered_channels or self.refresh_channels()
                for ch_info in channels:
                    ch = ch_info["channel"]
                    start_reg = ch_info["start_reg"]
                    end_reg = ch_info["end_reg"]
                    if ch in enabled_events:
                        ev = enabled_events[ch]
                        self._write_register(start_reg, ev.start_ticks)
                        self._write_register(end_reg, ev.end_ticks)
                        logger.debug(
                            "  %s (ch%02d) active start=%d end=%d",
                            ch_info["name"], ch, ev.start_ticks, ev.end_ticks
                        )
                    else:
                        self._write_register(start_reg, 0)
                        self._write_register(end_reg, 0)

            self.status_changed.emit("FPGA running")
            logger.info("FPGA sequence started.")
        except Exception as exc:
            msg = f"Failed to start FPGA: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)

    def safe_state(self) -> None:
        """Drive all discovered DIO channels to logic 0 (LOW / 0.0 V) safe state while keeping the VI running."""
        if self._session is None:
            return
        try:
            logger.info("Setting FPGA safe state: driving all DIO channels to 0.0 V LOW …")
            # Clear stop flag and ensure VI is running to actively drive 0.0 V LOW
            self._write_register("stop 2", False)
            if hasattr(self._session, "run"):
                try:
                    self._session.run()
                except Exception:
                    pass
            # Set all channel start/end registers to 0 so all pins are held LOW (0.0 V)
            channels = self._discovered_channels or self.refresh_channels()
            for ch_info in channels:
                self._write_register(ch_info["start_reg"], 0)
                self._write_register(ch_info["end_reg"], 0)
            self.status_changed.emit("FPGA safe state (all DIO 0.0 V)")
            logger.info("FPGA safe state set: all %d channels driving 0.0 V LOW.", len(channels))
        except Exception as exc:
            msg = f"Failed to set FPGA safe state: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)

    def stop(self) -> None:
        """Stop sequence execution and return all DIO channels to 0.0 V safe state without tristating lines."""
        if self._session is None:
            return
        logger.info("Stopping FPGA sequence (holding 0.0 V safe state) …")
        self.safe_state()
        self.status_changed.emit("FPGA stopped (Safe State)")

    def emergency_stop(self) -> None:
        """Emergency stop — assert stop flag and abort the session."""
        logger.warning("FPGA EMERGENCY STOP requested!")
        if self._session is None:
            return
        try:
            self._write_register("stop 2", True)
            if hasattr(self._session, "abort"):
                self._session.abort()
                logger.info("FPGA session aborted.")
            self.status_changed.emit("FPGA emergency stopped")
        except Exception as exc:
            msg = f"Emergency stop error: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)

    def reset_registers(self) -> None:
        """Zero all start/end registers and assert the stop flag."""
        if self._session is None:
            msg = "Cannot reset registers: FPGA not connected."
            logger.error(msg)
            self.error_occurred.emit(msg)
            return
        try:
            logger.info("Resetting all FPGA registers …")
            self._write_register("y", 0)
            channels = self._discovered_channels or self.refresh_channels()
            for ch_info in channels:
                self._write_register(ch_info["start_reg"], 0)
                self._write_register(ch_info["end_reg"], 0)
            self._write_register("stop 2", True)
            self.status_changed.emit("FPGA registers reset")
            logger.info("FPGA registers reset.")
        except Exception as exc:
            msg = f"Failed to reset registers: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)

    # ── Private helpers ─────────────────────────────────────────────────
    def _get_dio_register_name(self, channel: int, register_type: str) -> str:
        """Lookup exact raw register name for a channel, falling back to standard naming."""
        for ch_info in self._discovered_channels:
            if ch_info["channel"] == channel:
                return ch_info["start_reg"] if register_type == "start" else ch_info["end_reg"]
        name = f"dio{channel}{register_type}"
        if channel == 4 and register_type == "end":
            name = "dio4end "  # Trailing space in the FPGA bitfile!
        return name

    def _write_register(self, name: str, value) -> None:
        """Write *value* to the named FPGA register."""
        if self._session is None:
            raise RuntimeError("FPGA session is not open.")
        if name not in self._session.registers:
            msg = f"Register '{name}' not found in FPGA session."
            logger.error(msg)
            raise KeyError(msg)

        reg = self._session.registers[name]
        if getattr(reg, "datatype", None) == "Bool":
            val = bool(value)
        else:
            val = int(value)
        reg.write(val)
