"""
Build script to convert lab18b daq into a standalone Windows .exe
Uses PyInstaller to bundle Python, PySide6, NumPy, NI-FPGA, and NI-DAQmx.
"""
import os
import sys
import time
import subprocess
import shutil

project_dir = os.path.dirname(os.path.abspath(__file__))
dist_dir = os.path.join(project_dir, "dist")
build_dir = os.path.join(project_dir, "build")

print(f"Building standalone Windows GUI application: lab18b daq (.exe)...")
print(f"Project directory: {project_dir}")

# Ensure any previous running instance is closed before building
subprocess.run(["taskkill", "/F", "/IM", "lab18b_daq.exe"], capture_output=True)
subprocess.run(["taskkill", "/F", "/IM", "FPGA_Sequence_Controller.exe"], capture_output=True)
time.sleep(1.0)

# PyInstaller arguments
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--name=lab18b_daq",
    "--noconfirm",
    "--clean",
    "--windowed",  # GUI application (no black console window behind)
    # Application Icon
    f"--icon={os.path.join(project_dir, 'lab18b_daq.ico')}",
    # Include examples directory and icons
    f"--add-data={os.path.join(project_dir, 'examples')};examples",
    f"--add-data={os.path.join(project_dir, 'lab18b_daq.ico')};.",
    f"--add-data={os.path.join(project_dir, 'lab18b_daq_icon.png')};.",
    # Hidden imports that dynamic loaders might need
    "--hidden-import=nifpga",
    "--hidden-import=nidaqmx",
    "--hidden-import=nidaqmx.system",
    "--hidden-import=nidaqmx.stream_writers",
    "--hidden-import=nidaqmx.stream_readers",
    "--hidden-import=numpy",
    "--hidden-import=PySide6.QtCore",
    "--hidden-import=PySide6.QtGui",
    "--hidden-import=PySide6.QtWidgets",
    # Copy package metadata required by nidaqmx and nitypes at runtime
    "--copy-metadata=nitypes",
    "--copy-metadata=nidaqmx",
    "--copy-metadata=hightime",
    "--copy-metadata=deprecation",
    # Main entry point
    os.path.join(project_dir, "main.py"),
]

print("Running PyInstaller command:")
print(" ".join(cmd))

result = subprocess.run(cmd, cwd=project_dir)

if result.returncode == 0:
    exe_path = os.path.join(dist_dir, "lab18b_daq", "lab18b_daq.exe")
    readme_src = os.path.join(project_dir, "README.md")
    readme_dst = os.path.join(dist_dir, "lab18b_daq", "README.md")
    if os.path.exists(readme_src):
        shutil.copy2(readme_src, readme_dst)
    print("\n=======================================================")
    print("SUCCESS: Standalone executable created successfully!")
    print(f"Software Name: lab18b daq")
    print(f"Executable location: {exe_path}")
    print("=======================================================")
else:
    print(f"\nERROR: Build failed with exit code {result.returncode}")
    sys.exit(result.returncode)
