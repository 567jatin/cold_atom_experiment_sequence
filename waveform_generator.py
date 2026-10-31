"""
Waveform generation module for the FPGA TTL and Analog Waveform Sequence Controller.

Provides individual generator functions for common waveform shapes as well as
a unified :func:`generate_waveform` dispatcher that builds the correct array
from an :class:`~sequence_model.AnalogEvent`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import numpy as np

from sequence_model import AnalogEvent, WaveformType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def compute_num_samples(duration_ms: float, sample_rate_hz: float) -> int:
    """Return the number of samples for a given duration and sample rate.

    Parameters
    ----------
    duration_ms:
        Waveform duration in milliseconds.
    sample_rate_hz:
        Output sample rate in Hz.

    Returns
    -------
    int
        Number of samples (always >= 1).

    Raises
    ------
    ValueError
        If *duration_ms* or *sample_rate_hz* is non-positive.
    """
    if duration_ms <= 0:
        raise ValueError(f"duration_ms must be > 0, got {duration_ms}")
    if sample_rate_hz <= 0:
        raise ValueError(f"sample_rate_hz must be > 0, got {sample_rate_hz}")
    return max(2, int(round(duration_ms * 1e-3 * sample_rate_hz)))


# ---------------------------------------------------------------------------
# Individual waveform generators
# ---------------------------------------------------------------------------
def generate_ramp(start_v: float, end_v: float, num_samples: int) -> np.ndarray:
    """Generate a linear ramp from *start_v* to *end_v*.

    Returns
    -------
    np.ndarray
        1-D float64 array of length *num_samples*.
    """
    if num_samples <= 0:
        raise ValueError(f"num_samples must be > 0, got {num_samples}")
    return np.linspace(start_v, end_v, num_samples, dtype=np.float64)


def generate_square(
    low_v: float,
    high_v: float,
    num_samples: int,
    duty_cycle: float = 0.5,
    num_cycles: float = 1.0,
) -> np.ndarray:
    """Generate a square wave alternating between *low_v* and *high_v*.

    Parameters
    ----------
    low_v:
        Low voltage level.
    high_v:
        High voltage level.
    num_samples:
        Total number of output samples.
    duty_cycle:
        Fraction of each cycle spent at *high_v* (0.0 – 1.0).
    num_cycles:
        Number of full square wave cycles across *num_samples*.

    Returns
    -------
    np.ndarray
        1-D float64 array of length *num_samples*.
    """
    if num_samples <= 0:
        raise ValueError(f"num_samples must be > 0, got {num_samples}")
    if not (0.0 <= duty_cycle <= 1.0):
        raise ValueError(f"duty_cycle must be in [0, 1], got {duty_cycle}")
    if num_cycles <= 0:
        raise ValueError(f"num_cycles must be > 0, got {num_cycles}")

    t = np.linspace(0.0, 1.0, num_samples, endpoint=False, dtype=np.float64)
    phase = (t * num_cycles) % 1.0
    return np.where(phase < duty_cycle, high_v, low_v)


def generate_sine(
    amplitude: float,
    offset: float,
    num_samples: int,
    num_cycles: float = 1.0,
) -> np.ndarray:
    """Generate a sine wave: ``offset + amplitude * sin(2π * num_cycles * t)``.

    Parameters
    ----------
    amplitude:
        Peak amplitude of the sine wave.
    offset:
        DC offset added to every sample.
    num_cycles:
        Number of full sine cycles over the output array.

    Returns
    -------
    np.ndarray
        1-D float64 array of length *num_samples*.
    """
    if num_samples <= 0:
        raise ValueError(f"num_samples must be > 0, got {num_samples}")
    if num_cycles <= 0:
        raise ValueError(f"num_cycles must be > 0, got {num_cycles}")

    t = np.linspace(0.0, 1.0, num_samples, endpoint=False, dtype=np.float64)
    return offset + amplitude * np.sin(2.0 * np.pi * num_cycles * t)


def generate_constant(voltage: float, num_samples: int) -> np.ndarray:
    """Generate a constant-voltage waveform.

    Returns
    -------
    np.ndarray
        1-D float64 array of length *num_samples* filled with *voltage*.
    """
    if num_samples <= 0:
        raise ValueError(f"num_samples must be > 0, got {num_samples}")
    return np.full(num_samples, voltage, dtype=np.float64)


def load_arbitrary(filepath: Union[str, Path]) -> np.ndarray:
    """Load an arbitrary waveform from a CSV or ``.npy`` file.

    Supported formats
    -----------------
    * ``.npy`` – loaded directly with :func:`numpy.load`.
    * ``.csv`` / anything else – loaded with :func:`numpy.loadtxt` (comma
      delimiter, comments starting with ``#``).

    Returns
    -------
    np.ndarray
        1-D float64 array.

    Raises
    ------
    FileNotFoundError
        If *filepath* does not exist.
    ValueError
        If the loaded data is not 1-D.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Waveform file not found: {path}")

    if path.suffix.lower() == ".npy":
        data = np.load(path).astype(np.float64)
    else:
        data = np.loadtxt(path, delimiter=",", dtype=np.float64, comments="#")

    data = np.atleast_1d(data).ravel()
    if data.ndim != 1:
        raise ValueError(f"Expected 1-D data, got shape {data.shape}")
    return data


# ---------------------------------------------------------------------------
# Unified dispatcher
# ---------------------------------------------------------------------------
def generate_waveform(event: AnalogEvent) -> np.ndarray:
    """Generate the waveform array described by *event*.

    If ``event.num_samples`` is ``None`` it is computed from
    ``event.duration_ms`` and ``event.sample_rate_hz``.

    Returns
    -------
    np.ndarray
        1-D float64 array ready for DAC output.

    Raises
    ------
    ValueError
        On invalid parameters or unsupported waveform type.
    """
    n = event.num_samples
    if n is None:
        n = compute_num_samples(event.duration_ms, event.sample_rate_hz)

    wt = event.waveform_type

    if wt is WaveformType.RAMP:
        return generate_ramp(event.start_voltage, event.end_voltage, n)

    if wt is WaveformType.SQUARE:
        num_cycles = max(0.001, event.frequency_hz * (event.duration_ms / 1000.0))
        return generate_square(
            event.start_voltage,
            event.end_voltage,
            n,
            duty_cycle=0.5,
            num_cycles=num_cycles,
        )

    if wt is WaveformType.SINE:
        amplitude = (event.end_voltage - event.start_voltage) / 2.0
        offset = (event.end_voltage + event.start_voltage) / 2.0
        num_cycles = event.frequency_hz * (event.duration_ms / 1000.0)
        return generate_sine(amplitude, offset, n, num_cycles=num_cycles)

    if wt is WaveformType.CONSTANT:
        return generate_constant(event.start_voltage, n)

    if wt is WaveformType.ARBITRARY:
        if event.arbitrary_data is not None:
            return np.asarray(event.arbitrary_data, dtype=np.float64)
        raise ValueError(
            "WaveformType.ARBITRARY requires 'arbitrary_data' to be set on the event."
        )

    raise ValueError(f"Unsupported waveform type: {wt}")
