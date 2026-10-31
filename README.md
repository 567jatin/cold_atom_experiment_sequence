# lab18b daq

**FPGA TTL & Analog Waveform Sequence Controller**  
*Laboratory instrumentation software for cold-atom physics, quantum optics, and laser spectroscopy experiments (Lab 18B).*

---

## 🔬 System Overview

**`lab18b daq`** is a high-performance Python/Qt desktop application engineered for controlling synchronized, microsecond-accurate digital TTL pulses and analog waveforms using National Instruments PXI hardware:

* **Digital Output Engine (TTL)**: **NI PXIe-7820R FPGA** (`RIO0`) running a compiled LabVIEW bitfile at **40 MHz** (**25 ns timing resolution**) across **21 independent channels (`DIO0` – `DIO20`)**.
* **Analog Output Engine (AO)**: **NI PXI-6733** (`PXI2Slot3`) high-speed 16-bit analog output card delivering arbitrary, sine, ramp, and constant waveforms across **8 channels (`AO0` – `AO7`)** with aggregate rates up to **1 MS/s**.
* **Live Oscilloscope & Acquisition Engine (AI)**: **NI PXI Analog Input Card** (`PXI2Slot4` / streaming simulation) providing continuous real-time DSO monitoring and **pulse-gated capture with automated CSV export**.
* **PXI Backplane Trigger Bus**: Hardwired hardware synchronization routing `DIO0`–`DIO7` directly to `PXI_Trig0`–`PXI_Trig7` for jitter-free sub-microsecond analog execution.

---

## 🖥️ Application Interface & Tabs

