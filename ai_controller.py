"""
AI Controller Module (NI-DAQmx Analog Input Engine)
===================================================
Manages high-speed NI-DAQmx Analog Input (AI) tasks for real-time signal
acquisition, monitoring, and oscilloscope display.

Features:
- Automatic discovery of NI-DAQmx devices with AI physical channels.
- Configurable voltage ranges, terminal configurations (DIFF, RSE, NRSE),
  and sampling rates up to the card's hardware limit.
- Hardware-triggered acquisition from PXI backplane triggers (e.g. /PXI2Slot3/PXI_Trig0).
- High-performance streaming worker thread using AnalogMultiChannelReader.
- Seamless simulation fallback when the physical card is not yet plugged in.
"""

from __future__ import annotations

import os
import time
import math
from typing import Dict, List, Optional, Any, Tuple

import numpy as np
from PySide6.QtCore import QObject, Signal, QThread
import nidaqmx
from nidaqmx.constants import (
    AcquisitionType,
    Edge,
    TerminalConfiguration,
    VoltageUnits,
)
from nidaqmx.stream_readers import AnalogMultiChannelReader

from logging_utils import get_app_logger

logger = get_app_logger(__name__)


# ────────────────────────────────────────────────────────────────────────
#  Background Acquisition Worker Thread
# ────────────────────────────────────────────────────────────────────────

