"""
Verification test for DAQController unified AO task with 1 channel and multiple channels.
Ensures NI-DAQmx error -200524 never occurs.
"""

import sys
import os
import numpy as np

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from PySide6.QtWidgets import QApplication
from sequence_model import ExperimentSequence, AnalogEvent, DigitalEvent, WaveformType, FPGA_CLOCK_HZ
from daq_controller import DAQController

def test_daq_task_dimensions():
    app = QApplication.instance() or QApplication(sys.argv)
    print("======================================================================")
    print("  Testing Unified AO Task: 1 Channel (Single) vs Multiple Channels    ")
    print("======================================================================")

    daq = DAQController(device_name="PXI2Slot3")
    daq.initialize()

    clock = FPGA_CLOCK_HZ

    # Test 1: Exactly 1 channel enabled (Reproduces user error case)
    print("\n[1/4] Testing sequence with exactly 1 enabled AO channel (AO0)...")
    seq1 = ExperimentSequence(sequence_duration_ticks=int(0.05 * clock), clock_hz=clock)
    seq1.digital_events.append(DigitalEvent(channel=0, start_ticks=0, end_ticks=int(0.0425 * clock), enabled=True))
    seq1.analog_events.append(AnalogEvent(
        channel="PXI2Slot3/ao0",
        enabled=True,
        waveform_type=WaveformType.SINE,
        start_voltage=0.0,
        end_voltage=5.0,
        frequency_hz=100.0,
        name="AO0 Sine"
    ))

    # Should configure cleanly without error -200524
    ok1 = daq.configure_sequence_tasks(seq1)
    assert ok1, "Failed to configure unified task for 1 channel"
    print("      Unified AO task configured cleanly for 1 channel!")
    daq.clear_all_tasks()

    # Test 2: Multiple channels (AO0 and AO1)
    print("\n[2/4] Testing sequence with 2 enabled AO channels (AO0, AO1)...")
    seq2 = ExperimentSequence(sequence_duration_ticks=int(0.05 * clock), clock_hz=clock)
    seq2.digital_events.append(DigitalEvent(channel=0, start_ticks=0, end_ticks=int(0.0425 * clock), enabled=True))
    seq2.analog_events.append(AnalogEvent(
        channel="PXI2Slot3/ao0",
        enabled=True,
        waveform_type=WaveformType.SINE,
        start_voltage=0.0,
        end_voltage=5.0,
        frequency_hz=100.0,
    ))
    seq2.analog_events.append(AnalogEvent(
        channel="PXI2Slot3/ao1",
        enabled=True,
        waveform_type=WaveformType.RAMP,
        start_voltage=-2.0,
        end_voltage=2.0,
    ))
    ok2 = daq.configure_sequence_tasks(seq2)
    assert ok2, "Failed to configure unified task for 2 channels"
    print("      Unified AO task configured cleanly for 2 channels!")
    daq.clear_all_tasks()

    # Test 3: All 8 channels (AO0 to AO7)
    print("\n[3/4] Testing sequence with all 8 enabled AO channels...")
    seq8 = ExperimentSequence(sequence_duration_ticks=int(0.05 * clock), clock_hz=clock)
    for i in range(8):
        seq8.analog_events.append(AnalogEvent(
            channel=f"PXI2Slot3/ao{i}",
            enabled=True,
            waveform_type=WaveformType.SINE if i % 2 == 0 else WaveformType.RAMP,
            start_voltage=0.0,
            end_voltage=float(i + 1),
            frequency_hz=100.0 * (i + 1),
        ))
    ok8 = daq.configure_sequence_tasks(seq8)
    assert ok8, "Failed to configure unified task for 8 channels"
    print("      Unified AO task configured cleanly for 8 channels!")
    daq.clear_all_tasks()

    # Test 4: 0 enabled channels (graceful skip)
    print("\n[4/4] Testing sequence with 0 enabled AO channels...")
    seq0 = ExperimentSequence(sequence_duration_ticks=int(0.05 * clock), clock_hz=clock)
    ok0 = daq.configure_sequence_tasks(seq0)
    assert ok0, "Failed to gracefully skip 0 channels"
    print("      0 channels handled gracefully!")

    print("\n======================================================================")
    print(" [SUCCESS] ALL 1-CHANNEL AND MULTI-CHANNEL AO TESTS PASSED!           ")
    print("======================================================================")
    sys.exit(0)

if __name__ == "__main__":
    test_daq_task_dimensions()
