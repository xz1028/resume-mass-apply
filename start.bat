@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 就业海投简历

REM ============================================================
REM Config area (single source of truth)
REM Change APP_PORT here: port check, /health probe and browser
REM URL are all derived from it automatically.
REM ============================================================
set "APP_HOST=127.0.0.1"
set "APP_PORT=8000"
set "APP_URL=http://localhost:%APP_PORT%"
set "PROBE_INTERVAL_SEC=2"
set "PROBE_TIMEOUT_SEC=60"
set "HEALTH_CHECK_INTERVAL_SEC=5"
set "LOG_FILE=data\server.log"
set /a PING_PROBE_N=%PROBE_INTERVAL_SEC% + 1
set /a PING_HEALTH_N=%HEALTH_CHECK_INTERVAL_SEC% + 1
set /a PROBE_MAX_COUNT=%PROBE_TIMEOUT_SEC% / %PROBE_INTERVAL_SEC%

REM ============================================================
REM Environment check (serial, stop on first failure)
REM ============================================================
echo [环境自检中]...

python -c "import sys" >nul 2>&1
if errorlevel 1 (
    call :fail "未检测到 Python" "请安装 Python 3.11 后重试（可从 python.org 官网下载）"
    goto :eof
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    call :fail "当前 Python 版本不满足要求" "请安装 Python 3.11 及以上版本后重试"
    goto :eof
)

python -c "import app.main" >nul 2>&1
if errorlevel 1 (
    call :fail "软件依赖缺失" "请在命令行执行 pip install -e . 后重试"
    goto :eof
)

if not exist "data" mkdir "data" >nul 2>&1
echo ok > "data\.write_test" 2>nul
if errorlevel 1 (
    call :fail "数据目录无法写入" "请检查软件目录权限后重试"
    goto :eof
)
del "data\.write_test" >nul 2>&1

REM ============================================================
REM Port pre-check: free / already-running / conflict
REM ============================================================
netstat -ano | findstr /c:":%APP_PORT%" | findstr /c:"LISTENING" >nul 2>&1
if errorlevel 1 goto :port_free

call :probe_health
if errorlevel 1 (
    call :fail "端口 %APP_PORT% 被其他程序占用" "请关闭占用程序后重试，或修改启动脚本中的端口配置"
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
REM Start service in background of this console
REM ============================================================
:port_free
echo [服务启动中] 访问地址：%APP_URL%
start "" /b python -m uvicorn app.main:app --host %APP_HOST% --port %APP_PORT% >"%LOG_FILE%" 2>&1

REM ============================================================
REM Ready probe loop (interval %PROBE_INTERVAL_SEC%s, max %PROBE_TIMEOUT_SEC%s)
REM Browser is NEVER opened before service is ready.
REM ============================================================
echo [等待服务就绪]...
set /a PROBE_COUNT=0

:wait_ready
call :probe_health
if not errorlevel 1 goto :ready
set /a PROBE_COUNT+=1
if %PROBE_COUNT% GEQ %PROBE_MAX_COUNT% (
    call :fail "服务启动超时" "请关闭本窗口后重新双击启动；若反复失败，请检查软件目录后重试"
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
echo    关闭本窗口将退出软件
echo.
echo ==================================================

:run_loop
ping -n %PING_HEALTH_N% 127.0.0.1 >nul
call :probe_health
if errorlevel 1 (
    call :fail "服务已意外停止" "请关闭本窗口后重新双击启动"
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

REM Probe GET /health via python urllib, single timeout 3s.
REM ERRORLEVEL contract: 0 = HTTP 200 and status=ok, 1 = else.
:probe_health
python -c "import urllib.request,json,sys; r=urllib.request.urlopen('http://%APP_HOST%:%APP_PORT%/health', timeout=3); sys.exit(0 if r.status==200 and json.load(r).get('status')=='ok' else 1)" >nul 2>&1
if errorlevel 1 (exit /b 1) else (exit /b 0)