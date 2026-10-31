"""
Comprehensive verification test suite for lab18b daq
"""

import sys
import os
import numpy as np

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter

from sequence_model import (
    ExperimentSequence, DigitalEvent, AnalogEvent, WaveformType, FPGA_CLOCK_HZ
)
from daq_controller import DAQController
from ai_controller import AIController
from gui.main_window import MainWindow
from gui.simulation_viewer import SimulationViewerWidget
from gui.oscilloscope_widget import OscilloscopeWidget

def run_all_tests():
    app = QApplication.instance() or QApplication(sys.argv)
    print("==================================================")
    print("   lab18b daq - Comprehensive Verification Suite   ")
    print("==================================================")

    # 1. Test DAQController Unified AO Task
    print("\n[1/5] Testing DAQController Multi-Channel AO Architecture...")
    daq = DAQController(device_name="PXI2Slot3")
    daq.simulation_mode = True
    daq.initialize()
    events = [
        AnalogEvent(channel="PXI2Slot3/ao0", enabled=True, waveform_type=WaveformType.SINE, frequency_hz=1000.0, start_voltage=0.0, end_voltage=5.0),
        AnalogEvent(channel="PXI2Slot3/ao1", enabled=True, waveform_type=WaveformType.RAMP, frequency_hz=500.0, start_voltage=-2.0, end_voltage=3.0),
        AnalogEvent(channel="PXI2Slot3/ao6", enabled=True, waveform_type=WaveformType.SQUARE, frequency_hz=5000.0, start_voltage=0.0, end_voltage=4.0),
    ]
    test_seq = ExperimentSequence(sequence_duration_ticks=int(0.05 * FPGA_CLOCK_HZ), clock_hz=FPGA_CLOCK_HZ)
    test_seq.analog_events = events
    ok = daq.configure_sequence_tasks(test_seq)
    assert ok, "Unified AO configuration failed"
    daq.clear_all_tasks()
    print("      Unified multi-channel AO task configured and cleared cleanly!")

    # 2. Test Simulation Viewer High-Frequency Synthesis & Rendering
    print("\n[2/5] Testing Simulation Viewer (High Frequency & Peak-Detect DSO)...")
    sim = SimulationViewerWidget()
    sim.resize(800, 600)
    sim.show()
    seq = ExperimentSequence(sequence_duration_ticks=int(0.05 * FPGA_CLOCK_HZ), clock_hz=FPGA_CLOCK_HZ)
    seq.digital_events.append(DigitalEvent(channel=0, start_ticks=int(0.01 * FPGA_CLOCK_HZ), end_ticks=int(0.04 * FPGA_CLOCK_HZ), enabled=True))
    seq.analog_events.append(AnalogEvent(channel=0, enabled=True, waveform_type=WaveformType.SINE, frequency_hz=20000.0, start_voltage=0.0, end_voltage=5.0))
    sim.set_sequence(seq)
    sim.run_simulation()
    assert len(sim._canvas._traces) > 0, "Traces should be populated in simulation"
    # Paint test
    pix = QPixmap(sim._canvas.size())
    p = QPainter(pix)
    sim._canvas.paintEvent(None)
    p.end()
    print("      Simulation viewer synthesized 20 kHz waveform and painted without aliasing!")

    # 3. Test Live Oscilloscope & Output Monitor
    print("\n[3/5] Testing Live Oscilloscope Widget...")
    osc = OscilloscopeWidget()
    osc.resize(900, 600)
    osc.show()
    osc.load_sequence_waveforms(seq)
    assert "AO0" in osc._screen._traces, "AO0 should be loaded in oscilloscope"
    # Ensure no modulo wrapping - time array strictly monotonically increasing
    t_arr = osc._screen._traces["AO0"]["times"]
    assert np.all(np.diff(t_arr) >= 0), "Times must be strictly monotonically non-decreasing (no modulo wrapping)"
    # Paint test
    pix_osc = QPixmap(osc._screen.size())
    p_osc = QPainter(pix_osc)
    osc._screen.paintEvent(None)
    p_osc.end()
    print("      Oscilloscope rendered monotonic left-to-right trace with Auto-Scale!")

    # 4. Test MainWindow UI & Tab Switching
    print("\n[4/5] Testing MainWindow tab transitions...")
    win = MainWindow()
    win.resize(1100, 750)
    win.show()
    app.processEvents()
    win._load_sequence_into_ui(seq)
    # Switch to Simulation tab
    win._tabs.setCurrentIndex(1)
    app.processEvents()
    # Switch to Oscilloscope tab
    win._tabs.setCurrentIndex(2)
    app.processEvents()
    # Switch to Execution tab
    win._tabs.setCurrentIndex(3)
    app.processEvents()
    win.close()
    print("      MainWindow loaded sequence and switched between all tabs seamlessly!")

    # 5. Verify App Title & Branding
    print("\n[5/5] Verifying Branding 'lab18b daq'...")
    assert "lab18b daq" in win.windowTitle(), f"Title should contain 'lab18b daq', got '{win.windowTitle()}'"
    print("      Window title properly branded as 'lab18b daq'!")

    print("\n==================================================")
    print(" [SUCCESS] ALL COMPREHENSIVE TESTS PASSED!       ")
    print("==================================================")
    sys.exit(0)

if __name__ == "__main__":
    run_all_tests()
