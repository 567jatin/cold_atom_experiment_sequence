"""
Hardware configuration panel for FPGA and DAQ connections.

Provides controls for connecting to FPGA hardware, configuring
DAQ analog output devices, and monitoring connection status.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QPushButton, QListWidget, QFileDialog,
    QFormLayout, QSizePolicy, QCheckBox, QScrollArea, QFrame,
    QComboBox,
)
from PySide6.QtCore import Signal, Qt

from .styles import StatusIndicator, create_status_row, STATUS_COLORS
from fpga_controller import FPGAController


class HardwarePanel(QWidget):
    """Panel for configuring and connecting to FPGA and DAQ hardware."""

    # Signals
    fpga_connect_requested = Signal()
    fpga_disconnect_requested = Signal()
    daq_initialize_requested = Signal()
    ai_initialize_requested = Signal()
    safe_stop_requested = Signal()
    simulation_mode_toggled = Signal(bool)
    bitfile_changed = Signal(str)
    resource_changed = Signal(str)
    device_changed = Signal(str)
    ai_device_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(6, 6, 6, 6)

        # Simulation Mode Toggle Banner
        sim_box = QHBoxLayout()
        self._sim_chk = QCheckBox("⚡ Simulation Mode (Full software operation without physical PXI hardware)")
        self._sim_chk.setStyleSheet("color: #00d4ff; font-weight: bold; font-size: 13px; padding: 4px;")
        self._sim_chk.toggled.connect(self.simulation_mode_toggled.emit)
        sim_box.addWidget(self._sim_chk)
        sim_box.addStretch()
        main_layout.addLayout(sim_box)

        # --- FPGA Section ---
        main_layout.addWidget(self._create_fpga_group())

        # --- Analog Output Section ---
        main_layout.addWidget(self._create_daq_group())

        # --- Analog Input Section ---
        main_layout.addWidget(self._create_ai_group())

        # --- Bottom buttons ---
        main_layout.addLayout(self._create_button_row())

        main_layout.addStretch()

        scroll.setWidget(container)
        root_layout.addWidget(scroll)

    def _create_fpga_group(self) -> QGroupBox:
        group = QGroupBox("FPGA Configuration")
        layout = QFormLayout(group)
        layout.setSpacing(8)

        # Bitfile path
        bitfile_row = QHBoxLayout()
        self._bitfile_edit = QLineEdit(FPGAController.DEFAULT_BITFILE)
        self._bitfile_edit.setPlaceholderText("Select FPGA bitfile (.lvbitx)...")
        self._bitfile_edit.setReadOnly(True)
        self._bitfile_browse_btn = QPushButton("Browse…")
        self._bitfile_browse_btn.setFixedWidth(80)
        self._bitfile_browse_btn.clicked.connect(self._browse_bitfile)
        bitfile_row.addWidget(self._bitfile_edit)
        bitfile_row.addWidget(self._bitfile_browse_btn)
        layout.addRow("Bitfile:", bitfile_row)

        # Resource name
        self._resource_edit = QLineEdit("RIO0")
        self._resource_edit.editingFinished.connect(
            lambda: self.resource_changed.emit(self._resource_edit.text())
        )
        layout.addRow("Resource:", self._resource_edit)

        # Clock frequency (read-only)
        self._clock_label = QLineEdit("40.000 MHz")
        self._clock_label.setReadOnly(True)
        self._clock_label.setObjectName("lbl_mono")
        layout.addRow("Clock Freq:", self._clock_label)

        # Connection status
        (self._fpga_status_widget,
         self._fpga_indicator,
         self._fpga_status_label) = create_status_row(
            "Status", STATUS_COLORS["disconnected"], "Disconnected"
        )
        layout.addRow("Status:", self._fpga_status_widget)

        # Connect / Disconnect buttons
        btn_row = QHBoxLayout()
        self._fpga_connect_btn = QPushButton("Connect")
        self._fpga_connect_btn.clicked.connect(self.fpga_connect_requested.emit)
        self._fpga_disconnect_btn = QPushButton("Disconnect")
        self._fpga_disconnect_btn.setEnabled(False)
        self._fpga_disconnect_btn.clicked.connect(self.fpga_disconnect_requested.emit)
        btn_row.addWidget(self._fpga_connect_btn)
        btn_row.addWidget(self._fpga_disconnect_btn)
        btn_row.addStretch()
        layout.addRow("", btn_row)

        # Register list
        self._register_list = QListWidget()
        self._register_list.setMaximumHeight(120)
        self._register_list.setAlternatingRowColors(True)
        layout.addRow("Registers:", self._register_list)

        return group

    def _create_daq_group(self) -> QGroupBox:
        group = QGroupBox("Analog Output (DAQ)")
        layout = QFormLayout(group)
        layout.setSpacing(8)

        # Device name
        self._device_edit = QLineEdit("PXI2Slot3")
        self._device_edit.editingFinished.connect(
            lambda: self.device_changed.emit(self._device_edit.text())
        )
        layout.addRow("Device:", self._device_edit)

        # Available AO channels
        self._ao_channel_list = QListWidget()
        self._ao_channel_list.setMaximumHeight(100)
        self._ao_channel_list.setAlternatingRowColors(True)
        layout.addRow("AO Channels:", self._ao_channel_list)

        # Status
        (self._daq_status_widget,
         self._daq_indicator,
         self._daq_status_label) = create_status_row(
            "Status", STATUS_COLORS["uninitialized"], "Not Initialized"
        )
        layout.addRow("Status:", self._daq_status_widget)

        # Initialize button
        self._daq_init_btn = QPushButton("Initialize DAQ")
        self._daq_init_btn.clicked.connect(self.daq_initialize_requested.emit)
        layout.addRow("", self._daq_init_btn)

        # Device info
        self._device_info_label = QLabel("No device info available")
        self._device_info_label.setWordWrap(True)
        self._device_info_label.setStyleSheet("color: #8888a0; font-size: 11px;")
        layout.addRow("Info:", self._device_info_label)

        return group

    def _create_ai_group(self) -> QGroupBox:
        group = QGroupBox("Analog Input (AI) Card Configuration")
        layout = QFormLayout(group)
        layout.setSpacing(8)

        # AI Device name with auto-detect button
        ai_row = QHBoxLayout()
        self._ai_device_edit = QLineEdit("PXI2Slot4")
        self._ai_device_edit.setPlaceholderText("e.g. PXI2Slot4, Dev1...")
        self._ai_device_edit.editingFinished.connect(
            lambda: self.ai_device_changed.emit(self._ai_device_edit.text())
        )
        self._btn_ai_detect = QPushButton("Auto-Detect")
        self._btn_ai_detect.setFixedWidth(90)
        self._btn_ai_detect.setToolTip("Auto-discover any NI Analog Input card connected to the system")
        self._btn_ai_detect.clicked.connect(self._auto_detect_ai)
        ai_row.addWidget(self._ai_device_edit)
        ai_row.addWidget(self._btn_ai_detect)
        layout.addRow("AI Card Device:", ai_row)

        # Terminal configuration
        self._ai_term_combo = QComboBox()
        self._ai_term_combo.addItems([
            "Differential (DIFF)",
            "Referenced Single-Ended (RSE)",
            "Non-Referenced (NRSE)",
            "Default"
        ])
        layout.addRow("Terminal Config:", self._ai_term_combo)

        # Available AI channels
        self._ai_channel_list = QListWidget()
        self._ai_channel_list.setMaximumHeight(85)
        self._ai_channel_list.setAlternatingRowColors(True)
        layout.addRow("AI Channels:", self._ai_channel_list)

        # Status
        (self._ai_status_widget,
         self._ai_indicator,
         self._ai_status_label) = create_status_row(
            "Status", STATUS_COLORS["uninitialized"], "Not Initialized"
        )
        layout.addRow("Status:", self._ai_status_widget)

        # Initialize button
        self._ai_init_btn = QPushButton("Initialize AI Card")
        self._ai_init_btn.clicked.connect(self.ai_initialize_requested.emit)
        layout.addRow("", self._ai_init_btn)

        # Device info
        self._ai_info_label = QLabel("Ready for AI card installation")
        self._ai_info_label.setWordWrap(True)
        self._ai_info_label.setStyleSheet("color: #8888a0; font-size: 11px;")
        layout.addRow("Info:", self._ai_info_label)

        return group

    def _auto_detect_ai(self):
        from ai_controller import AIController
        devices = AIController.discover_ai_devices()
        if devices:
            self._ai_device_edit.setText(devices[0]["name"])
            self.ai_device_changed.emit(devices[0]["name"])
            self.update_ai_status(True, devices[0]["ai_channels"], {
                "Product": devices[0]["product_type"],
                "Channels": len(devices[0]["ai_channels"]),
            })
        else:
            self._ai_info_label.setText("No physical AI card detected. Running in Simulation Mode.")

    def _create_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()

        btn_init_all = QPushButton("Initialize All Hardware")
        btn_init_all.clicked.connect(self._initialize_all)

        btn_safe_stop = QPushButton("Safe Stop All")
        btn_safe_stop.setObjectName("btn_stop")
        btn_safe_stop.clicked.connect(self.safe_stop_requested.emit)

        btn_refresh = QPushButton("Refresh Status")
        btn_refresh.clicked.connect(self._refresh_status)

        row.addWidget(btn_init_all)
        row.addWidget(btn_safe_stop)
        row.addWidget(btn_refresh)
        row.addStretch()
        return row

    # ------------------------------------------------------------------
    # Slots / helpers
    # ------------------------------------------------------------------

    def _browse_bitfile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select FPGA Bitfile", "",
            "FPGA Bitfiles (*.lvbitx);;All Files (*)"
        )
        if path:
            self._bitfile_edit.setText(path)
            self.bitfile_changed.emit(path)

    def _initialize_all(self):
        self.fpga_connect_requested.emit()
        self.daq_initialize_requested.emit()

    def _refresh_status(self):
        # Simply re-emits the connect signals so the controller can
        # re-check status.  Actual refresh logic lives in the controller.
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_fpga_status(self, connected: bool, message: str):
        """Update the FPGA connection status display."""
        if connected:
            color = STATUS_COLORS["connected"]
            self._fpga_connect_btn.setEnabled(False)
            self._fpga_disconnect_btn.setEnabled(True)
        else:
            color = STATUS_COLORS["disconnected"]
            self._fpga_connect_btn.setEnabled(True)
            self._fpga_disconnect_btn.setEnabled(False)
        self._fpga_indicator.set_color(color)
        self._fpga_status_label.setText(message)
        self._fpga_status_label.setStyleSheet(f"color: {color};")

    def update_daq_status(self, initialized: bool, channels: list, info: dict):
        """Update the DAQ initialization status display."""
        if initialized:
            color = STATUS_COLORS["initialized"]
            self._daq_status_label.setText("Initialized")
        else:
            color = STATUS_COLORS["uninitialized"]
            self._daq_status_label.setText("Not Initialized")
        self._daq_indicator.set_color(color)
        self._daq_status_label.setStyleSheet(f"color: {color};")

        self._ao_channel_list.clear()
        for ch in channels:
            self._ao_channel_list.addItem(str(ch))

        if info:
            info_lines = [f"{k}: {v}" for k, v in info.items()]
            self._device_info_label.setText("\n".join(info_lines))
        else:
            self._device_info_label.setText("No device info available")

    def set_register_list(self, names: list):
        """Populate the register list display."""
        self._register_list.clear()
        for name in names:
            self._register_list.addItem(name)

    def get_bitfile(self) -> str:
        return self._bitfile_edit.text()

    def get_resource(self) -> str:
        return self._resource_edit.text()

    def get_device(self) -> str:
        return self._device_edit.text()

    def update_ai_status(self, initialized: bool, channels: list, info: dict):
        """Update the AI initialization status display."""
        if initialized:
            color = STATUS_COLORS["initialized"]
            self._ai_status_label.setText("Initialized")
        else:
            color = STATUS_COLORS["uninitialized"]
            self._ai_status_label.setText("Not Initialized")
        self._ai_indicator.set_color(color)
        self._ai_status_label.setStyleSheet(f"color: {color};")

        self._ai_channel_list.clear()
        for ch in channels:
            self._ai_channel_list.addItem(str(ch))

        if info:
            info_lines = [f"{k}: {v}" for k, v in info.items()]
            self._ai_info_label.setText("\n".join(info_lines))
        else:
            self._ai_info_label.setText("Ready for AI card")

    def get_ai_device(self) -> str:
        return self._ai_device_edit.text()

    def get_ai_terminal_config(self) -> str:
        idx = self._ai_term_combo.currentIndex()
        mapping = ["DIFF", "RSE", "NRSE", "DEFAULT"]
        return mapping[idx] if 0 <= idx < len(mapping) else "DIFF"