`lab18b daq` provides four specialized tabs tailored for sequence authoring, physics simulation, live signal acquisition, and hardware execution:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  lab18b daq - FPGA TTL & Analog Sequence Controller                                              │
├──────────────────────┬──────────────────────┬──────────────────────┬─────────────────────────────┤
│ 1. Sequence Builder  │ 2. Simulation Viewer │ 3. Live Oscilloscope │ 4. Execute Hardware         │
└──────────────────────┴──────────────────────┴──────────────────────┴─────────────────────────────┘
```

### 1. Sequence Builder (Channels & Timeline)
* **Digital Pulse Table (`DIO0`–`DIO20`)**: Configure start ticks, end ticks, active duration, and channel descriptions. Enforces the strict 1-pulse-per-channel FPGA hardware register constraint.
* **Analog Output Table (`AO0`–`AO7`)**: Configure waveform shapes (**Sine**, **Square**, **Ramp**, **Constant**, **Arbitrary**), voltage spans ($\pm 10.0\text{ V}$), frequencies, start/end timing, and DAC sampling rates.
* **Real-Time Interactive Timeline**: Gantt-style timeline visualization. Supports drag-and-drop pulse placement, duration resizing, auto-expanding duration, and synchronized analog gating.

### 2. Sequence Simulation (Signal vs. Time)
* Complete multi-channel simulated oscilloscope calculating continuous $V(t)$ for all active digital and analog channels across the entire experiment sequence.
* **DSO Peak-Detect Min-Max Rendering**: High-frequency signals (e.g. $10\text{ kHz}$ to $100\text{ kHz}$) render crisp peak-to-peak envelopes with zero aliasing or Moiré beating.
* **Stacked Lanes & Overlay Views**: Inspect individual channel lanes or overlay all signals on a shared time axis with high-precision time/voltage cursor inspection.

### 3. Live Oscilloscope & Output Monitor
* Phosphor LCD digital storage oscilloscope (DSO) display with $10 \times 8$ division grid.
* **Full DSO Timebase & Vertical Scale**:
  * Horizontal Timebase: $1\ \mu\text{s/div}$ up to $5\text{ s/div}$ with interactive horizontal time offset panning.
  * Vertical Sensitivity: $50\text{ mV/div}$ up to $10.0\text{ V/div}$.
  * **Auto-Scale**: One-click horizontal and vertical framing of loaded sequences.
* **Automated HUD Measurements**: Real-time display of $V_{\text{pp}}$, $V_{\text{max}}$, $V_{\text{min}}$, $V_{\text{rms}}$, and signal frequency.
* **🎯 Pulse-Gated Analog Input Capture (Input 1 / AI0)**:
  * Gates analog input acquisition strictly for the exact duration a chosen digital pulse (e.g., `DIO0: Laser Gate`) is active.
  * Captures at rates up to **2.0 MS/s** and instantly plots the result on the oscilloscope.
  * **Automated CSV Export**: Full-precision time and voltage data automatically saved to `captures/gated_capture_<CH>_<TIMESTAMP>.csv` with laboratory metadata headers.
  * Direct *"Open Captures"* and *"Save CSV As..."* export actions.

### 4. Execute Hardware
* **Hardware Connection Status**: Live indicators for FPGA (`RIO0`), DAQ Analog Output (`PXI2Slot3`), and Analog Input (`PXI2Slot4`).
* **Step-by-Step State Machine**: `Validate Sequence` → `Configure Hardware` → `Arm Analog Tasks` → `Start Experiment` → `Stop` → `Emergency Stop`.
* **Cycle Tracking**: Program finite repeat loops ($1 \dots N$) or continuous cycles with real-time elapsed time counters and phase logs.
* **Fail-Safe Safe State**: Dedicated Emergency Stop immediately commands all physical analog outputs to $0.0\text{ V}$ safe hold.

---

## ⚡ Hardware Trigger Architecture: DIO{N} ↔ Trig{N} ↔ AO{N}

On this PXI chassis, digital lines `DIO0` through `DIO7` are directly mapped across the PXI trigger backplane to trigger analog waveform channels:

| Digital Line | PXI Backplane Trigger | Controlled Analog Output | Physical DAQ Channel | Primary Purpose |
|:---:|:---:|:---:|:---:|---|
| **DIO0** | `PXI_Trig0` | **AO0** | `PXI2Slot3/ao0` | Laser Gate / AOM Frequency |
| **DIO1** | `PXI_Trig1` | **AO1** | `PXI2Slot3/ao1` | Magnetic Coil Ramp |
| **DIO2** | `PXI_Trig2` | **AO2** | `PXI2Slot3/ao2` | Microwave Transition Sweep |
| **DIO3** | `PXI_Trig3` | **AO3** | `PXI2Slot3/ao3` | Repumper Gate |
| **DIO4** | `PXI_Trig4` | **AO4** | `PXI2Slot3/ao4` | Optical Pumping Gate |
| **DIO5** | `PXI_Trig5` | **AO5** | `PXI2Slot3/ao5` | Imaging Shutter / Gate |
| **DIO6** | `PXI_Trig6` | **AO6** | `PXI2Slot3/ao6` | General Analog Waveform |
| **DIO7** | `PXI_Trig7` | **AO7** | `PXI2Slot3/ao7` | General Analog Waveform |
| **DIO8–DIO20** | — | — | — | Independent Digital TTL Pulses (Shutters, RF, Cameras) |

> **Hardware Rule**: When a digital pulse is created on `DIO{N}`, the software automatically binds and triggers the corresponding `AO{N}` waveform at the exact start time of the pulse, guaranteeing zero software latency jitter.

---

## 🚀 Quick Start & Launching

### Running from Standalone Executable (No Python Required)
Double-click the desktop shortcut:
```
lab18b daq.lnk  (on the Windows Desktop)
```
Or run the compiled executable directly:
```
dist\lab18b_daq\lab18b_daq.exe
```

### Running from Source
Ensure Python 3.9+ (64-bit) is installed with NI-DAQmx and NI-FPGA drivers:
```powershell
cd "C:\Users\nqm lab18b\.gemini\antigravity\scratch\fpga_sequence_controller"
pip install -r requirements.txt
python main.py
```

### Rebuilding the Standalone Executable
To recompile the `.exe` with all dependencies, metadata, and custom application icon:
```powershell
python build_exe.py
# or double-click build_exe.bat
```

---

## 📊 Pulse-Gated Capture & CSV Export

The **Pulse-Gated Capture** engine allows automated logging of physical sensor or photodiode responses strictly while an optical or RF pulse is active:

1. In **Tab 2 ("Live Oscilloscope & Output Monitor")**, click the **"🎯 Pulse Capture"** subtab on the right panel.
2. Select your **Target Input** (e.g. `AI0 (Input 1)`).
3. Select your **Gate Pulse** (e.g. `DIO0: Laser Gate (25.00 ms)`). The active duration automatically synchronizes.
4. Set your desired **Sample Rate** ($100\text{ kS/s}$ to $2.0\text{ MS/s}$).
5. Click **"▶ Capture Input 1 Gated Pulse"** (or enable *"Auto-Capture on Experiment Run"* to capture automatically during sequence execution).
6. Waveforms are instantly plotted on the oscilloscope screen, and data is saved to `captures/`:

```csv
# lab18b daq - Pulse-Gated Analog Input Capture
# Timestamp: 2026-10-30 06:15:22
# Gate Source: DIO0: Laser Gate (25.00 ms)
# Pulse Duration: 25.0000 ms
# Sample Rate: 500000.0 Hz
# Total Samples: 12500
# --------------------------------------------------
Time_s,Time_ms,AI0_V
0.000000000,0.000000,0.251703
0.000002000,0.002000,0.266564
0.000004000,0.004000,0.312449
...
```

Click **"📁 Open Captures"** to view the folder in Windows Explorer or **"💾 Save CSV As..."** to choose a custom save path.

---

## 🛠️ Architecture & Multi-Channel DAQmx Implementation

### Unified Anonymous AO Task Architecture
To ensure seamless execution on the physical **NI PXI-6733** card, `lab18b daq` uses a unified task architecture in `daq_controller.py`:
* **Single Master Task**: All active analog output channels are combined into a single hardware task sharing one sample clock and one PXI trigger line, eliminating sample clock resource reservation conflicts (`-50103`).
* **Anonymous Task Instances**: Tasks are instantiated without explicit names (`nidaqmx.Task()`), eliminating task name collisions (`-200089`).
* **Dynamic 1-D / 2-D Array Writing**:
  * **1 Channel Active**: Written using `AnalogSingleChannelWriter` with a **1-D array** of length `num_samples`.
  * **Multiple Channels Active**: Written using `AnalogMultiChannelWriter` with a **2-D array** of shape `(num_channels, num_samples)`.
  * *Prevents NI-DAQmx error `-200524` (Number of Channels in Task vs Data mismatch).*

---

## 🧪 Verification & Test Suite

The project includes automated verification test scripts in the `scratch/` directory:

| Test Script | Validates |
|---|---|
| `scratch\test_daq_single_and_multi_channel.py` | Direct hardware DAQmx configuration for 1 channel, 2 channels, and 8 channels on physical PXI-6733. |
| `scratch\test_sine_wave_no_fill.py` | Pixel-level validation of OscilloscopeScreen rendering; ensures zero orange brush fill leaks. |
| `scratch\test_pulse_gated_capture.py` | Pulse-gated acquisition duration, timing, and automated CSV export formatting. |
| `scratch\test_mainwindow_oscilloscope_tab.py` | Full MainWindow UI tab transitions and live sweep animations. |
| `scratch\test_comprehensive_suite.py` | End-to-end regression test across FPGA, DAQ, AI, simulation, and branding. |

Run all tests via:
```powershell
python scratch/test_comprehensive_suite.py
```

---

## 📁 Project Structure

```
fpga_sequence_controller/
├── main.py                         # Application entry point (DPI scaling, icons, logging)
├── sequence_model.py               # Core data models (ExperimentSequence, Events, Channels)
├── fpga_controller.py              # NI-FPGA RIO0 controller (21 DIO registers, 40 MHz clock)
├── daq_controller.py               # NI-DAQmx AO controller (PXI-6733 unified multi-channel engine)
├── ai_controller.py                # NI-DAQmx AI controller (PXI AI streaming & pulse capture)
├── synchronization.py              # Execution orchestrator (FPGA timing + DAQ sync)
├── waveform_generator.py           # Waveform math (Sine, Square, Ramp, Constant, Arbitrary)
├── logging_utils.py                # Application logging setup
├── config.py                       # Hardware configuration defaults
├── build_exe.py                    # PyInstaller standalone executable build script
├── build_exe.bat                   # 1-click batch compiler
├── lab18b_daq.ico                  # Custom application multi-resolution logo icon
├── lab18b_daq_icon.png             # Application logo image
│
├── gui/
│   ├── main_window.py              # Main application window (4 central tabs & status bar)
│   ├── channel_table.py            # Digital DIO0-DIO20 table widget
│   ├── analog_editor.py            # Analog AO0-AO7 table & waveform config dialogs
│   ├── timeline_widget.py          # Interactive Gantt-style timeline
│   ├── simulation_viewer.py        # High-frequency DSO sequence simulator
│   ├── oscilloscope_widget.py      # Live phosphor LCD oscilloscope & pulse capture HUD
│   ├── execution_panel.py          # Run controls, phase indicator, event log
│   └── styles.py                   # Dark laboratory instrumentation theme
│
├── captures/                       # Destination folder for auto-exported pulse CSV files
├── examples/                       # Pre-configured experiment sequences (.json)
└── scratch/                        # Automated unit tests and verification scripts
```

---

## ❓ Troubleshooting

| Issue | Root Cause | Solution |
|---|---|---|
| **DAQ Error `-200560`** | `Wait Until Done` timed out waiting for hardware trigger on `PXI_Trig0`. The FPGA card outputs on front-panel DIO pins and does not drive PXI backplane trigger lines. | **Fixed in `daq_controller.py`**: Start trigger on `PXI_Trig0` removed from default sequence execution; DAQ task starts synchronously via software in lockstep with the FPGA. |
| **Channel Inputs Overwriting / Wrong Values** | Artificial coupling was overwriting digital channels when analog was edited and disabling analog channels when digital was edited. | **Fixed across codebase**: Digital channels (`DIO0`–`DIO20`) and Analog channels (`AO0`–`AO7`) are fully decoupled and preserve exact user configurations independently. |
| **DAQ Error `-200524`** | Mismatch between task channels and data array dimensions (e.g. passing 2D array to 1-channel task). | **Fixed in `daq_controller.py`**: The writer dynamically dispatches to `AnalogSingleChannelWriter` (1D array) for single channel and `AnalogMultiChannelWriter` (2D array) for multi-channel tasks. |
| **DAQ Error `-200089`** | Task name specified conflicts with existing task name. | **Fixed in `daq_controller.py`**: Anonymous tasks (`nidaqmx.Task()`) are used, and all tasks are closed in a unique `set()` before new allocation. |
| **Oscilloscope Waveform Filled with Solid Color** | QPainter brush leaked from trigger marker handle. | **Fixed in `oscilloscope_widget.py`**: Brush is reset with `NoBrush` and paths are stroked via `strokePath()`. |
| **Execution Ending Early** | `wait_until_done()` stopped sequence right after short analog pulse. | **Fixed in `synchronization.py`**: Execution loop maintains full programmed FPGA cycle duration (`duration_ticks / clock_hz`). |
| **FPGA Bitfile Trailing Space** | Hardware bitfile exports `dio4end ` with a trailing space. | Automatically resolved by `fpga_controller.py` register name normalizer. |
| **Physical AI Card Missing** | PXI AI card not yet physically installed in chassis. | `ai_controller.py` automatically detects absent card (`-200477`) and switches to high-fidelity live simulation mode. |

---

## 📜 License & Lab Credits

* **Software**: `lab18b daq`
* **Laboratory**: Cold Atom & Laser Spectroscopy Lab (Lab 18B), School of Physical Sciences.
* **Architecture**: Built with Python 3, PySide6, NumPy, `nifpga`, and `nidaqmx`.
# cold_atom_experiment_sequence
