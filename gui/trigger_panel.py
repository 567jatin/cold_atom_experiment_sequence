"""
Trigger mapping and synchronization routing panel.

Provides configuration for routing digital triggers and PXI backplane lines
to analog output tasks and external experimental equipment.
"""

from __future__ import annotations

import sys
import os
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QComboBox, QPushButton,
    QCheckBox, QAbstractItemView, QGroupBox, QMessageBox,
)
from PySide6.QtCore import Signal, Qt

from sequence_model import TriggerMapping, TriggerEdge


COL_ENABLE = 0
COL_NAME = 1
COL_SRC_TYPE = 2
COL_SRC_CHAN = 3
COL_TGT_TYPE = 4
COL_TGT_CHAN = 5
COL_EDGE = 6
COL_NOTES = 7
NUM_COLS = 8

COL_HEADERS = [
    "Enable", "Name", "Source Type", "Source Channel",
    "Target Type", "Target Channel", "Edge", "Notes",
]


class TriggerMappingPanel(QWidget):
    """Panel for configuring trigger routing and synchronization."""

    mappings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._suppress_signals = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Info Box
        info_group = QGroupBox("Hardware Trigger Routing & Synchronization Principles")
        info_layout = QVBoxLayout(info_group)
        info_text = QLabel(
            "<b>Hardware Synchronization Guidelines:</b><br>"
            "• <b>PXI Backplane Triggers vs. Physical DIO:</b> Distinguish clearly between physical "
            "FPGA DIO pins and PXI chassis backplane trigger lines (e.g. <code>/PXI2Slot3/PXI_Trig0</code>). "
            "They are physically separate buses unless internally routed via NI-VISA / chassis routing.<br>"
            "• <b>Analog Output Start Trigger:</b> The PXI-6733 task listens by default on "
            "<code>/PXI2Slot3/PXI_Trig0</code> rising edge. Ensure your FPGA VI or timing sequence pulses this line.<br>"
            "• <b>Sequence Duration Coordination:</b> FPGA counter repeats automatically. Analog waveforms "
            "must complete before the next trigger arrival to prevent task collision errors."
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #a0a0b8; font-size: 12px; line-height: 1.4;")
        info_layout.addWidget(info_text)
        layout.addWidget(info_group)

        # Quick Add Presets
        presets_group = QGroupBox("Predefined Quick Routing Presets")
        presets_layout = QHBoxLayout(presets_group)

        btn_auto_map = QPushButton("⚡ Auto-Map All (aoN ↔ Trig N)")
        btn_auto_map.setStyleSheet("font-weight: bold; color: #00ff88;")
        btn_auto_map.setToolTip("Automatically configure 1-to-1 routes: ao0 ↔ Trig0, ao1 ↔ Trig1, ... ao7 ↔ Trig7")
        btn_auto_map.clicked.connect(self._auto_map_all_ao_triggers)
        presets_layout.addWidget(btn_auto_map)

        btn_preset1 = QPushButton("+ Quick Add: DIO3 → PXI_Trig0")
        btn_preset1.setToolTip("Route DIO3 pulse to trigger Analog Output via PXI_Trig0")
        btn_preset1.clicked.connect(self._add_preset_ao_trigger)
        presets_layout.addWidget(btn_preset1)

        btn_preset2 = QPushButton("+ Quick Add: PXI_Trig0 → AO0 Ramp")
        btn_preset2.setToolTip("Configure AO0 ramp trigger on PXI_Trig0")
        btn_preset2.clicked.connect(self._add_preset_ao_start)
        presets_layout.addWidget(btn_preset2)

        btn_preset3 = QPushButton("+ Quick Add: DIO4 → Camera Trigger")
        btn_preset3.setToolTip("Route DIO4 pulse to external camera TTL trigger")
        btn_preset3.clicked.connect(self._add_preset_camera_trigger)
        presets_layout.addWidget(btn_preset3)

        presets_layout.addStretch()
        layout.addWidget(presets_group)

        # Table & Controls
        table_group = QGroupBox("Active Trigger Routes")
        table_layout = QVBoxLayout(table_group)

        # Button row
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add Route")
        add_btn.clicked.connect(self._add_empty_row)
        btn_row.addWidget(add_btn)

        remove_btn = QPushButton("− Remove Selected")
        remove_btn.clicked.connect(self._remove_selected_row)
        btn_row.addWidget(remove_btn)

        clear_btn = QPushButton("Clear All Routes")
        clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(clear_btn)

        btn_row.addStretch()
        table_layout.addLayout(btn_row)

        # Table
        self._table = QTableWidget(0, NUM_COLS)
        self._table.setHorizontalHeaderLabels(COL_HEADERS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            COL_ENABLE, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            COL_NAME, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            COL_SRC_TYPE, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            COL_EDGE, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.cellChanged.connect(self._on_cell_changed)
        table_layout.addWidget(self._table)

        layout.addWidget(table_group)

    # ── Presets ──────────────────────────────────────────────────────────

    def _auto_map_all_ao_triggers(self):
        """Automatically create clean 1-to-1 trigger routes: ao0 <- Trig0, ao1 <- Trig1, etc."""
        self._table.setRowCount(0)
        for i in range(8):
            trig_idx = i if i <= 5 else 0
            mapping = TriggerMapping(
                name=f"PXI_Trig{trig_idx} to AO{i}",
                source_type="pxi_trigger",
                source_channel=f"/PXI2Slot3/PXI_Trig{trig_idx}",
                target_type="analog",
                target_channel=f"PXI2Slot3/ao{i}",
                trigger_edge=TriggerEdge.RISING,
                enabled=True,
                notes=f"Trigger AO{i} via backplane PXI_Trig{trig_idx}",
            )
            self._append_mapping_row(mapping)
        self.mappings_changed.emit()

    def _add_preset_ao_trigger(self):
        mapping = TriggerMapping(
            name="DIO3 to PXI_Trig0",
            source_type="digital",
            source_channel="DIO3",
            target_type="analog",
            target_channel="PXI2Slot3/ao0",
            trigger_edge=TriggerEdge.RISING,
            enabled=True,
            notes="DIO3 pulse triggers analog ramp via PXI backplane",
        )
        self._append_mapping_row(mapping)
        self.mappings_changed.emit()

    def _add_preset_ao_start(self):
        mapping = TriggerMapping(
            name="PXI_Trig0 AO Start",
            source_type="pxi_trigger",
            source_channel="/PXI2Slot3/PXI_Trig0",
            target_type="analog",
            target_channel="PXI2Slot3/ao0",
            trigger_edge=TriggerEdge.RISING,
            enabled=True,
            notes="PXI backplane trigger initiates finite waveform",
        )
        self._append_mapping_row(mapping)
        self.mappings_changed.emit()

    def _add_preset_camera_trigger(self):
        mapping = TriggerMapping(
            name="DIO4 Camera Trigger",
            source_type="digital",
            source_channel="DIO4",
            target_type="external",
            target_channel="Camera Trig In",
            trigger_edge=TriggerEdge.RISING,
            enabled=True,
            notes="Synchronous camera acquisition pulse",
        )
        self._append_mapping_row(mapping)
        self.mappings_changed.emit()

    # ── Row manipulation ─────────────────────────────────────────────────

    def _add_empty_row(self):
        mapping = TriggerMapping(
            name=f"Route {self._table.rowCount() + 1}",
            source_type="digital",
            source_channel="DIO0",
            target_type="analog",
            target_channel="PXI2Slot3/ao0",
            trigger_edge=TriggerEdge.RISING,
            enabled=True,
            notes="",
        )
        self._append_mapping_row(mapping)
        self.mappings_changed.emit()

    def _append_mapping_row(self, mapping: TriggerMapping):
        self._suppress_signals = True
        row = self._table.rowCount()
        self._table.insertRow(row)

        # Enable checkbox widget
        chk_container = QWidget()
        chk_layout = QHBoxLayout(chk_container)
        chk_layout.setContentsMargins(4, 2, 4, 2)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk = QCheckBox()
        chk.setChecked(mapping.enabled)
        chk.toggled.connect(lambda checked: self.mappings_changed.emit())
        chk_layout.addWidget(chk)
        self._table.setCellWidget(row, COL_ENABLE, chk_container)

        # Name
        self._table.setItem(row, COL_NAME, QTableWidgetItem(mapping.name))

        # Source Type
        combo_src = QComboBox()
        combo_src.addItems(["digital", "pxi_trigger"])
        combo_src.setCurrentText(mapping.source_type)
        combo_src.currentTextChanged.connect(lambda _: self.mappings_changed.emit())
        self._table.setCellWidget(row, COL_SRC_TYPE, combo_src)

        # Source Channel
        self._table.setItem(row, COL_SRC_CHAN, QTableWidgetItem(mapping.source_channel))

        # Target Type
        combo_tgt = QComboBox()
        combo_tgt.addItems(["analog", "external"])
        combo_tgt.setCurrentText(mapping.target_type)
        combo_tgt.currentTextChanged.connect(lambda _: self.mappings_changed.emit())
        self._table.setCellWidget(row, COL_TGT_TYPE, combo_tgt)

        # Target Channel
        self._table.setItem(row, COL_TGT_CHAN, QTableWidgetItem(mapping.target_channel))

        # Edge
        combo_edge = QComboBox()
        combo_edge.addItems(["rising", "falling"])
        edge_text = mapping.trigger_edge.value if hasattr(mapping.trigger_edge, "value") else str(mapping.trigger_edge)
        combo_edge.setCurrentText(edge_text)
        combo_edge.currentTextChanged.connect(lambda _: self.mappings_changed.emit())
        self._table.setCellWidget(row, COL_EDGE, combo_edge)

        # Notes
        self._table.setItem(row, COL_NOTES, QTableWidgetItem(mapping.notes))

        self._suppress_signals = False

    def _remove_selected_row(self):
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)
            self.mappings_changed.emit()

    def _clear_all(self):
        self._table.setRowCount(0)
        self.mappings_changed.emit()

    def _on_cell_changed(self, row, col):
        if not self._suppress_signals:
            self.mappings_changed.emit()

    # ── Public API ──────────────────────────────────────────────────────

    def get_trigger_mappings(self) -> List[TriggerMapping]:
        """Return the list of configured TriggerMapping objects."""
        mappings: List[TriggerMapping] = []
        for row in range(self._table.rowCount()):
            # Enable
            chk_w = self._table.cellWidget(row, COL_ENABLE)
            enabled = True
            if chk_w:
                chk = chk_w.findChild(QCheckBox)
                if chk:
                    enabled = chk.isChecked()

            # Name
            name_item = self._table.item(row, COL_NAME)
            name = name_item.text() if name_item else f"Route {row + 1}"

            # Source Type
            src_w = self._table.cellWidget(row, COL_SRC_TYPE)
            src_type = src_w.currentText() if src_w else "digital"

            # Source Channel
            src_chan_item = self._table.item(row, COL_SRC_CHAN)
            src_chan = src_chan_item.text() if src_chan_item else ""

            # Target Type
            tgt_w = self._table.cellWidget(row, COL_TGT_TYPE)
            tgt_type = tgt_w.currentText() if tgt_w else "analog"

            # Target Channel
            tgt_chan_item = self._table.item(row, COL_TGT_CHAN)
            tgt_chan = tgt_chan_item.text() if tgt_chan_item else ""

            # Edge
            edge_w = self._table.cellWidget(row, COL_EDGE)
            edge_val = edge_w.currentText() if edge_w else "rising"
            edge = TriggerEdge.RISING if edge_val == "rising" else TriggerEdge.FALLING

            # Notes
            notes_item = self._table.item(row, COL_NOTES)
            notes = notes_item.text() if notes_item else ""

            mappings.append(
                TriggerMapping(
                    name=name,
                    source_type=src_type,
                    source_channel=src_chan,
                    target_type=tgt_type,
                    target_channel=tgt_chan,
                    trigger_edge=edge,
                    enabled=enabled,
                    notes=notes,
                )
            )
        return mappings

    def set_trigger_mappings(self, mappings: List[TriggerMapping]):
        """Populate the table with the provided list of mappings."""
        self._table.setRowCount(0)
        for m in mappings:
            self._append_mapping_row(m)
