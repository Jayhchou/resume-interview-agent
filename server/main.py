"""
简历陪练 · 后端应用（FastAPI）

运行形态（见 README「运行形态」）：
  模型决策循环跑在端侧（平台云模型 keyless 直连，浏览器流式 + 工具调用），
  确定性工具与状态跑在这里（解析 / 量规算分 / 事实清单 / 事实冻结校验 / DOCX 导出）。

模块：
  main.py      路由与文件解析
  agent.py     系统指令拼装 + 工具清单下发
  tools.py     9 个可执行工具（统一契约）
  rubric.py    权重、算分、证据强度、改写校验
  session.py   会话状态（S0–S5，匿名标识隔离）
  docgen.py    DOCX 生成

监听 PORT 环境变量，绑定 0.0.0.0，用于 WorkBuddy 应用发布。
"""
import io
import json
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import agent as agent_rt
import knowledge
import session as session_store
import tools as agent_tools
from docgen import build_resume_docx

app = FastAPI(title="简历陪练", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SERVER_DIR)
WEB_DIR = os.path.join(ROOT_DIR, "web")
WEB_V1_DIR = os.path.join(ROOT_DIR, "web-v1")


# ============ 缓存策略 ============

# index.html 必须每次回源：它带着 app.js?v=N 的版本号，HTML 被缓存住，
# 重新发布后浏览器仍按旧版本号取脚本——实测同一条分享链接能同时拿到新版和旧版，
# 旧版启动时还用自己的空状态覆盖了存档里的简历。
@app.middleware("http")
async def no_cache_html(request, call_next):
    response = await call_next(request)
    path = request.url.path
    ctype = response.headers.get("content-type", "")
    if path.startswith("/api/") or path in ("/", "/index.html", "/legacy/", "/legacy/index.html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    elif "text/html" in ctype:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    else:
        # 脚本/样式带 ?v=，版本号变了才会换地址；这里只要求回源校验（ETag 命中走 304）
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


# ============ 数据模型 ============

class ResumeRequest(BaseModel):
    """简历评分请求（规则引擎兜底路径，不依赖模型）"""
    resume_text: str = Field(..., description="简历原文（纯文本）")
    target_company: str = Field("", description="目标公司")
    target_role: str = Field("", description="目标岗位")
    jd_text: str = Field("", description="岗位 JD（可选）")


class InterviewAnswer(BaseModel):
    role: str = Field(..., description="岗位：backend/frontend/algorithm")
    question: str = Field(..., description="面试问题")
    answer: str = Field(..., description="候选人回答")
    q_type: str = Field("tech", description="问题类型：tech/behavior")


class TTSRequest(BaseModel):
    text: str = Field(..., description="要合成的文本")
    voice: str = Field("zh-CN-XiaoxiaoNeural", description="音色")


class ToolCallRequest(BaseModel):
    """agent 工具调用"""
    session_id: str = Field(..., description="匿名会话标识")
    name: str = Field(..., description="工具名")
    args: Dict[str, Any] = Field(default_factory=dict, description="工具入参")


class PrepareRequest(BaseModel):
    """对话前预置：把确定性准备（存档 / 锁岗）提前做掉"""
    session_id: str = Field(..., description="匿名会话标识")
    module: str = Field("diagnosis", description="当前模块")
    resume: Optional[Dict[str, Any]] = Field(None, description="结构化简历")
    target_role: str = Field("", description="目标岗位")
    jd_text: str = Field("", description="岗位 JD")


class InterviewStartRequest(BaseModel):
    """开新一场面试：清掉上一场的轮次与计数器"""
    scene: str = Field("", description="专业面 / 行为面 / 压力面")
    role: str = Field("", description="目标岗位")
    rounds: int = Field(0, description="计划轮数，0 表示由模型决定")


class InterviewAnswerRequest(BaseModel):
    """前端兜底落库：学生的原话直接进本场面试记录"""
    answer: str = Field("", description="学生这一轮的原话")


class HydrateTurn(BaseModel):
    question: str = Field("", description="这一轮的问题原句")
    answer: str = Field("", description="学生这一轮的回答原话")
    fact_id: str = Field("", description="锚定的简历事实编号")
    layer: str = Field("", description="追问层级")


class HydrateRequest(BaseModel):
    """会话重灌：把前端手里的简历与本场问答重新灌回服务端。

    为什么要这条：会话存在服务端内存/本地磁盘里，进程被回收或换实例之后
    （实测「结束本场」时 stage 掉回 S0、has_report=false），复盘就没有题可判。
    学生手里一直留着简历和这三句回答，由前端在关键步骤前灌一次即可续上。
    """
    resume: Optional[Dict[str, Any]] = Field(None, description="结构化简历")
    target_role: str = Field("", description="目标岗位")
    scene: str = Field("", description="面试场景")
    rounds: int = Field(0, description="计划轮数")
    turns: List[HydrateTurn] = Field(default_factory=list, description="本场已答的题")


# ============ 语音合成 ============

async def tts_synthesize(text: str, voice: str = "zh-CN-XiaoxiaoNeural") -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    audio_bytes = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes.write(chunk["data"])
    return audio_bytes.getvalue()


# ============ 岗位能力模型（规则引擎兜底用） ============

ROLE_SKILLS: Dict[str, Dict[str, Any]] = {
    "后端开发": {
        "keywords": [
            "java", "python", "go", "golang", "spring", "springboot", "mybatis",
            "mysql", "redis", "mongodb", "postgresql", "kafka", "rabbitmq",
            "微服务", "docker", "kubernetes", "k8s", "linux", "分布式", "高并发",
            "jvm", "多线程", "并发", "缓存", "消息队列", "rpc", "grpc", "http",
            "sql", "索引", "事务", "restful", "api", "nginx", "负载均衡",
        ],
        "dimensions": ["技术栈匹配", "项目经验", "工程能力", "深度广度"],
    },
    "前端开发": {
        "keywords": [
            "javascript", "typescript", "vue", "react", "angular", "html", "css",
            "webpack", "vite", "node", "小程序", "uniapp", "h5", "前端工程化",
            "组件化", "性能优化", "http", "浏览器", "dom", "canvas", "webgl",
            "响应式", "跨端", "electron", "npm", "打包", "构建",
        ],
        "dimensions": ["技术栈匹配", "项目经验", "工程能力", "深度广度"],
    },
    "算法工程师": {
        "keywords": [
            "机器学习", "深度学习", "神经网络", "transformer", "nlp", "cv",
            "python", "pytorch", "tensorflow", "推荐系统", "数据挖掘", "特征工程",
            "模型训练", "模型部署", "大模型", "llm", "attention", "回归", "分类",
            "聚类", "调参", "过拟合", "数据清洗", "a/b测试", "指标",
        ],
        "dimensions": ["技术栈匹配", "项目经验", "模型能力", "深度广度"],
    },
}

COMMON_SKILLS = [
    "沟通", "协作", "团队", "项目", "实习", "比赛", "开源", "证书",
    "英语", "cet-4", "cet-6", "获奖", "专利", "论文",
]


# ============ 简历解析工具 ============

def extract_skills(text: str, keywords: List[str]) -> List[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if kw in text_lower]


def extract_years(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*年", text)
    return float(m.group(1)) if m else None


def extract_education(text: str) -> str:
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


# ============ 规则引擎兜底（模型不可用时仍可出分，口径与五维一致） ============

def score_resume(req: ResumeRequest) -> Dict[str, Any]:
    text = req.resume_text.strip()
    role = req.target_role.strip() or "后端开发"

    role_model = None
    for name, model in ROLE_SKILLS.items():
        if name in role or role in name:
            role_model, role = model, name
            break
    if role_model is None:
        role_model, role = ROLE_SKILLS["后端开发"], "后端开发"

    hit_skills = extract_skills(text, role_model["keywords"])
    common_hits = extract_skills(text, COMMON_SKILLS)

    total_kw = max(len(role_model["keywords"]), 1)
    skill_ratio = len(hit_skills) / total_kw
    tech_score = min(10, round(2 + skill_ratio * 20))

    project_count = len(re.findall(r"项目|实习|比赛|开发|主导|负责|搭建|上线|优化", text))
    has_quantified = bool(re.search(r"提升|降低|增长|达到|%|\d+%|万|亿|日均", text))
    project_score = min(10, round(2 + project_count * 1.2 + (2 if has_quantified else 0)))

    edu = extract_education(text)
    edu_score = {"博士": 9, "硕士": 8, "本科": 6, "大专": 4, "未知": 3}.get(edu, 3)
    soft_score = min(10, round(len(common_hits) * 2 + 2))

    weighted = tech_score * 0.4 + project_score * 0.3 + edu_score * 0.15 + soft_score * 0.15
    match_pct = min(100, round(weighted * 10))

    if match_pct >= 85:
        conclusion = "高度匹配，简历与目标岗位契合度高，可重点准备面试"
    elif match_pct >= 70:
        conclusion = "匹配度良好，部分技能与岗位有差距，建议针对性补强"
    elif match_pct >= 50:
        conclusion = "匹配度一般，存在明显短板，建议优化简历或调整目标岗位"
    else:
        conclusion = "匹配度较低，简历与岗位要求差距较大，建议重新定位"

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
        "scores": {"tech": tech_score, "project": project_score, "education": edu_score},
        "match_pct": match_pct,
        "conclusion": conclusion,
        "suggestions": suggestions,
        "engine": "rule-fallback",
    }


def score_answer(req: InterviewAnswer) -> Dict[str, Any]:
    answer = req.answer.strip()
    answer_len = len(answer)
    length_score = min(10, round(2 + answer_len / 40)) if answer_len < 400 else 10

    structure_markers = ["首先", "其次", "然后", "最后", "第一", "第二", "第三", "总结", "总之", "一方面", "另一方面"]
    structure_hits = sum(1 for m in structure_markers if m in answer)
    structure_score = min(10, round(4 + structure_hits * 1.5))

    tech_keywords = ["原理", "机制", "实现", "优化", "架构", "性能", "数据", "算法", "设计", "场景", "方案", "对比", "权衡", "取舍"]
    tech_hits = sum(1 for k in tech_keywords if k in answer)
    tech_score = min(10, round(3 + tech_hits * 1.2))

    star = {"S": False, "T": False, "A": False, "R": False}
    if req.q_type == "behavior":
        star["S"] = answer_len > 20
        star["T"] = bool(re.search(r"目标|任务|负责|需要|为了|背景", answer))
        star["A"] = bool(re.search(r"我|开发|搭建|设计|实现|优化|主导|做了|采用|推动", answer))
        star["R"] = bool(re.search(r"提升|降低|减少|增长|达到|%|\d+|万|亿|成果|结果", answer))

    avg = round((length_score + structure_score + tech_score) / 3, 1)
    star_feedback = []
    if req.q_type == "behavior":
        names = {"S": "情境", "T": "任务", "A": "行动", "R": "结果"}
        star_feedback = [f"缺【{k} {names[k]}】要素" for k, v in star.items() if not v]

    return {
        "scores": {"length": length_score, "structure": structure_score, "tech": tech_score, "overall": avg},
        "star": star,
        "star_feedback": star_feedback,
        "feedback": _gen_feedback(avg),
        "engine": "rule-fallback",
    }


def _gen_feedback(avg: float) -> str:
    if avg >= 8:
        return "回答质量较高，结构清晰、要点充分，继续保持"
    if avg >= 6:
        return "回答整体不错，可进一步提升结构化和专业深度"
    if avg >= 4:
        return "回答基本完整，建议补充更多细节、原理或量化成果"
    return "回答偏简短，建议展开说明，结合具体案例和原理"


# ============ 文件解析 ============

def extract_pdf_text(content: bytes) -> str:
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
    import docx

    doc = docx.Document(io.BytesIO(content))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def extract_resume_file(filename: str, content: bytes) -> str:
    name_lower = filename.lower()
    if name_lower.endswith(".pdf"):
        return extract_pdf_text(content)
    if name_lower.endswith(".docx"):
        return extract_docx_text(content)
    if name_lower.endswith(".doc"):
        raise ValueError("暂不支持 .doc 格式，请另存为 .docx 后再上传")
    if name_lower.endswith((".txt", ".md")):
        return content.decode("utf-8", errors="ignore")
    raise ValueError("不支持的文件格式，请上传 PDF、Word(.docx) 或纯文本(.txt)")


# ============ 路由：页面与配置 ============

@app.get("/")
def root():
    index_path = os.path.join(WEB_V1_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"service": "简历陪练", "status": "ok", "version": "2.0.0"}


@app.get("/config.js")
def client_config():
    """前端云服务配置（由 publicConfig 生成，勿手改 endpoint）。"""
    path = os.path.join(WEB_V1_DIR, "config.js")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/javascript")
    return Response(content="window.APP_CONFIG = window.APP_CONFIG || {};", media_type="application/javascript")


@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "engine": "agent",
        "session_store": True,
        "knowledge": knowledge.stats(),
    }


