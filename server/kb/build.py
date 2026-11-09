"""把本地知识库 md 抽取成 kb/*.json。

知识库源目录结构：
    01-岗位能力要求/<岗位>.md
    02-面试题库/<岗位>-题目.md
    03-评分锚点/<维度>.md
    04-简历写法/{动词库,量化写法,反例对照}.md

用法：
    python server/kb/build.py                    # 用默认源目录
    python server/kb/build.py --src "D:/kb"      # 指定源目录

只做「结构切分 + 字段归档」，不改写原文措辞。切不动的地方打印告警，
不猜测、不补内容——宁可少字段，也不要造字段。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(os.path.expanduser("~"), "Desktop", "简历陪练知识库")

# 维度中文名 → rubric.CAREER_DIMS 的 key
DIM_KEY = {
    "专业基础": "foundation",
    "实践经历": "practice",
    "成果产出": "output",
    "沟通表达": "expression",
    "协作推进": "collaboration",
}

LAYER_KEY = {"事实层": "事实", "方法层": "方法", "量化层": "量化", "归因层": "归因", "反思层": "反思"}

# 岗位别名：学生简历里可能这么写，用于命中岗位基线
ROLE_ALIASES = {
    "后端开发": ["后端", "服务端", "服务端开发", "Java后端", "后端工程师", "java开发", "golang", "服务端工程师"],
    "前端开发": ["前端", "前端工程师", "web前端", "h5", "前端开发工程师"],
    "数据分析": ["数据分析师", "数据运营", "商业分析", "bi", "数据科学"],
    "产品经理": ["产品", "产品助理", "pm", "产品设计", "产品专员"],
    "测试": ["测试开发", "测试工程师", "qa", "软件测试", "自动化测试"],
    "算法工程师": ["算法", "算法开发", "机器学习", "机器学习工程师", "深度学习", "ai算法",
              "推荐算法", "cv算法", "nlp算法", "数据挖掘", "算法研究员"],
}

warnings: List[str] = []


def warn(msg: str) -> None:
    warnings.append(msg)


def read(p: str) -> str:
    return io.open(p, encoding="utf-8").read()


def sections(text: str) -> List[Tuple[str, List[str]]]:
    """按二级标题切分。一级标题与标题前的引言丢弃。"""
    out: List[Tuple[str, List[str]]] = []
    cur, buf = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur is not None:
                out.append((cur, buf))
            cur, buf = line[3:].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out.append((cur, buf))
    return out


def bullets(lines: List[str]) -> List[str]:
    """取 `- ` 开头的条目，缩进续行并入上一条。"""
    items, cur = [], None
    for line in lines:
        if line.startswith("- "):
            if cur:
                items.append(cur)
            cur = line[2:].strip()
        elif cur and line.strip() and not line.startswith("#"):
            cur += " " + line.strip()
    if cur:
        items.append(cur)
    return items


def plain(lines: List[str]) -> List[str]:
    """非列表小节：每个非空行算一条。顺手剥掉行首的 `- ` / `* `。"""
    out: List[str] = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("- ") or s.startswith("* "):
            s = s[2:].strip()
        out.append(s)
    return out


def clean(s: str) -> str:
    """去掉首尾的空白与分隔符。题库模板有时用 `｜` 分段，切完会留下残符。"""
    return (s or "").strip().strip("｜|").strip()


def split_kv(s: str) -> Tuple[str, str]:
    """`名字：说明` 或 `名字 → 说明` → (名字, 说明)；没有分隔符返回 (s, '')。

    动词库用箭头（`参与 → 具体做了什么`），其余文件用冒号，两种都认。
    """
    m = re.match(r"^(.+?)\s*(?:[：:]|→)\s*(.+)$", s)
    return (m.group(1).strip(), m.group(2).strip()) if m else (s.strip(), "")


SOURCE_RE = re.compile(r"[〔\[【]\s*来源\s*[：:]\s*(.+?)\s*[〕\]】]")

# 抽别名时排除的英文虚词/通用词：它们出现在说明里但不代表某项技能
ALIAS_STOP = {
    "at", "the", "one", "and", "or", "is", "an", "to", "of", "in", "on", "for",
    "dataset", "batch", "size", "epoch", "loss", "model", "data", "api", "sdk",
}

# 条目名里可以切出子概念的连接词（`机器学习与深度学习基础` → 机器学习 / 深度学习基础）
NAME_SPLIT = r"[与和、/／+＋]"


def auto_aliases(name: str, detail: str) -> List[str]:
    """从条目名与说明里派生可匹配关键词，供技能重合率使用。

    为什么需要：题库里的岗位必备项有两种写法——具体技术名（Java、PyTorch）和
    能力描述（方向经验、模型训练与效果评估）。学生简历的技能清单只会出现前者，
    所以「方向经验」永远匹配不上，等于每份算法岗简历都被白扣两项。
    这里只做机械切分，不新增语义：名字按连接词拆、说明里的英文技术名直接收。
    """
    out: List[str] = []
    for tok in re.split(NAME_SPLIT, name):
        tok = tok.strip()
        if len(tok) < 2 or tok == name:
            continue
        out.append(tok)
        for suf in ("基础", "经验", "能力"):
            if tok.endswith(suf) and len(tok) - len(suf) >= 2:
                out.append(tok[: -len(suf)])
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,15}", detail or ""):
        if tok.lower() in ALIAS_STOP:
            continue
        # 只收「像技术名」的 token：以字母数字收尾（C++/C# 例外），排除 B+ 这类残片
        if tok in ("C++", "C#") or re.match(r"^[A-Za-z][A-Za-z0-9+#.\-]*[A-Za-z0-9]$", tok):
            # 已是条目名一部分的片段（`A/B 测试` 里的 `B 测试`）不算新别名
            if tok not in name:
                out.append(tok)
    return [x for x in dict.fromkeys(out) if x and x != name]


def take_sources(s: str) -> Tuple[str, List[str]]:
    """剥掉 `〔来源：JD1；JD2〕`，返回 (干净文本, 来源名列表)。

    来源只做溯源用，不进提示词——所以从 detail 里摘出来单独存。
    """
    found: List[str] = []

    def repl(m: "re.Match[str]") -> str:
        for x in re.split(r"[；;、,，]", m.group(1)):
            x = x.strip()
            if x and x not in found:
                found.append(x)
        return ""

    return SOURCE_RE.sub(repl, s).strip(), found


def split_skill(s: str) -> Dict[str, Any]:
    """`消息队列（Kafka / RabbitMQ）：理解削峰…` → skill/aliases/detail/src"""
    name, detail = split_kv(s)
    detail, src = take_sources(detail)
    if not src:
        name, src = take_sources(name)
    aliases: List[str] = []
    inner = re.search(r"[（(]([^）)]+)[）)]", name)
    if inner:
        for a in re.split(r"[/、,，]", inner.group(1)):
            a = a.strip()
            if a:
                aliases.append(a)
        name = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
    for a in auto_aliases(name, detail):
        if a not in aliases and a != name:
            aliases.append(a)
    return {"skill": name, "detail": detail, "aliases": aliases, "src": src}


# ---------------- 01 岗位能力要求 ----------------

def build_roles(src: str) -> Dict[str, Any]:
    d = os.path.join(src, "01-岗位能力要求")
    roles: Dict[str, Any] = {}
    if not os.path.isdir(d):
        warn("缺目录 01-岗位能力要求")
        return {"version": 1, "source": "01-岗位能力要求", "roles": roles}

    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        p = os.path.join(d, fn)
        text = read(p)
        m = re.search(r"^#\s+(.+)$", text, re.M)
        title = m.group(1).strip() if m else fn[:-3]
        role = re.sub(r"[（(][^）)]*[）)]", "", title).strip()
        secs = sections(text)
        got = {k: v for k, v in secs}

        # 小节名容错：允许尾部带括号说明
        def pick(*names: str) -> List[str]:
            for n in names:
                for k, v in secs:
                    if k == n or k.startswith(n):
                        return v
            return []

        must_raw = bullets(pick("必备技能"))
        plus_raw = bullets(pick("加分技能"))
        focus = bullets(pick("考察重点")) or plain(pick("考察重点"))
        projects = bullets(pick("典型项目")) or plain(pick("典型项目"))
        gaps = bullets(pick("常见不足")) or plain(pick("常见不足"))

        if not must_raw:
            warn(f"{fn}: 没有解析到必备技能")
        must = []
        for b in must_raw:
            item = split_skill(b)
            if not item["detail"]:
                warn(f"{fn}/必备技能 无冒号说明：{b[:30]}")
            must.append(item)
        plus = [split_skill(b) for b in plus_raw]

        roles[role] = {
            "title": title,
            "aliases": ROLE_ALIASES.get(role, []),
            "must": must,
            "plus": plus,
            "focus": focus,
            "projects": projects,
            "gaps": gaps,
        }
    return {"version": 1, "source": "01-岗位能力要求", "roles": roles}


# ---------------- 02 面试题库 ----------------

def build_questions(src: str) -> Dict[str, Any]:
    d = os.path.join(src, "02-面试题库")
    banks: Dict[str, Any] = {}
    if not os.path.isdir(d):
        warn("缺目录 02-面试题库")
        return {"version": 1, "source": "02-面试题库", "layers": list(LAYER_KEY.values()), "banks": banks}

    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        p = os.path.join(d, fn)
        role = re.sub(r"-?题目$", "", fn[:-3]).strip()
        text = read(p)
        bank: Dict[str, List[Dict[str, str]]] = {}
        for head, body in sections(text):
            layer = LAYER_KEY.get(head, LAYER_KEY.get(head + "层"))
            if not layer:
                warn(f"{fn}: 未知层级「{head}」，已跳过")
                continue
            items = []
            for b in bullets(body):
                # 两种行格式并存：老文件用换行续写（被 bullets 拼成空格分隔），
                # 新文件用 `｜` 分段。统一成空格再切。
                m = re.match(
                    r"^问[：:]\s*(.+?)\s*考察[：:]\s*(.+?)(?:\s*好答案(?:要素)?[：:]\s*(.+))?$",
                    b.replace("｜", " ").replace("|", " "),
                )
                if not m:
                    warn(f"{fn}/{head}: 条目格式无法解析：{b[:40]}")
                    continue
                items.append({
                    "q": clean(m.group(1)),
                    "check": clean(m.group(2)),
                    "good": clean(m.group(3) or ""),
                })
            bank[layer] = items
        if not bank:
            warn(f"{fn}: 没有解析到任何题目")
        banks[role] = bank
    return {"version": 1, "source": "02-面试题库", "layers": list(LAYER_KEY.values()), "banks": banks}


# ---------------- 03 评分锚点 ----------------

def build_anchors(src: str) -> Dict[str, Any]:
    d = os.path.join(src, "03-评分锚点")
    dims: Dict[str, Any] = {}
    if not os.path.isdir(d):
        warn("缺目录 03-评分锚点")
        return {"version": 1, "source": "03-评分锚点", "dims": dims}

    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        p = os.path.join(d, fn)
        name = fn[:-3].strip()
        key = DIM_KEY.get(name)
        if not key:
            warn(f"{fn}: 维度名不在五维之内，已跳过")
            continue
        text = read(p)
        bands: Dict[str, List[str]] = {}
        tips: List[str] = []
        for head, body in sections(text):
            m = re.match(r"^(\d+)\s*分$", head)
            if m:
                bands[m.group(1)] = plain(body)
            elif "提示" in head:
                tips = plain(body)
            else:
                warn(f"{fn}: 未识别小节「{head}」")
        if not bands:
            warn(f"{fn}: 没有解析到分数档位")
        dims[key] = {"label": name, "bands": bands, "tips": tips}
    return {"version": 1, "source": "03-评分锚点", "dims": dims}


# ---------------- 04 简历写法 ----------------

def build_writing(src: str) -> Dict[str, Any]:
    d = os.path.join(src, "04-简历写法")
    out: Dict[str, Any] = {"version": 1, "source": "04-简历写法", "verbs": {}, "quant": {}, "antipatterns": []}
    if not os.path.isdir(d):
        warn("缺目录 04-简历写法")
        return out

    p = os.path.join(d, "动词库.md")
    if os.path.isfile(p):
        text = read(p)
        verbs: Dict[str, Any] = {}
        for head, body in sections(text):
            items = bullets(body) or plain(body)
            if "弱" in head:
                verbs["weak"] = [split_kv(i) for i in items]
            elif "强" in head:
                verbs["strong"] = [split_kv(i) for i in items]
            elif "场景" in head:
                verbs["scenes"] = items
            elif "提醒" in head:
                verbs["tips"] = items
            else:
                warn(f"动词库.md: 未识别小节「{head}」")
        out["verbs"] = verbs
    else:
        warn("缺 04-简历写法/动词库.md")

    p = os.path.join(d, "量化写法.md")
    if os.path.isfile(p):
        text = read(p)
        quant: Dict[str, Any] = {}
        for head, body in sections(text):
            items = bullets(body) or plain(body)
            if "四类" in head or "类型" in head:
                quant["kinds"] = [split_kv(i) for i in items]
            elif "句式" in head:
                quant["patterns"] = items
            elif "口径" in head:
                quant["metrics"] = items
            elif "没有数字" in head:
                quant["no_number"] = items
            elif "错误" in head:
                quant["mistakes"] = items
            else:
                warn(f"量化写法.md: 未识别小节「{head}」")
        out["quant"] = quant
    else:
        warn("缺 04-简历写法/量化写法.md")

    p = os.path.join(d, "反例对照.md")
    if os.path.isfile(p):
        text = read(p)
        items = []
        for head, body in sections(text):
            node = {"name": head, "original": "", "problem": "", "rewrite": ""}
            for b in bullets(body):
                k, v = split_kv(b)
                if "原句" in k:
                    node["original"] = v
                elif "问题" in k:
                    node["problem"] = v
                elif "改后" in k or "改写" in k:
                    node["rewrite"] = v
            if not node["original"]:
                warn(f"反例对照.md/{head}: 没有原句")
            items.append(node)
        out["antipatterns"] = items
    else:
        warn("缺 04-简历写法/反例对照.md")

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default=HERE)
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        print(f"源目录不存在：{args.src}", file=sys.stderr)
        return 2

    bundle = {
        "roles": build_roles(args.src),
        "questions": build_questions(args.src),
        "anchors": build_anchors(args.src),
        "writing": build_writing(args.src),
    }
    for name, data in bundle.items():
        path = os.path.join(args.out, f"{name}.json")
        io.open(path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(data, ensure_ascii=False, indent=1)
        )
        print(f"写出 {os.path.relpath(path, HERE)}")

    print("\n统计：")
    r = bundle["roles"]["roles"]
    print(f"  岗位 {len(r)} 个：" + "、".join(f"{k}(必备{len(v['must'])})" for k, v in r.items()))
    tot = sum(len(v["must"]) + len(v["plus"]) for v in r.values())
    with_src = sum(1 for v in r.values() for it in v["must"] + v["plus"] if it.get("src"))
    print(f"  能力项 {tot} 条，其中带来源 {with_src} 条" + ("（其余为早期手写，无来源标注）" if with_src < tot else ""))
    q = bundle["questions"]["banks"]
    print(f"  题库 {len(q)} 个：" + "、".join(f"{k}({sum(len(v) for v in b.values())}题)" for k, b in q.items()))
    a = bundle["anchors"]["dims"]
    print(f"  锚点 {len(a)} 维：" + "、".join(f"{k}({len(v['bands'])}档)" for k, v in a.items()))
    w = bundle["writing"]
    print(f"  写法：动词 {len(w['verbs'])} 节、量化 {len(w['quant'])} 节、反例 {len(w['antipatterns'])} 组")

    if warnings:
        print("\n告警：")
        for x in warnings:
            print("  !", x)
    else:
        print("\n无告警")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
