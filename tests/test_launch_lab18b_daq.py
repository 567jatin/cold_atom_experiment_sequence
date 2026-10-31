"""
Verify that compiled lab18b_daq.exe starts up cleanly without missing DLLs or import crashes.
"""
import subprocess
import time
import os

exe_path = r"C:\Users\nqm lab18b\.gemini\antigravity\scratch\fpga_sequence_controller\dist\lab18b_daq\lab18b_daq.exe"
print(f"Launching {exe_path}...")

proc = subprocess.Popen([exe_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
# Give it 3 seconds to initialize Qt and NI-DAQmx / NI-FPGA bindings
time.sleep(3)

# Check if it crashed immediately or is running happily
poll = proc.poll()
if poll is None:
    print("Process is running smoothly! Terminating test instance...")
    proc.terminate()
    proc.wait(timeout=5)
    print("[SUCCESS] Compiled lab18b_daq.exe launched successfully with 0 errors!")
else:
    stdout, stderr = proc.communicate()
    print(f"[ERROR] Process exited prematurely with code {poll}!")
    print("STDOUT:", stdout.decode("utf-8", errors="replace"))
    print("STDERR:", stderr.decode("utf-8", errors="replace"))
    exit(1)
