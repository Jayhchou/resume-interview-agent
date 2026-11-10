"""简历 DOCX 生成（服务端确定性产物，作为 agent 的 export_resume_docx 工具）。

三套模板对齐前端 web-v1 的 paper 渲染：
- classic  经典单栏：居中姓名 + 章节标题左侧竖线
- modern   现代双栏：渐变页首 + 主辅双栏（技能证书进侧栏）
- minimal  极简黑白：宽字距标题 + 黑白配色
"""
from __future__ import annotations

import io
from typing import Any, Dict, List

# 前端 CSS 设计色（web-v1/styles.css :root）
ACCENT = (0x62, 0x5B, 0xF6)       # --accent
ACCENT_DEEP = (0x4A, 0x42, 0xE0)  # --accent-deep
ACCENT_SOFT = (0xEF, 0xED, 0xFE)  # --accent-soft
INK = (0x19, 0x22, 0x38)          # --ink 正文
INK_SOFT = (0x3F, 0x49, 0x5F)     # --ink-soft
MUTED = (0x7A, 0x84, 0x99)        # --muted 次要文字
FAINT = (0xA5, 0xAD, 0xBD)        # --faint
MINT = (0x16, 0x8E, 0x70)         # --mint 证书
LINE = (0xE3, 0xE7, 0xF0)         # --line 分隔线
BLACK = (0x1C, 0x1C, 0x22)        # minimal 黑

CN_FONT = "微软雅黑"


def _to_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " · ".join(str(v) for v in value.values() if v)
    if isinstance(value, (list, tuple)):
        return "；".join(_to_str(v) for v in value if v)
    return "" if value is None else str(value)


def _period_of(entry: Any) -> str:
    """取时间段，兼容前端历史上出现过的几种字段名。"""
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
        sections["skills"].append("、".join(_to_str(s) for s in skills))
    if certs:
        sections["skills"].append("证书：" + "、".join(_to_str(c) for c in certs))

    summary = data.get("summary") or basic.get("summaryText") or ""
    if summary:
        sections["self_eval"].append(_to_str(summary))

    for key, target in (("experiences", "experiences"), ("projects", "projects"), ("skills", "skills"), ("education", "education")):
        flat = data.get(key)
        if not sections[target] and isinstance(flat, list):
            sections[target] = [_to_str(x) for x in flat if _to_str(x)]
    if data.get("self_eval") and not sections["self_eval"]:
        sections["self_eval"] = [_to_str(data["self_eval"])]

    data.setdefault("_basic", basic)
    return sections


# ============ 结构化简历（保留条目级信息，供三套模板精确渲染）============

def _resume_blocks(data: Dict[str, Any]) -> Dict[str, Any]:
    """把简历整理成带条目结构的块，三套模板共用。"""
    basic = data.get("basic") or {}
    name = basic.get("name") or data.get("name") or ""
    target = basic.get("target") or data.get("target_role") or ""
    contact = " · ".join([x for x in [basic.get("city"), basic.get("phone"), basic.get("email")] if x])

    education = []
    for e in data.get("education") or []:
        if isinstance(e, dict):
            education.append({
                "head": e.get("school") or "",
                "time": e.get("time") or _period_of(e),
                "sub": " · ".join([x for x in [e.get("major"), e.get("degree"), e.get("extra")] if x]),
            })
        elif _to_str(e):
            education.append({"head": _to_str(e), "time": "", "sub": ""})

    internships = []
    for it in data.get("internships") or []:
        if isinstance(it, dict):
            internships.append({
                "head": it.get("company") or "",
                "time": it.get("time") or _period_of(it),
                "role": it.get("role") or "",
                "bullets": [_to_str(b).strip() for b in (it.get("bullets") or []) if _to_str(b).strip()],
            })
        elif _to_str(it):
            internships.append({"head": _to_str(it), "time": "", "role": "", "bullets": []})

    projects = []
    for pj in data.get("projects") or []:
        if isinstance(pj, dict):
            projects.append({
                "head": pj.get("name") or "",
                "time": pj.get("time") or _period_of(pj),
                "role": pj.get("role") or "",
                "stack": pj.get("stack") or "",
                "bullets": [_to_str(b).strip() for b in (pj.get("bullets") or []) if _to_str(b).strip()],
            })
        elif _to_str(pj):
            projects.append({"head": _to_str(pj), "time": "", "role": "", "stack": "", "bullets": []})

    skills = [_to_str(s) for s in (data.get("skills") or []) if _to_str(s)]
    certs = [_to_str(c) for c in (data.get("certs") or []) if _to_str(c)]
    summary = _to_str(data.get("summary") or basic.get("summaryText") or "")

    return {
        "name": name, "target": target, "contact": contact,
        "education": education, "internships": internships, "projects": projects,
        "skills": skills, "certs": certs, "summary": summary,
    }


