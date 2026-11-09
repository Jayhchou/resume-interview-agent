"""Agent 工具集（确定性能力层）。

每个工具都是「一次可验证的动作」，返回结构化结果回灌给模型。
模型不得自己算分、不得自己编号、不得自己判证据强度——这些都在这里。
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any, Callable, Dict, List, Tuple

import knowledge
import rubric
from docgen import build_resume_docx
from session import Session

# 导出产物：token → (bytes, filename, 过期时间)
_docs: Dict[str, Tuple[bytes, str, float]] = {}
DOC_TTL = 1800


def _clean_docs() -> None:
    now = time.time()
    for token in [t for t, v in _docs.items() if v[2] < now]:
        _docs.pop(token, None)


def take_doc(token: str) -> Tuple[bytes, str] | None:
    _clean_docs()
    item = _docs.get(token)
    if not item:
        return None
    _docs.pop(token, None)
    return item[0], item[1]


# ============ 简历完整性 ============

MODULE_CHECKS: List[Tuple[str, str, Callable[[Dict[str, Any]], bool]]] = [
    ("basic", "基本信息（姓名 / 求职意向）", lambda r: bool((r.get("basic") or {}).get("name") and (r.get("basic") or {}).get("target"))),
    ("education", "教育背景（学校 / 专业）", lambda r: any((e.get("school") and e.get("major")) for e in (r.get("education") or []))),
    ("internships", "实习经历（含要点）", lambda r: any((i.get("company") and i.get("bullets")) for i in (r.get("internships") or []))),
    ("projects", "项目经历（含要点）", lambda r: any((p.get("name") and p.get("bullets")) for p in (r.get("projects") or []))),
    ("skills", "技能或证书", lambda r: bool(r.get("skills") or r.get("certs"))),
    ("summary", "自我评价（≥ 20 字）", lambda r: len(str(r.get("summary") or "").strip()) >= 20),
]


def _completeness(resume: Dict[str, Any]) -> Tuple[int, List[str]]:
    missing = [label for _key, label, ok in MODULE_CHECKS if not ok(resume)]
    done = len(MODULE_CHECKS) - len(missing)
    return int(round(done / len(MODULE_CHECKS) * 100)), missing


# ============ 工具实现 ============

def tool_save_resume(args: Dict[str, Any], sess: Session) -> Dict[str, Any]:
    resume = args.get("resume")
    if not isinstance(resume, dict) or not resume:
        return {"ok": False, "error": "resume 必须是结构化对象（basic / education / internships / projects / skills / certs / summary）"}

    pct, missing = _completeness(resume)
    version = sess.bump_resume()
    resume["_completeness"] = pct
    resume["_missing"] = missing
    sess.resume = resume
    if args.get("target_role"):
        sess.target_role = str(args["target_role"]).strip()

    # 简历一改，下游产物全部失效，避免拿旧分数解新简历
    sess.career_scores = {}
    sess.career_total = 0
    sess.career_source = ""
    sess.career_evidence = []
    # 退回机会是按「这一版简历」给的：新简历不该因为上一版用过一次就失去校验
    sess.career_flat_blocked = 0
    sess.career_drift_blocked = 0
    sess.fact_sheet = None
    sess.report = None
    # 岗位基线里的 foundation_score 是按旧技能清单算的：简历变了必须按同样口径重算，
    # 否则模型拿到一个过期的基准值，专业基础分从第一步就是错的。
    if sess.jd_locked and sess.jd_args:
        tool_lock_jd(dict(sess.jd_args), sess)

    all_empty = pct == 0
    return {
        "ok": True,
        "resume_version": f"V{version}",
        "completeness": pct,
        "missing": missing,
        "can_diagnose": not all_empty,
        "note": "五类字段全空不得进入诊断（docs/03 §3.1）" if all_empty else "",
    }


def tool_lock_jd(args: Dict[str, Any], sess: Session) -> Dict[str, Any]:
    """锁定岗位与 JD，并给出专业基础分的基准值。

    三条路径：
    - 有 JD：按 JD 技能与简历技能的重合率算（jd_overlap）。
    - 无 JD 但岗位在基线库里：按岗位必备技能算（overlap_by_items），
      并回传该岗位的考察重点，让模型判分与出题有依据。
    - 无 JD 且岗位不在库里：不猜、不硬套别的岗位，明确告知基线缺失，
      要求模型在报告里说明——宁可如实说没有，也不要给一个假基准。
    """
    jd_text = str(args.get("jd_text") or "").strip()
    role = str(args.get("target_role") or sess.target_role or "").strip()
    if not role:
        return {"ok": False, "error": "缺目标岗位：先问学生投什么岗，再锁 JD"}
    skills = (sess.resume or {}).get("skills") or []

    if jd_text:
        overlap = rubric.jd_overlap(jd_text, skills)
        locked: Dict[str, Any] = {"role": role, **overlap, "source": "jd"}
    else:
        base = knowledge.baseline(role)
        if base:
            overlap = rubric.overlap_by_items(base.get("must") or [], skills)
            locked = {
                "role": role,
                **overlap,
                "source": "kb-role-baseline",
                "matched_role": base.get("role", ""),
                "focus": list(base.get("focus") or [])[:6],
                "gaps": list(base.get("gaps") or [])[:6],
                "note": f"未提供 JD，按「{base.get('role', role)}」岗位基线的必备技能计算重合率；报告里要注明基线来源",
            }
        else:
            locked = {
                "role": role,
                "required": [],
                "hit": [],
                "ratio": 0.0,
                "foundation_score": 3,
                "source": "no-baseline",
                "note": f"岗位基线库里没有「{role}」，也没有 JD：专业基础分无基准可依，必须按最低档给并在报告里说明基线缺失",
            }

    sess.target_role = role
    sess.jd_locked = locked
    sess.jd_args = {"target_role": role, "jd_text": jd_text}
    return {"ok": True, "locked": locked}


def _resume_fields(resume: Dict[str, Any]) -> List[str]:
    """把结构化简历拆成「一个个字段值」，逐个归一化。

    不能先把整份简历拍平成一段再比对：技能列表是 ["Python","PyTorch","机器学习"]，
    拍平后去掉标点会连成 `pythonpytorch机器学习`，模型拿这串当「原文引用」也能匹配上，
    但它在界面上看就是一段 JSON 拼串，不是简历里的句子。
    """
    parts: List[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            n = _norm(v)
            if n:
                parts.append(n)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(resume or {})
    return parts


_NORM_DROP = re.compile(r"[\s\u3000「」『』“”\"'‘’…·,，。；;：:()（）\[\]【】/、\\\-—–_~|]+")


def _norm(s: str) -> str:
    """去空白与标点后比较，避免模型抄原文时换了全角逗号就判不中。"""
    return _NORM_DROP.sub("", s or "").lower()


def _plausible(nq: str) -> bool:
    """一段引文是否「像一句话」。

    技能清单里的单个词（TensorFlow）技术上也出现在简历里，但拿它当「原文引用」
    说明模型没找到真正的句子，界面上一行一个字也很怪。要求：长度 ≥8，
    且含至少 2 个汉字或本身够长（照顾全英文简历）。
    """
    if len(nq) < 8:
        return False
    return len(re.findall(r"[\u4e00-\u9fa5]", nq)) >= 2 or len(nq) >= 12


def quote_verified(quote: str, fields: List[str]) -> bool:
    """引文是否为某一字段的原文片段（逐字段比对，不许跨字段拼接）。

    抄两句用 `…` 省略时，要求每段都落在同一个字段里。
    """
    segs = [x for x in re.split(r"…|\.\.\.", quote or "") if len(_norm(x)) >= 8]
    segs = [_norm(x) for x in segs]
    if not segs:
        nq = _norm(quote)
        segs = [nq] if _plausible(nq) else []
    if not segs or not all(_plausible(s) for s in segs):
        return False
    return any(all(s in f for s in segs) for f in fields)


def _hint_quote(fields: List[str], resume: Dict[str, Any]) -> str:
    """从简历里挑一条最像「可引用句子」的原文，给模型当范例。"""
    best = ""
    for f in fields:
        if len(f) >= 12 and (not best or len(f) > len(best)):
            best = f
    if not best:
        return ""
    # 还成原文的样子：从原结构里找含这段的最长原值
    def walk(v: Any) -> str:
        if isinstance(v, str):
            return v if _norm(v) == best else ""
        if isinstance(v, dict):
            for x in v.values():
                r = walk(x)
                if r:
                    return r
        if isinstance(v, list):
            for x in v:
                r = walk(x)
                if r:
                    return r
        return ""

    return walk(resume or {}) or ""


def _fallback_score(sess: Session) -> Dict[str, Any]:
    """AI 不可用时的规则估分：分数上限 6，只为让流程不卡死，不代表模型判断。

    刻意不接受前端传来的分数——那等于让浏览器判分入库，
    与「判定在服务端」直接冲突。
    """
    if not sess.resume:
        return {"ok": False, "error": "状态不足：还没有保存简历，不能估分"}

    foundation = (sess.jd_locked or {}).get("foundation_score")
    fb = rubric.fallback_career(sess.resume, foundation)
    total = rubric.weighted_total(fb["scores"], rubric.CAREER_DIMS)

    sess.career_scores = fb["scores"]
    sess.career_total = total
    sess.career_source = "rules"
    sess.career_evidence = list(fb["evidence"])
    sess.career_history.append(
        {
            "resume_version": f"V{sess.resume_version}",
            "scores": dict(fb["scores"]),
            "total": total,
            "source": "rules",
        }
    )
    return {
        "ok": True,
        "mode": "fallback",
        "scores": fb["scores"],
        "total": total,
        "level": rubric.level_of(total),
        "evidence": fb["evidence"],
        "score_cap": 6,
        "note": "云端模型不可用，由服务端规则估分：分数上限 6，只作兜底，不得当作模型判断复述",
    }


DEFAULT_ROUNDS = 5


def _clamp_rounds(rounds: Any) -> int:
    """计划轮数只允许 1–12；缺省/非法（空串、0、None）回到默认 5。

    不能保留 0：`rounds_planned=0` 在 Python 与 JS 里都是假值，
    前端「答满就锁」的判断 `rounds_planned && round_no >= rounds_planned`
    直接短路，输入框永远不锁，学生能一直答，复盘口径被改。
    """
    try:
        value = int(str(rounds).strip() or 0)
    except (TypeError, ValueError):
        value = 0
    return value if 1 <= value <= 12 else DEFAULT_ROUNDS


def reset_interview(sess: Session, scene: str = "", role: str = "", rounds: int = 0) -> None:
    """清空整场面试状态：重开一场、或新事实清单生效时调用。

    只清 turns 是不够的：asked / answered / round_no / layer_count / last_prompt_key
    任意一个留着，下一场都会被当成上一场的续篇——第一题就算成"第 6 轮"并立刻
    reached_limit，或者被上场的 last_prompt_key 判成"刚问过"而拒收。
    """
    sess.interview.update(
        {
            "scene": scene,
            "role": role,
            # 轮数是本场的硬约束：0 / 空 / 越界一律按默认 5 轮。
            # 放过 0 会建出一个 planned=0 的场次——第一题就 reached_limit，
            # 前端比的是 `rounds_planned && round_no >= rounds_planned`，0 是假值，
            # 于是永远不锁输入，学生能一直答下去，复盘口径全乱。
            "rounds_planned": _clamp_rounds(rounds),
            "round_no": 0,
            "layer": "",
            "layer_count": 0,
            "anchored_fact_id": "",
            "asked": 0,
            "answered": 0,
            "last_prompt_key": "",
            "multi_ask_blocked": 0,   # 本场是否已经因"一题多问"硬拒过一次
            "dup_fields_blocked": 0,  # 复盘四栏是否已经因"差在哪＝本可以答成"退回过一次
            "flat_blocked": 0,        # 复盘五维是否已经因"全同分"退回过一次
            "star_blocked": 0,        # 复盘是否已经因"三题 STAR 一模一样"退回过一次
            "asked_facts": {},
            "coverage_blocked": 0,
            "pending_question": {},
            "turns": [],
        }
    )


def tool_score_career(args: Dict[str, Any], sess: Session) -> Dict[str, Any]:
    if args.get("fallback") is True:
        return _fallback_score(sess)

    raw = args.get("scores") or {}
    evidence_in = args.get("evidence") or []

    if not sess.resume:
        return {"ok": False, "error": "状态不足：还没有保存简历，不能诊断"}

    scores: Dict[str, int] = {}
    for key, label, _w in rubric.CAREER_DIMS:
        if key not in raw:
            return {"ok": False, "error": f"缺维度 {key}（{label}）；五维必须齐全"}
        scores[key] = rubric.clamp_score(raw[key])

    # 区分度：五维给成同一个分等于没判——雷达图退化成正五边形，
    # 「最该先改的三件事」也就失去了依据。第一次退回让模型逐维重判，同场只退一次：
    # 有些简历确实五维同档，第二次照收，不能为了区分度把诊断卡死。
    # 只差 1 分（如 9/8/8/8/9）是正常的强弱信号，不拦，只在返回里提示。
    spread = max(scores.values()) - min(scores.values())
    if spread == 0 and not sess.career_flat_blocked:
        sess.career_flat_blocked = 1
        return {
            "ok": False,
            "scores": scores,
            "error": (
                "五维给成了同一个分（"
                + "/".join(str(scores[k]) for k, _l, _w in rubric.CAREER_DIMS)
                + "）：等于用整体印象套五维，雷达图会退化成正五边形，看不出强弱项。"
            ),
            "hint": (
                "逐维对照分档表重判，至少两维拉开 2 分以上：哪一维明确强于其他维（例如经历里有主导+量化），"
                "哪一维明确最弱（例如表达只写了职责没写动作）。确实没有明显强弱时，在 evidence 的 problem 里写清"
                "「为什么两维同档」，不要只给一个整体印象分再套到五维上。"
            ),
        }

    # 稳定性：同一份简历（版本没变）两次判分差超过 5 分，说明判分依据在漂。
    # 同样只退回一次，并给出上次的分数让模型对照，而不是让它重新猜一遍。
    total_now = rubric.weighted_total(scores, rubric.CAREER_DIMS)
    previous = sess.career_total
    same_resume = not sess.career_history or sess.career_history[-1].get("resume_version") == f"V{sess.resume_version}"
    if previous and same_resume and abs(total_now - previous) > 5 and not sess.career_drift_blocked:
        sess.career_drift_blocked = 1
        return {
            "ok": False,
            "scores": scores,
            "total": total_now,
            "previous_total": previous,
            "previous_scores": dict(sess.career_scores or {}),
            "error": (
                f"同一份简历上次判 {previous} 分，这次 {total_now} 分，相差 {abs(total_now - previous)} 分：判分依据在漂。"
            ),
            "hint": "对照 previous_scores 与分档表复核：哪一维的档位这次挪了？给出具体依据（原文片段）后再提交，不要为了凑分改口径。",
        }

    # 每处扣分必须带原文片段 + 问题类型 + 修改方向（docs/03 §3.2）
    text_norm = _resume_fields(sess.resume)
    example = _hint_quote(text_norm, sess.resume)
    by_dim: Dict[str, List[Dict[str, Any]]] = {}
    rejected: List[str] = []
    missing_modules = (sess.resume or {}).get("_missing", [])
    for ev in evidence_in:
        if not isinstance(ev, dict):
            continue
        dim = str(ev.get("dim") or "").strip()
        if dim not in scores:
            continue
        problem = str(ev.get("problem") or "").strip()
        fix = str(ev.get("fix") or "").strip()

        # 简历上根本没有这个模块时（例如零实习），没有原文可引是正确的，
        # 不该逼模型拿技能清单拼串硬凑。允许按「缺失」上报，但服务端要核：
        # 声明的模块必须真的在 _missing 里，否则照样驳回。
        if ev.get("missing") is True:
            module = str(ev.get("module") or "").strip()
            if not (problem and fix):
                return {"ok": False, "error": f"维度 {dim} 按缺失上报时，problem / fix 仍需给出"}
            if not module or not any(module in m for m in missing_modules):
                return {
                    "ok": False,
                    "error": f"「{module or '未指明模块'}」并不算缺失，不能按缺失上报",
                    "resume_missing": missing_modules,
                }
            by_dim.setdefault(dim, []).append(
                {
                    "quote": f"（简历缺「{module}」）",
                    "problem": problem,
                    "fix": fix,
                    "verified": False,
                    "missing": module,
                }
            )
            continue

        quote = str(ev.get("quote") or "").strip()
        if not (quote and problem and fix):
            return {"ok": False, "error": f"维度 {dim} 的证据缺字段：quote / problem / fix 三者缺一不可"}
        # 引文必须是简历原文的某一处。模型偶尔会把技能列表拼串、JSON 片段、自己的改写
        # 当成原文抄来，这种证据看着像证据，实际无法回查，必须挡掉。
        if not quote_verified(quote, text_norm):
            rejected.append(quote)
            continue
        by_dim.setdefault(dim, []).append({"quote": quote, "problem": problem, "fix": fix, "verified": True})

    if rejected and not any(by_dim.values()):
        return {
            "ok": False,
            "error": f"证据里没有一条能对上简历原文，例如「{rejected[0][:40]}」",
            "hint": "quote 必须是简历里某一处的原话（一个人写的一句话），不要用技能清单拼串、字段名、JSON 或自己的改写",
            "example_quote": example,
        }

    weak = [k for k, v in scores.items() if v <= 6]
    missing_evidence = [k for k in weak if not by_dim.get(k)]
    if missing_evidence:
        return {
            "ok": False,
            "error": "以下低于 7 分的维度没有给出有效扣分证据：" + "、".join(missing_evidence),
            "hint": "每个 ≤6 分的维度至少 1 条证据（简历原文逐字片段 + 问题 + 修改方向）",
            "rejected_quotes": rejected[:3],
            "example_quote": example,
        }

    total = rubric.weighted_total(scores, rubric.CAREER_DIMS)
    previous = sess.career_total
    unstable = bool(previous) and abs(total - previous) > 5

    flat = [{"dim": d, **item} for d, items in by_dim.items() for item in items]
    sess.career_scores = scores
    sess.career_total = total
    sess.career_source = "model"
    sess.career_evidence = flat
    sess.career_history.append({"resume_version": f"V{sess.resume_version}", "scores": dict(scores), "total": total})

    return {
        "ok": True,
        "scores": scores,
        "total": total,
        "level": rubric.level_of(total),
        "unstable": unstable,
        "previous_total": previous or None,
        "evidence": flat,
        "evidence_count": {k: len(v) for k, v in by_dim.items()},
        "rejected_quotes": rejected[:3],
        "spread": max(scores.values()) - min(scores.values()),
        "warning": (f"{len(rejected)} 条证据不是简历原文，已剔除，不要写进回答里" if rejected else ""),
        "note": (
            "总分波动超过 5 分，请复核分档依据后重判"
            if unstable
            else ("五维只差 1 分：区分度偏低，若确有明显强弱项请在 evidence 里说清依据" if max(scores.values()) - min(scores.values()) <= 1 else "")
        ),
    }


# 少于这个数，5 轮面试只能围着一两条打转。4 条经历要点 + 1 条结构事实
# （教育/技能）刚好够 5 轮各锚一条，不至于同一句反复换层问。
MIN_FACT_ITEMS = 5


def _fact_key(text: str) -> str:
    """比较两条事实是否重复用的粗略指纹：去掉抬头前缀与标点，取前 24 字。

    模型写的 `P｜做 A，12 个接口` 和规则摊出来的 `P · 主导｜做 A，12 个接口`
    说的是同一件事，只是抬头写法不同——按整串比会重复入库，所以先切掉 `｜` 之前的抬头。
    """
    body = str(text or "")
    if "｜" in body:
        body = body.rsplit("｜", 1)[-1]
    cleaned = "".join(ch for ch in body if ch.isalnum())
    return cleaned[:24]


def _supplement_items(normalized: List[Dict[str, Any]], resume: Dict[str, Any],
                      target: int = MIN_FACT_ITEMS) -> List[Dict[str, Any]]:
    """把模型给的清单补厚：按简历要点摊条目，跳过已经覆盖的。

    模型常见的偷懒方式是把一个项目的 3 条要点压成 1 条事实。清单只有 1–2 条时，
    5 轮面试必然反复锚定同一条，逐题点评也只会引同一段原文——补的是这个缺口，
    不是替模型编事实：每条都来自简历原句，来源模块照实写。
    """
    need = target - len(normalized)
    if need <= 0:
        return []
    existing = [_fact_key(i.get("fact")) for i in normalized if i.get("fact")]
    out: List[Dict[str, Any]] = []
    for cand in rubric.auto_items(resume or {}, limit=12):
        key = _fact_key(cand.get("fact"))
        if not key or any(key in old or old in key for old in existing if old):
            continue
        existing.append(key)
        out.append(cand)
        if len(out) >= need:
            break
    return out


def tool_build_fact_sheet(args: Dict[str, Any], sess: Session) -> Dict[str, Any]:
    auto = args.get("auto") is True
    if auto:
        # 规则兜底：只把简历里现成的要点摊成条目，不补事实、不猜归因
        if not sess.career_scores:
            return {"ok": False, "error": "状态不足：先完成诊断（S2）再建清单（S3）"}
        made = rubric.auto_items(sess.resume or {})
        if not made:
            return {"ok": False, "error": "简历里没有可用的经历要点，无法自动生成清单"}
        args = {"items": made}

    items = args.get("items")
    if not isinstance(items, list) or not items:
        return {"ok": False, "error": "items 为空：事实清单至少一条"}
    if not sess.career_scores:
        return {"ok": False, "error": "状态不足：先完成五维诊断（S2）再建清单（S3）"}

    raw_items = [i for i in items if isinstance(i, dict)]
    normalized = rubric.normalize_items(raw_items)
    bad = [i["id"] for i in normalized if not i["fact"]]
    if bad:
        return {"ok": False, "error": f"以下条目缺事实句：{'、'.join(bad)}"}

    supplemented: List[Dict[str, Any]] = []
    if not auto and len(normalized) < MIN_FACT_ITEMS:
        supplemented = _supplement_items(normalized, sess.resume or {})
        if supplemented:
            normalized = rubric.normalize_items(raw_items + supplemented)
    if len(normalized) > 12:
        normalized = normalized[:12]

    top_gaps = args.get("top_gaps")
    if not isinstance(top_gaps, list) or not top_gaps:
        # 「最该先改」只从经历里挑：教育/技能是补位锚点，结果字段本来就空，
        # 让它们占掉前三会变成「你的技能栏缺量化」这种没有可执行含义的建议。
        gap_pool = [i for i in normalized if i.get("source_module") in ("internships", "projects")] or normalized
        top_gaps = rubric.top_gaps_of(gap_pool)
    else:
        # 模型也会把同一句「最该先练」复制三遍，只是换个编号。描述撞车就换成
        # 该条事实自己的片段 + 这一档该做的事，别让三行读起来一模一样。
        top_gaps = [
            {
                "priority": int(g.get("priority") or i),
                "fact_id": g.get("fact_id"),
                "desc": str(g.get("desc") or "").strip(),
                "strength": g.get("strength") or "",
            }
            for i, g in enumerate([g for g in top_gaps if isinstance(g, dict)], start=1)
        ]
        top_gaps = rubric.distinguish_gaps(top_gaps, normalized)

    version = (sess.fact_sheet or {}).get("sheet_version", "v0")
    nxt = f"v{int(version.lstrip('v') or 0) + 1}" if version else "v1"

    sheet = {
        "sheet_version": nxt,
        "target_roles": [sess.target_role] if sess.target_role else [],
        "resume_version": f"V{sess.resume_version}",
        "scores": sess.career_scores,
        "items": normalized,
        "top_gaps": top_gaps[:3],
        "source": "rules" if auto else "model",
    }
    sess.fact_sheet = sheet
    # 新清单 = 新一场面试。只清 turns 会留下旧的 asked/answered/round_no/last_prompt_key：
    # 下一场第一题就被算成"第 6 轮"、立刻 reached_limit，还会因为旧 key 被判"刚问过"。
    reset_interview(sess)
    sess.report = None

    if auto:
        note = "规则兜底生成的清单：只搬运原句，未做证据分级与追问设计"
    elif supplemented:
        note = (
            f"你只交了 {len(raw_items)} 条，另按简历要点补齐 {len(supplemented)} 条"
            f"（共 {len(normalized)} 条）：逐题记录里只能引用这些编号"
        )
    else:
        note = ""

    return {
        "ok": True,
        "sheet_version": nxt,
        "items": normalized,
        "source": "rules" if auto else "model",
        "supplemented": len(supplemented),
        "strength_summary": {s: sum(1 for i in normalized if i["strength"] == s) for s in ("强", "中", "虚")},
        "top_gaps": sheet["top_gaps"],
        "note": note,
    }


def _has_digit(s: str) -> bool:
    return any(ch.isdigit() for ch in s or "")


def tool_validate_rewrite(args: Dict[str, Any], sess: Session) -> Dict[str, Any]:
    """校验改写是否只换了说法、没动事实；再按写作规范挑出「改了等于没改」的地方。

    violations 是硬错（新增了原文没有的数字/时间/角色），必须修；
    warnings 是软提示（弱动词没换掉、仍全是定性描述），不计入 ok。
    """
    original = str(args.get("original") or "").strip()
    rewritten = str(args.get("rewritten") or "").strip()
    if not original or not rewritten:
        return {"ok": False, "error": "original 与 rewritten 都必须提供"}

    res = rubric.validate_rewrite(original, rewritten)
    warnings: List[str] = []
    asks: List[str] = []

    # 1) 弱动词：原文有、改写也原样保留，说明只是换了语序
    kept = []
    for verb, tip in knowledge.weak_verbs().items():
        if verb and verb in original and verb in rewritten:
            kept.append(verb)
            if tip:
                asks.append(f"「{verb}」要问清：{tip}")
    if kept:
        warnings.append(
            "弱动词原样保留：" + "、".join(f"「{v}」" for v in kept)
            + "——这类词只说明在场，不说明做到什么程度，改后仍无法判断你的贡献"
        )

    # 2) 量化：原文与改写都没有数字，就仍是定性描述（不许靠编数字过校验）
    if not _has_digit(original) and not _has_digit(rewritten):
        kinds = knowledge.quant_kinds()
        sample = "；".join(f"{k}（{v}）" for k, v in list(kinds.items())[:4])
        warnings.append(
            "改后仍无可验证结果：不是让你凑数字，而是原文缺口径。"
            f"可补的口径有四类——{sample}。拿不到就写「待补充」，不许编"
        )

    return {
        "ok": res.get("ok", True),
        "violations": res.get("violations") or [],
        "added_numbers": res.get("added_numbers") or [],
        "warnings": warnings,
        "asks": asks,
    }


def _answer_key(text: str) -> str:
    """回答的粗略指纹：只留字母数字，取前 30 字。用来判「是不是同一句回答」。"""
    return "".join(ch for ch in str(text or "") if ch.isalnum())[:30]


def _is_duplicate_answer(it: Dict[str, Any], answer: str) -> bool:
    """本轮回答是否已经记过。前端先落库、模型后补一条时全靠这个去重。"""
    turns = it.get("turns") or []
    if not turns:
        return False
    last = turns[-1]
    old, new = _answer_key(last.get("answer")), _answer_key(answer)
    if not old or not new:
        return False
    if old == new:
        return True
    # 模型可能把学生原话略作转述（补个标点、截断半句），比前缀足够判断
    head = 16
    return old[:head] == new[:head]


def record_answer(sess: Session, answer: str, source: str = "client") -> Dict[str, Any]:
    """把学生的回答记进本场面试（前端兜底落库）。

    为什么需要这条路径：落库原本只走「模型主动调用 log_interview_turn(answer=…)」。
    模型经常只写点评就跳过这次调用，于是 answered 不涨 → round_no 不动 →
    界面永远显示第 1 轮、reached_limit 不触发、save_report 只能拿到已落库的题。
    学生原话前端本来就有，由服务端直接收，判定权仍在服务端（不改分、不改结论）。
    """
    text = str(answer or "").strip()
    if not text:
        return {"ok": False, "error": "回答为空"}
    if not sess.fact_sheet:
        return {"ok": False, "error": "状态不足：事实清单为空，还没开始面试"}

    it = sess.interview
    planned = int(it.get("rounds_planned") or 0) or 5
    if len(it.get("turns") or []) >= planned:
        # 答满后再收一句，复盘就按 4 题算分，和「3 轮」的承诺对不上。
        # 前端会锁输入框，这里是第二道闸：任何客户端都收不进来。
        return {
            "ok": False,
            "reached_limit": True,
            "round_no": it.get("round_no", len(it.get("turns") or [])),
            "rounds_planned": planned,
            "error": f"计划 {planned} 轮已答完，这一句不计入本场。点「结束本场」看复盘，或重新开一场。",
        }
    if _is_duplicate_answer(it, text):
        return {
            "ok": True,
            "deduped": True,
            "round_no": it["round_no"],
            "rounds_planned": planned,
            "reached_limit": it["round_no"] >= planned,
        }

    pending = it.get("pending_question") or {}
    valid_ids = {i["id"] for i in sess.fact_sheet.get("items", [])}
    fact_id = str(pending.get("fact_id") or it.get("anchored_fact_id") or "")
    if fact_id not in valid_ids:
        # 兜底：模型没记题时挂到清单第一条，总比丢掉这句回答强
        fact_id = sorted(valid_ids)[0] if valid_ids else ""
    layer = str(pending.get("layer") or it.get("layer") or "事实")

    it["turns"].append(
        {
            "fact_id": fact_id,
            "layer": layer,
            "question": str(pending.get("question") or ""),
            "answer": text,
            "source": source,
        }
    )
    it["round_no"] = len(it["turns"])
    it["answered"] = int(it.get("answered") or 0) + 1
    it["pending_question"] = {}

    return {
        "ok": True,
        "deduped": False,
        "fact_id": fact_id,
        "layer": layer,
        "round_no": it["round_no"],
        "rounds_planned": planned,
        "reached_limit": it["round_no"] >= planned,
    }


def tool_log_interview_turn(args: Dict[str, Any], sess: Session) -> Dict[str, Any]:
    if not sess.fact_sheet:
        return {"ok": False, "error": "状态不足：事实清单为空，先建清单（S3）再出题"}

    fact_id = str(args.get("fact_id") or "").strip()
    valid_ids = sorted(i["id"] for i in sess.fact_sheet["items"])
    if fact_id not in valid_ids:
        # 别把合法编号拼在句尾：模型会把「必须填 E1」读成「E1 不合法」。
        return {
            "ok": False,
            "error": f"fact_id 传的是「{fact_id or '空'}」，清单里没有这一条。",
            "valid_ids": valid_ids,
            "hint": "从 valid_ids 里挑一个填进 fact_id（清单内编号只有这些）",
        }

    layer = str(args.get("layer") or "").strip()
    question = str(args.get("question") or "").strip()
    answer = str(args.get("answer") or "").strip()

    it = sess.interview
    if args.get("scene"):
        it["scene"] = str(args["scene"]).strip()
    if args.get("rounds_planned"):
        try:
            it["rounds_planned"] = max(1, min(12, int(args["rounds_planned"])))
        except (TypeError, ValueError):
            pass
    if args.get("role"):
        it["role"] = str(args["role"]).strip()

    warnings: List[str] = []
    asks = rubric.split_asks(question)
    multi = rubric.is_multi_ask(question)
    if multi and not answer:
        # 前两次硬拒，逼模型当场改写成单问；之后只警告——模型要是改不过来，
        # 一直拒会让它把 maxRounds 耗光，学生只会看到"本轮没拿到问题"。
        # 计数在"通过一次"时归零：每次出题都重新拥有两次改写机会，
        # 不是整场共用两次（否则前两轮误判之后，后面多问就再没人管）。
        rejected = int(it.get("multi_ask_blocked") or 0)
        if rejected < 2:
            it["multi_ask_blocked"] = rejected + 1
            return {
                "ok": False,
                "error": f"一题多问：这一句里问了 {len(asks) or 2} 件事（{'、'.join(asks) or '多个问号'}），必须改写成单问。",
                "asks": asks,
                "hint": "只保留一个问点：其余问点留到后面几轮，或用一句话把它们收成一个问句（例如「这几个接口和你负责的部分是怎么分工的？」）",
            }
        warnings.append("一题多问：本轮仍问了不止一件事，必须只保留一个问点")
    elif not multi:
        it["multi_ask_blocked"] = 0
    if question.count("？") + question.count("?") > 1:
        warnings.append("一题多问：本轮出现了两个及以上问号，必须回退重写成单问")

    if answer:
        planned_now = int(it.get("rounds_planned") or 0) or 5
        if len(it.get("turns") or []) >= planned_now:
            # 与 record_answer 同一道闸：模型也可能在答满后继续调工具补记
            return {
                "ok": False,
                "reached_limit": True,
                "round_no": it.get("round_no", len(it.get("turns") or [])),
                "rounds_planned": planned_now,
                "error": f"计划 {planned_now} 轮已答完，不再记录新的回答；请出复盘（save_report）而不是继续提问",
            }
        # 前端在发回答时已经先落库过一次（record_answer）。模型随后再调一次带 answer
        # 的同一句，这里必须认出来，否则一轮回答记两条、复盘里同一个答案出现两次。
        if _is_duplicate_answer(it, answer):
            return {
                "ok": True,
                "deduped": True,
                "round_no": it["round_no"],
                "rounds_planned": it.get("rounds_planned") or 5,
                "reached_limit": it["round_no"] >= (it.get("rounds_planned") or 5),
                "warnings": warnings,
                "note": "这句回答前端已经落库过，本轮不重复记录",
            }
        pending = it.get("pending_question") or {}
        it["turns"].append(
            {
                "fact_id": fact_id,
                "layer": layer,
                "question": question or str(pending.get("question") or ""),
                "answer": answer,
                "source": "model",
            }
        )
        it["round_no"] = len(it["turns"])
        it["answered"] = int(it.get("answered") or 0) + 1
        it["pending_question"] = {}

    # 层数只按「同一事实连续同层」累计；换了事实就重新计数
    if layer and not answer:
        same_spot = layer == it.get("layer") and fact_id == (it.get("anchored_fact_id") or "")
        it["layer_count"] = int(it.get("layer_count") or 0) + 1 if same_spot else 1
    it["layer"] = layer or it.get("layer", "")
    it["anchored_fact_id"] = fact_id

    if it["layer_count"] >= 2 and not answer:
        warnings.append("连续两层停在同一层：按 docs/03 §5.2 停止下潜，给示范答法后重问")

    # 同一事实 + 同一层连续追问 = 原地打转：直接拒，逼模型换层或换条目
    prompt_key = f"{fact_id}::{layer}"
    if not answer:
        if it.get("last_prompt_key") == prompt_key:
            return {
                "ok": False,
                "error": f"{fact_id} 的「{layer}」层刚问过，不要换个说法重问：换层（方法 / 量化 / 归因 / 反思），或换另一个 fact_id",
            }
        # 覆盖率：3 轮全锚在 E1（清单里 E2/E3 一次没问）等于只验证了一条经历。
        # 允许同一条连续问两次（事实层 + 方法层是合理的深挖），第三次仍在原地就
        # 硬拒一次，把模型推向没问过的条目；没覆盖的条目用完之前不再拦，
        # 免得「清单只有 2 条但计划 5 轮」时把出题卡死。
        asked_map = it.setdefault("asked_facts", {})
        times = int(asked_map.get(fact_id) or 0)
        unused = [fid for fid in valid_ids if not asked_map.get(fid)]
        if unused and times >= 2 and int(it.get("coverage_blocked") or 0) < 1:
            it["coverage_blocked"] = 1
            return {
                "ok": False,
                "error": (
                    f"{fact_id} 已经问过 {times} 次，清单里的 {'、'.join(unused)} 一次都没问："
                    "面试只验证了一条经历，简历其余部分等于没被检查。"
                ),
                "uncovered": unused,
                "asked_facts": dict(asked_map),
                "hint": "换一个没问过的 fact_id 出题；要深挖同一条，等其余条目都覆盖过再说",
            }
        if unused and times >= 1:
            warnings.append(
                f"覆盖提醒：{fact_id} 已问过 {times} 次，{'、'.join(unused)} 还没覆盖"
            )
        asked_map[fact_id] = times + 1
        it["last_prompt_key"] = prompt_key
        it["asked"] = int(it.get("asked") or 0) + 1
        # 记下这道题，等学生回答时按它对号入座（模型跳过工具调用的那一路也要能挂上）
        it["pending_question"] = {"fact_id": fact_id, "layer": layer, "question": question}

    planned = it.get("rounds_planned") or 5
    asked_now = it.get("asked_facts") or {}
    return {
        "ok": True,
        "round_no": it["round_no"],
        "rounds_planned": planned,
        "reached_limit": it["round_no"] >= planned,
        "layer_count": it["layer_count"],
        "uncovered_facts": [fid for fid in valid_ids if not asked_now.get(fid)],
        "warnings": warnings,
    }


def tool_save_report(args: Dict[str, Any], sess: Session) -> Dict[str, Any]:
    if not sess.interview["turns"]:
        return {"ok": False, "error": "状态不足：还没有答题记录，不能出复盘"}

    per_q = args.get("per_question")
    if not isinstance(per_q, list) or not per_q:
        return {"ok": False, "error": "per_question 为空"}

    required = ("qid", "fact_id", "question", "intent", "expect", "actual", "gap")
    cleaned = []
    for item in per_q:
        if not isinstance(item, dict):
            continue
        lost = [k for k in required if not str(item.get(k) or "").strip()]
        if lost:
            return {"ok": False, "error": f"qid={item.get('qid', '?')} 缺字段：{'、'.join(lost)}（四栏缺一即不合格）"}
        # star 允许缺：模型没给就别替它判"四项全缺"——前端会把四个都标成灰色，
        # 学生读到的结论是"我四项全不会"，这比"未评"更误导。
        star_norm = rubric.normalize_star(item.get("star"))
        cleaned.append(
            {
                "qid": item["qid"],
                "fact_id": item["fact_id"],
                "question": item["question"],
                "intent": item["intent"],
                "expect": item["expect"],
                "actual": item["actual"],
                "gap": item["gap"],
                "star": star_norm,
            }
        )

    # 「本可以答成」和「差在哪」写成同一句 = 一张卡里同一句话印两遍，
    # 学生看不出「该答成什么样」和「我差哪一步」的区别。
    # 第一次退回让它把两者分开；已经退过一次就收下——措辞不该把复盘卡死，
    # 前端另有按内容去重的合并渲染兜底。
    dup_qids = []
    for c in cleaned:
        gap_key = _answer_key(c["gap"])
        if gap_key and gap_key in (_answer_key(c["expect"]), _answer_key(c["intent"])):
            dup_qids.append(c["qid"])
    if dup_qids and not sess.interview.get("dup_fields_blocked"):
        sess.interview["dup_fields_blocked"] = 1
        return {
            "ok": False,
            "error": (
                f"qid={dup_qids[0]} 的「差在哪」和前面的栏位是同一句话。"
                "四栏各管一件事：intent=考官想验证什么；expect=满分答法要包含哪几个动作；"
                "gap=他这句话比 expect 少的那一步（具体到动作或数据）。请改写后再提交。"
            ),
        }

    raw_scores = args.get("scores") or {}
    for key, _label, _w in rubric.INTERVIEW_DIMS:
        if key not in raw_scores:
            return {"ok": False, "error": f"缺面试维度 {key}"}
    scores = {k: rubric.clamp_score(raw_scores[k]) for k, _l, _w in rubric.INTERVIEW_DIMS}

    # 区分度：五维给成同一个分（本轮实测 7/7/7/7/7）等于用整体印象套五维，
    # 雷达图退化成正五边形，卡点排序也失去依据。
    # STAR 同理：几道题给出完全相同的四元组，等于只看了第一题。
    # 两条都只在第一次退回，同场各退一次——确实每题都平平的场次，第二次照收，
    # 不能为了区分度把复盘卡死。两个问题同时出现时一次说完，不让学生连吃两次退回。
    spread = max(scores.values()) - min(scores.values())
    star_sets = [tuple(sorted(c["star"].items())) for c in cleaned if c["star"]]
    star_same = (
        len(cleaned) >= 2
        and len(star_sets) == len(cleaned)
        and len(set(star_sets)) == 1
    )
    flat_hit = spread == 0 and not sess.interview.get("flat_blocked")
    star_hit = star_same and not sess.interview.get("star_blocked")
    if flat_hit or star_hit:
        problems, hints = [], []
        if flat_hit:
            sess.interview["flat_blocked"] = 1
            problems.append(
                "五维给成了同一个分（" + "/".join(str(scores[k]) for k, _l, _w in rubric.INTERVIEW_DIMS)
                + "），这是整体印象，不是逐维判定"
            )
            hints.append(
                "按题回看再判，至少两维拉开 2 分：tech_depth 看有没有讲清方法与取舍；project 看有没有"
                "可验证的结果；logic 看有没有结论先行；behavior 看归因边界（你的活还是团队的）；"
                "fit 看答的内容和岗位要求对不对得上。某一维确实没证据就压到 4 分以下，"
                "并在 gaps 里写明缺什么，不要五维一起给中位数"
            )
        if star_hit:
            sess.interview["star_blocked"] = 1
            flags = "".join(k for k, v in cleaned[0]["star"].items() if v) or "全缺"
            problems.append(f"{len(cleaned)} 道题的 STAR 完全相同（只有 {flags}），等于只判了第一题")
            hints.append(
                "逐题对着学生原话重判四项：S=有没有交代背景/约束；T=有没有说清要解决什么；"
                "A=有没有讲自己的动作；R=有没有可验证的结果。答得短的那题通常少 T 或 R。"
                "确实每题都只答了动作，就在对应 gap 里写「几题都只有动作」，再按同一组值提交"
            )
        return {
            "ok": False,
            "scores": scores,
            "error": "；".join(problems) + "。",
            "hint": "；".join(hints) + "。",
        }

    # 样本量以服务端记录为准，不信模型自己报的条数：
    # 让"题量封顶"依赖模型提交的数组长度，等于让它自己决定要不要封顶。
    rounds = len(sess.interview["turns"])
    if len(cleaned) > rounds:
        return {
            "ok": False,
            "error": f"per_question 有 {len(cleaned)} 条，本场实际只记录了 {rounds} 题；不得把没问过的题写进复盘",
        }
    sample_cap = {1: 4, 2: 6}.get(rounds)
    capped = []
    if sample_cap:
        for k in list(scores):
            if scores[k] > sample_cap:
                capped.append(f"{k} {scores[k]}→{sample_cap}")
                scores[k] = sample_cap

    total = rubric.weighted_total(scores, rubric.INTERVIEW_DIMS)

    gaps = []
    for i, g in enumerate(args.get("gaps") or [], start=1):
        if not isinstance(g, dict) or not str(g.get("desc") or "").strip():
            continue
        gaps.append(
            {
                "id": g.get("id") or f"G{i}",
                "desc": str(g["desc"]).strip(),
                "fact_id": g.get("fact_id") or None,
                "source": g.get("source") or "interview",
                "suggestion": str(g.get("suggestion") or "").strip(),
                "status": g.get("status") or "open",
            }
        )

    report = {
        "report_id": f"R{uuid.uuid4().hex[:8]}",
        "resume_version": f"V{sess.resume_version}",
        "target_role": sess.target_role,
        "scene": sess.interview.get("scene") or args.get("scene") or "",
        "rounds": rounds,
        "scores": scores,
        "total": total,
        "match_level": rubric.level_of(total),
        "per_question": cleaned,
        "gaps": gaps,
        "sample_size": rounds,
        "confidence": "低（只有 %d 题，仅供方向参考）" % rounds if rounds < 3 else "正常",
        "resume_advice": [str(x).strip() for x in (args.get("resume_advice") or []) if str(x).strip()][:3],
    }
    sess.report = report
    out = {"ok": True, "report_id": report["report_id"], "total": total, "match_level": report["match_level"],
           "sample_size": rounds, "confidence": report["confidence"],
           "star_missing": [c["qid"] for c in cleaned if c["star"] is None]}
    if capped:
        out["capped"] = capped
        out["note"] = "题量不足，单维按样本量封顶到 %d 分：%s；回答时要向学生说明分数上限来自题量，不是他答得差" % (sample_cap, "、".join(capped))
    return out


def tool_export_resume_docx(args: Dict[str, Any], sess: Session) -> Dict[str, Any]:
    data = args.get("resume") if isinstance(args.get("resume"), dict) else sess.resume
    if not data:
        return {"ok": False, "error": "没有可导出的简历内容"}
    try:
        blob = build_resume_docx(data)
    except Exception as exc:  # 生成失败必须显式报错，不静默降级
        return {"ok": False, "error": f"DOCX 生成失败：{exc}"}

    token = uuid.uuid4().hex
    _clean_docs()
    _docs[token] = (blob, "resume.docx", time.time() + DOC_TTL)
    return {"ok": True, "download_path": f"/api/agent/download/{token}", "bytes": len(blob), "expires_in": DOC_TTL}


def tool_get_context(_args: Dict[str, Any], sess: Session) -> Dict[str, Any]:
    ctx = sess.context()
    sheet = sess.fact_sheet or {}
    ctx["fact_items"] = sheet.get("items", [])
    # 逐题记录也一并回传：复盘要引用学生原话，只靠对话历史会记岔（早停轮不进历史）
    ctx["interview_turns"] = list(sess.interview.get("turns") or [])
    ctx["career_evidence_required"] = "每个 ≤6 分的维度至少一条证据"
    return {"ok": True, **ctx}


# ============ 注册表：JSON Schema 即工具契约 ============

RESUME_SCHEMA = {
    "type": "object",
    "description": "结构化简历",
    "properties": {
        "basic": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "target": {"type": "string"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "city": {"type": "string"},
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "school": {"type": "string"},
                    "major": {"type": "string"},
                    "degree": {"type": "string"},
                    "time": {"type": "string"},
                    "extra": {"type": "string"},
                },
            },
        },
        "internships": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "time": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "stack": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "skills": {"type": "array", "items": {"type": "string"}},
        "certs": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
}

TOOLS: Dict[str, Dict[str, Any]] = {
    "get_context": {
        "description": "读取服务端会话状态：阶段、简历版本、锁定岗位、五维分数、事实清单与面试轮次。状态摘要已随系统指令下发，只在摘要缺字段、或需要复核逐题记录（interview_turns）时调用；不要每轮都调。",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "run": tool_get_context,
    },
    "save_resume": {
        "description": "把学生简历存成五类字段结构并校验完整性。每次内容变化都要重新调用，会升版本号并作废旧分数与旧清单。",
        "parameters": {
            "type": "object",
            "properties": {
                "resume": RESUME_SCHEMA,
                "target_role": {"type": "string", "description": "目标岗位，可留空"},
            },
            "required": ["resume"],
        },
        "run": tool_save_resume,
    },
    "lock_jd": {
        "description": "锁定目标岗位与 JD，计算技能重合率并折算专业基础分。会话内只锁一次，后续不再变更。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_role": {"type": "string"},
                "jd_text": {"type": "string", "description": "岗位 JD 原文，可为空（回落岗位基线库）"},
            },
            "required": ["target_role"],
        },
        "run": tool_lock_jd,
    },
    "score_career": {
        "description": "提交职业能力五维分数（1-10 整数）与每个低分维度的原文证据。服务端校验证据完整性、按固定权重算总分与等级。五维必须逐维判：不要用一个整体印象分套到五维上（服务端会对「五维同分」退回一次）。简历本身缺某个模块（零实习、无项目）时，用 missing 上报，不要拿技能清单拼串当引文。",
        "parameters": {
            "type": "object",
            "properties": {
                "scores": {
                    "type": "object",
                    "properties": {
                        "foundation": {"type": "integer", "minimum": 1, "maximum": 10},
                        "practice": {"type": "integer", "minimum": 1, "maximum": 10},
                        "output": {"type": "integer", "minimum": 1, "maximum": 10},
                        "expression": {"type": "integer", "minimum": 1, "maximum": 10},
                        "collaboration": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["foundation", "practice", "output", "expression", "collaboration"],
                },
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dim": {"type": "string", "description": "foundation/practice/output/expression/collaboration"},
                            "quote": {"type": "string", "description": "简历原文片段，逐字引用；用 missing 上报时不必填"},
                            "problem": {"type": "string", "description": "扣在哪一档、什么问题"},
                            "fix": {"type": "string", "description": "修改方向，一句话"},
                            "missing": {"type": "boolean", "description": "该维度扣分是因为简历缺某个模块时置 true"},
                            "module": {"type": "string", "description": "缺的模块名，必须与状态里 resume_missing 的措辞对得上，例如「实习经历」"},
                        },
                        "required": ["dim", "problem", "fix"],
                    },
                },
            },
            "required": ["scores", "evidence"],
        },
        "run": tool_score_career,
    },
    "build_fact_sheet": {
        "description": "生成事实清单：服务端负责编号 E1…、按规则判证据强度（强/中/虚）与 top_gaps。只写可核实项，不写建议与形容词。",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fact": {"type": "string", "description": "一句话压缩「在哪/做了什么/用什么方法」，不含形容词"},
                            "result": {"type": "string", "description": "带数字或可验证事实；没有就写【待核实】，禁止推测补全"},
                            "role": {"type": "string", "enum": ["主导", "独立", "参与", "协助"]},
                            "follow_ups": {"type": "array", "items": {"type": "string"}},
                            "source_module": {"type": "string", "description": "internships/projects/skills"},
                        },
                        "required": ["fact", "result", "role"],
                    },
                },
                "top_gaps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "priority": {"type": "integer"},
                            "fact_id": {"type": "string"},
                            "desc": {"type": "string"},
                        },
                    },
                    "description": "留空则由服务端按证据强度自动排",
                },
            },
            "required": ["items"],
        },
        "run": tool_build_fact_sheet,
    },
    "validate_rewrite": {
        "description": "改写事实冻结校验：比对原句与改写句的数字、时间、角色词，新增即判违规。每次给出改写后必须调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "original": {"type": "string"},
                "rewritten": {"type": "string"},
            },
            "required": ["original", "rewritten"],
        },
        "run": tool_validate_rewrite,
    },
    "log_interview_turn": {
        "description": "记录一轮面试问答并做规则拦截：一题多问、同层连续两轮、轮次上限。出题前调用一次（answer 留空），收到回答后再调用一次。",
        "parameters": {
            "type": "object",
            "properties": {
                "fact_id": {"type": "string", "description": "锚定的事实编号，必须在清单内；优先挑还没问过的（见上下文 uncovered_facts），同一条最多连续问两次"},
                "layer": {"type": "string", "enum": ["事实", "方法", "量化", "归因", "反思"]},
                "question": {"type": "string"},
                "answer": {"type": "string", "description": "学生回答，出题时留空"},
                "scene": {"type": "string", "description": "只在第一题时传：专业面/行为面/压力面"},
                "role": {"type": "string", "description": "只在第一题时传：目标岗位"},
                "rounds_planned": {"type": "integer", "description": "只在第一题时传：计划轮数"},
            },
            "required": ["fact_id", "layer", "question"],
        },
        "run": tool_log_interview_turn,
    },
    "save_report": {
        "description": "保存面试复盘报告：服务端校验四栏（问了什么/想表达什么/实际答成什么/差在哪）、按固定权重算总分与结论。",
        "parameters": {
            "type": "object",
            "properties": {
                "per_question": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "qid": {"type": "string", "description": "题号 Q1/Q2…，与 log_interview_turn 一致"},
                            "fact_id": {"type": "string", "description": "这一题锚定的简历事实编号，如 E1"},
                            "question": {"type": "string", "description": "学生实际被问的那句原话"},
                            "intent": {
                                "type": "string",
                                "description": "考官想验证什么（一句，10-25 字），不要写成点评",
                            },
                            "expect": {
                                "type": "string",
                                "description": "满分答法应包含哪几个动作/数据，按要点写；不要复述 gap",
                            },
                            "actual": {"type": "string", "description": "学生实际回答的原话或近原话摘要"},
                            "gap": {
                                "type": "string",
                                "description": "他这句话比 expect 具体少了哪一步（动作或数据）；不得与 expect、intent 逐字相同",
                            },
                            "star": {
                                "type": "object",
                                "description": "逐题判四项：S 情境 / T 任务 / A 行动 / R 结果。每题必须单独判，不许整场复制同一组值（服务端会对「所有题完全相同」退回一次）",
                                "properties": {
                                    "S": {"type": "boolean", "description": "有没有交代背景或约束"},
                                    "T": {"type": "boolean", "description": "有没有说清要解决什么（答得短通常缺这项）"},
                                    "A": {"type": "boolean", "description": "有没有讲自己的具体动作"},
                                    "R": {"type": "boolean", "description": "有没有可验证的结果（数字或可核对事实）"},
                                },
                            },
                        },
                        "required": ["qid", "fact_id", "question", "intent", "expect", "actual", "gap"],
                    },
                },
                "scores": {
                    "type": "object",
                    "description": "按学生实际答出的内容逐维判，至少两维拉开 2 分；五维全同分会被退回一次（那是整体印象，不是判定）",
                    "properties": {
                        "tech_depth": {"type": "integer", "minimum": 1, "maximum": 10},
                        "project": {"type": "integer", "minimum": 1, "maximum": 10},
                        "logic": {"type": "integer", "minimum": 1, "maximum": 10},
                        "behavior": {"type": "integer", "minimum": 1, "maximum": 10},
                        "fit": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["tech_depth", "project", "logic", "behavior", "fit"],
                },
                "gaps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "desc": {"type": "string"},
                            "fact_id": {"type": "string"},
                            "source": {"type": "string"},
                            "suggestion": {"type": "string"},
                            "status": {"type": "string"},
                        },
                        "required": ["desc"],
                    },
                },
                "resume_advice": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["per_question", "scores"],
        },
        "run": tool_save_report,
    },
    "export_resume_docx": {
        "description": "把当前简历导出为 DOCX，返回下载路径。学生要求导出/下载时调用。",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "run": tool_export_resume_docx,
    },
}

# 每个模块只挂该模块用得到的工具——不把全部工具一次性塞给模型（docs/02 §3.3）
MODULE_TOOLS: Dict[str, List[str]] = {
    "diagnosis": ["get_context", "save_resume", "lock_jd", "score_career", "build_fact_sheet", "validate_rewrite", "export_resume_docx"],
    # 面试轮是只读的：不改简历、不出报告，改写建议留到诊断/复盘
    "interview": ["get_context", "log_interview_turn"],
    "review": ["get_context", "save_report", "export_resume_docx"],
}


def manifest(module: str) -> List[Dict[str, Any]]:
    names = MODULE_TOOLS.get(module, [])
    out = []
    for name in names:
        spec = TOOLS[name]
        out.append(
            {
                "type": "function",
                "function": {"name": name, "description": spec["description"], "parameters": spec["parameters"]},
            }
        )
    return out


def invoke(name: str, args: Dict[str, Any], sess: Session) -> Dict[str, Any]:
    spec = TOOLS.get(name)
    if not spec:
        return {"ok": False, "error": f"未知工具：{name}；可用工具：{'、'.join(MODULE_TOOLS.get('diagnosis', []))}"}

    # 环节护栏不靠"当前页面是哪个模块"（多标签页会误伤），
    # 而靠每个工具内部的状态门槛（S0–S5）：状态不到就拒，谁也绕不过去。
    try:
        result = spec["run"](args, sess)
    except Exception as exc:  # 工具异常必须回灌给模型，让它自己改参数重试
        result = {"ok": False, "error": f"工具执行异常：{type(exc).__name__}: {exc}"}
    sess.log_tool(name, bool(result.get("ok", True)), str(result.get("error") or "")[:80])
    return result
