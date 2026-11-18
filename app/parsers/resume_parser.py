"""简历文本提取：ResumeParser 契约（design 8.4）与默认实现。

- PDF：基于 PyMuPDF 提取文本层；无文本层的扫描件返回不可解析标记；
- docx：基于 python-docx 提取正文；
- doc：二进制老格式，默认实现返回不可解析（触发匹配降级，可替换实现增强）。
"""

import io
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.infra.logging import get_logger

logger = get_logger("resume_parser")

SKILL_VOCABULARY: set[str] = {
    "java", "python", "go", "golang", "c++", "c#", "javascript", "typescript",
    "sql", "mysql", "postgresql", "redis", "mongodb", "kafka", "rabbitmq",
    "spring", "springboot", "spring cloud", "django", "flask", "fastapi",
    "react", "vue", "angular", "node.js", "html", "css",
    "docker", "kubernetes", "k8s", "linux", "git", "jenkins", "ci/cd",
    "微服务", "分布式", "高并发", "大数据", "机器学习", "深度学习", "算法",
    "测试", "自动化测试", "性能测试", "产品经理", "运营", "销售", "市场营销",
    "财务", "会计", "人力资源", "行政", "设计", "ui", "ux",
}

YEARS_PATTERNS = [
    re.compile(r"(\d+(?:\.\d+)?)\s*年(?:工作)?经验"),
    re.compile(r"工作经验[：:\s]*(\d+(?:\.\d+)?)\s*年"),
    re.compile(r"(\d+(?:\.\d+)?)\s*年以上"),
]


@dataclass
class ResumeRawText:
    text: str
    parseable: bool


@dataclass
class ResumeMatchProfile:
    """结构化简历画像，供匹配引擎消费。"""

    raw_text: str
    skills: set[str] = field(default_factory=set)
    years_of_experience: float | None = None

    def to_dict(self) -> dict:
        return {
            "skills": sorted(self.skills),
            "years_of_experience": self.years_of_experience,
        }


@runtime_checkable
class ResumeParser(Protocol):
    def extract_text(self, name: str, fmt: str, content: bytes) -> ResumeRawText: ...

    def is_parseable(self, name: str, fmt: str, content: bytes) -> bool: ...


class DefaultResumeParser:
    """实现 ResumeParser 契约（无需显式继承）。"""

    def extract_text(self, name: str, fmt: str, content: bytes) -> ResumeRawText:
        try:
            if fmt == "pdf":
                text = self._extract_pdf(content)
            elif fmt == "docx":
                text = self._extract_docx(content)
            else:
                return ResumeRawText(text="", parseable=False)
            return ResumeRawText(text=text, parseable=bool(text.strip()))
        except Exception as exc:  # noqa: BLE001
            logger.warning("resume_extract_failed", name=name, error=str(exc))
            return ResumeRawText(text="", parseable=False)

    def is_parseable(self, name: str, fmt: str, content: bytes) -> bool:
        return self.extract_text(name, fmt, content).parseable

    def build_profile(self, raw: ResumeRawText) -> ResumeMatchProfile:
        """从原始文本构建结构化画像：技能词命中 + 经验年限。"""
        lowered = raw.text.lower()
        skills = {s for s in SKILL_VOCABULARY if s in lowered}
        years: float | None = None
        for pattern in YEARS_PATTERNS:
            m = pattern.search(raw.text)
            if m:
                years = float(m.group(1))
                break
        return ResumeMatchProfile(raw_text=raw.text, skills=skills, years_of_experience=years)

    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        import fitz

        with fitz.open(stream=content, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)

    @staticmethod
    def _extract_docx(content: bytes) -> str:
        import docx

        document = docx.Document(io.BytesIO(content))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    parts.append(cell.text)
        return "\n".join(parts)