"""
AI 面试官 · 后端应用（FastAPI）
阶段一：简历评分 + 岗位匹配度
阶段二：面试语义评分

监听 PORT 环境变量，绑定 0.0.0.0，用于 WorkBuddy 应用发布。
"""
import os
import re
import io
import asyncio
import tempfile
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

app = FastAPI(title="AI 面试官", version="1.0.0")

# 允许跨域（前端与后端可能不同域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件目录（托管前端，位于仓库根的 web/ 目录）
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(os.path.dirname(SERVER_DIR), "web")


# ============ 数据模型 ============

class ResumeRequest(BaseModel):
    """简历评分请求"""
    resume_text: str = Field(..., description="简历原文（纯文本）")
    target_company: str = Field("", description="目标公司")
    target_role: str = Field("", description="目标岗位，如：后端开发 / 前端开发 / 算法工程师")
    jd_text: str = Field("", description="岗位 JD（可选，为空则用内置岗位能力模型）")


class InterviewAnswer(BaseModel):
    """面试评分请求"""
    role: str = Field(..., description="岗位：backend/frontend/algorithm")
    question: str = Field(..., description="面试问题")
    answer: str = Field(..., description="候选人回答")
    q_type: str = Field("tech", description="问题类型：tech/behavior")


class TTSRequest(BaseModel):
    """语音合成请求"""
    text: str = Field(..., description="要合成的文本")
    voice: str = Field("zh-CN-XiaoxiaoNeural", description="音色")


class ResumeOptimizeRequest(BaseModel):
    """简历优化（生成 Word）请求，接收结构化简历内容"""
    name: str = Field("", description="姓名")
    target_role: str = Field("", description="求职意向")
    contact: str = Field("", description="联系方式")
    education: List[str] = Field(default_factory=list, description="教育背景，每项一条")
    experiences: List[str] = Field(default_factory=list, description="工作/实习经历，每项一条")
    projects: List[str] = Field(default_factory=list, description="项目经验，每项一条")
    skills: List[str] = Field(default_factory=list, description="技能栈")
    self_eval: str = Field("", description="自我评价")


# ============ 语音合成（TTS） ============

async def tts_synthesize(text: str, voice: str = "zh-CN-XiaoxiaoNeural") -> bytes:
    """用 edge-tts 合成语音，返回 mp3 字节"""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    audio_bytes = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes.write(chunk["data"])
    return audio_bytes.getvalue()


# ============ 简历 Word 生成 ============

def _set_cn_font(run, name='微软雅黑'):
    """给 run 设置中文字体（兼容不同 python-docx 版本）"""
    try:
        run.font.name = name
        rpr = run._element.get_or_add_rPr()
        rfonts = rpr.get_or_add_rFonts()
        from docx.oxml.ns import qn
        rfonts.set(qn('w:eastAsia'), name)
    except Exception:
        pass  # 字体设置失败不影响文档生成


def build_resume_docx(req: ResumeOptimizeRequest) -> bytes:
    """用 python-docx 生成一份格式化的优化简历，返回 docx 字节"""
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # 设置正文默认字体
    try:
        style = doc.styles['Normal']
        style.font.name = 'Calibri'
        style.font.size = Pt(10.5)
    except Exception:
        pass

    # 姓名（大标题，居中）
    if req.name:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(req.name)
        run.bold = True
        run.font.size = Pt(22)
        run.font.name = '微软雅黑'

    # 求职意向 + 联系方式（居中，一行）
    header_parts = []
    if req.target_role:
        header_parts.append(req.target_role)
    if req.contact:
        header_parts.append(req.contact)
    if header_parts:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(' | '.join(header_parts))
        run.font.size = Pt(10.5)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    # 分隔线
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)

    def add_section(title, items, bullet=True):
        # 章节标题
        hp = doc.add_paragraph()
        hp.paragraph_format.space_before = Pt(10)
        hp.paragraph_format.space_after = Pt(4)
        hr = hp.add_run(title)
        hr.bold = True
        hr.font.size = Pt(13)
        hr.font.name = '微软雅黑'
        hr.font.color.rgb = RGBColor(0x2B, 0x4C, 0x7E)
        hp.paragraph_format.keep_with_next = True
        # 内容（强制转字符串，防御前端传入非字符串元素）
        def _to_str(v):
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                return ' · '.join(str(x) for x in v.values() if x)
            if isinstance(v, (list, tuple)):
                return '；'.join(_to_str(x) for x in v if x)
            return str(v) if v is not None else ''
        if bullet:
            for item in items:
                text = _to_str(item)
                if not text:
                    continue
                ip = doc.add_paragraph(text, style='List Bullet')
                ip.paragraph_format.space_after = Pt(2)
        else:
            for item in items:
                text = _to_str(item)
                if not text:
                    continue
                ip = doc.add_paragraph(text)
                ip.paragraph_format.space_after = Pt(2)

    # 教育背景
    if req.education:
        add_section('教育背景', req.education)
    # 工作/实习经历
    if req.experiences:
        add_section('工作经历', req.experiences)
    # 项目经验
    if req.projects:
        add_section('项目经验', req.projects)
    # 专业技能
    if req.skills:
        add_section('专业技能', req.skills, bullet=False)
    # 自我评价
    if req.self_eval:
        add_section('自我评价', [req.self_eval], bullet=False)

    # 保存到字节流
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ============ 岗位能力模型 ============

