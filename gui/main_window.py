"""
Main application window for FPGA TTL and Analog Waveform Sequence Controller.

Integrates:
- Hardware configuration and status monitoring
- 20-channel digital TTL timing editor
- Graphical sequence timeline
- Tabbed analog waveform editor
- Trigger routing and synchronization panel
- Execution dashboard with real-time logging and safe shutdown
"""

from __future__ import annotations

import sys
import os
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QSplitter, QMenuBar, QMenu, QStatusBar, QFileDialog,
    QMessageBox, QLabel, QApplication,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QIcon

from sequence_model import (
    ExperimentSequence, DigitalEvent, AnalogEvent,
    TriggerMapping, TriggerEdge, WaveformType,
    RepeatMode, TimeUnit, FPGA_CLOCK_HZ,
    validate,
)
from fpga_controller import FPGAController
from daq_controller import DAQController
from ai_controller import AIController
from synchronization import SynchronizationManager
from logging_utils import get_app_logger, LogSignalHandler

from .styles import get_stylesheet, StatusIndicator, STATUS_COLORS
from .hardware_panel import HardwarePanel
from .digital_editor import DigitalSequenceEditor
from .analog_editor import AnalogWaveformEditor
from .trigger_panel import TriggerMappingPanel
from .execution_panel import ExecutionPanel
from .timeline_widget import TimelineWidget
from .simulation_viewer import SimulationViewerWidget
from .oscilloscope_widget import OscilloscopeWidget

