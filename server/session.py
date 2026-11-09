"""会话状态。

状态层纪律（docs/03 §七）：版本号、锁定岗位、事实清单、轮次与层级全部落在服务端，
模型每轮通过 get_context 复述，不靠对话历史硬撑。匿名标识只用于续接会话，不等于账号。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

SESSION_TTL = 6 * 3600  # 演示期 6 小时
MAX_SESSIONS = 500

# 存档落盘：原来 _store 纯内存，进程一重启会话全丢（实测：答完 3 题点「结束本场」，
# 复盘请求回来时 stage 已经是 S0、has_report=false，报告永远拿不到）。
# 落盘解决「同一进程重启」；跨实例/换机的那种丢失由前端的 hydrate 接口重灌。
STATE_FILE = os.environ.get("COACH_STATE_FILE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".state", "sessions.json"
)
SAVE_INTERVAL = 0.8   # 秒：同一进程内的高频读写不必每次都落盘

_lock = threading.Lock()
_store: Dict[str, "Session"] = {}
_loaded = False
_last_save = 0.0


def _now() -> float:
    return time.time()


class Session:
    def __init__(self, sid: str) -> None:
        self.sid = sid
        self.created_at = _now()
        self.updated_at = _now()

        # ---- 简历 ----
        self.resume: Optional[Dict[str, Any]] = None
        self.resume_version: int = 0
        self.resume_sig: str = ""      # 结构化简历的规范化指纹，用于幂等存档

        # ---- 岗位 ----
        self.target_role: str = ""
        self.jd_locked: Optional[Dict[str, Any]] = None
        self.jd_sig: str = ""          # 岗位 + JD 的指纹，用于幂等锁岗
        self.jd_args: Dict[str, str] = {}   # 锁岗时的原始入参：简历改了要按同样口径重算基线

        # ---- 诊断 ----
        self.career_scores: Dict[str, int] = {}
        self.career_total: int = 0
        self.career_source: str = ""   # ""=未诊断 / "model" / "rules"（规则兜底，上限 6 分）
        self.career_evidence: List[Dict[str, Any]] = []  # 最近一次诊断的原文证据，供刷新后还原界面
        self.career_history: List[Dict[str, Any]] = []  # 每次诊断的分数快照，用于成长曲线
        # 判分口径的两次退回机会（各一次）：五维同分、两次总分漂移过大。
        # 只退一次是有意的——措辞与口径问题不该把诊断卡死。
        self.career_flat_blocked: int = 0
        self.career_drift_blocked: int = 0

        # ---- 事实清单 ----
        self.fact_sheet: Optional[Dict[str, Any]] = None

        # ---- 面试 ----
        self.interview: Dict[str, Any] = {
            "scene": "",
            "role": "",
            "rounds_planned": 0,
            "round_no": 0,
            "layer": "",
            "layer_count": 0,
            "anchored_fact_id": "",
            "asked": 0,        # 已出题数：出题时 +1，用于判断"已出题未作答"
            "answered": 0,     # 已记录回答数
            "last_prompt_key": "",
            "multi_ask_blocked": 0,   # 本场是否已经因"一题多问"硬拒过一次
            "dup_fields_blocked": 0,  # 复盘四栏是否已经因"差在哪＝本可以答成"退回过一次
            "flat_blocked": 0,        # 复盘五维是否已经因"全同分"退回过一次
            "star_blocked": 0,        # 复盘是否已经因"三题 STAR 一模一样"退回过一次
            # 每条事实被问了几次：3 轮全锚在 E1 时，清单里别的事实一次没问，
            # 等于只验证了一条经历。计在这里才能算出「还没覆盖哪几条」。
            "asked_facts": {},
            "coverage_blocked": 0,    # 本场是否已经因"只锚一条事实"硬拒过一次
            # 最近一道"已出题、还没作答"的题：前端补录回答时靠它对齐 fact_id / layer，
            # 否则模型跳过工具调用后，学生这句回答会无处挂靠。
            "pending_question": {},
            "turns": [],
        }
        self.report: Optional[Dict[str, Any]] = None

        # ---- 审计：每一次工具调用都留痕，答辩可直接展示 ----
        self.tool_log: List[Dict[str, Any]] = []

        # ---- 编排：最近一次取 manifest 的模块，用于工具白名单校验 ----
        self.current_module: str = "diagnosis"

    # ---------- 触点 ----------
    def touch(self) -> None:
        self.updated_at = _now()

    def bump_resume(self) -> int:
        self.resume_version += 1
        return self.resume_version

    def log_tool(self, name: str, ok: bool, summary: str = "") -> None:
        self.tool_log.append({"name": name, "ok": ok, "summary": summary, "ts": int(_now())})
        if len(self.tool_log) > 60:
            self.tool_log = self.tool_log[-60:]

    # ---------- 快照 ----------
    def context(self) -> Dict[str, Any]:
        """给模型的状态摘要，每轮开头注入。"""
        sheet = self.fact_sheet or {}
        asked = self.interview.get("asked_facts") or {}
        uncovered = [i.get("id") for i in sheet.get("items", []) if not asked.get(i.get("id"))]
        return {
            "session_id": self.sid,
            "resume_version": f"V{self.resume_version}" if self.resume_version else "",
            "has_resume": bool(self.resume),
            "resume_completeness": (self.resume or {}).get("_completeness", 0),
            "resume_missing": (self.resume or {}).get("_missing", []),
            "target_role": self.target_role,
            "jd_locked": bool(self.jd_locked),
            "career_scores": self.career_scores,
            "career_total": self.career_total,
            "career_source": self.career_source,
            "fact_sheet_version": sheet.get("sheet_version", ""),
            "fact_count": len(sheet.get("items", [])),
            "top_gaps": sheet.get("top_gaps", []),
            "interview": {
                "scene": self.interview["scene"],
                "role": self.interview["role"],
                "round_no": self.interview["round_no"],
                "rounds_planned": self.interview["rounds_planned"],
                "layer": self.interview["layer"],
                "layer_count": self.interview["layer_count"],
                "anchored_fact_id": self.interview["anchored_fact_id"],
                # 已出题但还没记录回答：此时状态仍是 S3，仅凭 stage 看不出"面试已开始"，
                # 模型容易重复开场白或再问一次"准备好了吗"。这个标志专治那件事。
                "question_pending": self.interview["asked"] > self.interview["answered"],
                "answered": self.interview["answered"],
                # 覆盖情况：模型选锚点前先看一眼，别把 3 轮全用在 E1 上
                "asked_facts": dict(asked),
                "uncovered_facts": uncovered,
            },
            "has_report": bool(self.report),
            "stage": self._stage(),
        }

    def _stage(self) -> str:
        """S0–S5，见 docs/03 §二。状态即权限。"""
        if not self.resume:
            return "S0"
        if not self.career_scores:
            return "S1"
        if not self.fact_sheet:
            return "S2"
        if not self.interview["turns"]:
            return "S3"
        if not self.report:
            return "S4"
        return "S5"


def get(sid: str) -> Session:
    """取或建会话。空 sid 由调用方保证非空。"""
    global _last_save
    with _lock:
        _ensure_loaded_locked()
        _evict_locked()
        sess = _store.get(sid)
        if sess is None:
            sess = Session(sid)
            _store[sid] = sess
        # 上一次请求改完状态后没落盘就崩了：这里顺手补落一次（节流，不每次请求都写盘）
        if sess.updated_at - _last_save > SAVE_INTERVAL:
            _save_locked()
        sess.touch()
        return sess


def save(_sid: str = "") -> None:
    """把当前状态写盘。改过状态的路由调用一次，进程被回收也不丢。"""
    with _lock:
        _ensure_loaded_locked()
        _save_locked(force=True)


def reset(sid: str) -> None:
    with _lock:
        _store.pop(sid, None)
        _save_locked(force=True)


# ---------- 落盘 ----------

def _ensure_loaded_locked() -> None:
    """首次访问时把磁盘里的会话读回来。文件损坏就当没有，不能让服务起不来。"""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            blob = json.load(fh)
    except (OSError, ValueError):
        return
    if not isinstance(blob, dict):
        return
    now = _now()
    for sid, payload in blob.items():
        if not isinstance(payload, dict):
            continue
        if now - float(payload.get("updated_at") or 0) > SESSION_TTL:
            continue
        sess = Session(str(sid))
        for key, value in payload.items():
            if key in sess.__dict__:
                sess.__dict__[key] = value
        _store[str(sid)] = sess
    _evict_locked()


def _save_locked(force: bool = False) -> None:
    global _last_save
    now = _now()
    if not force and now - _last_save < SAVE_INTERVAL:
        return
    _last_save = now
    blob = {sid: sess.__dict__ for sid, sess in _store.items()}
    try:
        folder = os.path.dirname(STATE_FILE)
        if folder:
            os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder or ".", prefix=".sessions-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(blob, fh, ensure_ascii=False, default=str)
        os.replace(tmp, STATE_FILE)   # 原子替换：写一半断电也不会留半个 JSON
    except OSError:
        # 磁盘不可写（只读容器等）：退回纯内存，功能照旧，只是重启会丢
        pass


def _evict_locked() -> None:
    now = _now()
    dead = [k for k, v in _store.items() if now - v.updated_at > SESSION_TTL]
    for k in dead:
        _store.pop(k, None)
    if len(_store) > MAX_SESSIONS:
        oldest = sorted(_store.items(), key=lambda kv: kv[1].updated_at)[: len(_store) - MAX_SESSIONS]
        for k, _ in oldest:
            _store.pop(k, None)
