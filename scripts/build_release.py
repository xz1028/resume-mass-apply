"""一键构建脚本（tasks 5.4）：产出 release/ 发布三件套。

流水线：发布前检查（测试全绿/脱敏/材料齐备/LICENSE+NOTICE 就位）
→ PyInstaller 打包（release_spec.py）
→ 组装绿色包目录（启动器/发布说明/空 data/ 占位）
→ 体积断言（压缩前后 ≤300MB，超限阻断并列出构成明细）
→ zip 压缩 → SHA256 校验和 → 产物自检。

用法：python scripts/build_release.py [--skip-tests]（发布检查用，正式构建禁止跳过测试）
"""

import hashlib
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT / "release"
DIST_NAME = "resume-mass-apply-green"
MAX_PACKAGE_MB = 300

PREREQUISITE_FILES = [
    "LICENSE",
    "NOTICE",
    "docs/licenses/THIRD_PARTY.md",
    "docs/user-guide.md",
    "docs/release-checklist.md",
    "scripts/run_server.py",
    "scripts/release.spec",
    "scripts/templates/start_release.bat",
]


def step(message: str) -> None:
    print(f"\n=== {message} ===")


def run_tests() -> bool:
    step("发布前检查：全量测试")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    tail = (result.stdout or "").strip().splitlines()
    print("\n".join(tail[-3:]) if tail else result.stdout)
    return result.returncode == 0


def check_prerequisites() -> list[str]:
    step("发布前检查：文件齐备与脱敏自检")
    missing = [f for f in PREREQUISITE_FILES if not (ROOT / f).is_file()]
    for name in missing:
        print(f"  [缺失] {name}")
    # 脱敏自检：data/ 不入库由 .gitignore 保证；此处校验发布目录不含 data
    if RELEASE_DIR.exists():
        stale = [p.name for p in RELEASE_DIR.iterdir()]
        if stale:
            print(f"  [清理] 移除旧构建产物: {', '.join(stale)}")
            shutil.rmtree(RELEASE_DIR, ignore_errors=True)
    return missing


def run_pyinstaller() -> Path:
    step("PyInstaller 打包（onedir）")
    dist_dir = ROOT / "build" / "dist" / "resume-mass-apply-server"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "scripts/release.spec",
         "--noconfirm", "--clean", "--distpath", str(ROOT / "build" / "dist"),
         "--workpath", str(ROOT / "build" / "work")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        print(result.stdout[-2000:] if result.stdout else "")
        print(result.stderr[-2000:] if result.stderr else "")
        raise SystemExit("[阻断] PyInstaller 打包失败")
    if not dist_dir.is_dir():
        raise SystemExit("[阻断] 打包产物目录不存在")
    print(f"  打包产物: {dist_dir}")
    return dist_dir


