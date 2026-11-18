@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
title 一键构建发布包

REM 一键构建：产出 release/ 三件套（zip + SHA256 + RELEASE_NOTES）
REM 前置：已安装 PyInstaller（pip install pyinstaller）

echo [发布前提示] 正式构建会运行全部测试（约 1-2 分钟）...
python scripts\build_release.py %*
echo.
echo 构建结束，按任意键退出...
pause >nul