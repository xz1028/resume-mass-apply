@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 创建桌面快捷方式

REM ============================================================
REM Create desktop shortcut (run only when user double-clicks
REM this file; start.bat itself never writes to desktop).
REM Target: start.bat  WorkingDir: app root directory.
REM ============================================================

set "EXISTED=0"
for /f "delims=" %%D in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') do set "DESKTOP=%%D"
if exist "%DESKTOP%\就业海投简历.lnk" set "EXISTED=1"

REM Create/overwrite .lnk via PowerShell WScript.Shell COM.
REM Desktop path from GetFolderPath (OneDrive-redirect safe).
powershell -NoProfile -Command "try { $s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\就业海投简历.lnk'); $s.TargetPath = '%~dp0start.bat'; $s.WorkingDirectory = '%~dp0'; $s.Save(); exit 0 } catch { exit 1 }" >nul 2>&1

if errorlevel 1 (
    echo.
    echo   [创建失败] 桌面快捷方式创建失败
    echo.
    echo   处理建议：请检查桌面目录权限后重试
) else if "%EXISTED%"=="1" (
    echo   桌面快捷方式已更新
) else (
    echo   桌面快捷方式创建成功
)

echo.
echo 双击桌面「就业海投简历」即可一键启动软件
echo.
echo 按任意键退出...
pause >nul