class AIAcquisitionWorker(QThread):
    """Background worker thread that streams analog input samples non-blockingly."""

    data_chunk_ready = Signal(object, object)  # (times_array: np.ndarray, channel_data: Dict[str, np.ndarray])
    acquisition_error = Signal(str)

    def __init__(
        self,
        task: Optional[nidaqmx.Task],
        channels: List[str],
        sample_rate: float,
        chunk_size: int = 1000,
        is_simulated: bool = False,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._task = task
        self._channels = list(channels)
        self._sample_rate = max(100.0, float(sample_rate))
        self._chunk_size = max(10, int(chunk_size))
        self._is_simulated = is_simulated
        self._running = False
        self._time_offset = 0.0

    def run(self):
        self._running = True
        num_ch = len(self._channels)
        if num_ch == 0:
            return

        dt = 1.0 / self._sample_rate
        chunk_dur = self._chunk_size * dt

        if self._is_simulated:
            logger.info("Starting Simulated AI acquisition stream (%d channels, %.1f kS/s)", num_ch, self._sample_rate / 1000.0)
            while self._running:
                t_start = time.perf_counter()
                times = self._time_offset + np.arange(self._chunk_size, dtype=np.float64) * dt
                self._time_offset += chunk_dur

                # Generate simulated input waveforms (e.g. response to experiment pulses + small noise)
                ch_data: Dict[str, np.ndarray] = {}
                for idx, ch_name in enumerate(self._channels):
                    freq = 500.0 * (idx + 1)
                    noise = np.random.normal(0.0, 0.015, self._chunk_size)
                    sig = 2.5 * np.sin(2 * np.pi * freq * times) + 2.5 + noise
                    ch_data[ch_name] = sig

                self.data_chunk_ready.emit(times, ch_data)

                # Regulate to real-time chunk interval
                elapsed = time.perf_counter() - t_start
                sleep_s = max(0.001, chunk_dur - elapsed)
                time.sleep(sleep_s)
        else:
            try:
                reader = AnalogMultiChannelReader(self._task.in_stream)
                data_buf = np.zeros((num_ch, self._chunk_size), dtype=np.float64)
                logger.info("Starting hardware AI acquisition stream (%d channels, %.1f kS/s)", num_ch, self._sample_rate / 1000.0)

                while self._running:
                    # Read chunk from hardware DMA stream buffer
                    reader.read_many_sample(
                        data_buf,
                        number_of_samples_per_channel=self._chunk_size,
                        timeout=2.0,
                    )
                    times = self._time_offset + np.arange(self._chunk_size, dtype=np.float64) * dt
                    self._time_offset += chunk_dur

                    ch_data = {
                        self._channels[i]: data_buf[i].copy() for i in range(num_ch)
                    }
                    self.data_chunk_ready.emit(times, ch_data)

            except Exception as exc:
                if self._running:
                    msg = f"AI streaming read error: {exc}"
                    logger.error(msg)
                    self.acquisition_error.emit(msg)

    def stop(self):
        self._running = False
        self.wait(1000)


# ────────────────────────────────────────────────────────────────────────
#  Pulse-Gated Capture Worker Thread
# ────────────────────────────────────────────────────────────────────────

class AIPulseCaptureWorker(QThread):
    """Background worker thread that executes a pulse-gated analog input capture."""

    capture_completed = Signal(object, object, object)  # (times: np.ndarray, channel_data: Dict[str, np.ndarray], metadata: dict)
    capture_error = Signal(str)

    def __init__(
        self,
        task: Optional[nidaqmx.Task],
        channels: List[str],
        sample_rate: float,
        duration_s: float,
        trigger_source: Optional[str] = None,
        is_simulated: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._task = task
        self._channels = list(channels)
        self._sample_rate = max(100.0, float(sample_rate))
        self._duration_s = max(1e-6, float(duration_s))
        self._trigger_source = trigger_source
        self._is_simulated = is_simulated
        self._metadata = metadata or {}

    def run(self):
        num_ch = len(self._channels)
        if num_ch == 0:
            self.capture_error.emit("No analog input channels specified for pulse capture.")
            return

        num_samples = max(2, int(round(self._duration_s * self._sample_rate)))
        dt = 1.0 / self._sample_rate

        if self._is_simulated:
            logger.info(
                "Executing Simulated pulse capture (%d channels, %d samples, %.2f ms)",
                num_ch, num_samples, self._duration_s * 1000.0
            )
            times = np.arange(num_samples, dtype=np.float64) * dt
            ch_data: Dict[str, np.ndarray] = {}

            # Generate realistic physical response signal during the pulse gate:
            for idx, ch_name in enumerate(self._channels):
                freq = 2500.0 * (idx + 1)
                envelope = np.ones(num_samples)
                edge_len = min(num_samples // 10, 100)
                if edge_len > 0:
                    envelope[:edge_len] = np.linspace(0.1, 1.0, edge_len)
                    envelope[-edge_len:] = np.linspace(1.0, 0.1, edge_len)
                noise = np.random.normal(0.0, 0.02, num_samples)
                sig = (2.5 * np.sin(2.0 * np.pi * freq * times) + 2.5) * envelope + noise
                ch_data[ch_name] = sig

            # Simulate pulse execution duration (capped at 0.4s for snappy UI response)
            sim_delay = min(self._duration_s, 0.4)
            if sim_delay > 0.005:
                time.sleep(sim_delay)

            self.capture_completed.emit(times, ch_data, self._metadata)
        else:
            finite_task = None
            try:
                logger.info(
                    "Starting hardware pulse capture (%d channels, %d samples, %.2f ms)",
                    num_ch, num_samples, self._duration_s * 1000.0
                )
                finite_task = nidaqmx.Task()

                for ch in self._channels:
                    finite_task.ai_channels.add_ai_voltage_chan(
                        physical_channel=ch,
                        terminal_config=TerminalConfiguration.DIFF,
                        min_val=-10.0,
                        max_val=10.0,
                        units=VoltageUnits.VOLTS,
                    )

                finite_task.timing.cfg_samp_clk_timing(
                    rate=self._sample_rate,
                    active_edge=Edge.RISING,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=num_samples,
                )

                if self._trigger_source and self._trigger_source.strip().lower() != "none":
                    finite_task.triggers.start_trigger.cfg_dig_edge_start_trig(
                        trigger_source=self._trigger_source.strip(),
                        trigger_edge=Edge.RISING,
                    )

                reader = AnalogMultiChannelReader(finite_task.in_stream)
                data_buf = np.zeros((num_ch, num_samples), dtype=np.float64)
                finite_task.start()

                timeout = max(5.0, self._duration_s * 2.0 + 3.0)
                reader.read_many_sample(
                    data_buf,
                    number_of_samples_per_channel=num_samples,
                    timeout=timeout,
                )

                times = np.arange(num_samples, dtype=np.float64) * dt
                ch_data = {
                    self._channels[i]: data_buf[i].copy() for i in range(num_ch)
                }

                finite_task.stop()
                finite_task.close()
                finite_task = None

                self.capture_completed.emit(times, ch_data, self._metadata)

            except Exception as exc:
                if finite_task:
                    try:
                        finite_task.close()
                    except Exception:
                        pass
                msg = f"Hardware pulse capture error: {exc}"
                logger.error(msg)
                self.capture_error.emit(msg)


# ────────────────────────────────────────────────────────────────────────
#  Main Analog Input Controller
# ────────────────────────────────────────────────────────────────────────

class AIController(QObject):
    """High-level NI-DAQmx Analog Input Controller.

    Manages hardware AI task creation, streaming, and channel routing.
    """

    initialized = Signal()
    started = Signal()
    stopped = Signal()
    error_occurred = Signal(str)
    status_changed = Signal(str)
    data_received = Signal(object, object)  # (times_np, channel_dict)
    pulse_captured = Signal(object, object, object, str)  # (times, channel_data, metadata, csv_filepath)

    DEFAULT_DEVICE = "PXI2Slot4"  # Default slot for upcoming AI card
    DEFAULT_TRIGGER = "/PXI2Slot3/PXI_Trig0"

    def __init__(self, device_name: str = DEFAULT_DEVICE, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._device_name = device_name
        self._available_devices: List[Dict[str, Any]] = []
        self._ai_channels: List[str] = []
        self._active_channels: List[str] = []
        self._task: Optional[nidaqmx.Task] = None
        self._worker: Optional[AIAcquisitionWorker] = None
        self._pulse_worker: Optional[AIPulseCaptureWorker] = None
        self._latest_pulse_capture: Optional[Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, Any], str]] = None
        self._sample_rate: float = 500000.0  # 500 kS/s default
        self._is_initialized = False
        self._is_running = False
        self.simulation_mode = False

        logger.info("AIController created  default_device=%s", self._device_name)

    # ── Device Discovery ────────────────────────────────────────────────

    @classmethod
    def discover_ai_devices(cls) -> List[Dict[str, Any]]:
        """Scan system for all NI-DAQmx devices equipped with Analog Input channels.

        Returns
        -------
        list of dict:
            [{'name': 'PXI2Slot4', 'product_type': 'PXI-6115', 'ai_channels': ['PXI2Slot4/ai0', ...], ...}]
        """
        results = []
        try:
            system = nidaqmx.system.System.local()
            for dev in system.devices:
                ai_chans = [ch.name for ch in dev.ai_physical_chans]
                if len(ai_chans) > 0:
                    results.append({
                        "name": dev.name,
                        "product_type": getattr(dev, "product_type", "Unknown NI AI Device"),
                        "ai_channels": ai_chans,
                        "num_ai": len(ai_chans),
                        "bus_type": str(getattr(dev, "bus_type", "")),
                    })
        except Exception as exc:
            logger.warning("Error scanning for NI-DAQmx AI devices: %s", exc)
        return results

    # ── Initialisation ──────────────────────────────────────────────────

    def initialize(self, device_name: Optional[str] = None, allow_simulation: bool = True) -> bool:
        """Initialize and verify the Analog Input device.

        If physical device is not present and *allow_simulation* is True,
        falls back to simulation mode with 8 virtual channels (ai0-ai7).
        """
        if device_name:
            self._device_name = device_name

        self._available_devices = self.discover_ai_devices()

        # If not explicitly simulation mode, check if device exists
        if not self.simulation_mode:
            target = next((d for d in self._available_devices if d["name"] == self._device_name), None)
            if target:
                self._ai_channels = target["ai_channels"]
                self.simulation_mode = False
                self._is_initialized = True
                msg = f"AI Device '{self._device_name}' ({target['product_type']}) initialized with {len(self._ai_channels)} AI channels."
                logger.info(msg)
                self.status_changed.emit(msg)
                self.initialized.emit()
                return True
            else:
                # If any other AI device was discovered, offer the first one
                if self._available_devices:
                    first = self._available_devices[0]
                    self._device_name = first["name"]
                    self._ai_channels = first["ai_channels"]
                    self.simulation_mode = False
                    self._is_initialized = True
                    msg = f"AI Device '{self._device_name}' ({first['product_type']}) auto-selected."
                    logger.info(msg)
                    self.status_changed.emit(msg)
                    self.initialized.emit()
                    return True

        # Fallback to simulation mode
        if allow_simulation:
            self.simulation_mode = True
            self._ai_channels = [f"{self._device_name}/ai{i}" for i in range(8)]
            self._is_initialized = True
            msg = f"AI Device '{self._device_name}' running in Simulation Mode (8 channels)."
            logger.info(msg)
            self.status_changed.emit(msg)
            self.initialized.emit()
            return True

        self.error_occurred.emit(f"No Analog Input card found for '{self._device_name}'.")
        return False

    # ── Task Configuration ──────────────────────────────────────────────

    def configure_ai_task(
        self,
        channels: Optional[List[str]] = None,
        sample_rate_hz: float = 500000.0,
        min_v: float = -10.0,
        max_v: float = 10.0,
        terminal_config: str = "DIFF",
        trigger_source: Optional[str] = None,
        trigger_edge: str = "RISING",
    ) -> bool:
        """Create and configure the NI-DAQmx Analog Input task.

        Parameters
        ----------
        channels : list of str, optional
            Physical channels e.g. ['PXI2Slot4/ai0', 'PXI2Slot4/ai1']. Defaults to first 4 channels.
        sample_rate_hz : float
            Sampling rate in Hz (e.g. 500,000 for 500 kS/s).
        min_v, max_v : float
            Expected voltage limits (-10V to +10V).
        terminal_config : str
            'DIFF' (Differential), 'RSE' (Referenced Single-Ended), 'NRSE', or 'DEFAULT'.
        trigger_source : str, optional
            PXI trigger source line (e.g. '/PXI2Slot3/PXI_Trig0') or None for free-run.
        trigger_edge : str
            'RISING' or 'FALLING'.
        """
        self.stop_acquisition()
        self.clear_task()

        self._active_channels = channels or self._ai_channels[:4]
        self._sample_rate = float(sample_rate_hz)

        if self.simulation_mode:
            logger.info("Configured simulated AI task on channels: %s (%.1f kS/s)", self._active_channels, self._sample_rate / 1000.0)
            return True

        try:
            task = nidaqmx.Task()

            # Map terminal configuration string to nidaqmx constant
            t_cfg = TerminalConfiguration.DIFF
            u_cfg = (terminal_config or "").upper()
            if "RSE" in u_cfg and "NRSE" not in u_cfg:
                t_cfg = TerminalConfiguration.RSE
            elif "NRSE" in u_cfg:
                t_cfg = TerminalConfiguration.NRSE
            elif "DEFAULT" in u_cfg:
                t_cfg = TerminalConfiguration.DEFAULT

            for ch in self._active_channels:
                task.ai_channels.add_ai_voltage_chan(
                    physical_channel=ch,
                    terminal_config=t_cfg,
                    min_val=min_v,
                    max_val=max_v,
                    units=VoltageUnits.VOLTS,
                )

            # Configure sample clock timing (continuous circular buffer)
            buffer_samples = max(2000, int(self._sample_rate * 0.1))  # 100ms buffer
            task.timing.cfg_samp_clk_timing(
                rate=self._sample_rate,
                active_edge=Edge.RISING,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=buffer_samples,
            )

            # Configure hardware start trigger if requested
            if trigger_source and trigger_source.strip() and trigger_source.lower() != "none":
                edge = Edge.RISING if trigger_edge.upper() == "RISING" else Edge.FALLING
                task.triggers.start_trigger.cfg_dig_edge_start_trig(
                    trigger_source=trigger_source.strip(),
                    trigger_edge=edge,
                )
                logger.info("AI hardware start trigger configured: %s (%s edge)", trigger_source, trigger_edge)

            self._task = task
            logger.info("Configured NI-DAQmx AI task with %d channels on %s", len(self._active_channels), self._device_name)
            return True

        except Exception as exc:
            try:
                task.close()
            except Exception:
                pass
            msg = f"Failed to configure NI-DAQmx AI task: {exc}"
            # Check if physical device is absent from chassis
            if "200477" in str(exc) or "not present" in str(exc).lower() or "no devices" in str(exc).lower():
                logger.warning("Physical AI device not present in chassis (%s); auto-switching to simulation mode.", exc)
                self.simulation_mode = True
                self.clear_task()
                self.status_changed.emit("Device not in chassis; switched to simulated AI mode.")
                return True

            logger.error(msg)
            self.error_occurred.emit(msg)
            self.clear_task()
            return False

    # ── Acquisition Control ─────────────────────────────────────────────

    def start_acquisition(self, chunk_size: int = 1000):
        """Start continuous background acquisition streaming to the oscilloscope."""
        if self._is_running:
            return

        if not self._active_channels or (not self.simulation_mode and not self._task):
            self.configure_ai_task()

        try:
            is_sim = self.simulation_mode or (self._task is None)
            if not is_sim and self._task:
                self._task.start()

            self._worker = AIAcquisitionWorker(
                task=self._task,
                channels=self._active_channels,
                sample_rate=self._sample_rate,
                chunk_size=chunk_size,
                is_simulated=is_sim,
            )
            self._worker.data_chunk_ready.connect(self._on_chunk_ready)
            self._worker.acquisition_error.connect(self.error_occurred.emit)
            self._worker.start()

            self._is_running = True
            self.started.emit()
            self.status_changed.emit("AI Acquisition Running")
            logger.info("AI Acquisition started successfully.")

        except Exception as exc:
            msg = f"Error starting AI acquisition: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)

    def stop_acquisition(self):
        """Stop background acquisition streaming."""
        if self._worker:
            self._worker.stop()
            self._worker = None

        if self._task and not self.simulation_mode:
            try:
                self._task.stop()
            except Exception:
                pass

        if self._is_running:
            self._is_running = False
            self.stopped.emit()
            self.status_changed.emit("AI Acquisition Stopped")
            logger.info("AI Acquisition stopped.")

    def clear_task(self):
        """Close and release DAQmx task resources."""
        if self._task:
            try:
                self._task.close()
            except Exception:
                pass
            self._task = None

    def _on_chunk_ready(self, times: np.ndarray, channel_data: Dict[str, np.ndarray]):
        self.data_received.emit(times, channel_data)

    def is_running(self) -> bool:
        return self._is_running

    def get_channels(self) -> List[str]:
        return list(self._ai_channels)

    # ── Pulse-Gated Capture & CSV Export ────────────────────────────────

    def start_pulse_capture(
        self,
        channels: Optional[List[str]] = None,
        duration_s: float = 0.020,
        sample_rate_hz: float = 500000.0,
        trigger_source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        auto_export_csv: bool = True,
        csv_dir: Optional[str] = None,
    ):
        """Start a pulse-gated capture for the exact duration the pulse is active."""
        if self._pulse_worker and self._pulse_worker.isRunning():
            logger.warning("Pulse capture already in progress.")
            return

        active_chans = channels or ([self._ai_channels[0]] if self._ai_channels else [f"{self._device_name}/ai0"])
        meta = metadata.copy() if metadata else {}
        meta.setdefault("gate_source", "DIO Pulse Gate")
        meta.setdefault("duration_ms", duration_s * 1000.0)
        meta.setdefault("sample_rate", sample_rate_hz)
        meta.setdefault("channels", active_chans)
        meta["auto_export_csv"] = auto_export_csv
        meta["csv_dir"] = csv_dir

        is_sim = self.simulation_mode or (self._task is None)

        self._pulse_worker = AIPulseCaptureWorker(
            task=self._task,
            channels=active_chans,
            sample_rate=sample_rate_hz,
            duration_s=duration_s,
            trigger_source=trigger_source,
            is_simulated=is_sim,
            metadata=meta,
        )
        self._pulse_worker.capture_completed.connect(self._on_pulse_capture_done)
        self._pulse_worker.capture_error.connect(self.error_occurred.emit)
        self._pulse_worker.start()
        self.status_changed.emit(f"Capturing pulse on {active_chans[0]} ({duration_s*1e3:.2f} ms)...")

    def _on_pulse_capture_done(self, times: np.ndarray, channel_data: Dict[str, np.ndarray], metadata: dict):
        csv_path = ""
        if metadata.get("auto_export_csv", True):
            csv_dir = metadata.get("csv_dir") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
            timestamp_str = time.strftime("%Y%m%d_%H%M%S")
            primary_ch = list(channel_data.keys())[0].split("/")[-1].upper()
            filename = f"gated_capture_{primary_ch}_{timestamp_str}.csv"
            filepath = os.path.join(csv_dir, filename)
            try:
                csv_path = self.export_to_csv(filepath, times, channel_data, metadata)
                logger.info("Auto-exported pulse capture to: %s", csv_path)
            except Exception as exc:
                logger.error("Failed to auto-export pulse capture CSV: %s", exc)

        self._latest_pulse_capture = (times, channel_data, metadata, csv_path)
        self.pulse_captured.emit(times, channel_data, metadata, csv_path)
        self.status_changed.emit(f"Pulse capture completed ({len(times)} samples).")

    @staticmethod
    def export_to_csv(
        filepath: str,
        times: np.ndarray,
        channel_data: Dict[str, np.ndarray],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Export captured pulse data to a CSV file with laboratory metadata header."""
        meta = metadata or {}
        abs_path = os.path.abspath(filepath)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        with open(abs_path, "w", newline="", encoding="utf-8") as f:
            f.write("# lab18b daq - Pulse-Gated Analog Input Capture\n")
            f.write(f"# Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            if "gate_source" in meta:
                f.write(f"# Gate Source: {meta['gate_source']}\n")
            if "duration_ms" in meta:
                f.write(f"# Pulse Duration: {meta['duration_ms']:.4f} ms\n")
            if "sample_rate" in meta:
                f.write(f"# Sample Rate: {meta['sample_rate']:.1f} Hz\n")
            f.write(f"# Total Samples: {len(times)}\n")
            f.write("# --------------------------------------------------\n")

            import csv
            writer = csv.writer(f)
            ch_keys = list(channel_data.keys())
            col_names = []
            for k in ch_keys:
                clean = k.split("/")[-1].upper()
                col_names.append(f"{clean}_V")

            headers = ["Time_s", "Time_ms"] + col_names
            writer.writerow(headers)

            for i in range(len(times)):
                t_s = times[i]
                t_ms = t_s * 1000.0
                row = [f"{t_s:.9f}", f"{t_ms:.6f}"] + [f"{channel_data[k][i]:.6f}" for k in ch_keys]
                writer.writerow(row)

        return abs_path

    def get_latest_pulse_capture(self) -> Optional[Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, Any], str]]:
        """Return the most recent captured pulse tuple: (times, channel_data, metadata, csv_filepath)."""
        return self._latest_pulse_capture