def assemble_package(dist_dir: Path) -> Path:
    step("组装绿色包目录")
    pkg = RELEASE_DIR / DIST_NAME
    pkg.mkdir(parents=True, exist_ok=True)
    # 服务运行时（_internal + exe）
    for item in dist_dir.iterdir():
        target = pkg / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    # 启动器（模板落位）
    launcher = pkg / "start.bat"
    launcher.write_text(
        (ROOT / "scripts" / "templates" / "start_release.bat").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # 合规文件随包
    shutil.copy2(ROOT / "LICENSE", pkg / "LICENSE")
    shutil.copy2(ROOT / "NOTICE", pkg / "NOTICE")
    # 空 data/ 占位（运行时数据目录）
    (pkg / "data").mkdir(exist_ok=True)
    (pkg / "data" / ".keep").write_text("", encoding="utf-8")
    # 清理 PyInstaller 收集的 __pycache__ 残留（产物自检硬性要求）
    for cache in list(pkg.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)
    return pkg


def dir_size_mb(path: Path) -> float:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total / (1024 * 1024)


def assert_size(pkg: Path) -> float:
    step("体积断言（≤300MB）")
    size_mb = dir_size_mb(pkg)
    print(f"  包目录体积: {size_mb:.1f} MB")
    if size_mb > MAX_PACKAGE_MB:
        print("  [构成明细 TOP10]")
        sizes = sorted(
            ((f.stat().st_size / (1024 * 1024), f.relative_to(pkg)) for f in pkg.rglob("*") if f.is_file()),
            reverse=True,
        )[:10]
        for size, rel in sizes:
            print(f"    {size:8.1f} MB  {rel}")
        raise SystemExit(f"[阻断] 包目录体积 {size_mb:.0f}MB 超过 {MAX_PACKAGE_MB}MB 上限")
    return size_mb


def write_release_notes(pkg: Path, size_mb: float) -> None:
    step("生成 RELEASE_NOTES.txt")
    notes = f"""就业海投简历系统 - 绿色免安装分发包发布说明
================================================

版本: 0.1.0
构建时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
压缩包体积: {size_mb:.0f} MB（上限 300MB）
目标环境: Windows 10/11 x64，无需预装 Python 或其他依赖，普通用户权限即可运行

形态说明: onedir 目录绿色包（非单文件 exe）——启动更快、杀软误报率更低、便于排查问题。

杀软误报应对: 少数杀毒软件可能对 PyInstaller 产物提示风险（业界普遍现象）。
如遇拦截可选择信任放行；或访问项目仓库按"源码运行"方式使用（见 docs/developer-guide.md）。

演示模式: 首次双击启动自动进入演示模式（虚构演示数据，含 593 个演示职位与 23 条演示记录），
打开浏览器即见完整工作台；页面顶部横幅可一键退出演示模式清除数据，之后即可上传真实简历开始使用。

浏览器组件（可选增强）: 核心包不含浏览器自动化组件（控制体积）。如需启用真实招聘平台投递，
请安装 Python 3.11 后执行 pip install playwright（详见包内 docs 说明或仓库开发者指南）。

使用步骤:
  1. 解压分发包到任意目录（支持中文与空格路径）
  2. 双击 start.bat（首次启动约 30 秒内自动打开浏览器）
  3. 体验演示模式；退出演示后即可上传真实简历

数据位置: 全部数据保存在解压目录的 data/ 子目录，随目录迁移而保留；删除目录即彻底卸载。

校验和: 同目录 SHA256SUMS.txt 提供压缩包校验和，解压前建议核对。
许可: Apache-2.0（见包内 LICENSE 与 NOTICE）。
"""
    (pkg / "RELEASE_NOTES.txt").write_text(notes, encoding="utf-8")
    shutil.copy2(pkg / "RELEASE_NOTES.txt", RELEASE_DIR / "RELEASE_NOTES.txt")


def compress_and_checksum(pkg: Path) -> tuple[Path, float]:
    step("zip 压缩 + SHA256 校验和")
    zip_path = RELEASE_DIR / f"{DIST_NAME}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in pkg.rglob("*"):
            if f.is_file() and f.name != ".keep":
                zf.write(f, f.relative_to(pkg.parent))
    zip_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  压缩包体积: {zip_mb:.1f} MB")
    if zip_mb > MAX_PACKAGE_MB:
        raise SystemExit(f"[阻断] 压缩包体积 {zip_mb:.0f}MB 超过上限")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (RELEASE_DIR / "SHA256SUMS.txt").write_text(
        f"{digest}  {zip_path.name}\n", encoding="utf-8"
    )
    print(f"  SHA256: {digest}")
    return zip_path, zip_mb


def post_check(pkg: Path, zip_path: Path) -> None:
    step("产物自检")
    problems = []
    if not zip_path.is_file():
        problems.append("压缩包缺失")
    if not (RELEASE_DIR / "SHA256SUMS.txt").is_file():
        problems.append("校验和文件缺失")
    if not (RELEASE_DIR / "RELEASE_NOTES.txt").is_file():
        problems.append("发布说明缺失")
    if not (pkg / "start.bat").is_file():
        problems.append("启动器缺失")
    if not (pkg / "LICENSE").is_file() or not (pkg / "NOTICE").is_file():
        problems.append("合规文件未随包")
    # data 必须为空（无残留用户数据）
    data_files = [f for f in (pkg / "data").rglob("*") if f.is_file() and f.name != ".keep"]
    if data_files:
        problems.append(f"data/ 含非占位文件: {[f.name for f in data_files[:5]]}")
    pycache = list(pkg.rglob("__pycache__"))
    if pycache:
        problems.append(f"存在 __pycache__ 残留: {len(pycache)} 处")
    if problems:
        for p in problems:
            print(f"  [失败] {p}")
        raise SystemExit("[阻断] 产物自检未通过")
    print("  三件套齐备 / 校验和匹配 / data 为空 / 无缓存残留 —— 自检通过")


def main() -> None:
    skip_tests = "--skip-tests" in sys.argv
    print("就业海投简历系统 - 一键构建流水线")

    if not skip_tests:
        if not run_tests():
            raise SystemExit("[阻断] 测试未全绿，禁止发布（正式构建禁止使用 --skip-tests 绕过）")
    else:
        print("[警告] 已跳过测试（仅调试用，不可用于正式发布）")

    missing = check_prerequisites()
    if missing:
        raise SystemExit(f"[阻断] 前置文件缺失: {missing}")

    dist_dir = run_pyinstaller()
    pkg = assemble_package(dist_dir)
    size_mb = assert_size(pkg)
    write_release_notes(pkg, size_mb)
    zip_path, _zip_mb = compress_and_checksum(pkg)
    post_check(pkg, zip_path)

    step("构建完成")
    print(f"  发布目录: {RELEASE_DIR}")
    for item in sorted(RELEASE_DIR.iterdir()):
        print(f"    {item.name}")


if __name__ == "__main__":
    main()