logger = get_app_logger(__name__)


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("lab18b daq - FPGA TTL & Analog Sequence Controller")

        # Set Application & Window Icon
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for icon_candidate in [
            os.path.join(base_dir, "lab18b_daq.ico"),
            os.path.join(base_dir, "lab18b_daq_icon.png"),
        ]:
            if os.path.exists(icon_candidate):
                self.setWindowIcon(QIcon(icon_candidate))
                break

        # Responsive geometry fitting 1920x1080 display
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            w = min(1880, max(1280, avail.width() - 20))
            h = min(1010, max(700, avail.height() - 40))
            self.resize(w, h)
        else:
            self.resize(1760, 950)
        self.setMinimumSize(1100, 640)

        # Apply dark laboratory instrumentation stylesheet
        self.setStyleSheet(get_stylesheet())

        # Current sequence state
        self._current_filepath: Optional[str] = None
        self._sequence = ExperimentSequence()

        # Initialize hardware controllers
        self._fpga = FPGAController(parent=self)
        self._daq = DAQController(parent=self)
        self._ai = AIController(parent=self)
        self._sync = SynchronizationManager(self._fpga, self._daq, parent=self)

        # Build UI
        self._setup_menus()
        self._setup_central_ui()
        self._setup_status_bar()

        # Connect signals
        self._connect_signals()

        # Route app logging to execution panel
        self._setup_logging_bridge()

        # Load default or example sequence
        self._load_initial_sequence()

    # ── Menus ───────────────────────────────────────────────────────────

    def _setup_menus(self):
        menubar = self.menuBar()

        # ── File Menu ──
        file_menu = menubar.addMenu("&File")

        action_new = QAction("&New Sequence", self)
        action_new.setShortcut(QKeySequence.StandardKey.New)
        action_new.triggered.connect(self._new_sequence)
        file_menu.addAction(action_new)

        action_open = QAction("&Open Sequence…", self)
        action_open.setShortcut(QKeySequence.StandardKey.Open)
        action_open.triggered.connect(self._open_sequence)
        file_menu.addAction(action_open)

        action_save = QAction("&Save Sequence", self)
        action_save.setShortcut(QKeySequence.StandardKey.Save)
        action_save.triggered.connect(self._save_sequence)
        file_menu.addAction(action_save)

        action_save_as = QAction("Save Sequence &As…", self)
        action_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        action_save_as.triggered.connect(self._save_sequence_as)
        file_menu.addAction(action_save_as)

        file_menu.addSeparator()

        action_load_example = QAction("Load Example &Ramp Experiment", self)
        action_load_example.triggered.connect(self._load_example_experiment)
        file_menu.addAction(action_load_example)

        file_menu.addSeparator()

        action_exit = QAction("E&xit", self)
        action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

        # ── Hardware Menu ──
        hw_menu = menubar.addMenu("&Hardware")

        action_connect_fpga = QAction("Connect &FPGA Target", self)
        action_connect_fpga.triggered.connect(self._connect_fpga)
        hw_menu.addAction(action_connect_fpga)

        action_disconnect_fpga = QAction("Disconnect FPGA Target", self)
        action_disconnect_fpga.triggered.connect(self._disconnect_fpga)
        hw_menu.addAction(action_disconnect_fpga)

        hw_menu.addSeparator()

        action_init_daq = QAction("&Initialize NI-DAQmx PXI-6733", self)
        action_init_daq.triggered.connect(self._initialize_daq)
        hw_menu.addAction(action_init_daq)

        action_init_ai = QAction("Initialize Analog &Input (AI) Card", self)
        action_init_ai.triggered.connect(self._initialize_ai)
        hw_menu.addAction(action_init_ai)

        hw_menu.addSeparator()

        action_safe_stop = QAction("Safe Stop &All Hardware", self)
        action_safe_stop.triggered.connect(self._safe_stop_all)
        hw_menu.addAction(action_safe_stop)

        # ── Execution Menu ──
        exec_menu = menubar.addMenu("&Execution")

        action_val = QAction("&Validate Sequence", self)
        action_val.setShortcut(QKeySequence("F5"))
        action_val.triggered.connect(self._validate_sequence)
        exec_menu.addAction(action_val)

        action_arm = QAction("&Arm Analog Tasks", self)
        action_arm.triggered.connect(self._arm_analog_tasks)
        exec_menu.addAction(action_arm)

        action_start = QAction("&Start Experiment", self)
        action_start.setShortcut(QKeySequence("F6"))
        action_start.triggered.connect(self._start_experiment)
        exec_menu.addAction(action_start)

        action_stop = QAction("S&top Experiment", self)
        action_stop.setShortcut(QKeySequence("F7"))
        action_stop.triggered.connect(self._sync.stop)
        exec_menu.addAction(action_stop)

        exec_menu.addSeparator()

        action_estop = QAction("⚠ &EMERGENCY STOP", self)
        action_estop.setShortcut(QKeySequence("Esc"))
        action_estop.triggered.connect(self._sync.emergency_stop)
        exec_menu.addAction(action_estop)

        # ── View Menu ──
        view_menu = menubar.addMenu("&View")

        action_reset_view = QAction("&Reset Timeline Zoom/Pan", self)
        action_reset_view.triggered.connect(lambda: self._timeline.reset_view())
        view_menu.addAction(action_reset_view)

        # ── Help Menu ──
        help_menu = menubar.addMenu("&Help")

        action_about = QAction("&About…", self)
        action_about.triggered.connect(self._show_about_dialog)
        help_menu.addAction(action_about)

    # ── Central UI Layout ───────────────────────────────────────────────

    def _setup_central_ui(self):
        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        # ── 1. Sequence Builder Tab (Channels + Interactive Timeline) ──
        builder_tab = QWidget()
        builder_layout = QVBoxLayout(builder_tab)
        builder_layout.setContentsMargins(4, 4, 4, 4)

        builder_splitter = QSplitter(Qt.Orientation.Vertical)
        builder_splitter.setChildrenCollapsible(False)

        # Top half: Channels Tab (Analog AO0-AO7 & Digital DIO0-DIO20)
        channels_tabs = QTabWidget()
        self._analog_editor = AnalogWaveformEditor()
        self._digital_editor = DigitalSequenceEditor()
        channels_tabs.addTab(self._analog_editor, "∿ Analog Channels (8 Channels AO0–AO7)")
        channels_tabs.addTab(self._digital_editor, "⚡ Digital TTL Channels (Start & End Controls)")

        # Bottom half: Interactive Graphical Timeline
        self._timeline = TimelineWidget()

        builder_splitter.addWidget(self._timeline)
        builder_splitter.addWidget(channels_tabs)
        builder_splitter.setStretchFactor(0, 1)
        builder_splitter.setStretchFactor(1, 1)
        builder_splitter.setSizes([360, 420])

        builder_layout.addWidget(builder_splitter)
        self._tabs.addTab(builder_tab, "Sequence Builder (Channels & Timeline)")

        # ── 2. Sequence Simulation Tab (Signal vs. Time Multi-Channel Oscilloscope) ──
        self._sim_viewer = SimulationViewerWidget()
        self._tabs.addTab(self._sim_viewer, "Sequence Simulation (Signal vs. Time)")

        # ── 3. Live Oscilloscope & Analog Monitor Tab ──
        self._oscilloscope = OscilloscopeWidget(ai_controller=self._ai, parent=self)
        self._tabs.addTab(self._oscilloscope, "Live Oscilloscope & Output Monitor")

        # ── 4. Execution & Hardware Tab ──
        exec_hw_tab = QWidget()
        exec_hw_layout = QHBoxLayout(exec_hw_tab)
        exec_hw_layout.setContentsMargins(4, 4, 4, 4)

        exec_splitter = QSplitter(Qt.Orientation.Horizontal)
        exec_splitter.setChildrenCollapsible(False)
        self._hw_panel = HardwarePanel()
        self._hw_panel.setMinimumWidth(320)
        self._exec_panel = ExecutionPanel()

        exec_splitter.addWidget(self._hw_panel)
        exec_splitter.addWidget(self._exec_panel)
        exec_splitter.setStretchFactor(0, 1)
        exec_splitter.setStretchFactor(1, 3)
        exec_splitter.setSizes([380, 1200])

        exec_hw_layout.addWidget(exec_splitter)
        self._tabs.addTab(exec_hw_tab, "Execute & Hardware")

        # Background Trigger Routing Manager (Fixed 1-to-1 routing aoN ↔ Trig N)
        self._trigger_panel = TriggerMappingPanel()

        # Update simulation when switching to Simulation tab
        self._tabs.currentChanged.connect(self._on_central_tab_changed)

    # ── Status Bar ──────────────────────────────────────────────────────

    def _setup_status_bar(self):
        sb = self.statusBar()

        # FPGA indicator
        self._sb_fpga_ind = StatusIndicator(STATUS_COLORS["disconnected"], size=10)
        self._sb_fpga_lbl = QLabel("FPGA: Disconnected")
        self._sb_fpga_lbl.setStyleSheet("color: #8888a0; font-size: 11px; margin-right: 12px;")

        # DAQ indicator
        self._sb_daq_ind = StatusIndicator(STATUS_COLORS["uninitialized"], size=10)
        self._sb_daq_lbl = QLabel("DAQ: Uninitialized")
        self._sb_daq_lbl.setStyleSheet("color: #8888a0; font-size: 11px; margin-right: 16px;")

        # AI indicator
        self._sb_ai_ind = StatusIndicator(STATUS_COLORS["uninitialized"], size=10)
        self._sb_ai_lbl = QLabel("AI Card: Uninitialized")
        self._sb_ai_lbl.setStyleSheet("color: #8888a0; font-size: 11px; margin-right: 16px;")

        # File label
        self._sb_file_lbl = QLabel("Sequence: Untitled")
        self._sb_file_lbl.setStyleSheet("color: #00d4ff; font-size: 11px; margin-right: 16px;")

        # Duration label
        self._sb_dur_lbl = QLabel("Duration: 1.000 s (40,000,000 ticks)")
        self._sb_dur_lbl.setStyleSheet("color: #00ff88; font-size: 11px;")

        sb.addWidget(self._sb_fpga_ind)
        sb.addWidget(self._sb_fpga_lbl)
        sb.addWidget(self._sb_daq_ind)
        sb.addWidget(self._sb_daq_lbl)
        sb.addWidget(self._sb_ai_ind)
        sb.addWidget(self._sb_ai_lbl)
        sb.addWidget(self._sb_file_lbl)
        sb.addPermanentWidget(self._sb_dur_lbl)

    # ── Signal Wiring ───────────────────────────────────────────────────

    def _connect_signals(self):
        # Hardware panel requests
        self._hw_panel.fpga_connect_requested.connect(self._connect_fpga)
        self._hw_panel.fpga_disconnect_requested.connect(self._disconnect_fpga)
        self._hw_panel.daq_initialize_requested.connect(self._initialize_daq)
        self._hw_panel.ai_initialize_requested.connect(self._initialize_ai)
        self._hw_panel.safe_stop_requested.connect(self._safe_stop_all)
        self._hw_panel.simulation_mode_toggled.connect(self._on_simulation_toggled)

        # Hardware panel config changes
        self._hw_panel.bitfile_changed.connect(self._on_bitfile_changed)
        self._hw_panel.resource_changed.connect(lambda r: setattr(self._fpga, "_resource", r))
        self._hw_panel.device_changed.connect(lambda d: setattr(self._daq, "_device_name", d))
        self._hw_panel.ai_device_changed.connect(lambda d: setattr(self._ai, "_device_name", d))

        # Hardware controllers → Status updates
        self._fpga.connected.connect(self._on_fpga_connected)
        self._fpga.disconnected.connect(self._on_fpga_disconnected)
        self._fpga.error_occurred.connect(self._on_fpga_error)
        self._fpga.channels_discovered.connect(self._on_channels_discovered)

        self._daq.initialized.connect(self._on_daq_initialized)
        self._daq.error_occurred.connect(self._on_daq_error)

        # Editor edits → Bidirectional trigger sync & Timeline refresh
        self._syncing_editors = False
        self._digital_editor.sequence_changed.connect(self._on_digital_editor_changed)
        self._digital_editor.duration_changed.connect(self._on_duration_changed)
        self._digital_editor.auto_detect_requested.connect(self._auto_detect_channels)
        self._analog_editor.analog_events_changed.connect(self._on_analog_editor_changed)
        self._timeline.sequence_modified.connect(self._on_timeline_modified)

        # Execution panel controls
        self._exec_panel.validate_requested.connect(self._validate_sequence)
        self._exec_panel.configure_requested.connect(self._configure_hardware)
        self._exec_panel.arm_requested.connect(self._arm_analog_tasks)
        self._exec_panel.start_requested.connect(self._start_experiment)
        self._exec_panel.stop_requested.connect(self._sync.stop)
        self._exec_panel.stop_requested.connect(self._oscilloscope.stop_execution_sweep)
        self._exec_panel.emergency_stop_requested.connect(self._sync.emergency_stop)
        self._exec_panel.emergency_stop_requested.connect(self._oscilloscope.stop_execution_sweep)

        # Synchronization manager → Execution panel
        self._sync.phase_changed.connect(self._exec_panel.set_phase)
        self._sync.progress.connect(self._exec_panel.set_progress)
        self._sync.elapsed_time.connect(self._exec_panel.set_elapsed_time)
        self._sync.trigger_count.connect(self._exec_panel.set_trigger_count)
        self._sync.is_running_changed.connect(self._exec_panel.set_running)
        self._sync.completed.connect(self._on_execution_completed)
        self._sync.error_occurred.connect(self._on_execution_error)

    def _setup_logging_bridge(self):
        """Forward Python log records to GUI Execution Panel log widget."""
        handler = LogSignalHandler()
        handler.log_message.connect(lambda lvl, msg: self._exec_panel.append_log(msg, lvl))
        logger.addHandler(handler)

    # ── Hardware Slots ──────────────────────────────────────────────────

    def _on_simulation_toggled(self, enabled: bool):
        self._fpga.simulation_mode = enabled
        self._daq.simulation_mode = enabled
        self._ai.simulation_mode = enabled
        mode_str = "Simulation Mode (Design & test without hardware)" if enabled else "Physical Hardware Mode"
        self._exec_panel.append_log(f"Switched hardware target to: {mode_str}.", "INFO")

    def _connect_fpga(self):
        self._exec_panel.append_log(f"Connecting to FPGA resource {self._hw_panel.get_resource()}…", "INFO")
        self._fpga._bitfile = self._hw_panel.get_bitfile()
        self._fpga._resource = self._hw_panel.get_resource()
        self._fpga.connect()

    def _disconnect_fpga(self):
        self._fpga.disconnect()

    def _on_bitfile_changed(self, path: str):
        self._fpga._bitfile = path
        self._auto_detect_channels()

    def _auto_detect_channels(self):
        channels = self._fpga.refresh_channels()
        regs = self._fpga.get_register_names()
        self._hw_panel.set_register_list(regs)
        self._exec_panel.append_log(
            f"Auto-detected {len(channels)} digital channels with start/end registers: {[c['name'] for c in channels]}.",
            "INFO",
        )

    def _on_channels_discovered(self, channels: list):
        self._digital_editor.set_channels(channels)
        self._sync_editors_to_timeline()

    def _on_fpga_connected(self):
        regs = self._fpga.get_register_names()
        channels = self._fpga.get_discovered_channels()
        self._hw_panel.update_fpga_status(True, f"Connected ({len(regs)} registers, {len(channels)} DIO)")
        self._hw_panel.set_register_list(regs)
        self._sb_fpga_ind.set_color(STATUS_COLORS["connected"])
        self._sb_fpga_lbl.setText(f"FPGA: Connected ({len(channels)} DIO)")
        self._exec_panel.append_log(
            f"FPGA connected successfully ({len(regs)} registers, {len(channels)} start/end channels discovered: {[c['name'] for c in channels]}).",
            "SUCCESS",
        )

    def _on_fpga_disconnected(self):
        self._hw_panel.update_fpga_status(False, "Disconnected")
        self._sb_fpga_ind.set_color(STATUS_COLORS["disconnected"])
        self._sb_fpga_lbl.setText("FPGA: Disconnected")
        self._exec_panel.append_log("FPGA disconnected.", "INFO")

    def _on_fpga_error(self, message: str):
        self._hw_panel.update_fpga_status(False, message)
        self._sb_fpga_ind.set_color(STATUS_COLORS["error"])
        self._sb_fpga_lbl.setText("FPGA: Error")
        self._exec_panel.append_log(f"FPGA Error: {message}", "ERROR")

    def _initialize_daq(self):
        self._exec_panel.append_log(f"Initializing DAQ device {self._hw_panel.get_device()}…", "INFO")
        self._daq._device_name = self._hw_panel.get_device()
        self._daq.initialize()

    def _on_daq_initialized(self):
        channels = self._daq.get_ao_channels()
        info = self._daq.get_device_info()
        self._hw_panel.update_daq_status(True, channels, info)
        self._analog_editor.set_available_channels(channels)
        self._sb_daq_ind.set_color(STATUS_COLORS["initialized"])
        self._sb_daq_lbl.setText(f"DAQ: Initialized ({len(channels)} AO)")
        self._exec_panel.append_log(f"DAQ initialized successfully ({len(channels)} AO channels discovered).", "SUCCESS")

    def _initialize_ai(self):
        dev = self._hw_panel.get_ai_device()
        t_cfg = self._hw_panel.get_ai_terminal_config()
        self._exec_panel.append_log(f"Initializing Analog Input card {dev}…", "INFO")
        self._ai._device_name = dev
        ok = self._ai.initialize(device_name=dev, allow_simulation=True)
        if ok:
            chans = self._ai.get_channels()
            self._hw_panel.update_ai_status(True, chans, {
                "Card": dev,
                "Mode": "Simulated" if self._ai.simulation_mode else "Physical Hardware",
                "Channels": len(chans),
                "Terminal Config": t_cfg,
            })
            self._sb_ai_ind.set_color(STATUS_COLORS["initialized"])
            self._sb_ai_lbl.setText(f"AI: {dev} ({'Sim' if self._ai.simulation_mode else 'HW'})")
            self._exec_panel.append_log(
                f"Analog Input card initialized ({dev}) with {len(chans)} channels ({'Simulated' if self._ai.simulation_mode else 'Hardware'}).",
                "SUCCESS",
            )
        else:
            self._hw_panel.update_ai_status(False, [], {})
            self._sb_ai_ind.set_color(STATUS_COLORS["error"])
            self._sb_ai_lbl.setText("AI: Error")
            self._exec_panel.append_log(f"Failed to initialize Analog Input card {dev}.", "ERROR")

    def _on_daq_error(self, message: str):
        self._hw_panel.update_daq_status(False, [], {})
        self._sb_daq_ind.set_color(STATUS_COLORS["error"])
        self._sb_daq_lbl.setText("DAQ: Error")
        self._exec_panel.append_log(f"DAQ Error: {message}", "ERROR")

    def _safe_stop_all(self):
        self._exec_panel.append_log("Global Safe Stop initiated.", "WARN")
        self._sync.emergency_stop()
        self._oscilloscope.stop_execution_sweep()
        self._exec_panel.set_phase("Safe State")

    # ── Execution Slots ─────────────────────────────────────────────────

    def _validate_sequence(self):
        seq = self._build_sequence()
        messages = self._sync.validate_sequence(seq)
        self._exec_panel.show_validation_results(messages)
        errors = [m for m in messages if m.level == "error"]
        if errors:
            self._exec_panel.append_log(f"Validation failed with {len(errors)} error(s).", "ERROR")
        else:
            self._exec_panel.append_log("Sequence validation passed successfully.", "SUCCESS")
        return len(errors) == 0

    def _configure_hardware(self):
        seq = self._build_sequence()
        if not self._validate_sequence():
            QMessageBox.warning(self, "Validation Failed", "Please resolve validation errors before configuring hardware.")
            return

        self._exec_panel.set_phase("Configuring Hardware")
        try:
            self._fpga.configure_sequence(seq)
            self._exec_panel.append_log("FPGA numeric controls configured.", "SUCCESS")
        except Exception as exc:
            self._exec_panel.append_log(f"FPGA configuration failed: {exc}", "ERROR")

    def _arm_analog_tasks(self):
        self._exec_panel.set_phase("Arming Analog")
        try:
            self._daq.arm_all_tasks()
            self._exec_panel.append_log("All analog output tasks armed and waiting for triggers.", "SUCCESS")
        except Exception as exc:
            self._exec_panel.append_log(f"Arming analog tasks failed: {exc}", "ERROR")

    def _start_experiment(self):
        seq = self._build_sequence()
        if not self._validate_sequence():
            self._tabs.setCurrentIndex(3)
            QMessageBox.warning(self, "Validation Failed", "Sequence validation failed. Review the errors before starting.")
            return

        # Switch to execute tab
        self._tabs.setCurrentIndex(3)
        self._exec_panel.append_log("▶ Starting experiment sequence execution…", "INFO")
        # Load active waveforms into oscilloscope and start live monitor sweep
        self._oscilloscope.load_sequence_waveforms(seq)
        self._oscilloscope.start_execution_sweep()
        self._sync.execute_sequence(seq)

    def _on_execution_completed(self):
        self._exec_panel.append_log("✔ Experiment sequence completed.", "SUCCESS")
        self._oscilloscope.stop_execution_sweep()

    def _on_execution_error(self, message: str):
        self._exec_panel.append_log(f"Execution Error: {message}", "ERROR")
        self._oscilloscope.stop_execution_sweep()
        QMessageBox.critical(self, "Execution Error", message)

    # ── Sequence Model & File I/O ───────────────────────────────────────

    def _build_sequence(self) -> ExperimentSequence:
        """Collect current values from all editor tabs into an ExperimentSequence."""
        duration_ticks = self._digital_editor.get_sequence_duration_ticks()
        rep_mode = self._digital_editor.get_repeat_mode()
        rep_count = self._digital_editor.get_repeat_count()
        ch_labels = self._digital_editor.get_channel_labels()

        # Digital events
        raw_devs = self._digital_editor.get_digital_events()
        d_events = []
        for d in raw_devs:
            if isinstance(d, DigitalEvent):
                d_events.append(d)
            elif isinstance(d, dict):
                d_events.append(DigitalEvent(**d))

        # Analog events
        raw_aevs = self._analog_editor.get_analog_events()
        a_events = []
        for a in raw_aevs:
            if isinstance(a, AnalogEvent):
                a_events.append(a)
            elif isinstance(a, dict):
                a_events.append(AnalogEvent(**a))

        # Digital events and analog events are preserved independently as set by the user.

        # Trigger mappings (Fixed automatic hardware routing aoN ↔ Trig N)
        t_mappings = self._trigger_panel.get_trigger_mappings()
        if not t_mappings:
            for i in range(8):
                trig_idx = i if i <= 5 else 0
                t_mappings.append(
                    TriggerMapping(
                        name=f"PXI_Trig{trig_idx} to AO{i}",
                        source_type="pxi_trigger",
                        source_channel=f"/PXI2Slot3/PXI_Trig{trig_idx}",
                        target_type="analog",
                        target_channel=f"PXI2Slot3/ao{i}",
                        trigger_edge=TriggerEdge.RISING,
                        enabled=True,
                        notes=f"Fixed 1-to-1 route for AO{i}",
                    )
                )

        seq = ExperimentSequence(
            name=os.path.basename(self._current_filepath) if self._current_filepath else "Untitled Sequence",
            clock_hz=FPGA_CLOCK_HZ,
            repeat_mode=rep_mode,
            repeat_count=rep_count,
            sequence_duration_ticks=duration_ticks,
            digital_events=d_events,
            analog_events=a_events,
            trigger_mappings=t_mappings,
            safe_voltage=0.0,
            channel_labels=ch_labels,
        )
        return seq

    def _load_sequence_into_ui(self, seq: ExperimentSequence):
        """Populate all editor tabs from an ExperimentSequence instance."""
        self._sequence = seq

        # Digital editor
        self._digital_editor.set_sequence_duration_ticks(seq.sequence_duration_ticks)
        if seq.channel_labels:
            self._digital_editor.set_channel_labels(seq.channel_labels)
        self._digital_editor.set_digital_events(seq.digital_events)

        # Analog editor
        self._analog_editor.set_analog_events(seq.analog_events)

        # Trigger mappings
        self._trigger_panel.set_trigger_mappings(seq.trigger_mappings)

        # Timeline
        self._timeline.set_sequence(seq)

        # Simulation Viewer
        self._sim_viewer.set_sequence(seq)

        # Oscilloscope
        self._oscilloscope.load_sequence_waveforms(seq)

        # Status bar update
        dur_s = seq.sequence_duration_ticks / seq.clock_hz
        self._sb_dur_lbl.setText(f"Duration: {dur_s:.3f} s ({seq.sequence_duration_ticks:,} ticks)")

    def _on_analog_editor_changed(self):
        """Update timeline, simulation, and oscilloscope when analog waveforms change."""
        self._sync_editors_to_timeline()

    def _on_digital_editor_changed(self):
        """Update timeline, simulation, and oscilloscope when digital TTL channels change."""
        self._sync_editors_to_timeline()

    def _sync_editors_to_timeline(self):
        """Update timeline whenever digital or analog events change."""
        seq = self._build_sequence()
        self._sequence = seq
        self._timeline.set_sequence(seq)
        self._sim_viewer.set_sequence(seq)
        self._oscilloscope.load_sequence_waveforms(seq)

    def _on_central_tab_changed(self, index: int):
        seq = self._build_sequence()
        self._sequence = seq
        if index == 1:  # Switched to Sequence Simulation Tab
            self._sim_viewer.set_sequence(seq)
            self._sim_viewer.run_simulation()
        elif index == 2:  # Switched to Live Oscilloscope & Monitor Tab
            self._oscilloscope.load_sequence_waveforms(seq)

    def _on_timeline_modified(self):
        """Called when user draws, moves, resizes, or edits pulses directly on the timeline."""
        seq = getattr(self._timeline._canvas, "_sequence", None)
        if seq is None:
            return
        self._sequence = seq

        self._syncing_editors = True
        try:
            self._digital_editor.set_digital_events(seq.digital_events)
            self._analog_editor.set_analog_events(seq.analog_events)
        finally:
            self._syncing_editors = False

        self._sim_viewer.set_sequence(seq)
        self._oscilloscope.load_sequence_waveforms(seq)

    def _on_duration_changed(self, ticks: int):
        dur_s = ticks / FPGA_CLOCK_HZ
        self._sb_dur_lbl.setText(f"Duration: {dur_s:.3f} s ({ticks:,} ticks)")
        self._sync_editors_to_timeline()

    def _new_sequence(self):
        self._current_filepath = None
        self._sb_file_lbl.setText("Sequence: Untitled")
        seq = ExperimentSequence()
        self._load_sequence_into_ui(seq)
        self._exec_panel.append_log("Created new sequence configuration.", "INFO")

    def _open_sequence(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open Sequence Configuration", "",
            "JSON Sequence (*.json);;All Files (*)"
        )
        if not filepath:
            return

        try:
            seq = ExperimentSequence.load_json(filepath)
            self._current_filepath = filepath
            self._sb_file_lbl.setText(f"Sequence: {os.path.basename(filepath)}")
            self._load_sequence_into_ui(seq)
            self._exec_panel.append_log(f"Loaded sequence from {filepath}", "SUCCESS")
        except Exception as exc:
            logger.error("Failed to load sequence file: %s", exc)
            QMessageBox.critical(self, "Load Error", f"Failed to load sequence file:\n{exc}")

    def _save_sequence(self):
        if not self._current_filepath:
            self._save_sequence_as()
            return

        try:
            seq = self._build_sequence()
            seq.save_json(self._current_filepath)
            self._exec_panel.append_log(f"Saved sequence to {self._current_filepath}", "SUCCESS")
        except Exception as exc:
            logger.error("Failed to save sequence file: %s", exc)
            QMessageBox.critical(self, "Save Error", f"Failed to save sequence file:\n{exc}")

    def _save_sequence_as(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Sequence Configuration As", "",
            "JSON Sequence (*.json);;All Files (*)"
        )
        if not filepath:
            return

        if not filepath.endswith(".json"):
            filepath += ".json"

        self._current_filepath = filepath
        self._sb_file_lbl.setText(f"Sequence: {os.path.basename(filepath)}")
        self._save_sequence()

    def _load_initial_sequence(self):
        """Load default ramp experiment JSON if available, or initialize clean."""
        ex_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "examples", "example_ramp_experiment.json"
        )
        if os.path.exists(ex_path):
            try:
                seq = ExperimentSequence.load_json(ex_path)
                self._current_filepath = ex_path
                self._sb_file_lbl.setText(f"Sequence: {os.path.basename(ex_path)}")
                self._load_sequence_into_ui(seq)
                self._exec_panel.append_log(f"Auto-loaded default experiment: {ex_path}", "INFO")
                return
            except Exception as exc:
                logger.warning("Could not auto-load example experiment: %s", exc)

        self._new_sequence()

    def _load_example_experiment(self):
        ex_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "examples", "example_ramp_experiment.json"
        )
        if os.path.exists(ex_path):
            try:
                seq = ExperimentSequence.load_json(ex_path)
                self._current_filepath = ex_path
                self._sb_file_lbl.setText(f"Sequence: {os.path.basename(ex_path)}")
                self._load_sequence_into_ui(seq)
                self._exec_panel.append_log(f"Loaded example ramp experiment: {ex_path}", "SUCCESS")
            except Exception as exc:
                QMessageBox.critical(self, "Load Error", f"Failed to load example experiment:\n{exc}")
        else:
            QMessageBox.warning(self, "Not Found", f"Example file not found at: {ex_path}")

    def _show_about_dialog(self):
        QMessageBox.about(
            self,
            "About lab18b daq",
            "<b>lab18b daq</b><br>"
            "FPGA TTL & Analog Waveform Sequence Controller<br>"
            "Version 1.2.0<br><br>"
            "Designed for NQM Lab (Lab 18B) cold-atom & laser spectroscopy experiments.<br><br>"
            "<b>Hardware Targets:</b><br>"
            "• NI PXIe-7820R FPGA (40 MHz TTL Digital Output, DIO0–DIO20)<br>"
            "• NI PXI-6733 (High-Speed Analog Waveform Output, AO0–AO7)<br>"
            "• NI PXI Analog Input Card (Live Streaming Oscilloscope & Monitor)<br><br>"
            "Built with PySide6, nifpga, and NI-DAQmx."
        )

    def closeEvent(self, event):
        """Ensure safe shutdown when user closes the window."""
        if self._sync.is_running():
            reply = QMessageBox.question(
                self,
                "Experiment Running",
                "An experiment sequence is currently running. Stop it safely and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._sync.emergency_stop()
                event.accept()
            else:
                event.ignore()
                return

        # Perform safe shutdown
        try:
            self._fpga.stop()
            self._fpga.disconnect()
            self._daq.stop_all_tasks()
            self._daq.clear_all_tasks()
        except Exception:
            pass

        event.accept()
