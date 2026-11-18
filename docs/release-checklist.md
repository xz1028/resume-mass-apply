# 发布检查清单（Release Checklist）

> 人工勾选留档：任一不满足**禁止对外发布**（spec 4.4.3 / 6.6.4）。
> 用法：每次发布前逐项核对勾选，全部通过后方可执行 `python scripts/build_release.py`。

## 一、测试全绿

- [ ] `pytest -q` 全量通过（既有 142 项 + 新增测试，不删不改既有用例）
- [ ] CI 徽章为通过态（推送后 GitHub Actions 全绿）

## 二、脱敏自检

- [ ] 仓库无真实简历文件与 `data/` 运行数据入库（git status 对 data/ 变化不可见）
- [ ] 仓库无密钥/凭证/Token 类文件（`.env` 已忽略，仅 `.env.example` 模板）
- [ ] 无含敏感信息的日志文件入库
- [ ] 演示数据全量审查：无真实个人信息、无 API Key、联系方式均为演示专用值（`138****` / `demo@example.com`）
- [ ] 材料全量脱敏：截图/视频/文档无真实联系方式与凭证

## 三、作品材料齐备（四件套）

- [ ] `docs/user-guide.md` 用户说明书（含安装/演示/真实使用/AI 配置/常见问题五部分 + 华为云部署章节）
- [ ] `docs/architecture/` 两图齐备（context + pipeline，PlantUML 图源 + PNG 双交付）
- [ ] `docs/video/demo.mp4` 演示视频（3 分钟 ±30 秒，按 demo-script.md 分镜录制）
- [ ] `docs/poster.pdf` 一页纸简介（五要素齐备）

## 四、许可证与随附声明就位

- [ ] 仓库根 `LICENSE`（Apache-2.0 标准全文）存在且未被改动
- [ ] 仓库根 `NOTICE` 存在，版权声明与 LICENSE/README 三处一致
- [ ] `docs/licenses/THIRD_PARTY.md` 覆盖全部运行时依赖（无 GPL/AGPL 新增，PyMuPDF 豁免说明在档）

## 五、徽章与门面

- [ ] README 徽章通过态且链接可点开（CI Actions 构建详情可达）
- [ ] README 核心截图 ≥4 张且与运行实况一致（`docs/assets/`）
- [ ] 获取方式直达（仓库地址 + Releases 入口可访问）

## 六、发布产物（构建后核对）

- [ ] `release/` 三件套：分发包 zip + SHA256SUMS.txt + RELEASE_NOTES.txt
- [ ] 压缩包体积 ≤300MB；解压后 `data/` 为空、无 `__pycache__` 残留
- [ ] 全新 Windows 11 x64（无 Python）机器复验：解压 → 双击 → 30 秒开箱 → 演示旅程 → 退出演示（记录验收结论）