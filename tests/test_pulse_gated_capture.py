"""
Verification test for Pulse-Gated Capture & CSV Export feature in lab18b daq
"""

import os
import sys
import time
import numpy as np

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from PySide6.QtWidgets import QApplication
from sequence_model import FPGA_CLOCK_HZ, ExperimentSequence, DigitalEvent, AnalogEvent, WaveformType
from ai_controller import AIController
from gui.oscilloscope_widget import OscilloscopeWidget

def test_pulse_gated_capture():
    app = QApplication.instance() or QApplication(sys.argv)
    print("==========================================================")
    print("   Testing Pulse-Gated Capture & CSV Export Feature        ")
    print("==========================================================")

    # 1. Test AIController direct pulse capture
    print("\n[1/3] Testing AIController.start_pulse_capture()...")
    ai = AIController(device_name="PXI2Slot4")
    ai.simulation_mode = True
    ai.initialize()

    captured_result = {}

    def on_captured(times, ch_data, meta, csv_path):
        captured_result["times"] = times
        captured_result["ch_data"] = ch_data
        captured_result["meta"] = meta
        captured_result["csv_path"] = csv_path

    ai.pulse_captured.connect(on_captured)

    pulse_duration_s = 0.025  # 25 ms
    sample_rate = 500000.0    # 500 kS/s
    expected_samples = int(pulse_duration_s * sample_rate)

    ai.start_pulse_capture(
        channels=["PXI2Slot4/ai0"],
        duration_s=pulse_duration_s,
        sample_rate_hz=sample_rate,
        metadata={"gate_source": "DIO0: Laser Gate (25.00 ms)"},
        auto_export_csv=True,
    )

    # Wait for background worker to complete
    start_wait = time.time()
    while not captured_result and (time.time() - start_wait < 3.0):
        app.processEvents()
        time.sleep(0.01)

    assert "times" in captured_result, "Pulse capture did not complete in time"
    times = captured_result["times"]
    ch_data = captured_result["ch_data"]
    csv_path = captured_result["csv_path"]

    print(f"      Captured samples: {len(times)} (Expected: {expected_samples})")
    assert len(times) == expected_samples, f"Expected {expected_samples} samples, got {len(times)}"
    assert "PXI2Slot4/ai0" in ch_data, "Channel data missing"
    assert os.path.exists(csv_path), f"Auto-exported CSV does not exist: {csv_path}"
    print(f"      Auto-exported CSV: {csv_path}")

    # Validate CSV content
    with open(csv_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert any("Pulse-Gated Analog Input Capture" in line for line in lines), "Missing header title"
    assert any("Gate Source: DIO0: Laser Gate" in line for line in lines), "Missing gate source metadata"
    assert any("Time_s,Time_ms" in line for line in lines), "Missing column headers"
    print("      CSV format and metadata headers validated successfully!")

    # 2. Test OscilloscopeWidget Pulse Capture Tab & UI
    print("\n[2/3] Testing OscilloscopeWidget Pulse Capture Tab...")
    osc = OscilloscopeWidget(ai_controller=ai)
    osc.resize(950, 600)
    osc.show()

    assert osc._ctrl_tabs.count() == 2, "Expected 2 tabs in instrument panel"
    assert "Pulse Capture" in osc._ctrl_tabs.tabText(1), "Tab 1 should be Pulse Capture"

    # Switch to Pulse Capture tab
    osc._ctrl_tabs.setCurrentIndex(1)
    app.processEvents()

    # Load sequence with digital pulse on DIO0 (35 ms)
    seq = ExperimentSequence(sequence_duration_ticks=int(0.05 * FPGA_CLOCK_HZ), clock_hz=FPGA_CLOCK_HZ)
    seq.digital_events.append(DigitalEvent(
        channel=0,
        start_ticks=int(0.005 * FPGA_CLOCK_HZ),
        end_ticks=int(0.040 * FPGA_CLOCK_HZ),
        enabled=True,
        name="Imaging Gate"
    ))
    osc.load_sequence_waveforms(seq)

    # Verify gate combo populated with DIO0 pulse
    combo_text = osc._gate_source_combo.currentText()
    print(f"      Current Gate Combo item: {combo_text}")
    assert "DIO0: Imaging Gate" in combo_text, f"Expected DIO0 in combo, got: {combo_text}"
    print(f"      Auto-synced duration spinbox: {osc._gate_duration_spin.value():.2f} ms")
    assert abs(osc._gate_duration_spin.value() - 35.0) < 0.1, "Duration spinbox should auto-sync to 35 ms"

    # 3. Test triggering capture from widget
    print("\n[3/3] Testing trigger pulse capture via widget button...")
    osc._trigger_pulse_capture()

    start_wait = time.time()
    while ("AI0" not in osc._screen._traces) and (time.time() - start_wait < 3.0):
        app.processEvents()
        time.sleep(0.01)

    assert "AI0" in osc._screen._traces, "AI0 trace should be displayed on oscilloscope screen"
    ai0_trace = osc._screen._traces["AI0"]
    print(f"      Oscilloscope AI0 trace points: {len(ai0_trace['times'])}")
    assert len(ai0_trace["times"]) > 0, "AI0 trace data should not be empty"
    print(f"      HUD status: {osc._lbl_capture_status.text()}")
    assert "Captured" in osc._lbl_capture_status.text()
    assert osc._btn_save_csv_as.isEnabled(), "Save CSV As button should be enabled"

    osc.close()
    print("\n==========================================================")
    print(" [SUCCESS] ALL PULSE-GATED CAPTURE TESTS PASSED!          ")
    print("==========================================================")

if __name__ == "__main__":
    test_pulse_gated_capture()
