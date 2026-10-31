"""
DAQ Controller Module
=====================
Manages NI-DAQmx analog output tasks for waveform generation.
Supports hardware-triggered finite waveforms synchronised with the FPGA
digital sequence via PXI trigger lines.
"""

from __future__ import annotations

from typing import Dict, List, Optional
import time

import numpy as np
from PySide6.QtCore import QObject, Signal
import nidaqmx
from nidaqmx.constants import AcquisitionType, Edge
from nidaqmx.stream_writers import (
    AnalogSingleChannelWriter,
    AnalogMultiChannelWriter,
)

from sequence_model import (
    AnalogEvent,
    TriggerEdge,
    ExperimentSequence,
    FPGA_CLOCK_HZ,
)
from waveform_generator import generate_waveform
from logging_utils import get_app_logger

logger = get_app_logger(__name__)


class DAQController(QObject):
    """Controller for NI-DAQmx analog output on a PXI chassis slot.

    Manages one or more finite-sample AO tasks that can be hardware-
    triggered so their output is precisely synchronised with FPGA-driven
    digital TTL lines.
    """

    # ── Qt Signals ──────────────────────────────────────────────────────
    initialized = Signal()
    armed = Signal()
    completed = Signal()
    error_occurred = Signal(str)
    status_changed = Signal(str)
    trigger_count_changed = Signal(int)

    # ── Hardware defaults ───────────────────────────────────────────────
    DEFAULT_DEVICE = "PXI2Slot3"
    DEFAULT_TRIGGER = "/PXI2Slot3/PXI_Trig0"

    # ── Construction ────────────────────────────────────────────────────
    def __init__(
        self,
        device_name: str = DEFAULT_DEVICE,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_name = device_name
        self._ao_channels: List[str] = []
        self._tasks: Dict[str, nidaqmx.Task] = {}
        self._master_task: Optional[nidaqmx.Task] = None
        self._active_channel_names: List[str] = []
        self._is_initialized = False
        self._trigger_count = 0
        self.simulation_mode = False
        logger.info("DAQController created  device=%s", self._device_name)

    # ── Initialisation ──────────────────────────────────────────────────
    def initialize(self, allow_simulation: bool = True) -> bool:
        """Verify the device exists and discover available AO channels.

        If physical hardware is unavailable and *allow_simulation* is True,
        initializes virtual channels ao0-ao7 for simulation.

        Returns
        -------
        bool
            ``True`` if the device was found and AO channels discovered.
        """
        if self.simulation_mode:
            self._ao_channels = [f"{self._device_name}/ao{i}" for i in range(8)]
            self._is_initialized = True
            logger.info("DAQ initialized in Simulation Mode (8 virtual channels).")
            self.status_changed.emit("DAQ initialized (Simulated)")
            self.initialized.emit()
            return True

        try:
            logger.info("Initializing DAQ device %s …", self._device_name)
            system = nidaqmx.system.System.local()

            # Check that the device is present
            device_names = [d.name for d in system.devices]
            if self._device_name not in device_names:
                if allow_simulation:
                    logger.warning(
                        "Device '%s' not found. Falling back to Simulation Mode (8 virtual channels).",
                        self._device_name,
                    )
                    self._ao_channels = [f"{self._device_name}/ao{i}" for i in range(8)]
                    self._is_initialized = True
                    self.status_changed.emit("DAQ initialized (Simulated)")
                    self.initialized.emit()
                    return True

                msg = (
                    f"Device '{self._device_name}' not found. "
                    f"Available devices: {device_names}"
                )
                logger.error(msg)
                self.error_occurred.emit(msg)
                return False

            # Discover AO channels
            device = system.devices[self._device_name]
            self._ao_channels = [
                ch.name for ch in device.ao_physical_chans
            ]
            logger.info(
                "DAQ initialized – %d AO channels: %s",
                len(self._ao_channels),
                self._ao_channels,
            )
            self._is_initialized = True
            self.status_changed.emit("DAQ initialized")
            self.initialized.emit()
            return True
        except Exception as exc:
            if allow_simulation:
                logger.warning(
                    "DAQ initialization exception (%s). Falling back to Simulation Mode.", exc
                )
                self._ao_channels = [f"{self._device_name}/ao{i}" for i in range(8)]
                self._is_initialized = True
                self.status_changed.emit("DAQ initialized (Simulated)")
                self.initialized.emit()
                return True

            msg = f"Failed to initialize DAQ: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)
            return False

    # ── Channel discovery & trigger mapping ─────────────────────────────
    def get_ao_channels(self) -> List[str]:
        """Return the list of available AO physical channel names."""
        return list(self._ao_channels)

    def get_default_trigger_for_channel(self, channel: str) -> str:
        """Return the default PXI trigger line for an AO channel.

        Supported PXI trigger lines on PXI-6733 are PXI_Trig0 through PXI_Trig5.
        Channels 0-5 map to PXI_Trig0..PXI_Trig5.
        Channels 6-7 map to PXI_Trig0 (the primary PXI trigger line).
        """
        import re
        match = re.search(r"ao(\d+)", channel, re.IGNORECASE)
        ch_num = int(match.group(1)) if match else 0

        device = self._device_name
        if "/" in channel:
            parts = channel.strip("/").split("/")
            if len(parts) > 1:
                device = parts[0]

        # Valid trigger lines on PXI-6733 are PXI_Trig0 through PXI_Trig5
        trig_idx = ch_num if ch_num <= 5 else 0
        return f"/{device}/PXI_Trig{trig_idx}"

    def has_active_tasks(self) -> bool:
        """Return True if any hardware AO tasks are currently configured."""
        if self.simulation_mode:
            return False
        if self._master_task is not None:
            return True
        return any(t is not None for t in self._tasks.values())

    # ── Task configuration ──────────────────────────────────────────────
    def configure_sequence_tasks(
        self,
        sequence: ExperimentSequence,
        clock_hz: int = FPGA_CLOCK_HZ,
    ) -> bool:
        """Create and configure a unified multi-channel AO task for all enabled channels.

        Hardware architecture of NI PXI-6733:
        All simultaneously active AO channels on the same device must be in a single
        NI-DAQmx Task to share the internal sample clock and trigger engine without
        resource reservation conflicts (-50103, -89137).
        """
        self.clear_all_tasks()

        enabled_events = [ev for ev in sequence.analog_events if ev.enabled]
        if not enabled_events:
            logger.info("No enabled analog events in sequence; AO task skipped.")
            return True

        if self.simulation_mode:
            self._active_channel_names = [ev.channel for ev in enabled_events]
            logger.info(
                "Configured simulated sequence AO on %d channels: %s",
                len(self._active_channel_names), self._active_channel_names
            )
            self.status_changed.emit(f"AO sequence configured (Simulated): {len(self._active_channel_names)} channels")
            return True

        task = None
        try:
            # Use anonymous Task to completely eliminate task name collision errors (-200089)
            task = nidaqmx.Task()

            # Add each enabled physical channel to the unified task
            for ev in enabled_events:
                task.ao_channels.add_ao_voltage_chan(
                    ev.channel,
                    min_val=ev.min_voltage,
                    max_val=ev.max_voltage,
                )

            # Determine master sample rate and total sequence duration
            sample_rate = max(getattr(ev, "sample_rate_hz", 500000.0) for ev in enabled_events)
            duration_s = max(0.0001, sequence.sequence_duration_ticks / clock_hz)
            num_samples = max(2, int(round(duration_s * sample_rate)))

            times = np.linspace(0, duration_s, num_samples, endpoint=False)
            data_2d = np.zeros((len(enabled_events), num_samples), dtype=np.float64)

            # Synthesize each channel's waveform into its corresponding active window
            for idx, ev in enumerate(enabled_events):
                st_s = getattr(ev, "start_ms", 0.0) / 1000.0
                dur_ms = getattr(ev, "duration_ms", 10.0)
                end_s = getattr(ev, "end_ms", st_s + dur_ms) / 1000.0

                mask = (times >= st_s) & (times <= end_s)
                n_pts = int(np.count_nonzero(mask))
                if n_pts > 0:
                    ev_copy = AnalogEvent(**ev.__dict__)
                    ev_copy.num_samples = n_pts
                    ev_copy.duration_ms = max(0.000025, (end_s - st_s) * 1000.0)
                    data_2d[idx, mask] = generate_waveform(ev_copy)

            # Configure sample clock timing across all channels
            task.timing.cfg_samp_clk_timing(
                rate=sample_rate,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=num_samples,
            )

            # Optional external hardware trigger: only configure if explicitly requested by an event
            ext_trigger_src = None
            ext_trigger_edge = Edge.RISING
            for ev in enabled_events:
                trig_src = getattr(ev, "trigger_source", "") or ""
                if getattr(ev, "triggered", False) and trig_src and trig_src.lower() not in ("none", "immediate", "none/immediate", "default"):
                    ext_trigger_src = trig_src
                    if getattr(ev, "trigger_edge", None) == TriggerEdge.FALLING:
                        ext_trigger_edge = Edge.FALLING
                    break

            if ext_trigger_src:
                task.triggers.start_trigger.cfg_dig_edge_start_trig(
                    trigger_source=ext_trigger_src,
                    trigger_edge=ext_trigger_edge,
                )
                logger.info("Configured external hardware start trigger: %s (%s)", ext_trigger_src, ext_trigger_edge.name)
            else:
                logger.debug("Unified AO task configured for synchronous software start.")

            # Write buffer: NI-DAQmx strictly requires 1D array for 1 channel, and 2D array for multiple channels
            n_channels = len(enabled_events)
            if n_channels == 1:
                writer = AnalogSingleChannelWriter(task.out_stream, auto_start=False)
                waveform_1d = np.ascontiguousarray(data_2d[0], dtype=np.float64)
                if waveform_1d.ndim != 1:
                    waveform_1d = waveform_1d.ravel()
                writer.write_many_sample(waveform_1d)
            else:
                writer = AnalogMultiChannelWriter(task.out_stream, auto_start=False)
                waveform_2d = np.ascontiguousarray(data_2d, dtype=np.float64)
                if waveform_2d.ndim != 2:
                    waveform_2d = np.atleast_2d(waveform_2d)
                writer.write_many_sample(waveform_2d)

            self._master_task = task
            self._active_channel_names = [ev.channel for ev in enabled_events]
            for ev in enabled_events:
                self._tasks[ev.channel] = task

            msg = f"Configured unified AO task on {len(enabled_events)} channel(s): {self._active_channel_names}"
            logger.info(msg)
            self.status_changed.emit(msg)
            return True

        except Exception as exc:
            if task is not None:
                try:
                    task.close()
                except Exception:
                    pass
            self._master_task = None

            # Automatic recovery for resource reservation conflict (-50103)
            if "-50103" in str(exc) and not getattr(self, "_in_retry", False):
                logger.warning("Resource reserved (-50103); resetting device %s and retrying...", self._device_name)
                try:
                    self._in_retry = True
                    dev = nidaqmx.system.Device(self._device_name)
                    dev.reset_device()
                    time.sleep(0.05)
                    return self.configure_sequence_tasks(sequence, clock_hz)
                except Exception as retry_exc:
                    logger.error("Device reset retry failed: %s", retry_exc)
                finally:
                    self._in_retry = False

            msg = f"Failed to configure unified AO task: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)
            raise RuntimeError(msg) from exc

    def configure_analog_task(
        self,
        event: AnalogEvent,
        waveform_data: np.ndarray,
    ) -> None:
        """Create and configure a single AO task for one :class:`AnalogEvent`.

        Note: When running multi-channel sequences, use configure_sequence_tasks
        to combine all channels into a unified task.
        """
        channel = event.channel
        task = None
        try:
            # Clean up any previous task on the same channel
            if channel in self._tasks and self._tasks[channel] is not None:
                logger.debug("Closing previous task on %s", channel)
                try:
                    self._tasks[channel].stop()
                except Exception:
                    pass
                try:
                    self._tasks[channel].close()
                except Exception:
                    pass
                del self._tasks[channel]

            rate_val = getattr(
                event, "sample_rate_hz", getattr(event, "sample_rate", 500000.0)
            )

            logger.info(
                "Configuring AO task  channel=%s  samples=%d  rate=%.1f Hz",
                channel,
                len(waveform_data),
                rate_val,
            )

            if self.simulation_mode:
                self._tasks[channel] = None
                self.status_changed.emit(f"AO task configured (Simulated): {channel}")
                return

            # Use anonymous Task to completely eliminate task name collision errors (-200089)
            task = nidaqmx.Task()

            # Add the voltage channel
            task.ao_channels.add_ao_voltage_chan(
                channel,
                min_val=event.min_voltage,
                max_val=event.max_voltage,
            )

            # Configure finite-sample clock timing
            task.timing.cfg_samp_clk_timing(
                rate=rate_val,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=len(waveform_data),
            )

            # Configure hardware trigger if requested
            is_triggered = (
                getattr(event, "generation_mode", "triggered") == "triggered"
                or getattr(event, "triggered", False)
            )
            trig_src = getattr(event, "trigger_source", "") or ""
            if trig_src.lower() in ("none", "none/immediate", "immediate"):
                is_triggered = False

            if is_triggered:
                # Default to corresponding PXI_Trig{N} if not specified
                if not trig_src or trig_src.lower() in ("default", ""):
                    trigger_source = self.get_default_trigger_for_channel(channel)
                else:
                    trigger_source = trig_src

                # Check if hardware supports this trigger line (PXI-6733 only supports PXI_Trig0..PXI_Trig5)
                if "PXI_Trig6" in trigger_source or "PXI_Trig7" in trigger_source:
                    fallback_trig = f"/{self._device_name}/PXI_Trig0"
                    logger.warning(
                        "Trigger line %s is not supported on %s; auto-routing to %s",
                        trigger_source, channel, fallback_trig
                    )
                    trigger_source = fallback_trig

                edge = (
                    Edge.FALLING
                    if event.trigger_edge == TriggerEdge.FALLING
                    else Edge.RISING
                )
                task.triggers.start_trigger.cfg_dig_edge_start_trig(
                    trigger_source=trigger_source,
                    trigger_edge=edge,
                )
                logger.info(
                    "  Hardware trigger configured: %s on %s (%s edge)",
                    channel, trigger_source, edge.name
                )

            # Write waveform data to the task buffer
            if not self.simulation_mode:
                writer = AnalogSingleChannelWriter(task.out_stream)
                writer.write_many_sample(waveform_data)
                logger.debug("  Waveform data written to buffer.")

            self._tasks[channel] = task
            self.status_changed.emit(f"AO task configured: {channel}")
        except Exception as exc:
            if task is not None:
                try:
                    task.close()
                except Exception:
                    pass
            if self.simulation_mode:
                self._tasks[channel] = None
                self.status_changed.emit(f"AO task configured (Simulated): {channel}")
                return
            msg = f"Failed to configure AO task for {channel}: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)
            raise RuntimeError(msg) from exc

    # ── Arming / execution ──────────────────────────────────────────────
    def arm_all_tasks(self) -> None:
        """Start (arm) all configured tasks so they wait for triggers."""
        if self.simulation_mode:
            logger.info("Arming analog tasks (Simulated Mode) …")
            self.status_changed.emit("Analog tasks armed (Simulated)")
            self.armed.emit()
            return

        try:
            if self._master_task is not None:
                logger.info("Arming unified analog task on %d channel(s) …", len(self._active_channel_names))
                try:
                    self._master_task.stop()
                except Exception:
                    pass
                self._master_task.start()
            elif self._tasks:
                logger.info("Arming %d analog task(s) …", len(self._tasks))
                for channel, task in self._tasks.items():
                    if task is not None:
                        try:
                            task.stop()
                        except Exception:
                            pass
                        task.start()
                        logger.debug("  Armed: %s", channel)
            else:
                logger.warning("arm_all_tasks called but no tasks configured.")
                return

            self._trigger_count = 0
            self.status_changed.emit("Analog tasks armed")
            self.armed.emit()
        except Exception as exc:
            msg = f"Failed to arm analog tasks: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)
            raise

    def wait_for_completion(self, timeout_s: float = 60.0) -> bool:
        """Block until all armed tasks finish or *timeout_s* elapses."""
        if self.simulation_mode:
            import time
            time.sleep(0.02)
            self._trigger_count += 1
            self.trigger_count_changed.emit(self._trigger_count)
            self.status_changed.emit("Analog output completed (Simulated)")
            self.completed.emit()
            return True

        if self._master_task is None and not self._tasks:
            return True

        try:
            if self._master_task is not None:
                self._master_task.wait_until_done(timeout=timeout_s)
            else:
                for channel, task in self._tasks.items():
                    if task is not None:
                        task.wait_until_done(timeout=timeout_s)

            self._trigger_count += 1
            self.trigger_count_changed.emit(self._trigger_count)
            self.status_changed.emit("Analog output completed")
            self.completed.emit()
            return True
        except Exception as exc:
            msg = f"Timeout or error waiting for AO completion: {exc}"
            logger.error(msg)
            self.error_occurred.emit(msg)
            return False

    # ── Stop / cleanup ──────────────────────────────────────────────────
    def stop_all_tasks(self) -> None:
        """Stop all running tasks without closing them."""
        if self._master_task is not None:
            try:
                self._master_task.stop()
            except Exception as exc:
                logger.warning("Error stopping master AO task: %s", exc)
        for channel, task in self._tasks.items():
            if task is not None and task is not self._master_task:
                try:
                    task.stop()
                    logger.debug("Stopped task: %s", channel)
                except Exception as exc:
                    logger.warning("Error stopping task %s: %s", channel, exc)
        self.status_changed.emit("Analog tasks stopped")

    def clear_all_tasks(self) -> None:
        """Stop and close all tasks, releasing hardware resources."""
        all_unique_tasks = set()
        if self._master_task is not None:
            all_unique_tasks.add(self._master_task)
            self._master_task = None
        for task in self._tasks.values():
            if task is not None:
                all_unique_tasks.add(task)
        self._tasks.clear()
        self._active_channel_names.clear()

        for task in all_unique_tasks:
            try:
                task.stop()
            except Exception:
                pass
            try:
                task.close()
            except Exception as exc:
                logger.warning("Error closing AO task: %s", exc)

        if all_unique_tasks:
            time.sleep(0.10)  # Allow hardware driver to finalize handle release

        self.status_changed.emit("Analog tasks cleared")
        logger.info("All analog tasks cleared.")

    def safe_state(self, voltage: float = 0.0) -> None:
        """Drive all known AO channels to a safe voltage in a single unified operation."""
        if self.simulation_mode:
            logger.info("  [Simulated] Safe voltage %.2f V set on all channels.", voltage)
            return
        if not self._ao_channels:
            logger.warning("safe_state: no AO channels discovered.")
            return

        self.clear_all_tasks()

        logger.info(
            "Setting safe state: %.3f V on %d channel(s)",
            voltage,
            len(self._ao_channels),
        )
        try:
            with nidaqmx.Task() as task:
                for channel in self._ao_channels:
                    task.ao_channels.add_ao_voltage_chan(channel)
                task.write([voltage] * len(self._ao_channels))
            logger.debug("Safe state successfully set: %.3f V on all channels.", voltage)
        except Exception as exc:
            logger.warning("Standard safe state write encountered: %s; attempting device reset...", exc)
            try:
                dev = nidaqmx.system.Device(self._device_name)
                dev.reset_device()
                time.sleep(0.15)
                with nidaqmx.Task() as task:
                    for channel in self._ao_channels:
                        task.ao_channels.add_ao_voltage_chan(channel)
                    task.write([voltage] * len(self._ao_channels))
                logger.info("Safe state successfully set after device reset.")
            except Exception as exc2:
                msg = f"Failed to set safe state: {exc2}"
                logger.warning(msg)
                self.error_occurred.emit(msg)
        self.status_changed.emit("Safe state set")

    # ── Device info ─────────────────────────────────────────────────────
    def get_device_info(self) -> dict:
        """Return a dictionary of device metadata.

        Returns
        -------
        dict
            Keys: ``device_name``, ``serial_number``, ``product_type``,
            ``num_ao_channels``.
        """
        info: dict = {
            "device_name": self._device_name,
            "serial_number": "",
            "product_type": "",
            "num_ao_channels": len(self._ao_channels),
        }
        try:
            system = nidaqmx.system.System.local()
            device = system.devices[self._device_name]
            info["serial_number"] = str(getattr(device, "serial_num", ""))
            info["product_type"] = str(getattr(device, "product_type", ""))
        except Exception as exc:
            msg = f"Failed to query device info: {exc}"
            logger.warning(msg)
            self.error_occurred.emit(msg)
        return info
