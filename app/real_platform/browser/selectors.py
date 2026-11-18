"""多候选选择器定位策略：显式等待 + 依次降级尝试 + 失败环节记录。

不依赖 Playwright 的纯逻辑部分可被单元测试直接覆盖（fake 候选列表）。
"""

from dataclasses import dataclass, field

NORMAL_WAIT_SECONDS = 10
COMPLEX_WAIT_SECONDS = 30


@dataclass
class SelectorGroup:
    """一组语义等价的多候选选择器（语义属性优先排序）。"""

    name: str
    candidates: list[str]
    wait_seconds: int = NORMAL_WAIT_SECONDS
    parse_stage: str = ""

    def describe_failure(self) -> str:
        return self.parse_stage or f"定位失败: {self.name}"


@dataclass
class LocateReport:
    """定位结果报告：成功的索引或失败环节（供结构化日志 parse_stage 字段）。"""

    group_name: str
    success_index: int | None = None
    tried: list[str] = field(default_factory=list)
    parse_stage: str = ""

    @property
    def ok(self) -> bool:
        return self.success_index is not None


def try_locate(group: SelectorGroup, attempt_fn) -> LocateReport:
    """依次尝试候选选择器；attempt_fn(selector) 返回元素或 None。

    attempt_fn 抛出的异常视为该候选失败，继续下一候选；
    全部失败时报告含 parse_stage（定位失败环节）。
    """
    report = LocateReport(group_name=group.name, tried=[], parse_stage=group.parse_stage)
    for index, selector in enumerate(group.candidates):
        report.tried.append(selector)
        try:
            element = attempt_fn(selector)
        except Exception:  # noqa: BLE001
            continue
        if element is not None:
            report.success_index = index
            return report
    report.parse_stage = group.describe_failure()
    return report