# 每个岗位的关键技能词库，用于简历匹配
ROLE_SKILLS: Dict[str, Dict[str, Any]] = {
    "后端开发": {
        "keywords": [
            "java", "python", "go", "golang", "spring", "springboot", "mybatis",
            "mysql", "redis", "mongodb", "postgresql", "kafka", "rabbitmq",
            "微服务", "docker", "kubernetes", "k8s", "linux", "分布式", "高并发",
            "jvm", "多线程", "并发", "缓存", "消息队列", "rpc", "grpc", "http",
            "sql", "索引", "事务", "restful", "api", "nginx", "负载均衡"
        ],
        "dimensions": ["技术栈匹配", "项目经验", "工程能力", "深度广度"]
    },
    "前端开发": {
        "keywords": [
            "javascript", "typescript", "vue", "react", "angular", "html", "css",
            "webpack", "vite", "node", "小程序", "uniapp", "h5", "前端工程化",
            "组件化", "性能优化", "http", "浏览器", "dom", "canvas", "webgl",
            "响应式", "跨端", "electron", "npm", "打包", "构建"
        ],
        "dimensions": ["技术栈匹配", "项目经验", "工程能力", "深度广度"]
    },
    "算法工程师": {
        "keywords": [
            "机器学习", "深度学习", "神经网络", "transformer", "nlp", "cv",
            "python", "pytorch", "tensorflow", "推荐系统", "数据挖掘", "特征工程",
            "模型训练", "模型部署", "大模型", "llm", "attention", "回归", "分类",
            "聚类", "调参", "过拟合", "数据清洗", "a/b测试", "指标"
        ],
        "dimensions": ["技术栈匹配", "项目经验", "模型能力", "深度广度"]
    },
}

# 通用技能词（所有岗位都看）
COMMON_SKILLS = [
    "沟通", "协作", "团队", "项目", "实习", "比赛", "开源", "证书",
    "英语", "cet-4", "cet-6", "获奖", "专利", "论文"
]


# ============ 简历解析工具 ============

def extract_skills(text: str, keywords: List[str]) -> List[str]:
    """从简历文本中提取命中的技能关键词"""
    text_lower = text.lower()
    hits = []
    for kw in keywords:
        if kw in text_lower:
            hits.append(kw)
    return hits


def extract_years(text: str) -> Optional[float]:
    """粗略提取工作/项目年限（正则匹配"X年"）"""
    m = re.search(r'(\d+(?:\.\d+)?)\s*年', text)
    if m:
        return float(m.group(1))
    return None


def extract_education(text: str) -> str:
    """提取学历层次"""
    text_lower = text.lower()
    if "博士" in text or "phd" in text_lower:
        return "博士"
    if "硕士" in text or "研究生" in text or "master" in text_lower:
        return "硕士"
    if "本科" in text or "学士" in text or "bachelor" in text_lower:
        return "本科"
    if "大专" in text or "专科" in text:
        return "大专"
    return "未知"


# ============ 简历评分引擎 ============

