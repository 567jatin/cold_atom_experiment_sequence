"""
Synchronization Module
======================
Orchestrates the deterministic execution of an experiment sequence,
coordinating the FPGA digital controller and the DAQmx analog controller
so that analog waveforms are armed *before* the FPGA begins generating
trigger pulses.

Execution runs in a dedicated :class:`QThread` via the
:class:`ExecutionWorker` to keep the GUI responsive.
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from fpga_controller import FPGAController
from daq_controller import DAQController
from sequence_model import (
    ExperimentSequence,
    RepeatMode,
    ValidationMessage,
    validate,
    FPGA_CLOCK_HZ,
)
from waveform_generator import generate_waveform
from logging_utils import get_app_logger

logger = get_app_logger(__name__)


# ────────────────────────────────────────────────────────────────────────
#  Execution Worker
# ────────────────────────────────────────────────────────────────────────
class ExecutionWorker(QObject):
    """Worker that runs in a :class:`QThread` for non-blocking execution.

    The deterministic execution order is:

    1. Validate the sequence
    2. Initialise hardware, set safe state
    3. Configure FPGA registers
    4. Generate waveforms and configure analog tasks
    5. Arm analog tasks (so they wait for triggers)
    6. Start FPGA sequence
    7. Monitor completion (loop for repeat count or continuous)
    8. Stop FPGA and analog tasks
    9. Return to safe state
    """

    # ── Signals ─────────────────────────────────────────────────────────
    phase_changed = Signal(str)       # Current execution phase
    progress = Signal(int, int)       # current_cycle, total_cycles
    completed = Signal()
    error_occurred = Signal(str)
    elapsed_time = Signal(float)      # seconds
    trigger_count = Signal(int)

    def __init__(
        self,
        fpga: FPGAController,
        daq: DAQController,
        sequence: ExperimentSequence,
    ) -> None:
        super().__init__()
        self._fpga = fpga
        self._daq = daq
        self._sequence = sequence
        self._stop_event = threading.Event()
        self._trigger_counter = 0

    # ── Public API ──────────────────────────────────────────────────────
    def request_stop(self) -> None:
        """Thread-safe stop request."""
        logger.info("Stop requested by user.")
        self._stop_event.set()
        try:
            self._daq.stop_all_tasks()
        except Exception:
            pass
        try:
            self._fpga.stop()
        except Exception:
            pass

    # ── Main execution ──────────────────────────────────────────────────
    def run(self) -> None:  # noqa: C901  (complexity unavoidable in orchestrator)
        """Execute the full deterministic experiment sequence."""
        t_start = time.perf_counter()
        try:
            # ── 1. Validate ─────────────────────────────────────────────
            self._set_phase("Validating")
            messages = validate(self._sequence)
            errors = [m for m in messages if m.level == "error"]
            if errors:
                error_text = "; ".join(m.message for m in errors)
                self.error_occurred.emit(f"Validation failed: {error_text}")
                return

            if self._stop_event.is_set():
                return

            # ── 2. Initialise hardware ──────────────────────────────────
            self._set_phase("Initializing")

            if not self._fpga.is_connected():
                if not self._fpga.connect():
                    self.error_occurred.emit("Failed to connect to FPGA.")
                    return

            if not self._daq.initialize():
                self.error_occurred.emit("Failed to initialize DAQ.")
                return

            # Set a known-safe starting state
            self._daq.safe_state(0.0)
            self._fpga.safe_state()

            if self._stop_event.is_set():
                return

            # ── 3. Configure FPGA registers ─────────────────────────────
            self._set_phase("Configuring FPGA")
            self._fpga.configure_sequence(self._sequence)

            if self._stop_event.is_set():
                return

            # ── 4. Generate & configure analog waveforms ────────────────
            self._set_phase("Configuring Analog")
            self._daq.clear_all_tasks()
            self._daq.configure_sequence_tasks(self._sequence, FPGA_CLOCK_HZ)

            if self._stop_event.is_set():
                return

            # ── Determine cycle parameters ──────────────────────────────
            repeat_mode = self._sequence.repeat_mode
            total_cycles: int = 1
            if repeat_mode == RepeatMode.COUNT:
                total_cycles = max(1, self._sequence.repeat_count)
            elif repeat_mode == RepeatMode.CONTINUOUS:
                total_cycles = 0  # 0 → unbounded

            cycle_duration_s = (
                self._sequence.sequence_duration_ticks / FPGA_CLOCK_HZ
            )

            # ── Cycle loop ──────────────────────────────────────────────
            cycle = 0
            while True:
                if self._stop_event.is_set():
                    break

                cycle += 1
                self.progress.emit(cycle, total_cycles)
                logger.info(
                    "Cycle %d / %s",
                    cycle,
                    total_cycles if total_cycles else "∞",
                )

                # ── 5. Arm analog tasks ─────────────────────────────────
                self._set_phase("Arming Analog")
                self._daq.arm_all_tasks()

                if self._stop_event.is_set():
                    break

                # ── 6. Start FPGA ───────────────────────────────────────
                self._set_phase("Running")
                cycle_start_time = time.perf_counter()
                self._fpga.start()

                # ── 7. Wait for completion ──────────────────────────────
                # A) If analog tasks are configured, wait for their completion
                if self._daq.has_active_tasks():
                    timeout = cycle_duration_s + 5.0  # generous margin
                    completed_ok = self._daq.wait_for_completion(
                        timeout_s=timeout
                    )
                    if not completed_ok and not self._stop_event.is_set():
                        self.error_occurred.emit(
                            f"Analog output did not complete within "
                            f"{timeout:.1f} s on cycle {cycle}."
                        )
                        break

                # B) Guarantee the full FPGA sequence cycle duration elapses!
                # Do NOT end early before sequence_duration_ticks has completed.
                while not self._stop_event.is_set():
                    elapsed_in_cycle = time.perf_counter() - cycle_start_time
                    if elapsed_in_cycle >= cycle_duration_s:
                        break
                    # Sleep in small slices so UI stop request is immediate
                    sleep_time = min(0.01, cycle_duration_s - elapsed_in_cycle)
                    time.sleep(sleep_time)

                if self._stop_event.is_set():
                    break

                self._trigger_counter += 1
                self.trigger_count.emit(self._trigger_counter)

                # Emit elapsed time
                self.elapsed_time.emit(time.perf_counter() - t_start)

                # Check if we should continue
                if repeat_mode == RepeatMode.SINGLE:
                    break
                if (
                    repeat_mode == RepeatMode.COUNT
                    and cycle >= total_cycles
                ):
                    break

                # Re-arm for next cycle: stop and clear tasks, then re-configure
                # so they return to the armed state for the next trigger.
                self._daq.stop_all_tasks()
                self._daq.clear_all_tasks()

                # For subsequent cycles, re-configure unified analog task
                self._daq.configure_sequence_tasks(self._sequence, FPGA_CLOCK_HZ)

            # ── 8. Stop hardware ────────────────────────────────────────
            self._set_phase("Stopping")
            self._fpga.stop()
            self._daq.stop_all_tasks()
            self._daq.clear_all_tasks()

            # ── 9. Safe state ───────────────────────────────────────────
            self._set_phase("Safe State")
            self._daq.safe_state(0.0)
            self._fpga.safe_state()

            self._set_phase("Complete")
            self.elapsed_time.emit(time.perf_counter() - t_start)
            self.completed.emit()
            logger.info(
                "Sequence execution finished after %.2f s.",
                time.perf_counter() - t_start,
            )

        except Exception as exc:
            msg = f"Execution error: {exc}"
            logger.exception(msg)
            self.error_occurred.emit(msg)
            # Best-effort cleanup
            try:
                self._fpga.safe_state()
            except Exception:
                pass
            try:
                self._daq.clear_all_tasks()
                self._daq.safe_state(0.0)
            except Exception:
                pass

    # ── Private helpers ─────────────────────────────────────────────────
    def _set_phase(self, phase: str) -> None:
        logger.info("Phase → %s", phase)
        self.phase_changed.emit(phase)


# ────────────────────────────────────────────────────────────────────────
#  Synchronization Manager
# ────────────────────────────────────────────────────────────────────────
class SynchronizationManager(QObject):
    """High-level orchestrator for experiment execution.

    Launches the :class:`ExecutionWorker` in a dedicated :class:`QThread`
    and relays its signals to the rest of the application.
    """

    # ── Relayed signals ─────────────────────────────────────────────────
    phase_changed = Signal(str)
    progress = Signal(int, int)
    completed = Signal()
    error_occurred = Signal(str)
    elapsed_time = Signal(float)
    trigger_count = Signal(int)
    is_running_changed = Signal(bool)

    def __init__(
        self,
        fpga: FPGAController,
        daq: DAQController,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._fpga = fpga
        self._daq = daq
        self._thread: Optional[QThread] = None
        self._worker: Optional[ExecutionWorker] = None
        self._running = False

    # ── Validation ──────────────────────────────────────────────────────
    def validate_sequence(
        self, sequence: ExperimentSequence
    ) -> List[ValidationMessage]:
        """Validate the full sequence including sync constraints.

        Parameters
        ----------
        sequence : ExperimentSequence
            The sequence to validate.

        Returns
        -------
        list of ValidationMessage
            Any warnings or errors found.
        """
        messages = validate(sequence)

        # Additional sync-level checks
        for event in sequence.analog_events:
            if not event.enabled:
                continue
            # Warn if an analog event is longer than the digital sequence
            if event.num_samples is not None and event.sample_rate_hz > 0:
                analog_duration_s = event.num_samples / event.sample_rate_hz
            else:
                analog_duration_s = (event.duration_ms or 0.0) / 1000.0
            seq_duration_s = sequence.sequence_duration_ticks / FPGA_CLOCK_HZ
            if analog_duration_s > seq_duration_s:
                messages.append(
                    ValidationMessage(
                        level="warning",
                        source=f"analog:{event.channel}",
                        message=(
                            f"Analog waveform duration ({analog_duration_s:.4f} s) "
                            f"exceeds sequence duration ({seq_duration_s:.4f} s)."
                        ),
                    )
                )

        return messages

    # ── Execution ───────────────────────────────────────────────────────
    def execute_sequence(self, sequence: ExperimentSequence) -> None:
        """Launch the experiment sequence in a background worker thread.

        If an execution is already running the call is ignored.
        """
        if self._running:
            logger.warning("execute_sequence called while already running.")
            return

        logger.info("Launching sequence execution …")

        # Create thread and worker
        self._thread = QThread()
        self._worker = ExecutionWorker(self._fpga, self._daq, sequence)
        self._worker.moveToThread(self._thread)

        # Wire up worker signals → manager signals
        self._worker.phase_changed.connect(self.phase_changed)
        self._worker.progress.connect(self.progress)
        self._worker.completed.connect(self._on_completed)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.elapsed_time.connect(self.elapsed_time)
        self._worker.trigger_count.connect(self.trigger_count)

        # Start worker when thread starts
        self._thread.started.connect(self._worker.run)

        # Clean up when finished
        self._worker.completed.connect(self._thread.quit)
        self._worker.error_occurred.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)

        self._running = True
        self.is_running_changed.emit(True)
        self._thread.start()

    # ── Stop ────────────────────────────────────────────────────────────
    def stop(self) -> None:
        """Request a graceful stop of the running sequence."""
        if self._worker is not None:
            logger.info("Requesting graceful stop …")
            self._worker.request_stop()

    def emergency_stop(self) -> None:
        """Emergency stop — immediately halt all hardware.

        Sends the stop request to the worker *and* directly commands the
        hardware controllers to cease output.
        """
        logger.warning("EMERGENCY STOP triggered!")
        if self._worker is not None:
            self._worker.request_stop()
        # Directly command hardware regardless of worker state
        try:
            self._fpga.emergency_stop()
        except Exception as exc:
            logger.error("FPGA emergency stop failed: %s", exc)
        try:
            self._daq.stop_all_tasks()
            self._daq.clear_all_tasks()
            self._daq.safe_state(0.0)
        except Exception as exc:
            logger.error("DAQ emergency stop failed: %s", exc)

    # ── Status ──────────────────────────────────────────────────────────
    def is_running(self) -> bool:
        """Return whether an execution is currently in progress."""
        return self._running

    # ── Private slots ───────────────────────────────────────────────────
    def _on_completed(self) -> None:
        logger.info("Sequence completed.")
        self._running = False
        self.is_running_changed.emit(False)
        self.completed.emit()

    def _on_error(self, message: str) -> None:
        logger.error("Execution error: %s", message)
        self._running = False
        self.is_running_changed.emit(False)
        self.error_occurred.emit(message)

    def _cleanup_thread(self) -> None:
        """Clean up thread and worker references after execution ends."""
        logger.debug("Cleaning up execution thread.")
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
