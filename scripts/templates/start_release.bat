@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 就业海投简历

REM ============================================================
REM Config area (single source of truth)
REM ============================================================
set "APP_HOST=127.0.0.1"
set "APP_PORT=8000"
set "APP_URL=http://localhost:%APP_PORT%"
set "PROBE_INTERVAL_SEC=2"
set "PROBE_TIMEOUT_SEC=60"
set "HEALTH_CHECK_INTERVAL_SEC=5"
set "SERVER_EXE=resume-mass-apply-server.exe"
set "LOG_FILE=data\server.log"
set /a PING_PROBE_N=%PROBE_INTERVAL_SEC% + 1
set /a PING_HEALTH_N=%HEALTH_CHECK_INTERVAL_SEC% + 1
set /a PROBE_MAX_COUNT=%PROBE_TIMEOUT_SEC% / %PROBE_INTERVAL_SEC%

REM ============================================================
REM Environment check: embedded runtime core files exist
REM ============================================================
echo [环境自检中]...

if not exist "_internal" (
    call :fail "程序文件不完整" "请重新解压分发包并核对校验和（见 RELEASE_NOTES.txt）"
    goto :eof
)
if not exist "_internal\%SERVER_EXE%" if not exist "%SERVER_EXE%" (
    call :fail "程序文件不完整" "请重新解压分发包并核对校验和（见 RELEASE_NOTES.txt）"
    goto :eof
)

REM ============================================================
REM Port pre-check: free / already-running / conflict
REM ============================================================
netstat -ano | findstr /c:":%APP_PORT%" | findstr /c:"LISTENING" >nul 2>&1
if errorlevel 1 goto :port_free

call :probe_health
if errorlevel 1 (
    call :fail "端口 %APP_PORT% 被其他程序占用" "请关闭占用程序后重试，或联系分发者调整端口配置"
    goto :eof
)

echo.
echo 软件已在运行，正在为您打开界面...
start "" "%APP_URL%"
echo.
echo 按任意键退出...
pause >nul
goto :eof

REM ============================================================
REM Start embedded server (set demo mode auto before launch)
REM ============================================================
:port_free
echo [服务启动中] 访问地址：%APP_URL%
set "RMA_DEMO_MODE=auto"
start "" /b "%SERVER_EXE%" --port=%APP_PORT% >"%LOG_FILE%" 2>&1

REM ============================================================
REM Ready probe loop (interval %PROBE_INTERVAL_SEC%s, max %PROBE_TIMEOUT_SEC%s)
REM ============================================================
echo [等待服务就绪]...
set /a PROBE_COUNT=0

:wait_ready
call :probe_health
if not errorlevel 1 goto :ready
set /a PROBE_COUNT+=1
if %PROBE_COUNT% GEQ %PROBE_MAX_COUNT% (
    call :fail "服务启动超时" "请重新双击启动；若反复失败，请核对分发包校验和后重新解压"
    goto :eof
)
ping -n %PING_PROBE_N% 127.0.0.1 >nul
goto :wait_ready

REM ============================================================
REM Open browser, then keep running with health self-check
REM ============================================================
:ready
start "" "%APP_URL%"

cls
echo ==================================================
echo.
echo    软件运行中
echo.
echo    访问地址：%APP_URL%
echo    如浏览器未自动打开，请手动复制上方地址访问
echo.
echo    当前为演示模式：数据为虚构演示数据，可在页面顶部退出
echo.
echo    关闭本窗口将退出软件
echo.
echo ==================================================

:run_loop
ping -n %PING_HEALTH_N% 127.0.0.1 >nul
call :probe_health
if errorlevel 1 (
    call :fail "服务已意外停止" "请重新双击启动"
    goto :eof
)
goto :run_loop

REM ============================================================
REM Subroutines
REM ============================================================

:fail
echo.
echo ==================================================
echo   [启动失败] %~1
echo.
echo   处理建议：%~2
echo ==================================================
echo.
echo 按任意键退出...
pause >nul
exit /b 1

REM Health probe via Windows built-in curl.exe (decision D6):
REM single 3s timeout + HTTP 200 + status=ok triple contract,
REM ERRORLEVEL 0 = healthy / 1 = not.
:probe_health
curl -s -m 3 "http://%APP_HOST%:%APP_PORT%/health" 2>nul | findstr /c:"""status"":""ok""" >nul 2>&1
if errorlevel 1 (exit /b 1) else (exit /b 0)