def score_resume(req: ResumeRequest) -> Dict[str, Any]:
    """简历评分 + 岗位匹配度（本地规则算法，MVP 阶段）"""
    text = req.resume_text.strip()
    role = req.target_role.strip() or "后端开发"

    # 1. 确定岗位能力模型
    role_model = None
    for name, model in ROLE_SKILLS.items():
        if name in role or role in name:
            role_model = model
            role = name
            break
    if role_model is None:
        role_model = ROLE_SKILLS["后端开发"]
        role = "后端开发"

    # 2. 提取技能命中
    hit_skills = extract_skills(text, role_model["keywords"])
    common_hits = extract_skills(text, COMMON_SKILLS)

    # 3. 各维度打分（1-10）
    total_kw = max(len(role_model["keywords"]), 1)
    skill_ratio = len(hit_skills) / total_kw

    # 技术栈匹配：命中技能数 vs 岗位要求
    tech_score = min(10, round(2 + skill_ratio * 20))  # 命中越多越高

    # 项目经验：看项目/实习/开发/主导等经历关键词 + 是否有量化描述
    project_count = len(re.findall(r'项目|实习|比赛|开发|主导|负责|搭建|上线|优化', text))
    has_quantified = bool(re.search(r'提升|降低|增长|达到|%|\d+%|万|亿|日均', text))
    project_score = min(10, round(2 + project_count * 1.2 + (2 if has_quantified else 0)))

    # 教育背景
    edu = extract_education(text)
    edu_score = {"博士": 9, "硕士": 8, "本科": 6, "大专": 4, "未知": 3}.get(edu, 3)

    # 软素质（通用技能命中）
    soft_score = min(10, round(len(common_hits) * 2 + 2))

    # 综合匹配度（加权后转为百分制）
    # 各维度满分 10 分，加权后得到 0-10，再 ×10 转百分制
    weighted = tech_score * 0.4 + project_score * 0.3 + edu_score * 0.15 + soft_score * 0.15
    match_pct = min(100, round(weighted * 10))

    # 4. 匹配度结论分级
    if match_pct >= 85:
        conclusion = "高度匹配，简历与目标岗位契合度高，可重点准备面试"
    elif match_pct >= 70:
        conclusion = "匹配度良好，部分技能与岗位有差距，建议针对性补强"
    elif match_pct >= 50:
        conclusion = "匹配度一般，存在明显短板，建议优化简历或调整目标岗位"
    else:
        conclusion = "匹配度较低，简历与岗位要求差距较大，建议重新定位"

    # 5. 优化建议
    suggestions = []
    if skill_ratio < 0.3:
        suggestions.append("简历中岗位核心技能关键词覆盖不足，建议补充与目标岗位相关的技术栈表述")
    if not has_quantified:
        suggestions.append("项目经验缺少量化成果（如数据、提升幅度），建议补充可量化的产出")
    if project_count < 2:
        suggestions.append("项目/实习经历偏少，建议补充更多实践经历或突出已有项目的个人贡献")
    if len(hit_skills) < 5:
        suggestions.append(f"与「{role}」岗位匹配的技能仅命中 {len(hit_skills)} 项，建议按岗位 JD 逐条对照补充")
    if not suggestions:
        suggestions.append("简历整体质量较好，可针对目标公司做细节定制")

    return {
        "role": role,
        "education": edu,
        "hit_skills": hit_skills,
        "common_hits": common_hits,
        "scores": {
            "tech": tech_score,
            "project": project_score,
            "education": edu_score,
        },
        "match_pct": match_pct,
        "conclusion": conclusion,
        "suggestions": suggestions,
    }


# ============ 面试语义评分引擎 ============

def score_answer(req: InterviewAnswer) -> Dict[str, Any]:
    """面试回答评分（启发式 + STAR 诊断；真实语义评分预留大模型接口）"""
    answer = req.answer.strip()
    answer_len = len(answer)

    # 长度维度（回答过短扣分）
    length_score = min(10, round(2 + answer_len / 40)) if answer_len < 400 else 10

    # 结构化维度（是否有条理标记）
    structure_markers = ["首先", "其次", "然后", "最后", "第一", "第二", "第三", "总结", "总之", "一方面", "另一方面"]
    structure_hits = sum(1 for m in structure_markers if m in answer)
    structure_score = min(10, round(4 + structure_hits * 1.5))

    # 专业性维度（技术关键词）
    tech_keywords = ["原理", "机制", "实现", "优化", "架构", "性能", "数据", "算法", "设计", "场景", "方案", "对比", "权衡", "取舍"]
    tech_hits = sum(1 for k in tech_keywords if k in answer)
    tech_score = min(10, round(3 + tech_hits * 1.2))

    # STAR 诊断（行为面）
    star = {"S": False, "T": False, "A": False, "R": False}
    if req.q_type == "behavior":
        if answer_len > 20:
            star["S"] = True
        if re.search(r'目标|任务|负责|需要|为了|背景', answer):
            star["T"] = True
        if re.search(r'我|开发|搭建|设计|实现|优化|主导|做了|采用|推动', answer):
            star["A"] = True
        if re.search(r'提升|降低|减少|增长|达到|%|\d+|万|亿|成果|结果', answer):
            star["R"] = True

    # 综合评分
    avg = round((length_score + structure_score + tech_score) / 3, 1)

    # 缺失 STAR 要素提示
    star_feedback = []
    if req.q_type == "behavior":
        star_names = {"S": "情境", "T": "任务", "A": "行动", "R": "结果"}
        for k, v in star.items():
            if not v:
                star_feedback.append(f"缺【{k} {star_names[k]}】要素")

    return {
        "scores": {
            "length": length_score,
            "structure": structure_score,
            "tech": tech_score,
            "overall": avg,
        },
        "star": star,
        "star_feedback": star_feedback,
        "feedback": _gen_feedback(avg, req.q_type),
    }


