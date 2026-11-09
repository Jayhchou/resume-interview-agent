"""知识库：只读加载与查询。

三条约束：
1. **只读**。启动时载入内存，不写回、不联网。数据来自 `kb/*.json`，
   由 `kb/build.py` 从本地 md 抽取生成。
2. **失败降级**。文件缺失或损坏只让对应能力消失，绝不允许阻断服务启动。
   每个查询函数在拿不到数据时返回 None/空，调用方回落原有逻辑。
3. **不猜**。岗位命中不了就返回 None，不要挑一个"最像的"顶上——
   给学生套错岗位的基线，比没有基线更糟。
"""
from __future__ import annotations

import io
import json
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb")

_KINDS = ("roles", "questions", "anchors", "writing")
_cache: Dict[str, Any] = {}
_loaded = False
_lock = threading.Lock()


def _read(name: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(KB_DIR, f"{name}.json")
    try:
        with io.open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _ensure() -> None:
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        for kind in _KINDS:
            _cache[kind] = _read(kind)
        _loaded = True


def reload() -> None:
    """测试或知识库更新后重新载入。"""
    global _loaded
    with _lock:
        _cache.clear()
        _loaded = False
    _ensure()


# ---------------- 岗位 ----------------

def roles() -> Dict[str, Any]:
    _ensure()
    return ((_cache.get("roles") or {}).get("roles") or {})


def match_role(role: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """岗位名 → (规范名, 节点)。三级匹配：精确 → 别名 → 互相包含。

    匹配不上返回 None。别名表来自 kb/build.py 的 ROLE_ALIASES。
    """
    key = (role or "").strip().lower()
    if len(key) < 2:
        return None
    table = roles()
    for name, node in table.items():
        if name.lower() == key:
            return name, node
    for name, node in table.items():
        for alias in node.get("aliases") or []:
            a = str(alias).lower()
            if not a:
                continue
            if a == key or a in key or key in a:
                return name, node
    for name, node in table.items():
        if name.lower() in key or key in name.lower():
            return name, node
    return None


def baseline(role: str) -> Optional[Dict[str, Any]]:
    """岗位基线：必备/加分技能、考察重点、典型项目、常见不足。"""
    hit = match_role(role)
    if not hit:
        return None
    name, node = hit
    return {"role": name, **node}


def required_skills(role: str) -> List[str]:
    """必备技能名（含别名），用于技能重合率计算。"""
    b = baseline(role)
    if not b:
        return []
    out: List[str] = []
    for item in b.get("must") or []:
        out.append(item.get("skill", ""))
        out.extend(item.get("aliases") or [])
    return [s for s in dict.fromkeys(out) if s]


def focus_of(role: str) -> List[str]:
    b = baseline(role)
    return list(b.get("focus") or []) if b else []


def gaps_of(role: str) -> List[str]:
    b = baseline(role)
    return list(b.get("gaps") or []) if b else []


# ---------------- 题库 ----------------

def question_bank(role: str) -> Dict[str, List[Dict[str, str]]]:
    _ensure()
    data = (_cache.get("questions") or {}).get("banks") or {}
    hit = match_role(role)
    if hit and hit[0] in data:
        return data[hit[0]]
    key = (role or "").strip()
    return data.get(key) or {}


def question_hints(role: str, layer: str, limit: int = 6) -> List[Dict[str, str]]:
    """当前岗位 + 当前追问层的候选题。拿来给模型挑一条改写，不是直接照抄。"""
    bank = question_bank(role)
    items = bank.get(layer) or bank.get(layer.rstrip("层")) or []
    return items[:limit]


def layers() -> List[str]:
    _ensure()
    return list((_cache.get("questions") or {}).get("layers") or [])


# ---------------- 评分锚点 ----------------

def anchor(dim_key: str) -> Optional[Dict[str, Any]]:
    _ensure()
    dims = (_cache.get("anchors") or {}).get("dims") or {}
    return dims.get(dim_key)


def scoring_hints() -> Dict[str, List[str]]:
    """五维判分提示，按维度分组（dim_key → [提示]）。

    分组而不是拉平：模型逐维判分时对照本维提示，比在 41 条并列里找更准。
    """
    _ensure()
    dims = (_cache.get("anchors") or {}).get("dims") or {}
    return {k: list(v.get("tips") or []) for k, v in dims.items() if v.get("tips")}


def band_text(dim_key: str, score: int) -> str:
    """取该分数所在档位的描述（向下取最近档）。用于给扣分证据补口径。"""
    node = anchor(dim_key)
    if not node:
        return ""
    bands = node.get("bands") or {}
    keys = sorted(int(k) for k in bands if str(k).isdigit())
    pick = None
    for k in keys:
        if score >= k:
            pick = k
    if pick is None:
        pick = keys[0] if keys else None
    if pick is None:
        return ""
    return "；".join(bands.get(str(pick)) or [])


# ---------------- 简历写法 ----------------

def writing() -> Dict[str, Any]:
    _ensure()
    return _cache.get("writing") or {}


def weak_verbs() -> Dict[str, str]:
    data = writing().get("verbs") or {}
    out: Dict[str, str] = {}
    for name, detail in data.get("weak") or []:
        if name:
            out[str(name).strip()] = str(detail or "").strip()
    return out


def antipatterns() -> List[Dict[str, str]]:
    return list(writing().get("antipatterns") or [])


def quant_kinds() -> Dict[str, str]:
    data = writing().get("quant") or {}
    out: Dict[str, str] = {}
    for name, detail in data.get("kinds") or []:
        if name:
            out[str(name).strip()] = str(detail or "").strip()
    return out


# ---------------- 诊断信息 ----------------

def stats() -> Dict[str, Any]:
    """供 /api/health 与联调脚本核对，确认知识库确实被加载。"""
    _ensure()
    dims = (_cache.get("anchors") or {}).get("dims") or {}
    banks = (_cache.get("questions") or {}).get("banks") or {}
    return {
        "loaded": _loaded,
        "dir": KB_DIR,
        "roles": len(roles()),
        "role_names": list(roles()),
        "question_banks": {k: sum(len(v) for v in b.values()) for k, b in banks.items()},
        "anchors": list(dims),
        "scoring_hints": sum(len(v) for v in scoring_hints().values()),
        "antipatterns": len(antipatterns()),
        "missing": [k for k in _KINDS if _cache.get(k) is None],
    }
