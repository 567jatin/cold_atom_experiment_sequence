"""
NI-DAQmx Python Analog Input (AI) Reference Code
================================================
This script demonstrates how to configure and acquire Analog Input
voltage signals from an NI DAQ card (e.g., NI PXIe-6363, PXI-6115, PXI-6259)
using Python and the official `nidaqmx` library.

Scenarios Covered:
1. Device and AI Channel Auto-Discovery.
2. Finite Multi-Channel Voltage Acquisition.
3. High-Speed Continuous Streaming with `AnalogMultiChannelReader`.
4. Synchronizing AI Acquisition with PXI Backplane Triggers (/PXI2Slot3/PXI_Trig0).
"""

import time
import numpy as np
import nidaqmx
from nidaqmx.constants import (
    AcquisitionType,
    Edge,
    TerminalConfiguration,
    VoltageUnits,
)
from nidaqmx.stream_readers import AnalogMultiChannelReader


# ────────────────────────────────────────────────────────────────────────
# 1. Device and AI Channel Auto-Discovery
# ────────────────────────────────────────────────────────────────────────

def discover_ai_devices():
    """Discover all devices on the local system that possess AI channels."""
    print("--- 1. Scanning for NI-DAQmx Analog Input Devices ---")
    system = nidaqmx.system.System.local()
    ai_devices = []

    for dev in system.devices:
        ai_chans = [ch.name for ch in dev.ai_physical_chans]
        if ai_chans:
            print(f"Found AI Device: {dev.name} ({dev.product_type}) with {len(ai_chans)} AI channels:")
            print(f"  First channels: {ai_chans[:4]}")
            ai_devices.append((dev.name, ai_chans))

    if not ai_devices:
        print("No physical AI devices found currently in chassis.")
        print("When you plug in your Analog Input card (e.g. PXI-6115), it will appear here!")
    return ai_devices


# ────────────────────────────────────────────────────────────────────────
# 2. Finite Multi-Channel Acquisition
# ────────────────────────────────────────────────────────────────────────

def read_finite_samples(
    channels=("PXI2Slot4/ai0", "PXI2Slot4/ai1"),
    sample_rate_hz=500000.0,
    num_samples=10000,
    min_val=-10.0,
    max_val=10.0,
    terminal_config=TerminalConfiguration.DIFF,
):
    """Acquire a finite block of samples from specified AI channels."""
    print(f"\n--- 2. Finite Acquisition: {num_samples} samples at {sample_rate_hz/1e3:.1f} kS/s ---")

    with nidaqmx.Task() as task:
        # Add AI channels
        for ch in channels:
            task.ai_channels.add_ai_voltage_chan(
                physical_channel=ch,
                name_to_assign_to_channel="",
                terminal_config=terminal_config,
                min_val=min_val,
                max_val=max_val,
                units=VoltageUnits.VOLTS,
            )

        # Configure Sample Clock
        task.timing.cfg_samp_clk_timing(
            rate=sample_rate_hz,
            active_edge=Edge.RISING,
            sample_mode=AcquisitionType.FINITE,
            samps_per_chan=num_samples,
        )

        task.start()
        # Read all samples as 2D NumPy array
        data = task.read(number_of_samples_per_channel=num_samples, timeout=10.0)
        data_np = np.asarray(data, dtype=np.float64)

        print(f"Acquired shape: {data_np.shape} (Channels x Samples)")
        for idx, ch in enumerate(channels):
            ch_data = data_np[idx]
            print(f"  {ch}: Mean = {np.mean(ch_data):.3f}V, Min = {np.min(ch_data):.3f}V, Max = {np.max(ch_data):.3f}V")

        return data_np


# ────────────────────────────────────────────────────────────────────────
# 3. Continuous Streaming Acquisition with High-Speed DMA Reader
# ────────────────────────────────────────────────────────────────────────

def stream_continuous_samples(
    channels=("PXI2Slot4/ai0", "PXI2Slot4/ai1"),
    sample_rate_hz=1000000.0,  # 1 MS/s
    chunk_size=5000,
    total_seconds=2.0,
    terminal_config=TerminalConfiguration.DIFF,
):
    """Continuously stream analog input samples in real time (e.g. for an oscilloscope)."""
    print(f"\n--- 3. Continuous Streaming: {sample_rate_hz/1e3:.1f} kS/s, chunk size {chunk_size} ---")

    with nidaqmx.Task() as task:
        for ch in channels:
            task.ai_channels.add_ai_voltage_chan(
                physical_channel=ch,
                terminal_config=terminal_config,
                min_val=-10.0,
                max_val=10.0,
                units=VoltageUnits.VOLTS,
            )

        # Buffer size typically 10x chunk size for reliable DMA transfers
        buffer_size = chunk_size * 10
        task.timing.cfg_samp_clk_timing(
            rate=sample_rate_hz,
            sample_mode=AcquisitionType.CONTINUOUS,
            samps_per_chan=buffer_size,
        )

        reader = AnalogMultiChannelReader(task.in_stream)
        data_buffer = np.zeros((len(channels), chunk_size), dtype=np.float64)

        task.start()
        t_start = time.time()
        chunks_read = 0

        while (time.time() - t_start) < total_seconds:
            # High speed DMA transfer from DAQ FIFO to NumPy buffer
            reader.read_many_sample(
                data_buffer,
                number_of_samples_per_channel=chunk_size,
                timeout=2.0,
            )
            chunks_read += 1
            if chunks_read % 10 == 0:
                print(f"  Streamed chunk #{chunks_read} ({chunks_read * chunk_size:,} samples acquired so far)...")

        print(f"Streaming complete: {chunks_read} chunks ({chunks_read * chunk_size:,} total samples).")


# ────────────────────────────────────────────────────────────────────────
# 4. Synchronized Hardware-Triggered Acquisition via PXI Backplane
# ────────────────────────────────────────────────────────────────────────

def triggered_ai_acquisition(
    channels=("PXI2Slot4/ai0",),
    trigger_source="/PXI2Slot3/PXI_Trig0",
    sample_rate_hz=500000.0,
    samples_per_trigger=1000,
):
    """Wait for FPGA/AO sequence start trigger on PXI backplane before capturing."""
    print(f"\n--- 4. Hardware Triggered Acquisition via {trigger_source} ---")

    with nidaqmx.Task() as task:
        for ch in channels:
            task.ai_channels.add_ai_voltage_chan(
                physical_channel=ch,
                terminal_config=TerminalConfiguration.DIFF,
                min_val=-10.0,
                max_val=10.0,
            )

        task.timing.cfg_samp_clk_timing(
            rate=sample_rate_hz,
            sample_mode=AcquisitionType.FINITE,
            samps_per_chan=samples_per_trigger,
        )

        # Arm acquisition to start automatically on rising edge of PXI Trigger line
        task.triggers.start_trigger.cfg_dig_edge_start_trig(
            trigger_source=trigger_source,
            trigger_edge=Edge.RISING,
        )

        print(f"Task armed! Waiting for hardware trigger pulse on {trigger_source}...")
        task.start()
        # Task waits at hardware level until the trigger fires!
        data = task.read(number_of_samples_per_channel=samples_per_trigger, timeout=30.0)
        print(f"Trigger received! Captured {len(data)} samples synchronously with experiment sequence.")
        return data


if __name__ == "__main__":
    devices = discover_ai_devices()
    if devices:
        dev_name, chans = devices[0]
        read_finite_samples(channels=chans[:2])
    else:
        print("\nNote: When your AI module is installed in the chassis, run this script directly to verify hardware communication.")