# ============ 样式辅助 ============

def _set_font(run, size=None, bold=False, color=None, name=CN_FONT, spacing=None):
    from docx.shared import RGBColor
    run.font.name = name
    run.font.bold = bold
    if size is not None:
        run.font.size = size
    if color is not None:
        run.font.color.rgb = color if isinstance(color, RGBColor) else RGBColor(*color)
    if spacing is not None:
        rpr = run._element.get_or_add_rPr()
        # 字距（letter-spacing）：通过 w:spacing 设置，单位 1/20 pt
        from docx.oxml.ns import qn
        sp = rpr.find(qn('w:spacing'))
        if sp is None:
            sp = rpr.makeelement(qn('w:spacing'), {})
            rpr.append(sp)
        sp.set(qn('w:val'), str(int(spacing * 20)))


def _add_title(doc, text, template, accent_color):
    """章节标题，按模板差异化。"""
    from docx.shared import Pt
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(10)
    pf.space_after = Pt(4)
    pf.keep_with_next = True
    run = p.add_run(text)
    if template == "minimal":
        _set_font(run, Pt(12), bold=True, color=BLACK, spacing=4)
    else:
        _set_font(run, Pt(13), bold=True, color=accent_color)
    # classic 的标题左侧竖线：用左边框模拟
    if template == "classic":
        from docx.oxml.ns import qn
        pPr = p._p.get_or_add_pPr()
        pBdr = pPr.makeelement(qn('w:pBdr'), {})
        left = pPr.makeelement(qn('w:left'), {
            qn('w:val'): 'single', qn('w:sz'): '18', qn('w:space'): '6', qn('w:color'): '625BF6'
        })
        pBdr.append(left)
        pPr.append(pBdr)
    return p


def _add_entry(doc, head, time, role, bullets, template, muted_color, ink_color, accent_color):
    """一条经历/项目条目。"""
    from docx.shared import Pt, RGBColor

    # 抬头行：标题 + 右侧时间
    if head:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.keep_with_next = True
        r = p.add_run(head)
        _set_font(r, Pt(12), bold=True, color=ink_color)
        if time:
            r2 = p.add_run("    " + time)
            _set_font(r2, Pt(9.5), bold=False, color=muted_color)
    # 角色行
    if role:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        r = p.add_run(role)
        _set_font(r, Pt(10.5), bold=False, color=(INK_SOFT if template != "minimal" else BLACK))
    # 要点
    for b in bullets:
        p = doc.add_paragraph(b, style="List Bullet")
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.left_indent = Pt(12)
        for r in p.runs:
            _set_font(r, Pt(10.5), color=ink_color)


def _add_tags(doc, tags, certs, template, accent_color, mint_color):
    """技能标签 + 证书标签。"""
    from docx.shared import Pt
    if not tags and not certs:
        return
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    all_tags = [("skill", t) for t in tags] + [("cert", c) for c in certs]
    for i, (kind, t) in enumerate(all_tags):
        if i:
            p.add_run("  ")
        run = p.add_run(t)
        if template == "minimal":
            _set_font(run, Pt(10.5), bold=True, color=BLACK)
        else:
            _set_font(run, Pt(10.5), bold=True, color=(MINT if kind == "cert" else accent_color))


def _set_margins(section, top, bottom, left, right):
    from docx.shared import Cm
    section.top_margin = Cm(top)
    section.bottom_margin = Cm(bottom)
    section.left_margin = Cm(left)
    section.right_margin = Cm(right)


# ============ 三套模板的构建 ============