def _gen_feedback(avg: float, q_type: str) -> str:
    """根据均分生成简短反馈"""
    if avg >= 8:
        return "回答质量较高，结构清晰、要点充分，继续保持"
    elif avg >= 6:
        return "回答整体不错，可进一步提升结构化和专业深度"
    elif avg >= 4:
        return "回答基本完整，建议补充更多细节、原理或量化成果"
    else:
        return "回答偏简短，建议展开说明，结合具体案例和原理"


# ============ 简历文件解析 ============

def extract_pdf_text(content: bytes) -> str:
    """从 PDF 字节流提取纯文本"""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    texts = []
    for page in reader.pages:
        try:
            t = page.extract_text()
            if t:
                texts.append(t)
        except Exception:
            continue
    return "\n".join(texts)


def extract_docx_text(content: bytes) -> str:
    """从 DOCX 字节流提取纯文本（含段落和表格）"""
    import docx
    doc = docx.Document(io.BytesIO(content))
    parts = []
    # 段落
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())
    # 表格
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def extract_resume_file(filename: str, content: bytes) -> str:
    """根据扩展名分发解析，返回纯文本"""
    name_lower = filename.lower()
    if name_lower.endswith(".pdf"):
        return extract_pdf_text(content)
    if name_lower.endswith(".docx"):
        return extract_docx_text(content)
    if name_lower.endswith(".doc"):
        # 老式 .doc 二进制格式，pypdf/python-docx 都不支持，给出明确提示
        raise ValueError("暂不支持 .doc 格式，请另存为 .docx 后再上传")
    if name_lower.endswith(".txt") or name_lower.endswith(".md"):
        return content.decode("utf-8", errors="ignore")
    raise ValueError("不支持的文件格式，请上传 PDF、Word(.docx) 或纯文本(.txt)")


# ============ 路由 ============

@app.get("/")
def root():
    """返回前端页面"""
    index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"service": "AI 面试官", "status": "ok", "version": "1.0.0"}


@app.get("/api/roles")
def list_roles():
    """返回支持的岗位列表"""
    return {"roles": list(ROLE_SKILLS.keys())}


@app.post("/api/resume/upload")
async def resume_upload(file: UploadFile = File(...)):
    """上传简历文件（PDF/DOCX/TXT），解析并返回纯文本"""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大，请上传 20MB 以内的简历")
    try:
        text = extract_resume_file(file.filename or "", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败：{str(e)}")
    if not text.strip():
        raise HTTPException(status_code=400, detail="未能从文件中提取到文本，请检查文件是否为扫描图片版（扫描件需 OCR）")
    return {"filename": file.filename, "text": text, "length": len(text)}


@app.post("/api/resume/score")
def resume_score(req: ResumeRequest):
    """简历评分 + 匹配度"""
    if not req.resume_text.strip():
        raise HTTPException(status_code=400, detail="简历内容不能为空")
    result = score_resume(req)
    return result


@app.post("/api/interview/score")
def interview_score(req: InterviewAnswer):
    """面试回答评分"""
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="回答内容不能为空")
    result = score_answer(req)
    return result


@app.post("/api/tts")
async def tts(req: TTSRequest):
    """文字转语音，返回 mp3 音频"""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="文本过长")
    try:
        audio = await tts_synthesize(text, req.voice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音合成失败：{str(e)}")
    if not audio:
        raise HTTPException(status_code=500, detail="语音合成为空")
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/resume/optimize")
def resume_optimize(req: ResumeOptimizeRequest):
    """生成优化后的简历 Word 文档，返回 docx 字节"""
    try:
        docx_bytes = build_resume_docx(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"简历生成失败：{str(e)}")
    if not docx_bytes:
        raise HTTPException(status_code=500, detail="简历生成为空")
    # 文件名用 ASCII（响应头 latin-1 限制），实际下载文件名由前端 downloadBlob 指定
    filename = "resume.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/health")
def health():
    return {"status": "healthy"}


# 挂载静态文件（放在所有 API 路由之后，避免拦截 /api）
# 托管 index.html 及同目录资源
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")


# ============ 启动入口 ============
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
