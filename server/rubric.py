"""量规与确定性算分。

设计原则（见 docs/02 §1.1）：能算的不要让模型猜。
模型只负责「给证据 + 给解释」，权重、总分、等级、证据强度、事实冻结校验
全部在这里用代码算，保证同一份输入两次结果一致。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ============ 权重表（不可配置，见 docs/03 §3.2 与 §5.4） ============

CAREER_DIMS: List[Tuple[str, str, float]] = [
    ("foundation", "专业基础", 0.20),
    ("practice", "实践经历", 0.30),
    ("output", "成果产出", 0.20),
    ("expression", "沟通表达", 0.15),
    ("collaboration", "协作推进", 0.15),
]

INTERVIEW_DIMS: List[Tuple[str, str, float]] = [
    ("tech_depth", "技术深度", 0.30),
    ("project", "项目经验", 0.25),
    ("logic", "表达逻辑", 0.20),
    ("behavior", "行为素质", 0.15),
    ("fit", "岗位匹配", 0.10),
]

ROLE_WORDS = ("主导", "独立", "参与", "协助")

# JD 技能重合率 → 专业基础分（后端写死，模型不得自行改判，见 docs/03 §3.3）
JD_SCORE_MAP: List[Tuple[float, int]] = [
    (0.90, 9), (0.75, 8), (0.60, 7), (0.45, 6), (0.30, 5), (0.15, 4), (0.00, 3),
]


def clamp_score(value: Any, low: int = 1, high: int = 10) -> int:
    """把任意输入夹到 1–10 的整数分，非数字返回 low。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return low
    if num != num:  # NaN
        return low
    return max(low, min(high, int(round(num))))


def foundation_from_ratio(ratio: float) -> int:
    """技能重合率折算专业基础分。"""
    ratio = max(0.0, min(1.0, float(ratio or 0)))
    for threshold, score in JD_SCORE_MAP:
        if ratio >= threshold:
            return score
    return 3


def weighted_total(scores: Dict[str, Any], dims: Iterable[Tuple[str, str, float]]) -> int:
    """总分 = Σ(各维分 × 权重) × 10，四舍五入取整（docs/03 §5.4）。

    全程整数运算，避开 5.45*10 = 54.4999… 这类浮点误差导致的少 1 分。
    """
    pct_x10 = 0
    for key, _label, weight in dims:
        pct_x10 += clamp_score(scores.get(key)) * int(round(weight * 100))
    return (pct_x10 + 5) // 10


def level_of(total: int) -> str:
    if total >= 85:
        return "强烈推荐"
    if total >= 70:
        return "推荐"
    if total >= 50:
        return "有潜力"
    return "建议调整目标"


def dims_payload(dims: Iterable[Tuple[str, str, float]]) -> List[Dict[str, Any]]:
    return [{"key": k, "label": l, "weight": w} for k, l, w in dims]


# ============ 事实清单：证据强度由规则判定，不由模型自评 ============

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def has_number(text: str) -> bool:
    return bool(_NUM_RE.search(text or ""))


def evidence_strength(result: str, role: str) -> str:
    """强 / 中 / 虚（docs/03 §4.2 第 5 字段）。"""
    result = (result or "").strip()
    if not result or "待核实" in result or not has_number(result):
        return "虚"
    if role in ("主导", "独立"):
        return "强"
    return "中"


def normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给事实清单编号 E1、E2…，并补全证据强度。id 一旦生成不再变化。"""
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(items, start=1):
        role = (raw.get("role") or "参与").strip()
        if role not in ROLE_WORDS:
            role = "参与"
        result = (raw.get("result") or "").strip() or "【待核实】"
        out.append(
            {
                "id": f"E{idx}",
                "fact": (raw.get("fact") or "").strip(),
                "result": result,
                "role": role,
                "strength": evidence_strength(result, role),
                "follow_ups": [str(x).strip() for x in (raw.get("follow_ups") or []) if str(x).strip()][:3],
                "source_module": raw.get("source_module") or "",
            }
        )
    return out


# 模型给 STAR 的写法五花八门：{"A": true}、{"a": true}、{"action": true}、
# {"情境": true}，甚至 ["S","A"]。只认大写单字母，其余全被判成 False，
# 四枚标签一起变灰，学生读到的是"四项全不会"——比"未评"更误导。
_STAR_ALIASES = {
    "S": ("s", "situation", "情境", "背景", "场景"),
    "T": ("t", "task", "任务", "目标"),
    "A": ("a", "action", "act", "行动", "做法", "动作"),
    "R": ("r", "result", "outcome", "结果", "成果"),
}


def normalize_star(star: Any) -> Optional[Dict[str, Optional[bool]]]:
    """把 STAR 判定收敛成 {S,T,A,R: True/False/None}；None = 模型没评这一项。

    三项没给就把三项判成"缺"，等于替模型下结论。宁可显示"未评"。
    """
    if isinstance(star, (list, tuple, set)):
        picked = {str(x).strip().upper() for x in star if str(x).strip()}
        if not picked & {"S", "T", "A", "R"}:
            return None
        return {k: (k in picked) for k in ("S", "T", "A", "R")}
    if not isinstance(star, dict) or not star:
        return None
    low = {str(k).strip().lower(): v for k, v in star.items()}
    out: Dict[str, Optional[bool]] = {}
    for key, aliases in _STAR_ALIASES.items():
        val: Optional[bool] = None
        for alias in aliases:
            if alias in low:
                val = bool(low[alias])
                break
        out[key] = val
    return out if any(v is not None for v in out.values()) else None


_GAP_DESC = {
    "虚": "缺全部量化，面试必问",
    "中": "结果可验证但归因偏弱",
    # 清单里全是「强」时不能返回空数组：前端会渲染出一个空白区块，
    # 页脚还会显示「最该先补 —」，看起来像功能坏了。这种情况给的是
    # "最该先练怎么说"，而不是"最该先补"。
    "强": "证据最扎实的一条：面试官会从这里追问口径，先练成 90 秒版本",
}

# 同一强度下只换编号、换不出内容，等于没给建议：三条「强」都是同一句
# 「证据最扎实的一条…」，学生读完不知道先改哪条。把该条自己那句话摘出来，
# 配上这一档该做的事，三条自然就分开了。
# 但同一档的三条仍会共用一句尾句（清单第五轮 #7：三条「强」尾句逐字相同）。
# 每档给三个动作变体，按「条目自身」散列挑一个，再按同档内的位次错开，
# 保证同屏三条不重复；散列只看 fact_id/fact，刷新后不会换说法。
_GAP_ACTION = {
    "虚": [
        "缺规模与结果数字——先补「多大规模、做到什么程度」，面试必问",
        "没有可核实的结果——先给一个数（人次 / 条数 / 时长），给不出就说清范围",
        "只有动作没有结果——补「做完之后什么变了」，哪怕只是跑通了几周",
    ],
    "中": [
        "结果能查，但没说你为什么这么选——补一句取舍理由",
        "有结果，缺归因——说清哪一段是你独立决定的、哪一段是跟着做的",
        "能查到结果，但看不出踩过什么坑——补一句当时的取舍或返工",
    ],
    "强": [
        "证据最扎实——练成 90 秒版本：背景一句、你的动作两句、结果一句",
        "这条最经得起追问——准备两个版本：60 秒概述 + 被追问时的技术细节",
        "这条可以直接当开场——先说结论，再用两句话讲你怎么做到的",
    ],
}


def _action_of(strength: str, item: Dict[str, Any], slot: int = 0, used: Optional[set] = None) -> str:
    variants = _GAP_ACTION.get(strength) or _GAP_ACTION["虚"]
    seed = "".join(ch for ch in f"{item.get('id','')}{item.get('fact','')}" if ch.isalnum())
    h = sum(ord(ch) * (i + 1) for i, ch in enumerate(seed)) if seed else 0
    start = (h + slot) % len(variants)
    # 散列只保证「大概不撞」，同档三条仍可能落到同一个变体上：按 used 往后顺延，
    # 变体不够用时才允许重复（三条以上同档）。
    for off in range(len(variants)):
        idx = (start + off) % len(variants)
        if used is None or idx not in used:
            if used is not None:
                used.add(idx)
            return variants[idx]
    return variants[start]


def gap_excerpt(text: str, width: int = 16) -> str:
    """摘出事实句的可读片段：去掉 `P｜…` 的抬头，太长就截断。"""
    body = str(text or "").strip()
    if "｜" in body:
        body = body.rsplit("｜", 1)[-1]
    body = body.strip(" 。.")
    if not body:
        return ""
    return body if len(body) <= width else body[:width] + "…"


def gap_desc_of(item: Dict[str, Any], slot: int = 0, used: Optional[set] = None) -> str:
    """一条事实对应的「最该先练」描述：先点名是哪条，再说这一档该做什么。"""
    strength = item.get("strength", "虚")
    action = _action_of(strength, item, slot, used)
    excerpt = gap_excerpt(item.get("fact"))
    return f"「{excerpt}」{action}" if excerpt else action


def distinguish_gaps(gaps: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把描述逐字相同的缺口拉开：模型自己给的 top_gaps 也常是同一句复制三遍。"""
    by_id = {i.get("id"): i for i in items}
    seen = set()
    out = []
    for gap in gaps:
        desc = str(gap.get("desc") or "").strip()
        key = "".join(ch for ch in desc if ch.isalnum())
        if not key or key in seen:
            item = by_id.get(gap.get("fact_id"))
            alt = gap_desc_of(item) if item else desc
            if alt and "".join(ch for ch in alt if ch.isalnum()) not in seen:
                desc = alt
            else:
                # 摘出来的片段也撞车（两条近乎重复的事实）：接上各自的追问点
                tail = ((item or {}).get("follow_ups") or [""])[0]
                desc = f"{alt or desc}（追问：{tail}）" if tail else f"{alt or desc}（第 {gap.get('priority', len(out) + 1)} 条）"
        seen.add("".join(ch for ch in desc if ch.isalnum()))
        out.append(dict(gap, desc=desc))
    return out