def _build_classic(doc, b, sections):
    """经典单栏：居中姓名 + 章节标题左竖线。"""
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    if b["name"]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(b["name"])
        _set_font(r, Pt(20), bold=True, color=INK)
    if b["target"]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(b["target"])
        _set_font(r, Pt(12), bold=False, color=ACCENT_DEEP)
    if b["contact"]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run(b["contact"])
        _set_font(r, Pt(10), bold=False, color=MUTED)

    for key, title in [("education", "教育背景"), ("internships", "实习经历"), ("projects", "项目经历"), ("skills", "技能证书"), ("summary", "自我评价")]:
        if key == "education":
            items = b["education"]
            if items:
                _add_title(doc, title, "classic", RGB_from(ACCENT))
                for e in items:
                    _add_entry(doc, e["head"], e["time"], e["sub"], [], "classic", RGB_from(MUTED), RGB_from(INK), RGB_from(ACCENT))
        elif key == "internships":
            items = b["internships"]
            if items:
                _add_title(doc, title, "classic", RGB_from(ACCENT))
                for it in items:
                    _add_entry(doc, it["head"], it["time"], it["role"], it["bullets"], "classic", RGB_from(MUTED), RGB_from(INK), RGB_from(ACCENT))
        elif key == "projects":
            items = b["projects"]
            if items:
                _add_title(doc, title, "classic", RGB_from(ACCENT))
                for pj in items:
                    _add_entry(doc, pj["head"], pj["time"], pj["role"], pj["bullets"], "classic", RGB_from(MUTED), RGB_from(INK), RGB_from(ACCENT))
        elif key == "skills":
            if b["skills"] or b["certs"]:
                _add_title(doc, title, "classic", RGB_from(ACCENT))
                _add_tags(doc, b["skills"], b["certs"], "classic", RGB_from(ACCENT), RGB_from(MINT))
        elif key == "summary":
            if b["summary"]:
                _add_title(doc, title, "classic", RGB_from(ACCENT))
                p = doc.add_paragraph()
                r = p.add_run(b["summary"])
                _set_font(r, Pt(10.5), color=INK_SOFT)


def _set_cell_shading(cell, fill_hex):
    """给单元格设置背景色。"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:fill'), fill_hex)
    tcPr.append(shd)


def _set_cell_width(cell, cm):
    """精确设置单元格宽度（w:tcW）。"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    tcW = tcPr.find(qn('w:tcW'))
    if tcW is None:
        tcW = OxmlElement('w:tcW')
        tcPr.append(tcW)
    tcW.set(qn('w:type'), 'dxa')
    tcW.set(qn('w:w'), str(int(cm * 567)))  # 1cm ≈ 567 twips


def _set_cell_margins(cell, top=80, bottom=80, left=120, right=120):
    """设置单元格内边距（twips）。"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement('w:tcMar')
    for edge, val in (('top', top), ('bottom', bottom), ('left', left), ('right', right)):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:w'), str(val))
        el.set(qn('w:type'), 'dxa')
        mar.append(el)
    tcPr.append(mar)


def _hide_table_borders(table):
    """隐藏表格所有边框。"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tbl = table._tbl
    tblPr = tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'none')
        el.set(qn('w:sz'), '0')
        el.set(qn('w:space'), '0')
        borders.append(el)
    tblPr.append(borders)


def _set_table_width(table, cm):
    """设置表格总宽度（w:tblW），确保铺满指定宽度。"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tbl = table._tbl
    tblPr = tbl.tblPr
    tblW = tblPr.find(qn('w:tblW'))
    if tblW is None:
        tblW = OxmlElement('w:tblW')
        tblPr.append(tblW)
    tblW.set(qn('w:type'), 'dxa')
    tblW.set(qn('w:w'), str(int(cm * 567)))


def _set_table_fixed_layout(table):
    """设置表格为固定布局（w:tblLayout=fixed），否则 Word 按内容重算列宽。"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tbl = table._tbl
    tblPr = tbl.tblPr
    layout = tblPr.find(qn('w:tblLayout'))
    if layout is None:
        layout = OxmlElement('w:tblLayout')
        tblPr.append(layout)
    layout.set(qn('w:type'), 'fixed')


def _set_grid_cols(table, widths_cm):
    """设置表格每列的基准宽（w:gridCol），与 tcW 一致。"""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tbl = table._tbl
    grid = tbl.find(qn('w:tblGrid'))
    if grid is None:
        return
    grid_cols = grid.findall(qn('w:gridCol'))
    for i, cm in enumerate(widths_cm):
        if i < len(grid_cols):
            grid_cols[i].set(qn('w:w'), str(int(cm * 567)))


