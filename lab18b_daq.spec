# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata

datas = [('C:/Users/nqm lab18b/.gemini/antigravity/scratch/fpga_sequence_controller/examples', 'examples'), ('C:/Users/nqm lab18b/.gemini/antigravity/scratch/fpga_sequence_controller/lab18b_daq.ico', '.'), ('C:/Users/nqm lab18b/.gemini/antigravity/scratch/fpga_sequence_controller/lab18b_daq_icon.png', '.')]
datas += copy_metadata('nitypes')
datas += copy_metadata('nidaqmx')
datas += copy_metadata('hightime')
datas += copy_metadata('deprecation')


a = Analysis(
    ['C:/Users/nqm lab18b/.gemini/antigravity/scratch/fpga_sequence_controller/main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['nifpga', 'nidaqmx', 'nidaqmx.system', 'nidaqmx.stream_writers', 'nidaqmx.stream_readers', 'numpy', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='lab18b_daq',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:/Users/nqm lab18b/.gemini/antigravity/scratch/fpga_sequence_controller/lab18b_daq.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='lab18b_daq',
)
