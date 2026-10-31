"""
FPGA TTL and Analog Waveform Sequence Controller
Main application entry point.

This module initializes the Qt application, sets up logging,
and launches the main GUI window for configuring and executing
timing sequences on NI PXIe-7820R FPGA and NI PXI-6733 hardware.
"""
import sys
import os
import traceback

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Defensive shim for importlib.metadata in PyInstaller frozen bundles
try:
    import importlib.metadata
    _orig_version = importlib.metadata.version
    _orig_distribution = importlib.metadata.distribution

    _FALLBACK_VERSIONS = {
        "nitypes": "1.0.1",
        "nidaqmx": "1.6.0",
        "hightime": "0.2.2",
        "deprecation": "2.1.0",
        "numpy": "2.1.0",
        "nifpga": "23.0.0",
    }

    class _DummyDistribution:
        def __init__(self, name, ver):
            self.name = name
            self.version = ver
            self.metadata = {"Name": name, "Version": ver}

    def _safe_version(pkg_name):
        try:
            return _orig_version(pkg_name)
        except Exception:
            return _FALLBACK_VERSIONS.get(pkg_name, "1.0.0")

    def _safe_distribution(pkg_name):
        try:
            return _orig_distribution(pkg_name)
        except Exception:
            ver = _safe_version(pkg_name)
            return _DummyDistribution(pkg_name, ver)

    importlib.metadata.version = _safe_version
    importlib.metadata.distribution = _safe_distribution
except Exception:
    pass

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon

from gui.main_window import MainWindow
from logging_utils import setup_logger, get_app_logger, APP_LOGGER_NAME


def excepthook(exc_type, exc_value, exc_tb):
    """Global exception handler that logs unhandled exceptions."""
    logger = get_app_logger()
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical(f"Unhandled exception:\n{tb_text}")

    # Show a user-facing error dialog if a QApplication instance exists
    app = QApplication.instance()
    if app is not None:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Fatal Error")
        msg.setText("An unexpected error occurred. The application will close.")
        msg.setDetailedText(tb_text)
        msg.exec()

    sys.__excepthook__(exc_type, exc_value, exc_tb)


def main():
    """Initialize and run the lab18b daq application."""
    # Determine application root directory (works both in development and when frozen as .exe)
    app_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

    # Setup logging
    logger = setup_logger(
        APP_LOGGER_NAME,
        log_file=os.path.join(app_dir, 'app.log')
    )
    logger.info("Starting lab18b daq Application")

    # Install global exception hook
    sys.excepthook = excepthook

    try:
        # Set Windows process AppUserModelID for crisp taskbar icon grouping
        if sys.platform == "win32":
            import ctypes
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("lab18b.daq.controller.v2")
            except Exception:
                pass

        # Create application
        app = QApplication(sys.argv)
        app.setApplicationName("lab18b daq")
        app.setOrganizationName("NQM Lab (Lab 18B)")
        app.setApplicationVersion("1.2.0")

        # Set default application icon
        proj_dir = os.path.dirname(os.path.abspath(__file__))
        for icon_cand in [
            os.path.join(app_dir, "lab18b_daq.ico"),
            os.path.join(proj_dir, "lab18b_daq.ico"),
            os.path.join(app_dir, "lab18b_daq_icon.png"),
            os.path.join(proj_dir, "lab18b_daq_icon.png"),
        ]:
            if os.path.exists(icon_cand):
                app.setWindowIcon(QIcon(icon_cand))
                break

        # Set default font
        font = QFont("Segoe UI", 10)
        app.setFont(font)

        # Enable high DPI scaling (attribute available in older Qt versions)
        if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
            app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

        # Create and show main window maximized to fill 1920x1080 display
        window = MainWindow()
        window.showMaximized()

        logger.info("Application window displayed")

        # Run event loop
        exit_code = app.exec()

        logger.info(f"Application exiting with code {exit_code}")
        sys.exit(exit_code)

    except Exception:
        logger.critical("Fatal error during application startup", exc_info=True)
        raise


if __name__ == "__main__":
    main()
