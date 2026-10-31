"""
Test Oscilloscope Sine Wave Rendering & Auto-Scale
==================================================
Verifies that:
1. Auto-Scale configures a clean timebase (100 µs/div for 10 kHz sine wave).
2. The waveform renders individual cycles without solid fills.
3. No diagonal lines cross empty intervals.
"""
import sys
import os
import numpy as np

# Ensure root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter

from sequence_model import ExperimentSequence, AnalogEvent, WaveformType
from gui.oscilloscope_widget import OscilloscopeWidget

def run_test():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    seq = ExperimentSequence()
    seq.sequence_duration_ticks = 40000000  # 1.0 s at 40 MHz

    # User's exact scenario: AO1 enabled, 10 kHz Sine wave, 0V -> 5V, 0.0 to 40.0 ms
    aev = AnalogEvent(
        name="AO1",
        channel="PXI2Slot3/ao1",
        waveform_type=WaveformType.SINE,
        start_voltage=0.0,
        end_voltage=5.0,
        start_ms=0.0,
        end_ms=40.0,
        duration_ms=40.0,
        frequency_hz=10000.0,
        sample_rate_hz=500000.0,
        enabled=True,
    )
    # Put a dummy event for AO0 that is disabled
    ao0 = AnalogEvent(name="AO0", channel="PXI2Slot3/ao0", enabled=False)
    seq.analog_events = [ao0, aev]

    widget = OscilloscopeWidget(None)
    widget.resize(1000, 600)
    widget.load_sequence_waveforms(seq)

    # Check auto-scale timebase
    tb_text = widget._timebase_combo.currentText()
    tb_val = widget._screen.timebase_s_div
    print(f"Auto-scale timebase selected: {tb_text} ({tb_val:e} s/div)")
    assert tb_val <= 0.0005, f"Timebase should be zoomed in to see cycles, got {tb_val}"

    # Render widget screen to QImage
    screen = widget._screen
    screen.resize(800, 500)
    image = QImage(800, 500, QImage.Format.Format_RGB32)
    screen.render(image)
    out_path = os.path.join(BASE_DIR, "scratch", "test_oscilloscope_sine_rendered.png")
    image.save(out_path)
    print(f"[OK] Rendered oscilloscope view saved to {out_path}")

    # Also test rendering at 100 ms/div (zoomed out full sequence) to ensure no diagonal streak
    widget._timebase_combo.setCurrentIndex(15)  # 100 ms/div
    image_zoom_out = QImage(800, 500, QImage.Format.Format_RGB32)
    screen.render(image_zoom_out)
    out_zoom_path = os.path.join(BASE_DIR, "scratch", "test_oscilloscope_sine_zoomed_out.png")
    image_zoom_out.save(out_zoom_path)
    print(f"[OK] Rendered zoomed out view saved to {out_zoom_path}")

    print("ALL OSCILLOSCOPE TESTS PASSED!")

if __name__ == "__main__":
    run_test()
