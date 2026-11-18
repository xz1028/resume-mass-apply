"""简历解析器单元测试：PDF 文本层/扫描件/docx。"""

import io

from app.parsers.resume_parser import DefaultResumeParser


def make_text_pdf(text: str) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def make_blank_pdf() -> bytes:
    """无文本层的空白 PDF：模拟扫描件。"""
    import fitz

    doc = fitz.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def make_docx(text: str) -> bytes:
    import docx

    document = docx.Document()
    document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_pdf_text_layer_extracted() -> None:
    parser = DefaultResumeParser()
    raw = parser.extract_text("r.pdf", "pdf", make_text_pdf("Java 后端开发 3年经验"))
    assert raw.parseable is True
    assert "Java" in raw.text


def test_scanned_pdf_not_parseable() -> None:
    """spec 5.3.3.1 触发条件：扫描件 PDF 无法提取文本 → 匹配降级。"""
    parser = DefaultResumeParser()
    blank = make_blank_pdf()
    raw = parser.extract_text("r.pdf", "pdf", blank)
    assert raw.parseable is False
    assert parser.is_parseable("r.pdf", "pdf", blank) is False


def test_docx_extracted() -> None:
    parser = DefaultResumeParser()
    raw = parser.extract_text("r.docx", "docx", make_docx("Python 工程师，5年经验"))
    assert raw.parseable is True
    assert "Python" in raw.text


def test_doc_legacy_not_parseable_by_default() -> None:
    parser = DefaultResumeParser()
    raw = parser.extract_text("r.doc", "doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy")
    assert raw.parseable is False


def test_corrupted_file_not_parseable() -> None:
    parser = DefaultResumeParser()
    raw = parser.extract_text("r.pdf", "pdf", b"not a pdf at all")
    assert raw.parseable is False