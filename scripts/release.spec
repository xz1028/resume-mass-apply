# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec（tasks 5.2）：onedir 目录形态（design 决策 D1）。
#
# 排除 playwright 及关联包（核心包体积控制，浏览器组件分层可选，决策 D5）；
# add-data 收集静态前端、演示数据白名单三 JSON、LICENSE、NOTICE；
# frozen 形态下静态目录与白名单资源经 sys._MEIPASS 可达
# （loader._data_dir 与 StaticFiles 均已兼容该路径）。
#
# 锁定 PyInstaller 版本注释（可重复构建）：PyInstaller 6.x onedir。

import os

block_cipher = None

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(ROOT, "app", "static"), "app/static"),
    (os.path.join(ROOT, "app", "platforms", "demo_data"), "app/platforms/demo_data"),
    (os.path.join(ROOT, "LICENSE"), "."),
    (os.path.join(ROOT, "NOTICE"), "."),
]

excludes = [
    "playwright",
    "playwright._impl",
    "greenlet",
    "pytest",
    "pytest_asyncio",
    # 环境中存在但本项目不需要的重型依赖（体积控制）
    "numpy",
    "scipy",
    "llvmlite",
    "numba",
    "PIL",
]

a = Analysis(
    [os.path.join(ROOT, "scripts", "run_server.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["app.main"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="resume-mass-apply-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="resume-mass-apply-server",
)