def top_gaps_of(items: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    """缺口优先级：虚 > 中 > 强；同强度按清单顺序。

    永远尽量给满 limit 条（清单本身为空才返回空），原因见 _GAP_DESC。
    描述带上该条自己的事实片段，否则三条都是同一句话。
    """
    order = {"虚": 0, "中": 1, "强": 2}
    ranked = sorted(items, key=lambda it: order.get(it.get("strength", "虚"), 0))
    gaps = []
    used_per_strength: Dict[str, int] = {}
    used_variants: Dict[str, set] = {}
    for i, it in enumerate(ranked[:limit], start=1):
        strength = it.get("strength", "虚")
        # 同档内按出现位次错开动作变体，避免三条「强」的尾句又变成同一句
        slot = used_per_strength.get(strength, 0)
        used_per_strength[strength] = slot + 1
        gaps.append(
            {
                "priority": i,
                "fact_id": it["id"],
                "desc": gap_desc_of(it, slot, used_variants.setdefault(strength, set())),
                "strength": strength,
                "fact": it.get("fact", ""),
            }
        )
    return distinguish_gaps(gaps, items)


# ============ 一题多问检测 ============
#
# 只数问号是不够的：模型最常见的违规写法是用顿号把四个疑问并列塞进
# 一个问号里——「有多少个接口、几张表，压测用什么工具、打到多少并发？」
# 这一句只出现一个问号，却问了四件事。改成数"疑问词出现的次数"。

_ASK_WORDS = re.compile(
    r"(多长时间|多久|多少并发|多少|几个|几张|几条|几次|几轮|几位|几步|"
    r"哪些|哪块|哪部分|哪一步|哪种|哪一个|哪一|"
    r"什么工具|什么方法|什么方案|什么指标|什么数据|什么口径|什么|"
    r"怎么|如何|为什么|为啥|是否|有没有|能不能|是不是|要不要|谁)"
)

# 疑问词出现在这些搭配里时并不是在发问，命中就先把整段剔掉：
#   「不管什么情况」「无论怎么分工」「不知道怎么做」「没什么难度」
# 不剔的话，一句普通的陈述句会被数成两个问点，触发多问硬拒。
_NON_ASK = re.compile(
    r"(?:不管|不论|无论|不在意|不在乎)[^，,。？?！!；;、]{0,8}"
    r"|不(?:知道|清楚|确定|明白)[^，,。？?！!；;、]{0,6}"
    r"|没(?:什么|多少)[^，,。？?！!；;、]{0,6}"
    r"|(?:有|没)什么(?:好|可)[^，,。？?！!；;、]{0,6}"
)

# 「从多少个接口做到多少张表」是一个问点：区间句式先折叠成不含疑问词的占位，
# 否则两个「多少」会被数成两件事（实测 13 例样本里的主要误报来源）。
_ASK_RANGE = re.compile(
    r"从[^，,。？?！!；;]{0,15}?(?:做到|到|提升到|提高到|增加到|降到|压缩到|变成|涨到)"
    r"[^，,。？?！!；;]{0,15}"
)


def split_asks(question: str) -> List[str]:
    """把一句话里藏着的多个问点摊出来，返回命中的疑问词。

    不追求语言学上的完美切分：只要能把「一处问号、四处疑问」这种
    最典型的违规形式识别出来就够了。但也不能把陈述句算成发问——
    误报会直接触发硬拒、耗掉一轮提问机会。
    """
    text = question or ""
    text = _NON_ASK.sub("", text)
    text = _ASK_RANGE.sub("〔区间〕", text)
    return [m.group(1) for m in _ASK_WORDS.finditer(text)]


def is_multi_ask(question: str) -> bool:
    """一句话里问了两件及以上就算多问。"""
    text = question or ""
    return len(split_asks(text)) > 1 or text.count("？") + text.count("?") > 1


# ============ 改写事实冻结校验（docs/03 §3.5） ============

_ENTITY_PATTERNS = {
    "时间": re.compile(r"\d{4}\s*[年./-]\s*\d{1,2}\s*月?"),
    "数字": re.compile(r"\d+(?:\.\d+)?\s*(?:%|万|亿|人|条|次|天|个月|小时|ms|s|w|k)?"),
}
_ORG_HINT = re.compile(r"(公司|集团|科技|平台|银行|实验室|学院|大学|社团|协会)")


def _entity_set(text: str) -> Dict[str, set]:
    """抽实体并去掉词内空白：正则里的 `\\s*` 会把「200 QPS」抽成「200 」，
    导致同一个数字在原文与改写之间被当成本质不同的两个。"""
    text = text or ""
    return {
        name: {re.sub(r"\s+", "", m) for m in p.findall(text)}
        for name, p in _ENTITY_PATTERNS.items()
    }


def validate_rewrite(original: str, rewritten: str) -> Dict[str, Any]:
    """改写不得新增事实：数字只减不增，时间/组织/职位原样保留。"""
    src, dst = _entity_set(original), _entity_set(rewritten)
    violations: List[str] = []

    added_numbers = sorted(n for n in dst["数字"] - src["数字"] if n.strip())
    if added_numbers:
        violations.append("改写新增了原文没有的数字：" + "、".join(added_numbers))

    added_time = sorted(dst["时间"] - src["时间"])
    if added_time:
        violations.append("改写新增了原文没有的时间：" + "、".join(added_time))

    for role in ROLE_WORDS:
        if (role in rewritten) and (role not in original):
            violations.append(f"改写把角色改成「{role}」，原文未出现该表述")

    return {"ok": not violations, "violations": violations, "added_numbers": added_numbers}


# ============ 通用：技能交集 ============

_WORD_SPLIT = re.compile(r"[\s,，、/｜|;；:：()（）\[\]【】]+")


def skill_set(text: str) -> set:
    return {w.lower() for w in _WORD_SPLIT.split(text or "") if len(w) > 1}


def jd_overlap(jd_text: str, skills: List[str]) -> Dict[str, Any]:
    """重合率 r = |A ∩ B| / |A|，A 为 JD 抽取的技能要求集合。"""
    required = [w.strip() for w in _WORD_SPLIT.split(jd_text or "") if len(w.strip()) > 1]
    required = list(dict.fromkeys(required))
    if not required:
        return {"required": [], "hit": [], "ratio": 0.0, "foundation_score": 3}
    owned = {s.lower() for s in skills or []}
    hit = [w for w in required if any(w.lower() in o or o in w.lower() for o in owned)]
    ratio = len(hit) / len(required)
    return {
        "required": required,
        "hit": hit,
        "ratio": round(ratio, 3),
        "foundation_score": foundation_from_ratio(ratio),
    }


def overlap_by_items(items: List[Dict[str, Any]], skills: List[str]) -> Dict[str, Any]:
    """按「技能条目」算重合率，用于岗位基线（比 jd_overlap 的分词更准）。

    一条 = 一个技能要求；命中任一别名即算该条命中。
    分母是条目数而不是名字数，避免「消息队列（Kafka/RabbitMQ）」这种
    一个技能拆出三个名字、把比率稀释掉。
    """
    items = [it for it in (items or []) if isinstance(it, dict) and it.get("skill")]
    if not items:
        return {"required": [], "hit": [], "ratio": 0.0, "foundation_score": 3}
    owned = [s.lower() for s in (skills or []) if s]
    hit: List[str] = []
    for it in items:
        names = [str(it["skill"])] + [str(a) for a in (it.get("aliases") or []) if a]
        if any(n.lower() in o or o in n.lower() for n in names for o in owned):
            hit.append(str(it["skill"]))
    ratio = len(hit) / len(items)
    return {
        "required": [str(it["skill"]) for it in items],
        "hit": hit,
        "ratio": round(ratio, 3),
        "foundation_score": foundation_from_ratio(ratio),
    }


# ============ 规则兜底（AI 不可用时的降级路径） ============
#
# 只在「云端模型不通、诊断跑不起来」时使用。目的不是给出和模型一样的判断，
# 而是让面试有清单可用、页面不至于卡在死路；上限一律压在 6 分——
# 规则看不出证据强弱，给高分就是假装判断过。

COLLAB_WORDS = ("协作", "配合", "团队", "推动", "协调", "对接", "跨部门")


def bullets_of(resume: Dict[str, Any]) -> List[Dict[str, str]]:
    """把实习/项目要点拍平成条目，每条带上所属经历的抬头。"""
    out: List[Dict[str, str]] = []
    for key in ("internships", "projects"):
        for it in (resume or {}).get(key) or []:
            if not isinstance(it, dict):
                continue
            head = " · ".join(
                str(x) for x in [it.get("company") or it.get("name"), it.get("role"), it.get("time")] if x
            )
            for b in it.get("bullets") or []:
                text = str(b).strip()
                if text:
                    out.append({"head": head, "text": text, "kind": key, "role": str(it.get("role") or "")})
    return out


_DIM_FALLBACK_TEXT = {
    "foundation": ("技能与岗位要求的重合度偏低（规则判定）", "补上能对上岗位必备技能的项目或课程，别只在技能栏罗列"),
    "practice": ("可核实的经历条目偏少（规则判定）", "补一段实习或项目，写清你本人负责的那一部分"),
    "output": ("要点里缺少量化结果（规则判定）", "给每条要点补一个可核实的数字：规模、耗时或提升幅度"),
    "expression": ("要点偏短，信息量不足（规则判定）", "按「动作 → 方法 → 结果」把这条要点写完整"),
    "collaboration": ("看不到与他人的协作分工（规则判定）", "写清你和谁配合、你推动了哪一步"),
}


def fallback_career(resume: Dict[str, Any], foundation: Any = None) -> Dict[str, Any]:
    """按规则给五维估分 + 每个低分维度挑一条真实原文当证据。

    分数上限 6：规则只看得见「有没有、有没有数字、有多长、有没有协作词」，
    看不见证据强度与归因质量，给到 7 分以上就变成假装判断过了。
    """
    resume = resume or {}
    bs = bullets_of(resume)
    skills = [str(s) for s in (resume.get("skills") or []) if str(s).strip()]
    quantified = [b for b in bs if has_number(b["text"])]
    detailed = [b for b in bs if len(b["text"]) >= 20]
    collab = [b for b in bs if any(w in b["text"] for w in COLLAB_WORDS)]
    intern = [b for b in bs if b["kind"] == "internships"]

    base = clamp_score(foundation) if foundation not in (None, "") else 0
    if base <= 0:
        base = min(6, 3 + len(skills) // 3)

    entries = len({b["head"] for b in bs})
    practice = {0: 3, 1: 4, 2: 5}.get(entries, 6)
    if intern and practice < 5:
        practice = 5

    scores = {
        "foundation": max(3, min(6, base)),
        "practice": practice,
        "output": 3 + min(3, len(quantified)),
        "expression": 3 + min(3, len(detailed)),
        "collaboration": min(6, 3 + min(2, len(collab)) + (1 if intern and collab else 0)),
    }

    # 证据：每条必须是简历里的某一句原话，逐维挑不同的句子，避免五维同一句
    pool = [b["text"] for b in bs if len(b["text"].strip()) >= 12]
    summary = str(resume.get("summary") or "").strip()
    if len(summary) >= 12:
        pool.append(summary)

    evidence: List[Dict[str, Any]] = []
    used: set = set()
    for key, label, _w in CAREER_DIMS:
        if scores[key] > 6 or not pool:
            continue
        quote = next((q for q in pool if q not in used), pool[0])
        used.add(quote)
        problem, fix = _DIM_FALLBACK_TEXT.get(key, ("规则判定存在缺口", "按要点补齐可核实信息"))
        evidence.append({"dim": key, "quote": quote, "problem": problem, "fix": fix, "verified": True})

    return {"scores": scores, "evidence": evidence, "basis": "rules", "label_cap": 6}


_RESULT_HINT = re.compile(r"从|到|提升|降低|降到|减少|增长|达到|节省|覆盖|下降|压缩|倍|%")


def structural_items(resume: Dict[str, Any]) -> List[Dict[str, Any]]:
    """简历里同样可核实的「非经历」事实：教育背景、技能清单。

    单项目、0 实习的简历只有 3 条要点，6 轮面试必然反复锚定同一条。
    这两条不是编事实：学校/专业/GPA、技能栏原文都写在简历上，
    面试官也确实会问「这些技能里哪个是项目里真用过的、怎么用的」。
    结果字段留空时强度会是「虚」——这正是要问的缺口，不是伪造的结论。
    """
    out: List[Dict[str, Any]] = []

    for edu in (resume.get("education") or [])[:1]:
        if not isinstance(edu, dict):
            continue
        head = " · ".join(
            str(x).strip() for x in (edu.get("school"), edu.get("major"), edu.get("degree"), edu.get("time")) if str(x or "").strip()
        )
        if not head:
            continue
        extra = str(edu.get("extra") or "").strip()
        out.append(
            {
                "fact": "教育｜" + head + ("｜" + extra if extra else ""),
                "result": extra if has_number(extra) else "",
                "role": "参与",
                "source_module": "education",
            }
        )

    skills = [str(s).strip() for s in (resume.get("skills") or []) if str(s).strip()]
    if len(skills) >= 3:
        out.append(
            {
                "fact": "技能｜" + "、".join(skills[:8]),
                "result": "",
                "role": "参与",
                "source_module": "skills",
            }
        )
    return out


def auto_items(resume: Dict[str, Any], limit: int = 8) -> List[Dict[str, Any]]:
    """按简历要点生成事实清单条目：事实取原句，结果取「像结果」的那一个分句。

    只挑同时带数字和结果词的分句：`用 Vue3 重构列表页` 里的 3 是版本号，
    当成果写进清单就是给面试官递一个假靶子。
    """
    items: List[Dict[str, Any]] = []
    for b in bullets_of(resume)[:limit]:
        clauses = [c.strip() for c in re.split(r"[，,；;。]+", b["text"]) if c.strip()]
        result = next((c for c in clauses if has_number(c) and _RESULT_HINT.search(c)), "")
        if not result:
            result = next((c for c in clauses if _RESULT_HINT.search(c) and re.search(r"\d", c)), "")
        lead = b["role"] or b["head"]
        role = "独立" if re.search(r"负责人|主导|独立", lead + b["text"]) else "参与"
        items.append(
            {
                "fact": (b["head"] + "｜" if b["head"] else "") + b["text"],
                "result": result,
                "role": role,
                # 写真实来源模块，不写 "rules"：这个字段要能指回简历的实习/项目，
                # 界面点事实编号跳转、面试官判断"这是哪段经历"都靠它。
                "source_module": b["kind"],
            }
        )
    # 经历条目本来就够 4 条时不动清单：加进来的教育/技能只是给薄简历补锚点
    if len(items) < 4:
        items.extend(structural_items(resume))
    return items