def _build_modern(doc, b, sections):
    """现代双栏：渐变页首（段落底纹）+ 主辅双栏（固定布局表格）。

    关键：页首用独立段落（带段落底纹），双栏用独立表格并设置
    tblLayout=fixed + gridCol + tcW 三层，避免 Word 按内容重算列宽。
    不再用 merge 合并单元格——合并会导致 Word 忽略列宽。
    """
    from docx.shared import Pt, Cm
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    # 页面内容区宽度：A4 210mm - 左右边距(18mm*2) ≈ 174mm ≈ 16.5cm
    TOTAL_W = 16.5
    MAIN_W = 12.3   # 主栏宽
    ASIDE_W = 4.2   # 侧栏宽（约 25%，对齐前端 112px 侧栏）

    # ===== 页首：独立段落 + 段落底纹 =====
    head = doc.add_paragraph()
    head.paragraph_format.space_after = Pt(6)
    # 段落底纹（模拟渐变，用纯色 accent）
    pPr = head._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:fill'), '625BF6')
    pPr.append(shd)
    # 段落内边距（模拟 cell padding）
    ind = pPr.makeelement(qn('w:ind'), {})
    ind.set(qn('w:left'), '160')
    ind.set(qn('w:right'), '160')
    pPr.append(ind)

    if b["name"]:
        r = head.add_run(b["name"])
        _set_font(r, Pt(18), bold=True, color=(0xFF, 0xFF, 0xFF))
        head.add_run("\n")
    if b["target"]:
        r = head.add_run(b["target"])
        _set_font(r, Pt(11), bold=False, color=(0xEA, 0xE8, 0xFF))
        head.add_run("\n")
    if b["contact"]:
        r = head.add_run(b["contact"])
        _set_font(r, Pt(9), bold=False, color=(0xD8, 0xD4, 0xFB))

    # ===== 双栏：固定布局表格 =====
    table = doc.add_table(rows=1, cols=2)
    table.alignment = 1
    table.autofit = False
    _hide_table_borders(table)
    _set_table_fixed_layout(table)
    _set_table_width(table, TOTAL_W)

    main_cell = table.cell(0, 0)
    aside_cell = table.cell(0, 1)
    _set_cell_width(main_cell, MAIN_W)
    _set_cell_width(aside_cell, ASIDE_W)
    _set_grid_cols(table, [MAIN_W, ASIDE_W])
    _set_cell_margins(main_cell, top=80, bottom=80, left=140, right=140)
    _set_cell_margins(aside_cell, top=80, bottom=80, left=100, right=100)

    # 侧栏左侧浅色竖线
    aside_tcPr = aside_cell._tc.get_or_add_tcPr()
    aside_borders = OxmlElement('w:tcBorders')
    left_b = OxmlElement('w:left')
    left_b.set(qn('w:val'), 'single')
    left_b.set(qn('w:sz'), '6')
    left_b.set(qn('w:space'), '0')
    left_b.set(qn('w:color'), 'E3E7F0')
    aside_borders.append(left_b)
    aside_tcPr.append(aside_borders)

    # 主栏内容
    for key, title in [("education", "教育背景"), ("internships", "实习经历"), ("projects", "项目经历"), ("summary", "自我评价")]:
        if key == "education" and b["education"]:
            _add_title_in(main_cell, title)
            for e in b["education"]:
                _add_entry_in(main_cell, e["head"], e["time"], e["sub"], [])
        elif key == "internships" and b["internships"]:
            _add_title_in(main_cell, title)
            for it in b["internships"]:
                _add_entry_in(main_cell, it["head"], it["time"], it["role"], it["bullets"])
        elif key == "projects" and b["projects"]:
            _add_title_in(main_cell, title)
            for pj in b["projects"]:
                _add_entry_in(main_cell, pj["head"], pj["time"], pj["role"], pj["bullets"])
        elif key == "summary" and b["summary"]:
            _add_title_in(main_cell, title)
            p = main_cell.add_paragraph()
            r = p.add_run(b["summary"])
            _set_font(r, Pt(10.5), color=INK_SOFT)

    # 侧栏：技能证书
    if b["skills"] or b["certs"]:
        _add_title_in(aside_cell, "技能证书")
        for t in b["skills"]:
            p = aside_cell.add_paragraph()
            p.paragraph_format.space_after = Pt(3)
            r = p.add_run(t)
            _set_font(r, Pt(10), bold=True, color=ACCENT)
        for c in b["certs"]:
            p = aside_cell.add_paragraph()
            p.paragraph_format.space_after = Pt(3)
            r = p.add_run(c)
            _set_font(r, Pt(10), bold=True, color=MINT)

    # 表格后补一个空段，避免表格紧贴文档末尾
    doc.add_paragraph()


