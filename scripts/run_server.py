"""服务入口脚本（tasks 5.1）：PyInstaller 打包目标。

直接导入 app 对象（非字符串引用），确保 PyInstaller 静态分析可追踪全部依赖。
既有 app/main.py 装配点零修改；host/port 与启动器配置区一致。
"""

import sys


def main() -> None:
    import uvicorn

    from app.main import app

    host = "127.0.0.1"
    port = 8000
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            try:
                port = int(arg.split("=", 1)[1])
            except ValueError:
                pass
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()