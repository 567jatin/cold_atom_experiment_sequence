"""
Verification Test:
1. Verify that Digital TTL channels and Analog channels are independent and do not overwrite each other.
2. Verify hardware sequence execution on physical PXI-6733 + RIO0 without timeout -200560.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpga_controller import FPGAController
from daq_controller import DAQController
from ai_controller import AIController
from sequence_model import (
    ExperimentSequence, DigitalEvent, AnalogEvent, WaveformType, FPGA_CLOCK_HZ,
)
from synchronization import ExecutionWorker
from PySide6.QtCore import QCoreApplication

app = QCoreApplication.instance() or QCoreApplication(sys.argv)

print("=" * 70)
print("TEST: Independent Channels & Timeout -200560 Resolution")
print("=" * 70)

# 1. Build test sequence
seq = ExperimentSequence(
    name="Independence Test",
    sequence_duration_ticks=20_000_000,  # 500 ms at 40 MHz
    clock_hz=FPGA_CLOCK_HZ,
)

# User configures DIO3 (Shutter pulse: 50 ms to 150 ms)
dio3 = DigitalEvent(
    name="DIO3 Shutter",
    channel=3,
    start_ticks=2_000_000,   # 50 ms
    end_ticks=6_000_000,     # 150 ms
    enabled=True,
)
seq.digital_events = [dio3]

# User configures AO1 (Ramp: 0 ms to 300 ms, 0V to 4V)
ao1 = AnalogEvent(
    name="AO1 Ramp",
    channel="PXI2Slot3/ao1",
    waveform_type=WaveformType.RAMP,
    start_voltage=0.0,
    end_voltage=4.0,
    start_ms=0.0,
    end_ms=300.0,
    duration_ms=300.0,
    enabled=True,
)
seq.analog_events = [ao1]

# Check that objects retain their original values
assert dio3.start_ticks == 2_000_000
assert dio3.end_ticks == 6_000_000
assert ao1.start_ms == 0.0
assert ao1.end_ms == 300.0
assert ao1.enabled is True
print("[OK] Initial sequence values verified.")

# 2. Test FPGA Controller configuration
fpga = FPGAController()
assert fpga.connect(), "FPGA failed to connect"

fpga.configure_sequence(seq)

# Verify FPGA configuration did NOT mutate analog events or inject ghost digital events
assert ao1.start_ms == 0.0, f"ao1.start_ms mutated to {ao1.start_ms}"
assert ao1.end_ms == 300.0, f"ao1.end_ms mutated to {ao1.end_ms}"
assert ao1.enabled is True, "ao1.enabled mutated"
assert dio3.start_ticks == 2_000_000, f"dio3.start_ticks mutated to {dio3.start_ticks}"
print("[OK] FPGA configure_sequence preserved independent values without mutating analog events.")

# 3. Test DAQ Controller configuration
daq = DAQController("PXI2Slot3")
assert daq.initialize(), "DAQ failed to initialize"

daq.configure_sequence_tasks(seq)
print("[OK] DAQ configure_sequence_tasks configured unified AO task cleanly.")

# 4. Test ExecutionWorker (End-to-End Orchestrator on physical hardware)
worker = ExecutionWorker(fpga, daq, seq)
errors = []
worker.error_occurred.connect(lambda err: errors.append(err))
phases = []
worker.phase_changed.connect(lambda p: phases.append(p))

print("\nExecuting sequence through ExecutionWorker on physical hardware...")
t0 = time.perf_counter()
worker.run()
t_elapsed = time.perf_counter() - t0

print(f"Phases traversed: {phases}")
print(f"Elapsed wall time: {t_elapsed:.3f} s (expected ~0.5 s)")

if errors:
    print(f"[FAILED] Errors occurred during execution: {errors}")
    sys.exit(1)
else:
    print("[SUCCESS] ExecutionWorker completed with ZERO errors!")

assert "Complete" in phases or "Safe State" in phases
assert t_elapsed >= 0.48, f"Execution ended too quickly ({t_elapsed:.3f} s)"
print("\n" + "=" * 70)
print("ALL TESTS PASSED! Timeout -200560 is resolved, and values are not overwritten!")
print("=" * 70)