# ============ 路由：agent 编排 ============

@app.get("/api/agent/manifest")
def agent_manifest(module: str = "diagnosis", session_id: str = "anon"):
    """下发系统指令 + 该模块可用工具清单 + 会话状态，由端侧循环消费。"""
    if not session_id or session_id == "anon":
        raise HTTPException(status_code=400, detail="缺 session_id：前端需生成匿名会话标识")
    sess = session_store.get(session_id)
    payload = agent_rt.manifest(module, sess)
    return payload


@app.post("/api/agent/tool")
def agent_tool(req: ToolCallRequest):
    """执行一次工具调用。模型只能通过这里改状态、拿确定性结果。"""
    if not req.session_id:
        raise HTTPException(status_code=400, detail="缺 session_id")
    sess = session_store.get(req.session_id)
    result = agent_tools.invoke(req.name, req.args or {}, sess)
    session_store.save(req.session_id)
    return {
        "ok": result.get("ok", True),
        "result": result,
        "stage": sess.context()["stage"],
        "tool_log": sess.tool_log[-3:],
    }


def _sig(value: Any) -> str:
    """规范化指纹：字段顺序不同也算同一份。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _resume_sig(resume: Optional[Dict[str, Any]]) -> str:
    """简历指纹去掉服务端附加的 _completeness / _missing，避免自比不自等。"""
    if not isinstance(resume, dict):
        return ""
    return _sig({k: v for k, v in resume.items() if not str(k).startswith("_")})


@app.post("/api/agent/prepare")
def agent_prepare(req: PrepareRequest):
    """会话预置：对话开始前把「存档 / 锁岗」这两个确定性动作做完。

    为什么放在这里：这两个动作没有判断空间（字段填进去、岗位记下来），
    却要占掉模型一整轮往返。提前做完，模型第一轮就能直接判分，
    界面上的空白等待随之缩短一轮。幂等——同一份简历重复进入不会重复存档，
    也不会把已经算好的分数冲掉。判分、找证据、建清单仍然必须由模型发起。
    """
    if not req.session_id:
        raise HTTPException(status_code=400, detail="缺 session_id")
    sess = session_store.get(req.session_id)
    prepared: List[Dict[str, Any]] = []

    resume = req.resume if isinstance(req.resume, dict) else None
    role = str(req.target_role or "").strip()
    if not role and resume:
        basic = resume.get("basic")
        if isinstance(basic, dict):
            role = str(basic.get("target") or "").strip()

    if resume:
        sig = _resume_sig(resume)
        if sig and sig != sess.resume_sig:
            res = agent_tools.tool_save_resume({"resume": resume, "target_role": role}, sess)
            if res.get("ok"):
                sess.resume_sig = sig
            sess.log_tool("save_resume", bool(res.get("ok")), f"prefetch {res.get('resume_version', '')} 完整度 {res.get('completeness', 0)}%")
            prepared.append({"name": "save_resume", "ok": bool(res.get("ok")), "result": res})

    if role:
        jd_text = str(req.jd_text or "").strip()
        sig = _sig({"role": role, "jd": jd_text})
        if sig != sess.jd_sig:
            res = agent_tools.tool_lock_jd({"target_role": role, "jd_text": jd_text}, sess)
            if res.get("ok"):
                sess.jd_sig = sig
            sess.log_tool("lock_jd", bool(res.get("ok")), f"prefetch 锁定 {role}")
            prepared.append({"name": "lock_jd", "ok": bool(res.get("ok")), "result": res})

    payload = agent_rt.manifest(req.module, sess)
    payload["prepared"] = prepared
    session_store.save(req.session_id)
    return payload


@app.get("/api/agent/session/{sid}")
def agent_session(sid: str):
    sess = session_store.get(sid)
    ctx = sess.context()
    sheet = sess.fact_sheet or {}
    ctx["fact_items"] = sheet.get("items", [])
    ctx["career_evidence"] = sess.career_evidence   # 刷新页面后靠它还原证据区
    ctx["report"] = sess.report
    return ctx


@app.post("/api/agent/session/{sid}/reset")
def agent_session_reset(sid: str):
    session_store.reset(sid)
    return {"ok": True, "reset": sid}


@app.post("/api/agent/session/{sid}/hydrate")
def agent_session_hydrate(sid: str, req: HydrateRequest):
    """把前端手里的简历 + 本场问答灌回服务端（幂等）。

    只补缺，不覆盖：服务端已有简历/清单/答题记录时一律原样保留，
    避免把正常会话的状态冲掉。返回灌完之后的上下文，前端可据此确认轮次。
    """
    sess = session_store.get(sid)
    restored = {"resume": False, "sheet": False, "turns": 0}

    if req.resume and not sess.resume:
        res = agent_tools.tool_save_resume({"resume": req.resume, "target_role": req.target_role}, sess)
        restored["resume"] = bool(res.get("ok"))

    if sess.resume and not sess.fact_sheet:
        # 清单是面试与复盘的准入条件（S3），且建清单要求先有诊断分数（S2）。
        # 会话丢过一轮的话这里什么都没有：按规则补一次诊断（上限 6 分、来源标 rules），
        # 再把简历要点摊成清单——够复盘用，且不会冒充模型判断。
        if not sess.career_scores:
            agent_tools._fallback_score(sess)
        res = agent_tools.tool_build_fact_sheet({"auto": True}, sess)
        restored["sheet"] = bool(res.get("ok"))

    if req.turns and not sess.interview.get("turns"):
        rounds = agent_tools._clamp_rounds(req.rounds or len(req.turns))
        agent_tools.reset_interview(sess, str(req.scene or ""), str(req.target_role or ""), rounds)
        for turn in req.turns:
            if not turn.answer.strip():
                continue
            sess.interview["pending_question"] = {
                "question": turn.question,
                "fact_id": turn.fact_id,
                "layer": turn.layer or "事实",
            }
            res = agent_tools.record_answer(sess, turn.answer, source="hydrate")
            if res.get("ok") and not res.get("deduped"):
                restored["turns"] += 1

    if any(restored.values()):
        sess.log_tool("hydrate", True, f"重灌 简历{int(restored['resume'])} 清单{int(restored['sheet'])} 答题{restored['turns']}")
    session_store.save(sid)
    ctx = sess.context()
    ctx["restored"] = restored
    return ctx


@app.post("/api/agent/session/{sid}/interview/start")
def agent_interview_start(sid: str, req: InterviewStartRequest):
    """开新一场面试：清空上一场的轮次、计数器与追问记录。

    前端点「开始面试」时先调这里。少了这一步，同一会话里的第二场会接着
    上一场的 round_no 数下去：第一题就被判 reached_limit，界面直接显示
    「第 6 / 5 轮」，学生只能刷新页面。
    """
    sess = session_store.get(sid)
    if not sess.fact_sheet:
        return {"ok": False, "error": "还没有事实清单，先完成简历诊断", "stage": sess.context()["stage"]}
    # 轮数在这里就收敛：前端传 "" / 0 / 越界都不能建出场次（收敛规则见 _clamp_rounds）
    rounds = agent_tools._clamp_rounds(req.rounds)
    agent_tools.reset_interview(sess, str(req.scene or "").strip(), str(req.role or "").strip(), rounds)
    sess.report = None
    sess.log_tool("start_interview", True, f"新一场面试 · 计划 {rounds} 轮")
    session_store.save(sid)
    return {"ok": True, "stage": sess.context()["stage"], "rounds_planned": sess.interview["rounds_planned"]}


@app.post("/api/agent/session/{sid}/interview/answer")
def agent_interview_answer(sid: str, req: InterviewAnswerRequest):
    """落一条学生回答（前端在发模型之前先调这里）。

    模型那一路不可靠：它常只输出点评、跳过 log_interview_turn(answer=…)，
    于是 answered 不增长、轮次不前进、复盘少题。学生原话前端本来就有，
    由服务端直接收；模型随后若也提交同一句，工具侧会按指纹去重。
    """
    sess = session_store.get(sid)
    res = agent_tools.record_answer(sess, req.answer)
    if res.get("ok"):
        sess.log_tool(
            "record_answer",
            True,
            "回答已落库" if not res.get("deduped") else "回答重复，已忽略",
        )
    session_store.save(sid)
    return res


@app.get("/api/agent/download/{token}")
def agent_download(token: str):
    item = agent_tools.take_doc(token)
    if not item:
        raise HTTPException(status_code=404, detail="下载链接已过期，请重新导出")
    blob, filename = item
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ============ 路由：兼容旧接口 ============

@app.get("/api/roles")
def list_roles():
    return {"roles": list(ROLE_SKILLS.keys())}


@app.post("/api/resume/upload")
async def resume_upload(file: UploadFile = File(...)):
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
        raise HTTPException(status_code=400, detail=f"文件解析失败：{e}")
    if not text.strip():
        raise HTTPException(status_code=400, detail="未能从文件中提取到文本，请检查文件是否为扫描图片版（扫描件需 OCR）")
    return {"filename": file.filename, "text": text, "length": len(text)}


@app.post("/api/resume/score")
def resume_score(req: ResumeRequest):
    if not req.resume_text.strip():
        raise HTTPException(status_code=400, detail="简历内容不能为空")
    return score_resume(req)


@app.post("/api/interview/score")
def interview_score(req: InterviewAnswer):
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="回答内容不能为空")
    return score_answer(req)


@app.post("/api/tts")
async def tts(req: TTSRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="文本过长")
    try:
        audio = await tts_synthesize(text, req.voice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音合成失败：{e}")
    if not audio:
        raise HTTPException(status_code=500, detail="语音合成为空")
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/resume/optimize")
def resume_optimize(payload: Dict[str, Any]):
    try:
        docx_bytes = build_resume_docx(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"简历生成失败：{e}")
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=resume.docx"},
    )


@app.on_event("shutdown")
def _flush_sessions():
    """正常停机时统一落盘：重启后再进来，简历/清单/答题记录都还在。"""
    session_store.save()


# ============ 静态文件挂载（必须放在所有 API 路由之后）============
# 根路径给智能体版前端（web-v1），早期单页版本保留在 /legacy 作对照
if os.path.isdir(WEB_DIR):
    app.mount("/legacy", StaticFiles(directory=WEB_DIR, html=True), name="legacy")
app.mount("/", StaticFiles(directory=WEB_V1_DIR, html=True), name="root")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
