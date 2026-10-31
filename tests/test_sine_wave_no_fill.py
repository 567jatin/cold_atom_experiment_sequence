"""
Test verifying that sine wave in OscilloscopeScreen is NOT filled with orange brush.
"""

import sys
import os
import numpy as np

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QColor

from sequence_model import ExperimentSequence, AnalogEvent, DigitalEvent, WaveformType, FPGA_CLOCK_HZ
from gui.oscilloscope_widget import OscilloscopeWidget

def test_sine_wave_no_orange_fill():
    app = QApplication.instance() or QApplication(sys.argv)
    
    osc = OscilloscopeWidget()
    osc.resize(900, 550)
    osc.show()

    # Create sequence matching user's exact screenshot:
    # 50 ms total duration, 100 Hz sine wave, 0V to 5V
    clock = FPGA_CLOCK_HZ
    seq = ExperimentSequence(sequence_duration_ticks=int(0.050 * clock), clock_hz=clock)
    
    # 42.5 ms pulse
    seq.digital_events.append(DigitalEvent(
        channel=0,
        start_ticks=0,
        end_ticks=int(0.0425 * clock),
        enabled=True,
        name="Main Pulse"
    ))
    seq.analog_events.append(AnalogEvent(
        channel=0,
        enabled=True,
        waveform_type=WaveformType.SINE,
        start_voltage=0.0,
        end_voltage=5.0,
        frequency_hz=100.0,
        name="AO0 Sine"
    ))

    osc.load_sequence_waveforms(seq)
    app.processEvents()

    # Render OscilloscopeScreen to QPixmap
    screen = osc._screen
    pix = QPixmap(screen.size())
    pix.fill(Qt.GlobalColor.black)
    screen.render(pix)

    img = pix.toImage()
    w = img.width()
    h = img.height()

    orange_pixels = 0
    cyan_pixels = 0

    # Scan screen area (excluding right 100px where trigger marker handle is drawn)
    for x in range(10, w - 100):
        for y in range(10, h - 10):
            c = img.pixelColor(x, y)
            # Orange trigger color #ffaa00 is (255, 170, 0)
            if c.red() > 220 and 140 <= c.green() <= 190 and c.blue() < 40:
                orange_pixels += 1
            # Cyan trace color #00e5ff is (0, 229, 255)
            if c.red() < 40 and c.green() > 200 and c.blue() > 220:
                cyan_pixels += 1

    print(f"Cyan outline pixels: {cyan_pixels}")
    print(f"Orange pixels in waveform area: {orange_pixels}")

    # Cyan trace must exist
    assert cyan_pixels > 100, f"Expected cyan sine trace pixels, got {cyan_pixels}"
    # Orange pixels inside the waveform area MUST BE ZERO!
    assert orange_pixels == 0, f"Found {orange_pixels} unexpected orange pixels inside sine wave! Waveform was filled!"

    print("[SUCCESS] Sine wave rendered as a clean, unfilled trace with zero orange polygon fill!")
    osc.close()

if __name__ == "__main__":
    test_sine_wave_no_orange_fill()