def _build_minimal(doc, b, sections):
    """极简黑白：宽字距标题 + 黑白配色。"""
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    if b["name"]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = p.add_run(b["name"])
        _set_font(r, Pt(18), bold=True, color=BLACK, spacing=2)
    if b["target"]:
        p = doc.add_paragraph()
        r = p.add_run(b["target"])
        _set_font(r, Pt(11), bold=False, color=(0x44, 0x44, 0x44))
    if b["contact"]:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run(b["contact"])
        _set_font(r, Pt(9.5), bold=False, color=(0x66, 0x66, 0x66))

    for key, title in [("education", "教育背景"), ("internships", "实习经历"), ("projects", "项目经历"), ("skills", "技能证书"), ("summary", "自我评价")]:
        if key == "education" and b["education"]:
            _add_title(doc, title, "minimal", None)
            for e in b["education"]:
                _add_entry(doc, e["head"], e["time"], e["sub"], [], "minimal", RGB_from(FAINT), RGB_from(BLACK), None)
        elif key == "internships" and b["internships"]:
            _add_title(doc, title, "minimal", None)
            for it in b["internships"]:
                _add_entry(doc, it["head"], it["time"], it["role"], it["bullets"], "minimal", RGB_from(FAINT), RGB_from(BLACK), None)
        elif key == "projects" and b["projects"]:
            _add_title(doc, title, "minimal", None)
            for pj in b["projects"]:
                _add_entry(doc, pj["head"], pj["time"], pj["role"], pj["bullets"], "minimal", RGB_from(FAINT), RGB_from(BLACK), None)
        elif key == "skills" and (b["skills"] or b["certs"]):
            _add_title(doc, title, "minimal", None)
            _add_tags(doc, b["skills"], b["certs"], "minimal", None, None)
        elif key == "summary" and b["summary"]:
            _add_title(doc, title, "minimal", None)
            p = doc.add_paragraph()
            r = p.add_run(b["summary"])
            _set_font(r, Pt(10.5), color=(0x44, 0x44, 0x44))


# modern 双栏用（在单元格内加标题/条目）
def _add_title_in(cell, text):
    from docx.shared import Pt
    from docx.oxml.ns import qn
    p = cell.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(8)
    pf.space_after = Pt(3)
    pf.keep_with_next = True
    run = p.add_run(text)
    _set_font(run, Pt(12.5), bold=True, color=RGB_from(ACCENT))
    # modern 标题下边框
    pPr = p._p.get_or_add_pPr()
    pBdr = pPr.makeelement(qn('w:pBdr'), {})
    bottom = pPr.makeelement(qn('w:bottom'), {
        qn('w:val'): 'single', qn('w:sz'): '12', qn('w:space'): '2', qn('w:color'): '625BF6'
    })
    pBdr.append(bottom)
    pPr.append(pBdr)
    return p


def _add_entry_in(cell, head, time, role, bullets):
    from docx.shared import Pt
    if head:
        p = cell.add_paragraph()
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.keep_with_next = True
        r = p.add_run(head)
        _set_font(r, Pt(11.5), bold=True, color=RGB_from(INK))
        if time:
            r2 = p.add_run("  " + time)
            _set_font(r2, Pt(9), bold=False, color=RGB_from(MUTED))
    if role:
        p = cell.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(role)
        _set_font(r, Pt(10), bold=False, color=RGB_from(INK_SOFT))
    for b in bullets:
        p = cell.add_paragraph(b, style="List Bullet")
        p.paragraph_format.space_after = Pt(1)
        for r in p.runs:
            _set_font(r, Pt(10), color=RGB_from(INK))


def RGB_from(tup):
    from docx.shared import RGBColor
    return RGBColor(*tup)


def build_resume_docx(data: Dict[str, Any]) -> bytes:
    """生成一份格式化简历，返回 docx 字节。template 取自 data['_template']。"""
    from docx import Document

    template = data.get("_template") or "classic"
    if template not in ("classic", "modern", "minimal"):
        template = "classic"

    sections = _flatten_resume(data)
    b = _resume_blocks(data)

    doc = Document()
    try:
        style = doc.styles["Normal"]
        style.font.name = CN_FONT
        style.font.size = Pt(10.5)
        style.font.color.rgb = RGB_from(INK)
    except Exception:
        pass

    # 页边距
    _set_margins(doc.sections[0], 1.8, 1.8, 1.8, 1.8)

    if template == "modern":
        _build_modern(doc, b, sections)
    elif template == "minimal":
        _build_minimal(doc, b, sections)
    else:
        _build_classic(doc, b, sections)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
