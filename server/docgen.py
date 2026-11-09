"""简历 DOCX 生成（服务端确定性产物，作为 agent 的 export_resume_docx 工具）。"""
from __future__ import annotations

import io
from typing import Any, Dict, List


def _to_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " · ".join(str(v) for v in value.values() if v)
    if isinstance(value, (list, tuple)):
        return "；".join(_to_str(v) for v in value if v)
    return "" if value is None else str(value)


def _period_of(entry: Any) -> str:
    """取时间段，兼容前端历史上出现过的几种字段名。

    web-v1 的编辑页写的是 `time`，但从模型/旧存档进来的简历可能写成
    `period`、`date`、`duration`，或者是拆开的 `start` / `end`。
    只认 `time` 会让教育经历那行静默少掉时间——导出看起来像丢了数据。
    """
    if not isinstance(entry, dict):
        return ""
    for key in ("time", "period", "date", "duration", "range"):
        value = _to_str(entry.get(key)).strip()
        if value:
            return value
    start = _to_str(entry.get("start")).strip()
    end = _to_str(entry.get("end")).strip()
    if start and end:
        return f"{start} - {end}"
    return start or end


def _flatten_resume(data: Dict[str, Any]) -> Dict[str, List[str]]:
    """兼容两种入参：web-v1 的结构化简历 / 早期扁平字段。"""
    basic = data.get("basic") or {}
    sections: Dict[str, List[str]] = {
        "education": [],
        "experiences": [],
        "projects": [],
        "skills": [],
        "self_eval": [],
    }

    for edu in data.get("education") or []:
        line = " · ".join(
            [x for x in [edu.get("school"), edu.get("major"), edu.get("degree"), _period_of(edu), edu.get("extra")] if x]
        ) if isinstance(edu, dict) else _to_str(edu)
        if line:
            sections["education"].append(line)

    for it in data.get("internships") or []:
        head = " · ".join([x for x in [it.get("company"), it.get("role"), _period_of(it)] if x]) if isinstance(it, dict) else _to_str(it)
        if head:
            sections["experiences"].append(head)
        for b in (it.get("bullets") if isinstance(it, dict) else []) or []:
            if _to_str(b).strip():
                sections["experiences"].append("· " + _to_str(b).strip())

    for pj in data.get("projects") or []:
        head = " · ".join([x for x in [pj.get("name"), pj.get("role"), pj.get("stack"), _period_of(pj)] if x]) if isinstance(pj, dict) else _to_str(pj)
        if head:
            sections["projects"].append(head)
        for b in (pj.get("bullets") if isinstance(pj, dict) else []) or []:
            if _to_str(b).strip():
                sections["projects"].append("· " + _to_str(b).strip())

    skills = list(data.get("skills") or [])
    certs = list(data.get("certs") or [])
    if skills:
        # 这一段的标题本来就是「专业技能」，再写「技能：」是重复的抬头。
        sections["skills"].append("、".join(_to_str(s) for s in skills))
    if certs:
        sections["skills"].append("证书：" + "、".join(_to_str(c) for c in certs))

    summary = data.get("summary") or basic.get("summaryText") or ""
    if summary:
        sections["self_eval"].append(_to_str(summary))

    # 早期扁平字段兜底
    for key, target in (("experiences", "experiences"), ("projects", "projects"), ("skills", "skills"), ("education", "education")):
        flat = data.get(key)
        if not sections[target] and isinstance(flat, list):
            sections[target] = [_to_str(x) for x in flat if _to_str(x)]
    if data.get("self_eval") and not sections["self_eval"]:
        sections["self_eval"] = [_to_str(data["self_eval"])]

    data.setdefault("_basic", basic)
    return sections


def build_resume_docx(data: Dict[str, Any]) -> bytes:
    """生成一份格式化简历，返回 docx 字节。"""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    basic = data.get("basic") or data.get("_basic") or {}
    sections = _flatten_resume(data)

    doc = Document()
    try:
        style = doc.styles["Normal"]
        style.font.name = "Calibri"
        style.font.size = Pt(10.5)
    except Exception:
        pass

    name = basic.get("name") or data.get("name") or ""
    if name:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(name)
        run.bold = True
        run.font.size = Pt(22)
        run.font.name = "微软雅黑"

    header = [x for x in [basic.get("target") or data.get("target_role"), basic.get("phone"), basic.get("email"), basic.get("city")] if x]
    if header:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(" | ".join(header))
        run.font.size = Pt(10.5)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    titles = [
        ("education", "教育背景"),
        ("experiences", "工作 / 实习经历"),
        ("projects", "项目经验"),
        ("skills", "专业技能"),
        ("self_eval", "自我评价"),
    ]

    for key, title in titles:
        items = [i for i in sections.get(key, []) if i.strip()]
        if not items:
            continue
        hp = doc.add_paragraph()
        hp.paragraph_format.space_before = Pt(10)
        hp.paragraph_format.space_after = Pt(4)
        hp.paragraph_format.keep_with_next = True
        hr = hp.add_run(title)
        hr.bold = True
        hr.font.size = Pt(13)
        hr.font.name = "微软雅黑"
        hr.font.color.rgb = RGBColor(0x2B, 0x4C, 0x7E)

        for text in items:
            if text.startswith("· "):
                ip = doc.add_paragraph(text[2:], style="List Bullet")
            else:
                ip = doc.add_paragraph(text)
            ip.paragraph_format.space_after = Pt(2)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
