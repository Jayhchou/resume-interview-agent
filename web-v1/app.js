(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  // 存档键升到 v2：旧版（被浏览器缓存住的那份）只认 resume-coach-demo-modules，
  // 它在启动时会拿自己的空状态覆盖这个键。换成新键之后，旧版写多少都碰不到新数据，
  // 用户刷新一次不会再把简历洗掉。
  const STORAGE_KEY = "resume-coach-state-v2";
  const LEGACY_KEYS = ["resume-coach-demo-modules"];

  // 与 agent.js 同一套探测规则：线上同源走相对路径，本机静态服务器另起 8000
  function apiBase() {
    const configured = (window.AGENT_CONFIG && window.AGENT_CONFIG.apiBase) || "";
    if (configured) return String(configured).replace(/\/$/, "");
    if (location.protocol === "file:") return "http://127.0.0.1:8000";
    const host = location.hostname;
    const local = host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" || host.endsWith(".local");
    if (!local) return "";
    if (location.port === "8000") return "";
    return `${location.protocol}//${host}:8000`;
  }

  /* ============ 基础数据 ============ */

  const templates = [
    { id: "classic", name: "经典单栏", tag: "单栏", desc: "居中姓名 + 章节竖条，按时间倒序完整呈现经历" },
    { id: "modern", name: "现代双栏", tag: "双栏", desc: "渐变页首 + 主辅双栏，技能证书收纳进侧栏" },
    { id: "minimal", name: "极简黑白", tag: "单栏", desc: "黑白细框 + 宽字距标题，弱化装饰内容取胜" }
  ];

  const blankResume = {
    basic: { name: "", phone: "", email: "", city: "", target: "" },
    education: [],
    internships: [],
    projects: [],
    skills: [],
    certs: [],
    summary: ""
  };


  const modules = [
    { id: "basic", label: "基本信息", icon: "user" },
    { id: "education", label: "教育背景", icon: "school" },
    { id: "internships", label: "实习经历", icon: "case" },
    { id: "projects", label: "项目经历", icon: "code" },
    { id: "skills", label: "技能与证书", icon: "badge" },
    { id: "summary", label: "自我评价", icon: "star" }
  ];

  const factModuleMap = { E1: "internships", E2: "internships", E3: "projects", E4: "projects", E5: "projects", E6: "skills" };

  const careerMeta = [
    ["foundation", "专业基础", 20], ["practice", "实践经历", 30], ["output", "成果产出", 20],
    ["expression", "沟通表达", 15], ["collaboration", "协作推进", 15]
  ];
  const interviewMeta = [
    ["tech_depth", "技术深度", 30], ["project", "项目经验", 25], ["logic", "表达逻辑", 20],
    ["behavior", "行为素质", 15], ["fit", "岗位匹配", 10]
  ];

  const questionBank = [
    { fact: "E1", layer: "事实", text: "你在订单服务中具体负责哪一部分工作？", intent: "确认个人工作边界" },
    { fact: "E1", layer: "方法", text: "你提到使用 Redis 处理热点数据，为什么当时选择这个方案？", intent: "验证技术选型理解" },
    { fact: "E1", layer: "量化", text: "这个方案上线后，接口耗时或缓存命中率有什么变化？", intent: "确认结果是否可验证" },
    { fact: "E3", layer: "归因", text: "在 4 人项目中，下单接口的哪些关键决策由你完成？", intent: "区分个人与团队贡献" },
    { fact: "E3", layer: "反思", text: "如果重新设计这个下单流程，你会优先改哪一处？", intent: "验证复盘与迁移能力" },
    { fact: "E5", layer: "事实", text: "你在座位预约系统中独立完成了哪些接口？", intent: "核实独立项目范围" },
    { fact: "E5", layer: "方法", text: "你如何避免同一座位被重复预约？", intent: "验证并发控制思路" },
    { fact: "E2", layer: "归因", text: "你补充的日志最终帮助团队定位到了什么问题？", intent: "确认日志工作的价值" },
    { fact: "E4", layer: "反思", text: "6 次迭代中哪一次返工最多，你后来怎么调整协作方式？", intent: "验证协作改进能力" },
    { fact: "E5", layer: "反思", text: "如果预约量扩大十倍，你会先改造哪一部分？", intent: "验证系统扩展意识" }
  ];

  const sceneOrders = {
    专业面: [0, 1, 2, 5, 6, 9, 3, 8],
    行为面: [7, 8, 3, 4, 6, 2, 5, 9],
    压力面: [2, 9, 4, 1, 7, 3, 6, 8]
  };

  const scenes = [
    { id: "专业面", icon: "code", desc: "围绕技术选型与实现细节追问，验证你真的做过" },
    { id: "行为面", icon: "user", desc: "考察协作、决策与复盘方式，区分团队与个人贡献" },
    { id: "压力面", icon: "alert", desc: "质疑结果与归因，训练被追问时的表达稳定性" }
  ];

  const sampleAnswers = [
    "我主要负责商品与订单两个接口，把热点商品数据放到 Redis，数据库仍由订单服务统一写入。",
    "因为商品详情读多写少，直接查库耗时比较长。我们用 Redis 做缓存，并设置了过期时间。",
    "我补充过接口日志，平均耗时从 180ms 降到 65ms，但缓存命中率我当时没有统计。",
    "我负责事务边界和订单字段设计，同伴负责前端与库存接口，最终由我们一起联调。",
    "我会先补幂等处理。当时只考虑了正常下单，重复点击和超时重试考虑得不够。"
  ];

  /* ============ 状态 ============ */

  const defaultState = {
    nav: "resume",
    resumeView: "entry",
    templateId: "classic",
    // 导出/预览用的版式，与「简历从哪来」（source）解耦。
    // 之前两者共用一个字段：粘贴或上传会把 source 改成 paste/upload，
    // 于是选过的模板被静默覆盖，导出一律回落到经典单栏。
    exportTemplate: "classic",
    source: null,
    resume: null,
    selectedModule: "basic",
    interviewView: "setup",
    selectedScene: "专业面",
    interview: null
  };
  const clone = value => JSON.parse(JSON.stringify(value));
  let state = clone(defaultState);

  // 读存档：新键优先，其次旧键（首次升级时把旧数据迁过来）。
  // 多份候选里挑「简历最完整」的那份——旧版留下的空壳不能盖掉带简历的存档。
  function readSaved() {
    const picks = [];
    [STORAGE_KEY, ...LEGACY_KEYS].forEach(key => {
      try {
        const raw = JSON.parse(localStorage.getItem(key));
        if (raw && typeof raw === "object" && !Array.isArray(raw) && ("resume" in raw || "nav" in raw)) picks.push({ key, data: raw });
      } catch (_) { /* 损坏的存档直接跳过 */ }
    });
    if (!picks.length) return null;
    const weight = p => (p.data.resume ? JSON.stringify(p.data.resume).length : 0);
    return picks.sort((a, b) => weight(b) - weight(a))[0];
  }

  try {
    // 旧版判断的是 saved.basic，但 state 里根本没有这个键（简历在 saved.resume.basic），
    // 于是整段持久化一直是空转：刷新后简历、模板、当前页面全部回到初始态，
    // 复盘页也永远还原不出来。按 state 自己的字段判断。
    const saved = readSaved();
    if (saved) {
      state = { ...state, ...saved.data };
      // 从旧键迁过来的数据立刻写进新键：旧版再怎么覆盖旧键都伤不到这份
      if (saved.key !== STORAGE_KEY && saved.data.resume) localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    }
  } catch (_) { /* 忽略损坏的本地存储 */ }

  /* 时间段字段名收敛：编辑页写的是 time，但从外部存档/模型回来的简历
     可能写成 period / date / start+end。不收敛的话，编辑页那一栏是空的，
     导出的 DOCX 也会少掉时间段。 */
  function normalizeResume(resume) {
    if (!resume || typeof resume !== "object") return resume;
    const fix = row => {
      if (!row || typeof row !== "object" || row.time) return row;
      const alias = row.period || row.date || row.duration || row.range;
      row.time = alias || (row.start && row.end ? `${row.start} - ${row.end}` : row.start || row.end || "");
      return row;
    };
    ["education", "internships", "projects"].forEach(key => (resume[key] || []).forEach(fix));
    return resume;
  }
  if (state.resume) normalizeResume(state.resume);

  /* 版式字段迁移：旧存档没有 exportTemplate，版式藏在 source 的 `template:xxx` 里。
     只迁移一次，之后 source 记「简历从哪来」、exportTemplate 记「导出用哪套版式」，
     两者互不覆盖。 */
  {
    const ids = templates.map(t => t.id);
    if (!ids.includes(state.exportTemplate)) {
      const legacy = typeof state.source === "string" && state.source.startsWith("template:")
        ? state.source.split(":")[1] : null;
      state.exportTemplate = ids.includes(legacy) ? legacy : "classic";
    }
    state.templateId = state.exportTemplate;
  }

  function saveState() {
    try {
      // 手里没有简历时一律不写盘：一份空状态落下去，存档里已有的简历就没了
      // （旧版覆盖数据的现场就是这样——176 字符、"resume": null）。
      if (!state.resume) {
        const prev = JSON.parse(localStorage.getItem(STORAGE_KEY));
        if (prev && prev.resume) return;
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (_) { /* 本地存储不可用 */ }
  }

  /* ============ 面试历史（独立键：不受 saveState「无简历不写盘」影响） ============ */

  const HISTORY_KEY = "resume-coach-history-v1";
  const HISTORY_CAP = 50;

  function readHistory() {
    try {
      const list = JSON.parse(localStorage.getItem(HISTORY_KEY));
      return Array.isArray(list) ? list : [];
    } catch (_) { return []; }
  }

  function writeHistory(list) {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(-HISTORY_CAP))); }
    catch (_) { /* 本地存储不可用 */ }
  }

  /** 每场面试复盘生成时记录一条。重复防护：同一 state.interview 只记一次
      （agent 模式下刷新会走 restoreReview → renderAgentReview 重放，没这层会重复记）。 */
  function recordHistory(entry) {
    const list = readHistory();
    list.push({ ts: Date.now(), ...entry });
    writeHistory(list);
    if (state.nav === "profile") renderProfile();
  }

  /* ============ 工具 ============ */

  const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const escapeHTML = (value = "") => String(value).replace(/[&<>'"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[c]);
  // 卡片标题行只留一句能扫读的话：超出长度的截断，全文另有证据正文可看
  const clip = (text, max = 30) => {
    const s = String(text || "").replace(/\s+/g, " ").trim();
    return s.length > max ? s.slice(0, max - 1) + "…" : s;
  };
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));

  function showToast(message, type = "success") {
    const toast = document.createElement("div");
    toast.className = `toast ${type === "error" ? "error" : ""}`;
    toast.innerHTML = `${icon(type === "error" ? "alert" : "check")}<span>${escapeHTML(message)}</span>`;
    $("#toastRegion").appendChild(toast);
    setTimeout(() => toast.classList.add("leaving"), 2400);
    setTimeout(() => toast.remove(), 2800);
  }

  function setPath(object, path, value) {
    const keys = path.split(".");
    let cursor = object;
    for (let i = 0; i < keys.length - 1; i++) cursor = cursor[keys[i]];
    cursor[keys[keys.length - 1]] = value;
  }

  /* 多行要点的高度跟着内容走：先置 auto 再读 scrollHeight，
     否则只要高度没变过，scrollHeight 会沿用上一次的内联高度而算小。
     scrollHeight 不含边框，而全局是 border-box，所以要补回上下边框，
     否则永远差 2px、底部会露一条滚动条。 */
  function autoGrow(el) {
    if (!el || el.tagName !== "TEXTAREA") return;
    // 面板还 hidden 时量出来是 0，写死高度会把框压成 2px；等它显示后再由输入事件撑开
    if (el.offsetParent === null) return;
    el.style.height = "auto";
    const cs = getComputedStyle(el);
    const border = (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0);
    el.style.height = `${el.scrollHeight + border}px`;
  }

  function totalOf(scores, meta) {
    return Math.round(meta.reduce((sum, [key, , weight]) => sum + scores[key] * weight, 0) / 10);
  }

  /* 五维雷达图。半径从 72 提到 98：原来 320 宽的画布里五边形只有 144px，
     卡片给到 320 宽时还空着一半（报告里「svg 只画到约 150px」量的就是五边形本身）。
     标签同步换短名（专业 / 实践 / 产出…），4 字标签会把画面又顶回原来的尺寸；
     完整名称在右侧「维度明细」里，这里只要能对上轴就够了。 */
  const RADAR_SHORT = {
    专业基础: "专业", 实践经历: "实践", 成果产出: "产出", 沟通表达: "表达", 协作推进: "协作",
    技术深度: "深度", 项目经验: "项目", 表达逻辑: "逻辑", 行为素质: "行为", 岗位匹配: "匹配",
  };

  function radarSVG(scores, meta, color = "#625bf6") {
    const cx = 160, cy = 150, radius = 98;
    const point = (index, scale = 1) => {
      const angle = (-90 + index * 72) * Math.PI / 180;
      return [cx + Math.cos(angle) * radius * scale, cy + Math.sin(angle) * radius * scale];
    };
    const polygon = scale => meta.map((_, i) => point(i, scale).map(v => v.toFixed(1)).join(",")).join(" ");
    let html = "";
    [0.25, 0.5, 0.75, 1].forEach(scale => { html += `<polygon points="${polygon(scale)}" fill="${scale === 1 ? "#fafaff" : "none"}" stroke="#e2e5ee" stroke-width="1"/>`; });
    meta.forEach((_, i) => { const [x, y] = point(i); html += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#e5e7ef"/>`; });
    const dataPoints = meta.map(([key], i) => point(i, clamp(scores[key], 0, 10) / 10));
    html += `<polygon points="${dataPoints.map(p => p.map(v => v.toFixed(1)).join(",")).join(" ")}" fill="${color}25" stroke="${color}" stroke-width="2.2"/>`;
    dataPoints.forEach(([x, y]) => { html += `<circle cx="${x}" cy="${y}" r="3.3" fill="#fff" stroke="${color}" stroke-width="2"/>`; });
    meta.forEach(([key, label], i) => {
      const angle = (-90 + i * 72) * Math.PI / 180;
      const x = cx + Math.cos(angle) * 118, y = cy + Math.sin(angle) * 116 + 3;
      const anchor = Math.cos(angle) > .35 ? "start" : Math.cos(angle) < -.35 ? "end" : "middle";
      html += `<text x="${x}" y="${y}" text-anchor="${anchor}" fill="#727d92" font-size="10" font-family="Noto Sans SC, sans-serif">${RADAR_SHORT[label] || label} <tspan fill="${color}" font-weight="700">${scores[key]}</tspan></text>`;
    });
    // 画布按实际着墨范围裁：原来 320×250 里上下各留了十几像素空白，白占尺寸
    return `<svg viewBox="4 22 312 258">${html}</svg>`;
  }

  /* ============ 简历：摘要与完成度 ============ */

  const allBullets = r => [...(r.internships || []).flatMap(i => i.bullets || []), ...(r.projects || []).flatMap(p => p.bullets || [])];

  const moduleInfo = {
    basic: {
      summary: r => r.basic.name || r.basic.target ? `${r.basic.name || "未填姓名"} · ${r.basic.target || "未填求职意向"}` : "尚未填写基本信息",
      complete: r => [r.basic.name, r.basic.target, r.basic.phone, r.basic.email].filter(Boolean).length / 4
    },
    education: {
      summary: r => r.education.length ? `${r.education[0].school || "未填学校"} · ${r.education[0].major || "未填专业"}` : "尚未添加教育背景",
      complete: r => r.education.length ? clamp(r.education.filter(e => e.school && e.major).length / r.education.length, 0, 1) : 0
    },
    internships: {
      summary: r => r.internships.length ? `${r.internships.length} 段实习 · ${r.internships.reduce((n, i) => n + (i.bullets || []).length, 0)} 条要点` : "尚未添加实习经历",
      complete: r => r.internships.length ? clamp(r.internships.filter(i => i.company && (i.bullets || []).length).length / r.internships.length, 0, 1) : 0
    },
    projects: {
      summary: r => r.projects.length ? `${r.projects.length} 个项目 · ${r.projects.reduce((n, p) => n + (p.bullets || []).length, 0)} 条要点` : "尚未添加项目经历",
      complete: r => r.projects.length ? clamp(r.projects.filter(p => p.name && (p.bullets || []).length).length / r.projects.length, 0, 1) : 0
    },
    skills: {
      summary: r => (r.skills.length || r.certs.length) ? `${r.skills.length} 项技能 · ${r.certs.length} 本证书` : "尚未添加技能证书",
      complete: r => clamp((r.skills.length + r.certs.length) / 6, 0, 1)
    },
    summary: {
      summary: r => r.summary ? r.summary.slice(0, 16) + (r.summary.length > 16 ? "…" : "") : "尚未填写自我评价",
      complete: r => clamp(r.summary.length / 60, 0, 1)
    }
  };

  function overallProgress(r) {
    return Math.round(modules.reduce((sum, m) => sum + moduleInfo[m.id].complete(r), 0) / modules.length * 100);
  }

  /* ============ 五维评分 ============ */

  function computeScores(r) {
    const bullets = allBullets(r);
    const quantified = bullets.filter(b => /\d/.test(b)).length;
    const roleText = [...(r.internships || []).map(i => i.role || ""), ...(r.projects || []).map(p => p.role || "")].join(" ");
    const scores = {
      foundation: clamp(Math.round(3 + (r.skills.length ? 3 : 0) + Math.min(3, r.skills.length * .5) + (r.certs.length ? 1 : 0)), 1, 9),
      practice: clamp(Math.round(2 + r.internships.length * 3 + r.projects.length * 1.5), 1, 9),
      output: clamp(Math.round(2 + quantified * 2), 1, 9),
      expression: clamp(Math.round(r.summary.length >= 50 && /负责|完成|提升|实现|独立/.test(r.summary) ? 8 : r.summary.length >= 20 ? 6 : 3), 1, 9),
      collaboration: clamp(Math.round(/负责|协作|团队|联调|4 人/.test(roleText + r.summary) ? 7 : 4), 1, 9)
    };
    return scores;
  }

  function buildAdvice(r, scores) {
    const advice = [];
    const weak = allBullets(r).filter(b => !/\d/.test(b));
    if (!r.basic.name || !r.basic.target) advice.push({ title: "补全基本信息", detail: "姓名和求职意向还空着，这两个字段决定面试官怎么读你后面所有内容。" });
    if (scores.output <= 5 && weak.length) advice.push({ title: `${weak.length} 条要点没有结果数据`, detail: `例如“${weak[0].slice(0, 18)}…”——补上耗时、数量或覆盖率，成果产出分会明显上升。` });
    if (scores.practice <= 5) advice.push({ title: "实践经历偏薄", detail: "当前实习与项目数量不足，优先把最有把握讲清楚的一件事写完整。" });
    if (scores.expression <= 6) advice.push({ title: "自我评价太笼统", detail: "写满 50 字以上，并且至少出现一次“独立完成 / 负责”这样的个人动作词。" });
    if (scores.collaboration <= 5) advice.push({ title: "协作证据缺失", detail: "在经历里写清“几个人、你负责哪块、怎么联调”，比形容词更有说服力。" });
    if (!advice.length) advice.push({ title: "结构已经完整", detail: "各模块都有内容且结果可验证，建议直接进 AI 面试，验证口头表达。" });
    return advice.slice(0, 3);
  }

  /* ============ 导航与子视图切换 ============ */

  function switchNav(nav) {
    state.nav = nav;
    $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.nav === nav));
    $("#resumeModule").hidden = nav !== "resume";
    $("#interviewModule").hidden = nav !== "interview";
    $("#profileModule").hidden = nav !== "profile";
    if (nav === "resume") showResumeView(state.resumeView);
    else if (nav === "interview") showInterviewView(state.interviewView);
    else renderProfile();
    saveState();
  }

  function showResumeView(view) {
    if (!state.resume && view === "editor") view = "entry";
    if (!state.resume && view === "analysis") view = "entry";
    state.resumeView = view;
    $("#resumeEntry").hidden = view !== "entry";
    $("#resumeEditor").hidden = view !== "editor";
    $("#resumeAnalysis").hidden = view !== "analysis";
    if (view === "editor") renderEditor();
    if (view === "analysis") renderAnalysis();
    saveState();
  }

  /** 编辑页三块面板（目录 / 编辑 / 预览）必须一起重画：只重画其中一块会让左栏计数、
      编辑区标签、预览正文各自停在不同的版本上。 */
  function renderEditor() {
    renderCatalog();
    renderEditPanel();
    renderPaper();
  }

  function showInterviewView(view) {
    if (view === "chat" && !state.interview) view = "setup";
    if (view === "review" && !(state.interview && state.interview.done)) view = "setup";
    state.interviewView = view;
    $("#interviewSetup").hidden = view !== "setup";
    $("#interviewChat").hidden = view !== "chat";
    $("#interviewReview").hidden = view !== "review";
    if (view === "setup") renderSceneOptions();
    saveState();
  }

  /* ============ 入口：模板画廊 + 上传 ============ */

  const templateMocks = {
    classic: `<div class="mock mock-classic">
      <i class="m-name"></i><i class="m-line w30 center"></i>
      <i class="m-title"></i><i class="m-line w90"></i><i class="m-line w75"></i>
      <i class="m-title"></i><i class="m-line w85"></i><i class="m-line w60"></i>
      <i class="m-title"></i><i class="m-line w80"></i>
    </div>`,
    modern: `<div class="mock mock-modern">
      <i class="m-banner"></i>
      <div class="m-cols">
        <div class="m-col"><i class="m-title"></i><i class="m-line w85"></i><i class="m-line w70"></i><i class="m-title"></i><i class="m-line w80"></i></div>
        <div class="m-col side"><i class="m-fill"></i><i class="m-line"></i><i class="m-line w80"></i></div>
      </div>
    </div>`,
    minimal: `<div class="mock mock-minimal">
      <i class="m-name dark"></i><i class="m-line w32 center dark"></i>
      <i class="m-h"></i><i class="m-line w90"></i><i class="m-line w70"></i>
      <i class="m-h"></i><i class="m-line w80"></i>
    </div>`
  };

  function renderGallery() {
    $("#tplGallery").innerHTML = templates.map(t => `
      <article class="tpl-card">
        <div class="tpl-thumb">${templateMocks[t.id]}</div>
        <div class="tpl-info">
          <div class="tpl-name-row"><h2>${t.name}</h2><span class="tpl-tag">${t.tag}</span></div>
          <p>${t.desc}</p>
          <button class="btn primary" data-template="${t.id}">使用此模板</button>
        </div>
      </article>`).join("");
    renderTemplatePicker();
  }

  /* 编辑页工具栏的版式下拉：导出前随时可换，不碰简历内容。
     首屏文案承诺「最后再选也不迟」，这个入口是承诺的落点。 */
  function renderTemplatePicker() {
    const picker = $("#tplPicker");
    if (!picker) return;
    picker.innerHTML = templates
      .map(t => `<option value="${t.id}">${t.name}</option>`).join("");
    picker.value = paperTemplate();
  }

  // 原生 confirm() 会把整个标签页挂起：弹窗没关掉之前，脚本、截图、导航全都没有响应，
  // 自动化里看到的就是「点了没反应 / frame is not responding」。换成页面内的确认层，
  // 不阻塞任何线程（实测：留一个 confirm 未处理，Runtime.evaluate 直接超时）。
  function askConfirm(message, okText = "确定") {
    return new Promise(resolve => {
      const mask = document.createElement("div");
      mask.className = "confirm-mask";
      mask.innerHTML = `<div class="confirm-card" role="dialog" aria-modal="true">
        <p>${escapeHTML(message)}</p>
        <div class="confirm-actions">
          <button type="button" class="btn ghost sm" data-act="cancel">取消</button>
          <button type="button" class="btn primary sm" data-act="ok">${escapeHTML(okText)}</button>
        </div>
      </div>`;
      const close = ok => {
        document.removeEventListener("keydown", onKey);
        mask.remove();
        resolve(ok);
      };
      const onKey = e => {
        if (e.key === "Escape") close(false);
        else if (e.key === "Enter") close(true);
      };
      mask.addEventListener("click", e => {
        const act = e.target.closest("[data-act]");
        if (act) close(act.dataset.act === "ok");
        else if (e.target === mask) close(false);
      });
      document.addEventListener("keydown", onKey);
      document.body.appendChild(mask);
      const ok = mask.querySelector('[data-act="ok"]');
      if (ok) ok.focus();
    });
  }

  async function startFromTemplate(templateId) {
    // 版式只决定预览与导出的长相，跟简历内容无关：已有内容时只换版式，绝不清空（N18）。
    // 首屏文案早就写着「版式只在导出 DOCX 时用到，最后再选也不迟」，实现要跟文案一致。
    const tpl = templates.find(t => t.id === templateId) || templates[0];
    const filled = state.resume ? sectionsFilled(state.resume) : 0;
    if (!filled) {
      state.resume = clone(blankResume);
      state.selectedModule = "basic";
      state.source = `template:${tpl.id}`;
      invalidateAgentScores();
    }
    setExportTemplate(tpl.id);
    showResumeView("editor");
    showToast(filled ? `已切到「${tpl.name}」，简历内容保留` : `已进入「${tpl.name}」模板编辑器`);
  }

  /* ============ 简历文本 → 结构化（本地确定性解析） ============
     这一段只做机械切分：按常见小节标题分段，再按标点/关键词抽字段。
     不猜内容、不补事实——抽不出来的留空，交给用户在编辑页补。
     之前这里直接加载一份写死的示例简历，学生贴自己的简历会看到别人的内容。 */

  const SECTION_RULES = [
    ["education", /^(教育背景|教育经历|学历|教育与培训|教育信息|教育)/],
    ["internships", /^(实习经历|工作经历|实习经验|工作实习|实习|工作经验|实践经历)/],
    ["projects", /^(项目经历|项目经验|科研经历|项目实践|项目)/],
    ["skills", /^(专业技能|技能特长|技术栈|技术能力|技能证书|技能)/],
    ["certs", /^(证书|获奖|荣誉|奖项|资格证书|奖项荣誉)/],
    ["summary", /^(自我评价|个人评价|自我介绍|个人总结|个人简介|自我描述)/],
    ["basic", /^(基本信息|个人信息|联系方式|个人资料)/]
  ];

  const BULLET_RE = /^[-*•·–—○●▪]|^\d{1,2}[.、)）]/;
  const DATE_RE = /(19|20)\d{2}\s*[.\-/年]?\s*(\d{1,2})?\s*(月)?\s*[-–—~至到]\s*((19|20)\d{2})?\s*[.\-/年]?\s*(\d{1,2})?\s*(月)?/;
  const DEGREE_RE = /(博士|硕士|本科|大专|专科|研究生)/;

  function stripLead(s) {
    return (s || "").replace(BULLET_RE, "").trim();
  }

  function pickTime(s) {
    const m = (s || "").match(DATE_RE);
    return m ? m[0].replace(/\s+/g, "") : "";
  }

  /** 从原文里摘掉时间段（连同分隔符两侧的空格），返回剩下的部分。
      `2022.07 - 2022.12` 里的 `-` 一旦被当成列分隔符，公司名会错取到 `2022.07`，
      剩下的 `- 2022.12 某公司` 还会落成一条垃圾要点，一路传染到事实清单和首问。 */
  function cutTime(line) {
    const m = (line || "").match(DATE_RE);
    return m ? line.replace(m[0], " ") : (line || "");
  }

  /** 按分隔符切列后，把等于空或只由标点组成的碎片去掉。 */
  function cutPart(text, part) {
    return part ? text.split(part).join(" ") : text;
  }

  /* 技术名里的空格是真名的一部分。按空白切会把 `Spring Boot` 砍成 `Spring` + `Boot`，
     连带把技能计数、E6 事实和导出的 DOCX 一起带偏。先把已知多词技术名换成不含
     空白与分隔符的占位符，切完再还原。 */
  const SKILL_PHRASES = [
    "Spring Boot", "Spring Cloud", "Spring MVC", "Spring Security", "Spring Data", "Spring Batch",
    "React Native", "React Router", "Vue Router", "Vue CLI",
    "Node.js", "Vue.js", "Next.js", "Nuxt.js", "Express.js", "Three.js",
    "Git Flow", "GitLab CI", "GitHub Actions", "VS Code", "Visual Studio",
    "Machine Learning", "Deep Learning", "Reinforcement Learning",
    "REST API", "RESTful API", "MyBatis Plus", "Elastic Search"
  ];
  const SKILL_PH = "\u0001";

  function splitSkills(text) {
    let work = String(text || "");
    const kept = [];
    SKILL_PHRASES.forEach(name => {
      const pattern = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
      work = work.replace(new RegExp(pattern, "gi"), () => {
        kept.push(name);
        return `${SKILL_PH}${kept.length - 1}${SKILL_PH}`;
      });
    });
    const out = [];
    const restore = new RegExp(`${SKILL_PH}(\\d+)${SKILL_PH}`, "g");
    work.split(/[、,，;；/／|｜\s]+/)
      .map(s => s.replace(/[。.]$/, "").trim())
      .map(s => s.replace(restore, (_m, i) => kept[Number(i)] || ""))
      .filter(s => s.length >= 2 && s.length <= 24)
      .filter(s => !/^(熟悉|掌握|了解|熟练|精通|使用|负责|参与|具备|能够|以及|相关|良好|等)$/.test(s))
      .forEach(s => { if (!out.includes(s)) out.push(s); });
    return out;
  }

  function parseResumeText(text) {
    const out = clone(blankResume);
    out.basic = { name: "", phone: "", email: "", city: "", target: "" };
    out.education = []; out.internships = []; out.projects = []; out.skills = []; out.certs = []; out.summary = "";

    const raw = (text || "").replace(/\u00a0/g, " ").split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    if (!raw.length) return out;

    // 1) 切小节：短行且命中标题关键词 → 换段；其余归当前段
    const buckets = { head: [] };
    let cur = "head";
    raw.forEach(line => {
      const bare = line.replace(/[【】\[\]#*]/g, "").replace(/[：:]\s*$/, "").trim();
      const hit = bare.length <= 14 && SECTION_RULES.find(([, re]) => re.test(bare));
      if (hit) { cur = hit[0]; buckets[cur] = buckets[cur] || []; return; }
      (buckets[cur] = buckets[cur] || []).push(line);
    });

    const head = buckets.head || [];
    const allText = raw.join("\n");

    // 2) 基本信息：姓名 / 电话 / 邮箱 / 城市 / 求职意向
    const phone = allText.match(/1[3-9]\d{9}/);
    const email = allText.match(/[\w.+-]+@[\w-]+\.[\w.]+/);
    const cityLine = allText.match(/(?:现居|所在城市|城市|所在地)\s*[：:]?\s*([\u4e00-\u9fa5]{2,8})/);
    const targetLine = allText.match(/(?:求职意向|目标岗位|应聘职位|意向岗位|求职岗位)\s*[：:]\s*([^\n|，,；;]{2,20})/);
    const nameLine = head.find(l => /^[\u4e00-\u9fa5]{2,4}$/.test(l)) ||
      head.find(l => /^[A-Za-z][A-Za-z .]{1,24}$/.test(l) && !/^(java|python|go|c\+\+|sql)$/i.test(l)) ||
      (head[0] || "").split(/[\s|｜·,，]/)[0];

    // 姓名只接受「2-4 个汉字」或「拉丁字母」，且不能是小节标题词：
    // 否则第一行写「求职意向：前端开发」时，整行会被当成姓名显示在预览顶部。
    let nameCandidate = (nameLine || "").trim();
    if (/简历|求职|个人|信息|联系|应聘|意向|目标|教育|背景|经历|项目|技能|评价|总结/.test(nameCandidate)) nameCandidate = "";
    out.basic.name = (/^[\u4e00-\u9fa5]{2,4}$/.test(nameCandidate) || /^[A-Za-z][A-Za-z .]{1,24}$/.test(nameCandidate))
      ? nameCandidate : "";
    out.basic.phone = phone ? phone[0] : "";
    out.basic.email = email ? email[0] : "";
    out.basic.city = cityLine ? cityLine[1] : "";
    out.basic.target = targetLine ? targetLine[1].trim()
      : (head.concat(buckets.summary || []).find(l => /(工程师|开发|算法|产品经理|测试|运营|分析师|设计师)/.test(l) && l.length <= 20 && !/(大学|学院|学校)/.test(l)) || "")
        .replace(/^(求职意向|目标岗位)\s*[：:]\s*/, "").trim();

    // 3) 教育背景：每遇到「学校」类关键词起一条
    (buckets.education || []).forEach(line => {
      const school = line.match(/[\u4e00-\u9fa5A-Za-z]{2,20}(?:大学|学院|学校|研究院)/);
      const degree = line.match(DEGREE_RE);
      if (school || degree) {
        if (!out.education.length || out.education[out.education.length - 1].school) out.education.push({ school: "", major: "", degree: "", time: "", extra: "" });
        const row = out.education[out.education.length - 1];
        if (school) row.school = row.school || school[0];
        if (degree) row.degree = row.degree || degree[1];
        row.time = row.time || pickTime(line);
        const major = line.replace(school ? school[0] : "", "").match(/(计算机|软件|电子|自动化|数学|统计|信息|通信|机械|金融|经济|管理|设计|传媒|人工智能|数据)[\u4e00-\u9fa5]{0,10}/);
        if (major) row.major = row.major || major[0];
        const rest = cutTime(line)
          .replace(school ? school[0] : "", "")
          .replace(major ? major[0] : "", "")
          .replace(DEGREE_RE, "")
          .replace(/[|｜·,，]/g, " ")
          .replace(/\s+/g, " ").trim();
        if (rest && !row.extra && rest !== row.major) row.extra = rest;
      } else if (out.education.length) {
        const row = out.education[out.education.length - 1];
        row.extra = row.extra ? `${row.extra}；${line}` : line;
      }
    });
    out.education = out.education.filter(e => e.school || e.degree);

    // 4) 实习 / 项目：非项目符号行当标题，符号行当要点
    const buildBlocks = (lines, isProject) => {
      const rows = [];
      let row = null;
      lines.forEach(line => {
        const bullet = BULLET_RE.test(line);
        const looksHeader = !bullet && (DATE_RE.test(line) ||
          (isProject ? /(项目|系统|平台|工具|模型|算法|框架)/.test(line) : /(公司|集团|科技|有限|实习|工作)/.test(line)));
        if (looksHeader || !row) {
          row = isProject
            ? { name: "", role: "", stack: "", bullets: [] }
            : { company: "", role: "", time: "", bullets: [] };
          const time = pickTime(line);
          // 先摘掉时间段再切列：`2022.07 - 2022.12` 会被空白切成三列，
          // 公司名错取 `2022.07`、余下的 `- 2022.12 某公司` 还会变成一条垃圾要点。
          const work = cutTime(line);
          if (isProject) {
            const stack = work.match(/(?:技术栈|使用|基于|采用)\s*[：:]?\s*([^，。;；|｜]{2,30})/);
            const role = work.match(/([\u4e00-\u9fa5]{0,4}(?:项目负责人|负责人|主导|独立开发|主要开发|参与者|参与|成员))/);
            row.stack = stack ? stack[1].trim() : "";
            row.role = role ? role[1] : "";
            row.name = work
              .replace(stack ? stack[0] : "", "")
              .replace(role ? role[0] : "", "")
              .replace(/[|｜]/g, " ")
              .replace(/\s+/g, " ").trim().slice(0, 40);
          } else {
            const role = work.match(/([\u4e00-\u9fa5A-Za-z]{0,8}(?:实习生|实习|工程师|开发|助理|专员|研究员|分析师))/);
            row.role = role ? role[1] : "";
            row.time = time;
            const parts = work.split(/[|｜·,，\s]+/).filter(Boolean);
            row.company = parts.find(x => x !== row.role) || "";
            const rest = cutPart(cutPart(work, row.company), row.role)
              .replace(/[|｜·,，]/g, " ").replace(/\s+/g, " ").trim();
            if (rest) row.bullets.push(rest);
          }
          rows.push(row);
        } else {
          const text = stripLead(line);
          if (text) row.bullets.push(text);
        }
      });
      return rows.filter(r => (isProject ? r.name : r.company) || r.bullets.length);
    };

    out.internships = buildBlocks(buckets.internships || [], false);
    out.projects = buildBlocks(buckets.projects || [], true);

    // 5) 技能：按分隔符拆成词条（多词技术名先占位，见 splitSkills）
    const skillText = (buckets.skills || []).join(" ").replace(/^(专业技能|技能特长|技术栈|技能)\s*[：:]\s*/, "");
    out.skills = splitSkills(skillText);

    // 6) 证书 / 自我评价
    out.certs = (buckets.certs || []).map(stripLead).filter(Boolean);
    out.summary = (buckets.summary || []).join(" ").replace(/\s+/g, " ").slice(0, 200);

    return out;
  }

  function sectionsFilled(r) {
    return [r.basic.name, r.basic.target, r.education.length, r.internships.length,
      r.projects.length, r.skills.length, r.summary].filter(Boolean).length;
  }

  function applyParsedResume(text, label, kind = "paste") {
    const parsed = parseResumeText(text);
    const filled = sectionsFilled(parsed);
    if (!filled) {
      showToast("没解析出内容：请确认文件里是可选中的文字（扫描件需先 OCR），或直接粘贴正文", "error");
      return false;
    }
    state.source = kind;
    state.resume = parsed;
    state.selectedModule = "basic";
    invalidateAgentScores();
    showResumeView("editor");
    // 解析是异步进来的（FileReader / 服务端提取 → setTimeout）。首屏三块面板再补画一帧，
    // 保证左栏计数、编辑面板、预览读的是同一份结构化结果，不会出现「0 项技能 + 6 个标签」。
    requestAnimationFrame(() => { if (state.resume === parsed && state.resumeView === "editor") renderEditor(); });
    if (filled < 3) {
      showToast(`只解析出 ${filled} 项（${parsed.basic.name || "无姓名"}）。简历是整段文字时请按「教育背景 / 实习经历 / 项目经历 / 专业技能」分行加小标题，否则抽不出内容`, "error");
      return true;
    }
    showToast(`${label}已解析：姓名${parsed.basic.name || "待补"}、技能 ${parsed.skills.length} 项、项目 ${parsed.projects.length} 段，请在左侧逐项核对`);
    return true;
  }

  function parseUpload(fileName, text, kind = "paste") {
    const zone = $("#dropzone");
    zone.classList.add("parsing");
    $("strong", zone).textContent = "正在解析简历结构…";
    setTimeout(() => {
      zone.classList.remove("parsing");
      $("strong", zone).textContent = "点击选择文件，或拖拽到这里";
      applyParsedResume(text || "", fileName ? `「${fileName}」` : "粘贴的文本", kind);
    }, 320);
  }

  /** PDF / Word：浏览器里抽不出可靠纯文本，交给服务端（pypdf / python-docx）提取后再走同一套解析。 */
  async function uploadResumeFile(file) {
    const zone = $("#dropzone");
    const strong = $("strong", zone);
    const idle = "点击选择文件，或拖拽到这里";
    zone.classList.add("parsing");
    strong.textContent = `正在提取「${file.name}」的文字…`;

    let content = "";
    let failure = "";
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(apiBase() + "/api/resume/upload", { method: "POST", body: form });
      const raw = await res.text();
      let data = null;
      try { data = raw ? JSON.parse(raw) : null; } catch (_) { data = { detail: raw }; }
      if (!res.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${res.status}`);
      content = String((data && data.text) || "");
      if (!content.trim()) throw new Error("文件里没有可提取的文字（可能是扫描件）");
    } catch (err) {
      failure = err && err.message ? err.message : String(err);
    }

    zone.classList.remove("parsing");
    strong.textContent = idle;
    if (failure) {
      showToast(`「${file.name}」解析失败：${failure}｜可以把文字复制出来粘贴到下方`, "error");
      return;
    }
    parseUpload(file.name, content, "upload");
  }

  function readResumeFile(file) {
    const name = (file.name || "").toLowerCase();
    if (/\.(pdf|docx)$/.test(name)) {
      uploadResumeFile(file);
      return;
    }
    const isText = /\.(txt|md|markdown)$/.test(name) || (file.type || "").startsWith("text/");
    if (!isText) {
      showToast("支持 PDF / Word(.docx) / .txt / .md；.doc 老格式请另存为 .docx，或直接粘贴正文", "error");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => parseUpload(file.name, String(reader.result || ""), "upload");
    reader.onerror = () => showToast("读取文件失败，请改用粘贴", "error");
    reader.readAsText(file, "utf-8");
  }

  /* ============ 编辑页：左栏模块目录 ============ */

  function renderCatalog() {
    const r = state.resume;
    const progress = overallProgress(r);
    $("#moduleCatalog").innerHTML = `
      <div class="outline-head">
        <strong>简历模块</strong>
        <div class="progress-track"><i style="width:${progress}%"></i></div>
        <span>整体完成度 ${progress}%</span>
      </div>
      ${modules.map(m => {
        const ratio = moduleInfo[m.id].complete(r);
        const dot = ratio >= .99 ? "ok" : ratio > 0 ? "warn" : "empty";
        return `<button class="outline-item ${state.selectedModule === m.id ? "active" : ""}" data-module="${m.id}" id="cat-${m.id}">
          <span class="oi-icon">${icon(m.icon)}</span>
          <span class="oi-main"><strong>${m.label}</strong><span>${escapeHTML(moduleInfo[m.id].summary(r))}</span></span>
          <span class="oi-dot ${dot}" title="${dot === "ok" ? "已完整" : dot === "warn" ? "部分完成" : "未开始"}"></span>
        </button>`;
      }).join("")}`;
  }

  /* ============ 编辑页：右栏整体预览（按模板渲染） ============ */

  function paperTemplate() {
    const ids = templates.map(t => t.id);
    return ids.includes(state.exportTemplate) ? state.exportTemplate : "classic";
  }

  function templateName(id = paperTemplate()) {
    return (templates.find(t => t.id === id) || templates[0]).name;
  }

  /* 换版式统一入口：工具栏下拉、首屏模板卡、导出前预览都走这里，
     保证「选了哪套」只有一个真相（state.exportTemplate），不再依赖 source。 */
  function setExportTemplate(id) {
    const ids = templates.map(t => t.id);
    state.exportTemplate = ids.includes(id) ? id : "classic";
    state.templateId = state.exportTemplate;
    const picker = $("#tplPicker");
    if (picker) picker.value = state.exportTemplate;
    renderPaper();
    saveState();
  }

  function renderPaper() {
    const r = state.resume;
    const progress = overallProgress(r);
    $("#progressText").textContent = `整体完成度 ${progress}%`;
    const badge = $("#sourceBadge");
    const tname = templateName();
    // 徽章同时交代「内容从哪来」和「现在用哪套版式」：模板被 source 覆盖过，
    // 光写「粘贴解析」看不出导出会是什么样子。
    if (state.source === "upload") { badge.textContent = `上传解析 · ${tname}`; badge.className = "badge upload"; }
    else if (state.source === "paste") { badge.textContent = `粘贴解析 · ${tname}`; badge.className = "badge upload"; }
    else { badge.textContent = `模板 · ${tname}`; badge.className = "badge"; }

    const tpl = paperTemplate();
    const text = (value, placeholder = "未填写") => value ? escapeHTML(value) : `<span class="pp-empty">${placeholder}</span>`;
    const sec = (id, inner) => `<section class="pp-sec pp-${id} ${state.selectedModule === id ? "active" : ""}" data-module="${id}" id="sec-${id}">${inner}</section>`;
    const bullets = list => list?.length
      ? `<ul class="pp-bullets">${list.map(b => `<li class="${/\d/.test(b) ? "" : "unverified"}" title="${/\d/.test(b) ? "" : "待核实：没有可验证的结果数据"}">${escapeHTML(b)}</li>`).join("")}</ul>`
      : '<p class="pp-empty">尚未添加要点</p>';

    const basic = sec("basic", `
      <p class="pp-name">${text(r.basic.name, "姓名")}</p>
      <p class="pp-target">${text(r.basic.target, "求职意向未填写")}</p>
      <p class="pp-contact">${[r.basic.city, r.basic.phone, r.basic.email].filter(Boolean).map(escapeHTML).join(" · ") || '<span class="pp-empty">联系方式未填写</span>'}</p>`);

    const education = sec("education", `
      <h3 class="pp-title">教育背景</h3>
      ${r.education.length ? r.education.map(e => `
        <div class="pp-entry">
          <div class="pp-entry-head"><strong>${text(e.school, "学校")}</strong><span>${escapeHTML(e.time || "")}</span></div>
          <p>${[e.major, e.degree, e.extra].filter(Boolean).map(escapeHTML).join(" · ") || '<span class="pp-empty">专业等信息未填写</span>'}</p>
        </div>`).join("") : '<p class="pp-empty">尚未添加</p>'}`);

    const internships = sec("internships", `
      <h3 class="pp-title">实习经历</h3>
      ${r.internships.length ? r.internships.map(i => `
        <div class="pp-entry">
          <div class="pp-entry-head"><strong>${text(i.company, "公司")}</strong><span>${escapeHTML(i.time || "")}</span></div>
          <p class="pp-role">${text(i.role, "职位未填写")}</p>
          ${bullets(i.bullets)}
        </div>`).join("") : '<p class="pp-empty">尚未添加</p>'}`);

    const projects = sec("projects", `
      <h3 class="pp-title">项目经历</h3>
      ${r.projects.length ? r.projects.map(p => `
        <div class="pp-entry">
          <div class="pp-entry-head"><strong>${text(p.name, "项目名")}</strong><span>${escapeHTML(p.stack || "")}</span></div>
          <p class="pp-role">${text(p.role, "角色未填写")}</p>
          ${bullets(p.bullets)}
        </div>`).join("") : '<p class="pp-empty">尚未添加</p>'}`);

    const skills = sec("skills", `
      <h3 class="pp-title">技能证书</h3>
      ${(r.skills.length || r.certs.length)
        ? `<div class="pp-tags">${r.skills.map(s => `<span class="pp-tag">${escapeHTML(s)}</span>`).join("")}${r.certs.map(c => `<span class="pp-tag cert">${escapeHTML(c)}</span>`).join("")}</div>`
        : '<p class="pp-empty">尚未添加</p>'}`);

    const summary = sec("summary", `
      <h3 class="pp-title">自我评价</h3>
      <p class="pp-summary">${text(r.summary, "尚未填写自我评价")}</p>`);

    let paperBody;
    if (tpl === "modern") {
      paperBody = `
        ${basic}
        <div class="pp-cols">
          <div class="pp-main">${education}${internships}${projects}${summary}</div>
          <div class="pp-aside">${skills}</div>
        </div>`;
    } else {
      paperBody = `${basic}${education}${internships}${projects}${skills}${summary}`;
    }

    $("#previewScroll").innerHTML = `<div class="paper ${tpl}">${paperBody}</div>`;
  }

  /* ============ 编辑页：右侧表单 ============ */

  // 「没有可验证的结果数据」这条提示原来只在渲染时判一次，用户补上数字后
  // 提示还挂着，只有切模块重渲染才消失。改成挂在容器 class 上，输入时实时切换。
  // 要点天然是「动作 + 方法 + 结果」的整句，单行 input 在 330px 的列里只看得到
  // 前面十几个字（scrollWidth 288 > clientWidth 188），后半句被横向藏起来。
  // 换成 textarea，高度随内容自增，一行看不完的句子能整条看到。
  function bulletField(path, value) {
    return `<div class="bullet-block${/\d/.test(value) ? "" : " no-result"}" data-bullet="${path}">
      <div class="bullet-row"><span class="bullet-mark">•</span>
        <textarea rows="2" data-path="${path}" data-autogrow placeholder="动作 + 结果，例如：完成 xx 接口，覆盖 12 个场景">${escapeHTML(value)}</textarea>
        <button class="icon-btn sm remove-bullet" data-action="remove-bullet" data-args="${path}" title="删除这条"><svg aria-hidden="true"><use href="#i-trash"/></svg></button>
      </div>
      <p class="bullet-flag">${icon("alert")}这条没有可验证的结果数据（数字 / 覆盖率 / 耗时）</p>
    </div>`;
  }

  function renderEditPanel() {
    const r = state.resume;
    const id = state.selectedModule;
    const meta = modules.find(m => m.id === id);
    let body = "";

    if (id === "basic") {
      body = `<div class="field-grid">
        <label class="field"><span>姓名</span><input type="text" data-path="basic.name" value="${escapeHTML(r.basic.name)}"></label>
        <label class="field"><span>求职意向</span><input type="text" data-path="basic.target" value="${escapeHTML(r.basic.target)}"></label>
        <label class="field"><span>电话</span><input type="text" data-path="basic.phone" value="${escapeHTML(r.basic.phone)}" placeholder="138-0000-0000"></label>
        <label class="field"><span>邮箱</span><input type="text" data-path="basic.email" value="${escapeHTML(r.basic.email)}" placeholder="name@example.com"></label>
        <label class="field wide"><span>城市</span><input type="text" data-path="basic.city" value="${escapeHTML(r.basic.city)}" placeholder="意向城市"></label>
      </div>`;
    } else if (id === "education") {
      body = r.education.map((e, i) => `
        <div class="entry-block">
          <button class="remove-entry" data-action="remove-education" data-args="${i}" title="删除这段">${icon("trash")}</button>
          <div class="field-grid">
            <label class="field"><span>学校</span><input type="text" data-path="education.${i}.school" value="${escapeHTML(e.school)}"></label>
            <label class="field"><span>专业</span><input type="text" data-path="education.${i}.major" value="${escapeHTML(e.major)}"></label>
            <label class="field"><span>学历</span>
              <select data-path="education.${i}.degree">${["本科", "硕士", "博士", "专科"].map(d => `<option ${e.degree === d ? "selected" : ""}>${d}</option>`).join("")}</select>
            </label>
            <label class="field"><span>起止时间</span><input type="text" data-path="education.${i}.time" value="${escapeHTML(e.time)}" placeholder="2023.09 – 2027.06"></label>
            <label class="field wide"><span>GPA / 排名 / 亮点</span><input type="text" data-path="education.${i}.extra" value="${escapeHTML(e.extra)}" placeholder="GPA 3.6 / 4.0 · 专业前 20%"></label>
          </div>
        </div>`).join("") + `<button class="add-entry" data-action="add-education">${icon("plus")}添加一段教育经历</button>`;
    } else if (id === "internships") {
      body = r.internships.map((it, i) => `
        <div class="entry-block">
          <button class="remove-entry" data-action="remove-internship" data-args="${i}" title="删除这段实习">${icon("trash")}</button>
          <div class="field-grid">
            <label class="field"><span>公司 / 组织</span><input type="text" data-path="internships.${i}.company" value="${escapeHTML(it.company)}"></label>
            <label class="field"><span>职位</span><input type="text" data-path="internships.${i}.role" value="${escapeHTML(it.role)}"></label>
            <label class="field wide"><span>起止时间</span><input type="text" data-path="internships.${i}.time" value="${escapeHTML(it.time)}" placeholder="2025.06 – 2025.09"></label>
          </div>
          <div style="margin-top:12px">${(it.bullets || []).map((b, j) => bulletField(`internships.${i}.bullets.${j}`, b)).join("")}
            <button class="add-entry" data-action="add-bullet" data-args="internships.${i}.bullets">${icon("plus")}添加一条要点</button>
          </div>
        </div>`).join("") + `<button class="add-entry" data-action="add-internship">${icon("plus")}添加一段实习经历</button>`;
    } else if (id === "projects") {
      body = r.projects.map((p, i) => `
        <div class="entry-block">
          <button class="remove-entry" data-action="remove-project" data-args="${i}" title="删除这个项目">${icon("trash")}</button>
          <div class="field-grid">
            <label class="field"><span>项目名称</span><input type="text" data-path="projects.${i}.name" value="${escapeHTML(p.name)}"></label>
            <label class="field"><span>你的角色</span><input type="text" data-path="projects.${i}.role" value="${escapeHTML(p.role)}" placeholder="后端负责人 / 独立开发"></label>
            <label class="field wide"><span>技术栈</span><input type="text" data-path="projects.${i}.stack" value="${escapeHTML(p.stack || "")}" placeholder="Spring Boot · MySQL"></label>
          </div>
          <div style="margin-top:12px">${(p.bullets || []).map((b, j) => bulletField(`projects.${i}.bullets.${j}`, b)).join("")}
            <button class="add-entry" data-action="add-bullet" data-args="projects.${i}.bullets">${icon("plus")}添加一条要点</button>
          </div>
        </div>`).join("") + `<button class="add-entry" data-action="add-project">${icon("plus")}添加一个项目</button>`;
    } else if (id === "skills") {
      body = `
        <div class="skill-chips">${r.skills.map((s, i) => `<span class="skill-chip">${escapeHTML(s)}<button data-action="remove-skill" data-args="${i}" title="移除">${icon("close")}</button></span>`).join("") || '<span style="color:var(--faint);font-size:12.5px">还没有技能标签</span>'}</div>
        <div class="skill-add"><input type="text" id="newSkill" placeholder="输入技能后回车，例如 Redis"><button class="btn ghost sm" data-action="add-skill">${icon("plus")}添加技能</button></div>
        <h2 style="margin:22px 0 10px;font-size:14px">证书</h2>
        <div class="skill-chips">${r.certs.map((c, i) => `<span class="skill-chip">${escapeHTML(c)}<button data-action="remove-cert" data-args="${i}" title="移除">${icon("close")}</button></span>`).join("") || '<span style="color:var(--faint);font-size:12.5px">还没有证书</span>'}</div>
        <div class="skill-add"><input type="text" id="newCert" placeholder="例如 CET-4 · 568 分"><button class="btn ghost sm" data-action="add-cert">${icon("plus")}添加证书</button></div>`;
    } else if (id === "summary") {
      body = `
        <label class="field wide"><span>自我评价（建议 50–120 字）</span>
          <textarea rows="6" data-path="summary" placeholder="一两句定位 + 最有把握的一件事 + 正在补什么">${escapeHTML(r.summary)}</textarea>
        </label>
        <p class="setup-tip" style="margin-top:12px">${icon("spark")}好的写法：先说方向和定位，再说一件具体事实，最后说正在补的短板。避免堆形容词。</p>`;
    }

    const hints = {
      basic: "这部分决定面试官的第一眼印象，缺字段会在大纲上显示黄点。",
      education: "有排名或 GPA 就写上，没有就留空，不要编。",
      internships: "每条要点 = 动作 + 结果。没有数字的要点会被标为待核实。",
      projects: "角色写清楚“几个人、你负责哪块”，面试官最在意边界。",
      skills: "只写敢被追问的技能，写上去的每一项都可能变成面试题。",
      summary: "这一段会进入五维分析里的「沟通表达」维度。"
    };
    $("#editPanel").innerHTML = `
      <div class="edit-head">
        <h2>${icon(meta.icon)}${meta.label}</h2>
      </div>
      <p>${hints[id]}</p>
      ${body}`;
    // 渲染完量一次：要点 textarea 按真实内容撑开，否则刚进模块时只显示两行
    $$("#editPanel textarea[data-autogrow]").forEach(autoGrow);
  }

  function handleEditActions(event) {
    const target = event.target;
    const action = target.closest("[data-action]")?.dataset.action;
    if (!action) return;
    const args = target.closest("[data-action]")?.dataset.args;
    const r = state.resume;
    if (action === "add-education") r.education.push({ school: "", major: "", degree: "本科", time: "", extra: "" });
    else if (action === "remove-education") r.education.splice(Number(args), 1);
    else if (action === "add-internship") r.internships.push({ company: "", role: "", time: "", bullets: [""] });
    else if (action === "remove-internship") r.internships.splice(Number(args), 1);
    else if (action === "add-project") r.projects.push({ name: "", role: "", stack: "", bullets: [""] });
    else if (action === "remove-project") r.projects.splice(Number(args), 1);
    else if (action === "add-bullet") {
      const keys = args.split(".");
      let cursor = r;
      keys.forEach(k => { cursor = cursor[isNaN(k) ? k : Number(k)]; });
      cursor.push("");
    }
    else if (action === "remove-bullet") {
      const keys = args.split(".");
      const last = Number(keys.pop());
      let cursor = r;
      keys.forEach(k => { cursor = cursor[isNaN(k) ? k : Number(k)]; });
      cursor.splice(last, 1);
    }
    else if (action === "add-skill" || action === "add-cert") {
      const input = $(action === "add-skill" ? "#newSkill" : "#newCert");
      const value = input.value.trim();
      if (!value) { showToast("先输入内容再添加", "error"); return; }
      (action === "add-skill" ? r.skills : r.certs).push(value);
    }
    else if (action === "remove-skill") r.skills.splice(Number(args), 1);
    else if (action === "remove-cert") r.certs.splice(Number(args), 1);
    else return;
    invalidateAgentScores();
    saveState();
    renderCatalog();
    renderPaper();
    renderEditPanel();
  }

  /* ============ 五维分析页 ============ */

  function renderAnalysis() {
    const r = state.resume;
    // 有智能体但分数还没回来（且没失败）：先不显示本地估算，避免"公式分→模型分"闪变
    const pending = agentReady() && !agentScores && !agentDiagFailed;
    const scores = agentScores || (pending ? null : computeScores(r));
    const total = agentTotal != null ? agentTotal : (scores ? totalOf(scores, careerMeta) : null);

    const numEl = $("#analysisTotal");
    const pendEl = $("#analysisPending");
    if (numEl) {
      if (total == null) numEl.hidden = true;
      else { numEl.hidden = false; numEl.textContent = total; }
    }
    if (pendEl) pendEl.hidden = total != null;

    $("#analysisRadar").innerHTML = scores
      ? radarSVG(scores, careerMeta)
      : `<div class="radar-skeleton"><span>正在解析简历结构…</span></div>`;
    $("#analysisDims").innerHTML = careerMeta.map(([key, label, weight]) => {
      const v = scores ? scores[key] : null;
      return `
      <div class="dimension-row ${v != null && v <= 5 ? "low" : ""} ${v == null ? "is-pending" : ""}">
        <span class="dimension-label">${label}<small>权重 ${weight}%</small></span>
        <div class="dimension-track"><span style="width:${v == null ? 0 : v * 10}%"></span></div>
        <span class="dimension-value">${v == null ? "" : v}<small>${v == null ? "" : "/10"}</small></span>
      </div>`;
    }).join("");
    // 第三栏：有 AI 证据就直接给证据（同一页不出现两套结论），没有才用本地固定建议兜底
    renderAdvicePanel(r, scores);
    // 正在从服务端还原结果时不要抢跑：否则会白跑一次几十秒的诊断，再被还原结果覆盖
    if (!agentScores && !agentDiagFailed && !restoring) runAgentDiagnosis();   // 失败后不自动重试，避免死循环；改简历或手动重试才再跑
  }

  // 引文本身常自带「」/“”：外面再套一层就成「…「…」…」。这里先剥掉最外层
  // 已有的成对引号再包，成对不成立（只有左半边）就原样保留。
  // 还要先摘掉句末标点：`“GPA 3.6”。` 以「。」结尾，首尾比对配不上成对引号，
  // 结果是外层再包一层——双层嵌套就是这么来的。
  function stripQuoteMarks(text) {
    const raw = String(text || "").trim();
    const tailMatch = raw.match(/[。．.，,；;！!？?…]+$/);
    const tail = tailMatch ? tailMatch[0] : "";
    let core = tail ? raw.slice(0, raw.length - tail.length).trim() : raw;
    const pairs = [["「", "」"], ["『", "』"], ["“", "”"], ['"', '"'], ["'", "'"]];
    for (let pass = 0; pass < 2; pass += 1) {
      const hit = pairs.find(([open, close]) => core.length >= 2 && core.startsWith(open) && core.endsWith(close));
      if (!hit) break;
      core = core.slice(hit[0].length, core.length - hit[1].length).trim();
    }
    return core ? core + tail : raw;
  }

  // 引文外面统一用「」框住，但原文自己就带书名号/引号时（`他说「这不算我的功劳」`），
  // 再包一层就成了「…「…」…」——读起来像引了两层。这种情况只保留原文，
  // 靠 .evidence-quote 自己的浅底与缩进区分「这是引用」。
  function wrapQuote(text) {
    const core = stripQuoteMarks(text);
    return /[「」『』]/.test(core) ? core : `「${core}」`;
  }

  // 模型偶尔把内部字段名（foundation / tech_depth…）直接写进扣分说明（N13），
  // 学生看不懂。渲染前统一换成中文标签：只匹配完整 ASCII 词，不会误伤正常英文术语。
  const DIM_KEY_LABEL = {};
  [...careerMeta, ...interviewMeta].forEach(([k, label]) => { DIM_KEY_LABEL[k] = label; });
  const DIM_KEY_RE = new RegExp(
    `(^|[^A-Za-z0-9_])(${Object.keys(DIM_KEY_LABEL).join("|")})(?![A-Za-z0-9_])`, "g");
  const scrubInternal = text => String(text || "")
    .replace(DIM_KEY_RE, (m, pre, k) => pre + (DIM_KEY_LABEL[k] || k));

  // 从证据里挑「最该先改的三件事」：先按该维分数从低到高（弱项先修），
  // 同一维内按原顺序；改法文案撞车的只留一条。
  function topFixes(evidence, scores) {
    const key = dim => DIM_ALIAS[dim] || dim;
    const rank = dim => {
      const k = key(dim);
      return scores && typeof scores[k] === "number" ? scores[k] : 9;
    };
    const seen = new Set();
    const seenDim = new Set();
    const ordered = evidence
      .map((e, i) => ({ e, i }))
      .sort((a, b) => rank(a.e.dim) - rank(b.e.dim) || a.i - b.i)
      .filter(({ e }) => {
        const sig = String(e.fix || "").replace(/\s+/g, "");
        if (!sig || seen.has(sig)) return false;
        seen.add(sig);
        return true;
      });
    // 第一轮：同一维度只留一条——三条里出现两条「沟通表达」等于只给了两件事，
    // 改起来还是同一个模块，白占额度（N19）。
    const picked = [];
    const rest = [];
    ordered.forEach(item => {
      const dk = key(item.e.dim);
      if (!seenDim.has(dk) && picked.length < 3) { seenDim.add(dk); picked.push(item); }
      else rest.push(item);
    });
    // 维度不足三个时才用剩下的补位，保证「三件事」不会只剩两条
    return picked.concat(rest).slice(0, 3).map(({ e }) => e);
  }

  function renderAdvicePanel(r, scores) {
    const box = $("#analysisAdvice");
    const title = $("#adviceTitle");
    if (!box) return;
    if (agentEvidence.length) {
      if (title) {
        // 标题保持「最该先改的三件事」：这一页的核心承诺就是这三条。
        // 之前有证据时整块换成「AI 扣分证据」，卡片名字就没了，看起来像核心卡没出结果。
        title.innerHTML = '最该先改的三件事<span class="agent-badge" title="' +
          (agentDiagMode === "fallback"
            ? "AI 不可用，由服务端规则挑出原文片段；分数上限 6 分"
            : "由 " + escapeHTML(agentStatus.model || "模型") + " 判分，分数与等级由服务端量规计算") +
          '">' + (agentDiagMode === "fallback" ? "规则估分 · 非模型判断" : "服务端量分") + '</span>';
      }
      box.classList.add("is-evidence");
      const fixes = topFixes(agentEvidence, scores);
      const fixesHtml = fixes.map(e => `
        <li class="advice-top"><div>
          <strong>${escapeHTML(dimLabel(e.dim))}：${escapeHTML(clip(e.problem, 30))}</strong>
          <span class="advice-fix">改法：${escapeHTML(e.fix)}</span>
        </div></li>`).join("");
      // 证据列表跟在三条改法后面：同一份材料，先给结论再给原文，不用两处对照
      const evidenceHtml = agentEvidence.map(e => `
        <li><div>
          <div class="evidence-quote">${escapeHTML(wrapQuote(e.quote))}</div>
          <div class="evidence-line"><strong>${escapeHTML(dimLabel(e.dim))}</strong>${escapeHTML(scrubInternal(e.problem))}</div>
          <div class="evidence-fix">改法：${escapeHTML(scrubInternal(e.fix))}</div>
        </div></li>`).join("");
      const gaps = agentGaps.filter(g => g && g.fact_id);
      const gapsHtml = gaps.length ? `
        <li class="advice-gaps"><div>
          <div class="advice-gaps-title">事实清单里最该先练的 ${gaps.length} 条</div>
          <ul>${gaps.map(g => `<li>
            <button class="meta-chip fact" data-fact="${escapeHTML(g.fact_id)}" title="点击跳回简历对应模块">${escapeHTML(g.fact_id)}</button>
            <span>${escapeHTML(g.desc)}</span>
          </li>`).join("")}</ul>
          <p class="advice-gaps-note">面试首题就从这几条里出，编号与「AI 面试」里标注的一致。</p>
        </div></li>` : "";
      box.innerHTML = fixesHtml
        + `<li class="advice-divider"><div>AI 扣分证据 · 逐条原文与改法</div></li>`
        + evidenceHtml
        + gapsHtml;
      return;
    }
    if (title) title.textContent = "最该先改的三件事";
    box.classList.remove("is-evidence");
    // 空列表会让这一栏变成一个空白卡片（下面还挂着「改完这几处…」），
    // 看起来像功能坏了。没有条目时给一条明确的状态说明。
    const items = scores ? buildAdvice(r, scores) : [];
    box.innerHTML = items.length
      ? items.map(a => `<li><div><strong>${escapeHTML(a.title)}</strong>${escapeHTML(a.detail)}</div></li>`).join("")
      : `<li><div><strong>${scores ? "结构已经完整" : "诊断结果还没回来"}</strong>${
        scores ? "各模块都有内容且结果可验证，建议直接进 AI 面试，验证口头表达。" : "AI 正在读这份简历，分数出来前先别改内容；这里会自动换成最该先改的三处。"
      }</div></li>`;
  }

  /* ============ Agent 桥接（模型决策 + 服务端工具） ============ */

  let agentStatus = { ready: false, reason: "检测中", model: "" };
  let agentScores = null;      // 来自 score_career：服务端算的总分与等级
  let agentTotal = null;       // 服务端算好的总分，前端不再复算
  let agentEvidence = [];      // 来自 score_career：原文片段 / 问题 / 改法
  let agentSheet = null;       // 来自 build_fact_sheet：E1…En
  let agentGaps = [];          // 来自 build_fact_sheet：清单里最该先练的三条（页脚与右栏都引用它）
  let agentDiagBusy = false;
  let agentDiagSig = "";
  let agentDiagFailed = false;   // 诊断失败过：回落到本地估算，并允许重试
  let agentDiagMode = "";        // ""=模型判分 / "fallback"=服务端规则兜底
  let agentDiagPromise = null;   // 并发调用复用同一个 promise，避免误判"没跑完"
  let restoring = false;         // 启动时正在从服务端还原诊断结果：这期间别抢跑诊断

  const agentReady = () => !!(window.CoachAgent && agentStatus.ready);

  // 简历变了：分数、事实清单、证据全部作废，否则页面会拿旧结果当新结论
  function invalidateAgentScores() {
    agentScores = null;
    agentTotal = null;
    agentEvidence = [];
    agentSheet = null;
    agentGaps = [];
    agentDiagSig = "";
    agentDiagFailed = false;
    agentDiagMode = "";
    const note = $("#agentNote");
    if (note) note.remove();
  }
  // 证据的 dim 可能来自诊断五维，也可能被模型写成面试五维的键（tech/express/collab），
  // 认不出来时别把英文键直接印在界面上——学生读到的应是中文维度名。
  const DIM_ALIAS = { tech: "tech_depth", express: "expression", collab: "collaboration" };
  const dimLabel = key => {
    const k = DIM_ALIAS[key] || key;
    const hit = careerMeta.find(m => m[0] === k) || interviewMeta.find(m => m[0] === k);
    return hit ? hit[1] : "相关维度";
  };

  window.addEventListener("coach-agent-status", event => {
    agentStatus = event.detail || agentStatus;
    const footer = $(".nav-mode");
    if (footer) {
      footer.textContent = agentReady() ? "AGENT" : "DEMO";
      footer.title = agentReady()
        ? `模型：${agentStatus.model}｜9 个工具在服务端`
        : `智能体未就绪：${agentStatus.reason}`;
    }
    if (!agentReady()) {
      console.warn("[coach] 智能体未就绪：", agentStatus.reason);
      if (agentStatus.reason && agentStatus.reason !== "检测中") {
        renderAgentNote(`智能体未连通：${agentStatus.reason}｜当前为本地演示模式，分数由前端估算`);
      }
    } else {
      // 就绪是异步探测出来的：init 里那次 renderAnalysis 可能比它早，于是只画了本地
      // 估算分就停住（页面看着"诊断完了"，其实根本没调模型）。补一次自动开跑。
      maybeAutoDiagnose();
    }
  });

  // 已经就绪、有简历、停在分析页、还没分数，就自动跑一次诊断。
  // runAgentDiagnosis 自己按 promise 与简历签名去重，重复调用不会跑两遍。
  function maybeAutoDiagnose() {
    if (!agentReady() || !state.resume || state.resumeView !== "analysis") return;
    if (agentScores || agentDiagFailed || restoring || agentDiagPromise) return;
    renderAnalysis();
  }

  function agentBubble() {
    const el = document.createElement("div");
    el.className = "chat-msg ai";
    el.innerHTML = `<span class="chat-avatar">陪</span><div class="chat-body"><div class="chat-bubble"></div></div>`;
    $("#chatStream").appendChild(el);
    scrollChat();
    return el.querySelector(".chat-bubble");
  }

  // 流式正文按帧合并写入。网关常把一段回答切成几十上百个小 chunk，逐条
  // `textContent = buffer` 会让浏览器为每个 chunk 重排整段文字（越长越贵），
  // 长复盘这种几千字的文本叠起来足以把主线程占满——表现就是标签页「点了没反应」。
  const paintJobs = new WeakMap();
  function paintText(el, text) {
    if (!el || !el.isConnected) return;
    el.textContent = text;
    scrollChat();
  }
  function schedulePaint(el, text) {
    if (!el) return;
    const running = paintJobs.get(el);
    if (running) { running.text = text; return; }   // 这一帧内再来 chunk 只更新待写内容
    const job = { text, raf: 0 };
    job.raf = requestAnimationFrame(() => {
      paintJobs.delete(el);
      paintText(el, job.text);
    });
    paintJobs.set(el, job);
  }
  function flushPaint(el, text) {
    const job = paintJobs.get(el);
    if (job) { cancelAnimationFrame(job.raf); paintJobs.delete(el); }
    paintText(el, text);
  }

  function agentTyping(stage) {
    const el = document.createElement("div");
    el.className = "chat-msg ai";
    el.innerHTML = `<span class="chat-avatar">AI</span><div class="chat-body"><div class="chat-bubble"><span class="typing-dots"><i></i><i></i><i></i></span>${
      stage ? `<span class="typing-stage">${escapeHTML(stage)}</span>` : ""
    }</div></div>`;
    $("#chatStream").appendChild(el);
    scrollChat();
    return el;
  }

  function renderQuestion(q) {
    const el = document.createElement("div");
    el.className = "chat-msg ai";
    el.innerHTML = `<span class="chat-avatar">AI</span>
      <div class="chat-body">
        <div class="chat-meta">
          <span class="meta-chip layer">${escapeHTML(q.layer)}层追问</span>
          <button class="meta-chip fact" data-fact="${escapeHTML(q.fact)}" title="点击跳回简历对应模块">${escapeHTML(q.fact)} · 简历事实</button>
        </div>
        <div class="chat-bubble">${escapeHTML(q.text)}</div>
      </div>`;
    $("#chatStream").appendChild(el);
    scrollChat();
  }

  function renderAgentNote(text, retry) {
    const host = $(".advice-card");
    if (!host) return;
    let note = $("#agentNote");
    if (!note) {
      note = document.createElement("p");
      note.id = "agentNote";
      note.className = "agent-note";
      host.appendChild(note);
    }
    note.textContent = text;
    if (retry) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "重试";
      btn.style.cssText = "margin-left:8px;border:0;padding:0;background:none;color:inherit;text-decoration:underline;cursor:pointer;font:inherit";
      btn.onclick = () => runAgentDiagnosis(true);
      note.appendChild(btn);
    }
  }

  // 模型不通时的降级：让服务端按规则出分 + 从简历要点摊出事实清单。
  // 走的是本地后端工具，不依赖云模型；分数上限 6 分，界面上必须标明来源。
  async function runFallbackDiagnosis() {
    if (!window.CoachAgent || !state.resume) return false;
    try {
      const rawScore = await window.CoachAgent.callTool("score_career", { fallback: true });
      const p = rawScore && (rawScore.result || rawScore);
      if (!p || p.ok === false) return false;
      agentScores = p.scores;
      agentTotal = p.total;
      agentEvidence = p.evidence || [];
      agentDiagMode = "fallback";
      const rawSheet = await window.CoachAgent.callTool("build_fact_sheet", { auto: true });
      const q = rawSheet && (rawSheet.result || rawSheet);
      if (q && q.ok !== false) { agentSheet = q.items; agentGaps = q.top_gaps || []; }
      return true;
    } catch (_) {
      return false;
    }
  }

  function runAgentDiagnosis(force) {
    const r = state.resume;
    if (!agentReady() || !r) return;
    if (force) { agentDiagFailed = false; agentDiagSig = ""; }
    if (agentDiagPromise) return agentDiagPromise;          // 正在跑：复用，别当"没跑"
    const sig = JSON.stringify(r);
    if (sig === agentDiagSig && agentScores) return;        // 同一份简历已出过分
    agentDiagSig = sig;
    agentDiagBusy = true;
    agentDiagFailed = false;
    renderAgentNote("准备中：存档简历、锁定岗位…");

    let progress = "";        // 模型这一轮的进度话，流式贴到提示区
    let scored = false;       // 分数已经回来：之后模型的话不再挤进这里
    let last = { total: null, level: "" };

    const fail = async message => {
      if (agentDiagFailed) return;                            // 只兜一次，避免 error 与 done 各跑一遍
      agentDiagFailed = true;
      agentDiagSig = "";                                      // 失败不锁签名，允许重试
      renderAgentNote(`AI 诊断中断：${message}｜正在用服务端规则兜底…`);
      // 兜底也要落库：只在界面上算个分，服务端就没有分数与清单，
      // 面试页会因为"S3 都没到"一直拒绝——之前重启多少次都进不去就是这个原因。
      const ok = await runFallbackDiagnosis();
      renderAgentNote(
        ok
          ? `AI 不可用（${message}）｜已用服务端规则估分 ${agentTotal} 分，分档上限 6：不是模型判断，只能保证流程走得下去`
          : `AI 不可用（${message}）｜当前显示的是前端估算分，面试需要 AI，暂不可用`,
        true
      );
      renderAnalysis();
    };

    agentDiagPromise = window.CoachAgent.diagnose({
      resume: r,
      role: r.basic?.target || "",
      jd: "",
      onEvent: e => {
        if (e.type === "stage") {
          const done = (e.prepared || []).map(p => (p.name === "save_resume" ? "已存档" : "已锁定岗位"));
          const head = done.length ? done.join(" · ") + "｜" : "";
          renderAgentNote(`${head}正在逐维找原文证据…`);
        }
        if (e.type === "text" && !scored) {
          progress += e.text;
          const line = progress.replace(/\s+/g, " ").trim();
          if (line) renderAgentNote(`AI：${line.length > 90 ? "…" + line.slice(-90) : line}`);
        }
        if (e.type === "scores") {
          scored = true;
          agentScores = e.scores;
          agentTotal = e.total;
          agentEvidence = e.evidence || [];
          last = { total: e.total, level: e.level };
          renderAnalysis();
          renderAgentNote(`分数已出：${e.total}（${e.level}）｜正在建事实清单…`);
        }
        if (e.type === "sheet") {
          agentSheet = e.items;
          agentGaps = e.top_gaps || [];
          // scores 事件先到（那时 top_gaps 还是空，区块不渲染），sheet 事件只改数据不重绘，
          // 于是首次诊断永远缺「最该先练」这一块，页脚却已经指向它；刷新走还原路径才补上。
          // 只在已经判过分时重绘：没分就重绘会再触发一次诊断（renderAnalysis 里有那段）。
          if (scored) renderAnalysis();
          // 页脚本来说「最该先补 E1」，可正文里没有叫「最该先补」的区块，
          // 学生照着找找不到。改成和右栏区块同一句话，并在面板里把这三条列出来。
          renderAgentNote(
            `诊断完成：${last.total}（${last.level}）｜事实清单 ${e.version} · ${e.items.length} 条` +
            `｜最该先练 ${(agentGaps[0] || {}).fact_id || "—"}（见右栏「事实清单里最该先练的 ${agentGaps.length || 3} 条」）｜分数由服务端量规计算`
          );
        }
        if (e.type === "done" && scored && !agentSheet) {
          renderAgentNote(`分数已出：${last.total}（${last.level}）｜事实清单本轮没建起来，面试前建议重试一次`);
        }
        if (e.type === "done" && !scored) {
          // 模型可能只是说了一堆话就收工：不处理会一直停在"正在解析"，也没有分数入库
          fail("模型这一轮没有提交分数");
        }
        if (e.type === "error") {
          showToast(`AI 诊断失败：${e.message}`, "error");
          fail(e.message);
        }
      }
    })
      .catch(err => { fail(err && err.message ? err.message : String(err)); })
      .finally(() => { agentDiagBusy = false; agentDiagPromise = null; });

    return agentDiagPromise;
  }

  function agentInterviewTurn(kind, answer) {
    const it = state.interview;
    const typing = agentTyping();
    let live = null;
    let buffer = "";
    let gotQuestion = false;
    let lastError = "";

    const onEvent = e => {
      if (e.type === "text") {
        // 只在有正文时才把「正在输入」换成气泡：先建空气泡再等文字，
        // 断流时会留下一个空白 AI 气泡，看着像界面卡住了。
        buffer += e.text;
        if (!live && buffer.trim()) { typing.remove(); live = agentBubble(); }
        if (live) schedulePaint(live, buffer);
        return;
      }
      if (e.type === "question") {
        typing.remove();
        live = null; buffer = "";
        gotQuestion = true;
        it.nudged = false;
        $("#roundPill").textContent = `第 ${Math.min(e.round_no + 1, e.rounds_planned)} / ${e.rounds_planned} 轮`;
        renderQuestion({ text: e.question, layer: e.layer, fact: e.fact_id });
        return;
      }
      if (e.type === "error") {
        typing.remove();
        lastError = e.message || "未知错误";
        showToast(`面试官不可用：${e.message}`, "error");
      }
    };

    const task = kind === "start"
      ? window.CoachAgent.interviewStart({ scene: it.scene, role: it.role, rounds: it.rounds, onEvent })
      : kind === "nudge"
        ? window.CoachAgent.interviewNext({ onEvent })
        : window.CoachAgent.interviewAnswer({ answer, onEvent });

    const sendBtn = $("#sendAnswer");
    if (sendBtn) sendBtn.disabled = true;   // 面试官还在写，先别让用户插话（否则会被 busy 挡住）

    return task.then(async () => {
      typing.remove();
      if (live) flushPaint(live, buffer);   // 收尾时把最后一帧没画完的字补上
      if (live && !String(live.textContent || "").trim()) {
        const msg = live.closest(".chat-msg");
        if (msg) msg.remove();
      }
      if (gotQuestion) return;
      // 请求本身就是失败的：别用"本轮没拿到问题"糊过去，学生只会以为是运气问题
      if (lastError) {
        appendSystem(`面试官连不上（${lastError}）。这一场先停了：回简历页点「重试」确认 AI 通了再开，或换网络再试。`);
        return;
      }
      if (kind === "start") {
        // 出题为空是最容易被当成"功能坏了"的路径：别只写一句说明，得给一个能点的出口
        appendSystemButton(
          "本轮没有拿到问题——多半是模型这轮只写了寒暄。重试一次出题，或直接点「结束本场」看复盘。",
          "重新出题",
          () => agentInterviewTurn("start"),
        );
        return;
      }
      if (kind === "nudge") {
        // 补题也没拿到：别让对话静默卡住，明确告诉用户下一步能做什么
        appendSystemButton(
          "面试官这轮没出题（模型跳过了出题这一步）。重试一次，或直接补一句你的经历。",
          "重新要一题",
          () => agentInterviewTurn("nudge"),
        );
        return;
      }
      if (it.done) return;
      // 答完一题后固定另起一轮要题：模型偶尔只写点评不调工具，靠提示词不可靠
      try {
        const ctx = await window.CoachAgent.session();
        const iv = ctx.interview || {};
        if (iv.rounds_planned && iv.round_no >= iv.rounds_planned) {
          lockInterview(iv.rounds_planned);
          return;
        }
      } catch (_) { /* 读不到状态就继续要题 */ }
      return agentInterviewTurn("nudge");
    }).catch(err => {
      typing.remove();
      showToast(`面试官出错：${err && err.message ? err.message : err}`, "error");
    }).finally(() => {
      // 答满那一轮收尾时不能把发送键放回可点状态：放回去就等于又开了一口子
      if (sendBtn && !(state.interview && state.interview.locked)) sendBtn.disabled = false;
    });
  }

  // 答满计划轮数 → 锁输入 + 给明确出口。
  // 原来只插一句「计划 N 轮已答完」，输入框照样能点：多发的回答被记成第 N+1 题，
  // 复盘按 N+1 题算分，「设定 3 轮却出 4 题」的口径差就是这么来的。
  function setInterviewLocked(locked, planned) {
    if (!state.interview) return;
    state.interview.locked = !!locked;
    const input = $("#answerInput");
    const sendBtn = $("#sendAnswer");
    const sample = $("#sampleAnswer");
    if (input) {
      input.disabled = !!locked;
      if (locked) input.value = "";   // 锁上后还留着半句没发的内容，像"还能发"
      input.placeholder = locked
        ? `计划 ${planned} 轮已答完，点右上「结束本场」看复盘`
        : "用一句话先给结论，再补动作和结果…";
    }
    if (sendBtn) sendBtn.disabled = !!locked;
    if (sample) sample.disabled = !!locked;
    const pill = $("#roundPill");
    if (locked && pill) pill.textContent = `已答完 ${planned} / ${planned} 轮`;
  }

  function lockInterview(planned) {
    const it = state.interview || {};
    const p = Number(planned) || Number(it.rounds) || 5;
    setInterviewLocked(true, p);
    saveState();
    if ($("#chatStream .chat-exit")) return;
    const el = document.createElement("div");
    el.className = "chat-msg ai chat-exit";
    el.innerHTML = `<span class="chat-avatar">陪</span><div class="chat-body">
      <div class="chat-bubble" style="background:var(--accent-soft);border-color:transparent;color:var(--accent-deep);font-size:12.5px">计划 ${p} 轮已答完，输入框已锁——再多答的不会计入本场，也不会改动复盘口径。</div>
      <div class="chat-actions"><button type="button" class="btn primary sm" data-act="review">结束本场，看复盘</button></div>
    </div>`;
    $("#chatStream").appendChild(el);
    const btn = el.querySelector('[data-act="review"]');
    if (btn) btn.addEventListener("click", () => endInterview());
    scrollChat();
  }

  // 复盘这一段只能等模型：逐题四栏 + STAR + 五维要跑几十秒。期间原来只有三个点，
  // 学生既不知道在干什么也不知道还要多久；按时间推进阶段文案，至少能看出没卡死。
  const REVIEW_STAGES = [
    [0, "正在整理这场的对话…"],
    [9000, "正在逐题写点评与 STAR…"],
    [26000, "正在汇总卡点与改法…"],
    [50000, "还在收尾，通常再等十几秒…"],
    [85000, "模型这轮写得久，报告一旦落库就自动跳转…"],
  ];

  // 复盘前把前端手里的简历与本场问答灌回服务端。
  // 会话存在服务端内存/磁盘里：进程被回收或换实例后（实测结束本场时 stage 掉回 S0、
  // has_report=false），复盘就没有题可判，学生等到超时也拿不到报告。
  // 只补缺不覆盖，服务端状态正常时这一步等于一次空写。
  async function seedServerForReview() {
    const it = state.interview;
    if (!window.CoachAgent || !window.CoachAgent.hydrate || !state.resume || !it) return null;
    const answers = Array.isArray(it.answers) ? it.answers : [];
    const turns = answers.map((answer, i) => {
      // 演示模式的题来自本地题库，能对上 fact_id；智能体模式题目是模型给的，留给服务端兜底
      const q = it.agentMode ? {} : ((it.qs || [])[i] || {});
      return { question: q.text || "", answer: String(answer || ""), fact_id: q.fact || "", layer: q.layer || "" };
    });
    try {
      const ctx = await window.CoachAgent.hydrate({
        resume: state.resume,
        target_role: it.role || "",
        scene: it.scene || "",
        rounds: Number(it.rounds) || 0,
        turns,
      });
      const restored = (ctx && ctx.restored) || {};
      return restored.turns ? restored.turns : null;
    } catch (_) {
      return null;   // 服务端不可用时照常往下走，模型那一路还可能成功
    }
  }

  async function agentReview() {
    const it = state.interview;
    if (!it) return;
    if (it.reviewing) { showToast("复盘正在生成，稍等一下"); return; }
    it.reviewing = true;

    let typingEl = agentTyping(REVIEW_STAGES[0][1]);
    let live = null;
    let buffer = "";
    let failed = "";
    let report = null;
    let closed = false;

    const stage = text => {
      if (!typingEl.isConnected) {
        // 模型已经开始吐正文（阶段气泡已被正文气泡顶掉）：不再插一条新气泡打扰朗读
        if (live) return;
        typingEl = agentTyping(text);   // 自动重试时重建，让学生看得到"在重试"
      }
      const label = typingEl.querySelector(".typing-stage");
      if (label) label.textContent = text;
      scrollChat();
    };
    const stageTimers = REVIEW_STAGES.slice(1).map(([ms, text]) => setTimeout(() => stage(text), ms));

    // 空白气泡：文字还没吐出来就建了 bubble，中途断流会留一个空壳在对话流里。
    const dropEmptyBubble = () => {
      if (live) flushPaint(live, buffer);   // 先补最后一帧，否则会被误判成空气泡删掉
      if (live && !String(live.textContent || "").trim()) {
        const msg = live.closest(".chat-msg");
        if (msg) msg.remove();
      }
      live = null;
    };

    const once = async () => {
      let saved = false;
      let finishEarly = null;
      const early = new Promise(resolve => { finishEarly = resolve; });
      failed = "";
      try {
        await Promise.race([
          window.CoachAgent.review({
            onEvent: e => {
              if (closed) return;   // 已经跳去复盘页：后面吐的字不再往对话流里塞
              if (e.type === "text" && String(e.text || "").trim()) {
                if (!live) { typingEl.remove(); live = agentBubble(); }
                buffer += e.text;
                schedulePaint(live, buffer);   // 复盘文本最长，逐条重排最伤主线程
              }
              if (e.type === "report") {
                // 报告已落库，界面立刻可以跳；模型后面那段总结属于锦上添花，
                // 它卡住不该把学生一起卡在面试页。
                saved = true;
                finishEarly && finishEarly();
              }
              if (e.type === "error") {
                failed = e.message || "未知错误";
                finishEarly && finishEarly();
              }
            }
          }).catch(err => { failed = failed || (err && err.message ? err.message : String(err)); }),
          early,
          // 硬上限：不许无限停在「生成中」。120s 是实测留的余量——复盘 prompt 最长，
          // 75s 那版真实场景里两次都没拿到报告，直接判失败太早。
          new Promise(resolve => setTimeout(resolve, 120000))
        ]);
      } finally {
        dropEmptyBubble();
      }

      // 报告以服务端为准：不管是早退、超时还是断流，都以能取到 report 为准
      let got = null;
      for (let i = 0; i < 4 && !got; i += 1) {
        try {
          const ctx = await window.CoachAgent.session();
          got = (ctx && ctx.report) || null;
        } catch (_) { /* 服务端暂时读不到，退一次再试 */ }
        if (!got) await new Promise(r => setTimeout(r, saved ? 300 : 900));
      }
      return got;
    };

    showToast("正在生成复盘，通常半分钟到一分钟，进度显示在对话里");

    // 先续会话：进程重启过的场次，服务端一条答题记录都没有，模型再怎么写也出不了报告
    const restoredTurns = await seedServerForReview();
    if (restoredTurns) {
      stage(`服务端会话已断开，已按本地记录恢复 ${restoredTurns} 道题，继续生成复盘…`);
      showToast(`服务端会话已恢复 ${restoredTurns} 道题`, "success");
    }

    try {
      // 网关偶发 502 / 半路断流时服务端并没有报告：自动重跑一次，
      // 比让学生自己再点一遍「结束本场」省事（报告没落库，重跑无副作用）。
      for (let round = 1; round <= 2 && !report; round += 1) {
        if (round === 2) { live = null; buffer = ""; stage("第一次没连上，正在自动重试…"); }
        report = await once();
        if (!report && failed) showToast(`第 ${round} 次失败：${failed}`, "error");
      }
    } finally {
      stageTimers.forEach(clearTimeout);
      typingEl.remove();
      dropEmptyBubble();
      closed = true;
    }

    try {
      if (report) {
        it.done = true;        // 只有真拿到报告才算"这场结束了"
        renderAgentReview(report);
      } else {
        // 没出报告就别把场景锁死：done 一置真，下次点结束会进一个空复盘页
        it.done = false;
        saveState();
        showToast(failed ? `复盘没生成：${failed}（可再点一次「结束本场」）` : "复盘未生成，可再点一次「结束本场」", "error");
      }
    } finally {
      it.reviewing = false;
      saveState();
    }
  }

  // STAR 四枚标签：模型没给判定时不能一律显示灰色——
  // 四个灰标签读起来就是「四栏全缺」，可实际结论只是「这一项没评」。
  // STAR 三态：true=讲到 / false=没讲到 / null=模型没评这一项。
  // 只有一项有判定时，另外三项原来渲染成灰色划线，看起来像"四项缺三项"，
  // 而事实是模型只判了哪一项。未评的用中性底色，别冒充"缺"。
  function starChips(star) {
    const keys = ["S", "T", "A", "R"];
    const rated = star ? keys.filter(k => star[k] === true || star[k] === false) : [];
    if (!rated.length) {
      return `<span class="star-chip na" title="这一题模型没有给出 STAR 判定">STAR 未评</span>`;
    }
    return keys.map(k => {
      if (star[k] === true) return `<span class="star-chip on">${k}</span>`;
      if (star[k] === false) return `<span class="star-chip off" title="这一项没讲到">${k}</span>`;
      return `<span class="star-chip na" title="这一项模型没有判定">${k}</span>`;
    }).join("");
  }

  // 复盘左栏的 STAR 覆盖：把每题的四个字母汇总成命中率。
  // 原来左栏只有分数卡，卡到 y≈370 就结束，下面 300px 空着；
  // 这块填的是同一份报告里已有的判定，不加新数据。
  const STAR_META = [
    ["S", "情境", "先说清背景与限制（团队规模、业务量级、时间压力），再讲你做的事"],
    ["T", "任务", "把「这件事要达成什么」说成一句可检验的目标，别让人自己猜"],
    ["A", "行动", "用动词讲你亲手做的动作；只说团队做了什么，等于没答你自己的部分"],
    ["R", "结果", "补一个可验证的结果：数字、时长、上线范围，至少给一个"],
  ];

  function renderStarCard(report) {
    const box = $("#reviewStarBody");
    if (!box) return;
    const qs = report.per_question || [];
    const stat = {};
    STAR_META.forEach(([k]) => { stat[k] = { on: 0, off: 0 }; });
    let rated = 0;
    qs.forEach(q => {
      const st = q.star;
      if (!st) return;
      STAR_META.forEach(([k]) => {
        if (st[k] === true) { stat[k].on += 1; rated += 1; }
        else if (st[k] === false) { stat[k].off += 1; rated += 1; }
      });
    });
    if (!rated) {
      box.innerHTML = `<p class="star-note">本场没有拿到 STAR 判定，逐题卡里的字母因此都是灰的。分数与点评不受影响，只是少一层结构提示。</p>`;
      return;
    }
    const rows = STAR_META.map(([k, name]) => {
      const { on, off } = stat[k];
      const total = on + off;
      const pct = total ? Math.round((on / total) * 100) : 0;
      const weak = total > 0 && on / total < 0.5;
      return `<div class="star-row ${weak ? "is-weak" : ""}">
        <span class="star-key">${k}</span><span class="star-name">${name}</span>
        <div class="star-track"><span style="width:${pct}%"></span></div>
        <span class="star-count" title="${name}：${on} 题讲到 / ${total} 题有判定">${on}/${total}</span>
      </div>`;
    }).join("");
    const worst = STAR_META
      .map(([k, name, tip]) => ({ k, name, tip, on: stat[k].on, off: stat[k].off }))
      .filter(x => x.on + x.off > 0)
      .sort((a, b) => a.on / (a.on + a.off) - b.on / (b.on + b.off))[0];
    const tip = worst
      ? `<p class="star-note">最该补的是 <strong>${worst.k} · ${worst.name}</strong>（${worst.on}/${worst.on + worst.off} 题讲到）：${worst.tip}。</p>`
      : "";
    box.innerHTML = rows + tip;
  }

  // 卡片头部的胶囊只需要一个判断词，整句留给下面「差在哪」。
  // 原来头部和正文印的是同一个 q.gap，一张卡里同一句话出现两次，
  // 加上模型把 expect 写成同一句，就是清单里「三栏内容雷同」。
  function shortVerdict(text, max = 12) {
    const s = String(text || "").trim();
    if (!s) return "未评";
    const head = (s.split(/[：:，,。；;\n]/)[0] || s).trim() || s;
    return head.length > max ? head.slice(0, max) + "…" : head;
  }

  // 去掉标点/空白后比较：模型换个逗号就当成两句，等于没去重
  function plainOf(text) {
    return String(text || "").replace(/[\s。．.，,；;！!？?、：:「」『』“”"'‘’…—·\-]/g, "");
  }

  // 三栏逐条去重：内容逐字相同就并到上一行的标签里（「本可以答成 / 差在哪：…」），
  // 而不是把同一句话印两遍；和头部胶囊重复的那一项也不再单独占一行。
  function reviewLines(q, chipOf) {
    const fields = [["想验证", q.intent], ["本可以答成", q.expect], ["差在哪", q.gap]];
    const seen = new Set(chipOf ? [plainOf(chipOf)] : []);
    const out = [];
    for (const [label, raw] of fields) {
      // 模型常把「想验证…」写进 intent，行首再加一个「想验证：」就成了同一句重复
      let text = String(raw || "").trim();
      if (label === "想验证") text = text.replace(/^(主要|重点)?(想|要)?(验证|考察|看)(的)?[是为]?[：:，,]?\s*/, "").trim() || text;
      const key = plainOf(text);
      if (!key) continue;
      if (seen.has(key)) {
        if (out.length) out[out.length - 1].labels.push(label);
        continue;
      }
      seen.add(key);
      out.push({ labels: [label], text });
    }
    return out
      .map(x => `<strong>${x.labels.join(" / ")}：</strong>${escapeHTML(x.text)}`)
      .join("<br>");
  }

  function renderAgentReview(report) {
    const it = state.interview || {};
    const scores = report.scores || {};
    $("#reviewTotal").textContent = report.total;
    $("#reviewRadar").innerHTML = radarSVG(scores, interviewMeta, "#168e70");
    $("#reviewContext").textContent = `${report.scene || it.scene || "模拟面试"} · ${report.rounds} 轮问答 · 岗位「${report.target_role || it.role || "未填"}」`;
    const rows = (report.per_question || []).map((q, i) => {
      const chip = shortVerdict(q.gap);
      return `
      <article class="review-item">
        <div class="review-item-head">
          <span class="review-index">${String(i + 1).padStart(2, "0")}</span>
          <div class="review-q">
            <strong>${escapeHTML(q.question)}</strong>
            <span class="review-verdict" title="${escapeHTML(q.gap)}">${escapeHTML(chip)}</span>
          </div>
          <div class="star-chips">${starChips(q.star)}</div>
        </div>
        <div class="review-detail">
          <blockquote>${escapeHTML(q.actual)}</blockquote>
          <p class="review-fix">${reviewLines(q, chip)}</p>
          <p class="review-fix"><button class="meta-chip fact" data-fact="${escapeHTML(q.fact_id)}">${escapeHTML(q.fact_id)} 简历事实</button></p>
        </div>
      </article>`;
    }).join("");
    const gapRows = (report.gaps || []).length
      ? `<article class="review-item"><div class="review-item-head"><span class="review-index">卡</span>
          <div class="review-q"><strong>卡点清单</strong><span class="review-verdict">${report.gaps.length} 条，回简历优先处理</span></div></div>
          <div class="review-detail">${report.gaps.map(g => `<p class="review-fix">${escapeHTML(g.desc)}${g.fact_id ? `（${escapeHTML(g.fact_id)}）` : ""}${g.suggestion ? " · " + escapeHTML(g.suggestion) : ""}</p>`).join("")}</div>
        </article>`
      : "";
    $("#reviewList").innerHTML = rows + gapRows;
    renderStarCard(report);
    if (state.interview) {
      state.interview.reviewReady = true;
      if (!state.interview.recorded) {
        state.interview.recorded = true;
        recordHistory({
          scene: report.scene || it.scene || "模拟面试",
          rounds: Number(report.rounds) || (it.answers || []).length || 0,
          total: Number(report.total) || 0,
          scores: report.scores || {},
          facts: (report.per_question || []).length
        });
      }
      saveState();
    }
    showInterviewView("review");
    showToast(`复盘已生成：${report.total} 分 · ${report.match_level}`);
  }

  /* ============ AI 面试 ============ */

  function renderSceneOptions() {
    $("#sceneOptions").innerHTML = scenes.map(s => `
      <button class="scene-option ${state.selectedScene === s.id ? "active" : ""}" data-scene="${s.id}">
        ${icon(s.icon)}<span class="oi-main"><strong>${s.id}</strong><span>${s.desc}</span></span>
      </button>`).join("");
    // 只在空着时用简历里的求职意向兜底：每次点场景都会重渲染，
    // 无条件覆盖会把学生刚改过的岗位名冲掉
    const roleInput = $("#setupRole");
    if (roleInput && !roleInput.value.trim() && state.resume?.basic?.target) roleInput.value = state.resume.basic.target;
  }

  function startInterview() {
    const scene = state.selectedScene;
    const role = $("#setupRole").value.trim() || "后端开发工程师";
    const roundsSelect = $("#setupRounds");
    const options = [...roundsSelect.options].map(o => Number(o.value)).filter(n => Number.isFinite(n) && n >= 1);
    let rounds = Number(roundsSelect.value);
    // 下拉框 value 被清空（手改 DOM、浏览器恢复表单、旧页面缓存）时 Number("") === 0，
    // 照发就会让服务端建出一个 0 轮的场次：第一题直接 reached_limit，输入框还锁不住。
    if (!Number.isFinite(rounds) || rounds < 1 || rounds > 12) {
      rounds = options.includes(5) ? 5 : (options[0] || 5);
      roundsSelect.value = String(rounds);
      showToast(`轮数取值无效，已按 ${rounds} 轮开始`, "error");
    }
    const order = sceneOrders[scene] || sceneOrders[Object.keys(sceneOrders)[0]] || [];
    const qs = order.slice(0, rounds).map(i => questionBank[i]).filter(Boolean);
    state.interview = { scene, role, rounds, qs, idx: 0, answers: [], done: false, locked: false, agentMode: agentReady() };
    setInterviewLocked(false, rounds);
    $("#chatSceneBadge").textContent = `${scene} · ${role}`;
    $("#chatTitle").textContent = "AI 面试官";
    // 编号范围按真实清单条数写，不写死 E1–E6：清单只有 1 条时说「E1–E6」等于骗人
    const hint = $("#factHint");
    if (hint && agentSheet && agentSheet.length) {
      hint.innerHTML = `${icon("alert")}面试官会引用简历事实编号（E1–E${agentSheet.length}，共 ${agentSheet.length} 条），点击编号可跳回简历对应模块。`;
    }
    $("#chatStream").innerHTML = "";
    $("#answerInput").value = "";
    showInterviewView("chat");
    if (state.interview.agentMode) {
      appendSystem(`本场为 ${scene} · ${rounds} 轮 · 岗位「${role}」。面试官只问事实清单里的条目，每题标注编号与追问层级。`);
      // 面试题只从事实清单里出；清单还没生成时先把诊断补上，否则面试官会拒答
      if (!agentSheet) {
        if (!state.resume) {
          appendSystem("还没有简历——先回简历页上传或粘贴一份，再回来开始面试。");
          showToast("先创建简历", "error");
          return;
        }
        // 诊断已经失败过就别再自动重跑一遍：结果是同样的失败，只是让学生多等十几秒。
        if (agentDiagFailed) {
          appendSystem("AI 诊断没跑通，服务端没有事实清单，面试官开不了口。回简历页点「重试」把诊断跑通再来——这一场先不开始。");
          showToast("AI 不可用：面试需要模型出题，当前开不了", "error");
          return;
        }
        appendSystem("事实清单还没生成——先跑一次简历诊断，拿到清单后立刻开始面试。");
        const typing = agentTyping();
        Promise.resolve(runAgentDiagnosis()).then(() => {
          typing.remove();
          if (agentSheet) { agentInterviewTurn("start"); return; }
          showToast("诊断没跑完，拿不到事实清单；回简历页重试一次诊断", "error");
        });
        return;
      }
      agentInterviewTurn("start");
      return;
    }
    appendSystem(`本场为 ${scene} · ${rounds} 轮 · 岗位「${role}」。问题均来自简历事实，回答越具体越好。`);
    showToast(`本地演示模式：智能体未连通（${agentStatus.reason || "未知原因"}）`, "error");
    askNext();
  }

  function appendSystem(text) {
    const el = document.createElement("div");
    el.className = "chat-msg ai";
    el.innerHTML = `<span class="chat-avatar">陪</span><div class="chat-body"><div class="chat-bubble" style="background:var(--accent-soft);border-color:transparent;color:var(--accent-deep);font-size:12.5px">${escapeHTML(text)}</div></div>`;
    $("#chatStream").appendChild(el);
    scrollChat();
  }

  // 需要用户当场动手的系统提示（重新出题 / 看复盘）：只写文字等于把人晾在那儿
  function appendSystemButton(text, label, onClick) {
    const el = document.createElement("div");
    el.className = "chat-msg ai";
    el.innerHTML = `<span class="chat-avatar">陪</span><div class="chat-body">
      <div class="chat-bubble" style="background:var(--accent-soft);border-color:transparent;color:var(--accent-deep);font-size:12.5px">${escapeHTML(text)}</div>
      <div class="chat-actions"><button type="button" class="btn ghost sm">${escapeHTML(label)}</button></div>
    </div>`;
    $("#chatStream").appendChild(el);
    const btn = el.querySelector("button");
    if (btn && onClick) btn.addEventListener("click", () => { btn.disabled = true; onClick(); });
    scrollChat();
  }

  function askNext() {
    const it = state.interview;
    $("#roundPill").textContent = `第 ${Math.min(it.idx + 1, it.rounds)} / ${it.rounds} 轮`;
    if (it.idx >= it.qs.length) { finishInterview(); return; }
    const q = it.qs[it.idx];
    const typing = agentTyping();
    setTimeout(() => {
      typing.remove();
      renderQuestion(q);
    }, 800);
  }

  function analyzeAnswer(text) {
    return {
      conclusion: /^(我|结论|主要是|关键|因为)/.test(text.slice(0, 12)) || /结论|主要是|关键是|我会/.test(text.slice(0, 24)),
      action: /我|负责|实现|编写|设计|补充|完成/.test(text),
      result: /\d|降低|提升|覆盖|降到|涨|次|条|ms|%/.test(text)
    };
  }

  function sendAnswer() {
    const input = $("#answerInput");
    const text = input.value.trim();
    // 答满后输入框已禁用，但回车、脚本、旧页面都可能把内容塞进来，这里再挡一次
    if (state.interview && state.interview.locked) {
      showToast("计划轮数已答完，点「结束本场」看复盘", "error");
      return;
    }
    if (!text) { showToast("先写下一句回答", "error"); input.focus(); return; }
    const sendBtn = $("#sendAnswer");
    // 面试官还在写时发下一句，会被排队到下一轮，点评就错位到上一题上
    if (sendBtn && sendBtn.disabled) { showToast("面试官还在写，等这一轮结束再发", "error"); return; }
    const it = state.interview;
    state.interview.answers.push(text);
    const el = document.createElement("div");
    el.className = "chat-msg me";
    el.innerHTML = `<span class="chat-avatar">我</span><div class="chat-body"><div class="chat-bubble">${escapeHTML(text)}</div></div>`;
    $("#chatStream").appendChild(el);
    input.value = "";
    if (agentReady() && it.agentMode) {
      saveState();
      scrollChat();
      // 先落库，再让模型点评。顺序反了就是两条记录：模型那条先到，前端这条后补，
      // 复盘里同一题会出现两次。落库失败也照常往下走——模型那一路还有机会记上。
      if (sendBtn) sendBtn.disabled = true;
      const recorded = window.CoachAgent.recordAnswer
        ? window.CoachAgent.recordAnswer(text).catch(() => null)
        : Promise.resolve(null);
      // 落库慢或服务端不通时不能把这一轮卡死：4 秒没结果就先让模型接着点评
      Promise.race([recorded, new Promise(r => setTimeout(r, 4000))])
        .then(() => agentInterviewTurn("answer", text));
      return;
    }
    const a = analyzeAnswer(text);
    const miss = [];
    if (!a.conclusion) miss.push("开头先给结论");
    if (!a.action) miss.push("说清「我」的动作");
    if (!a.result) miss.push("挂一个可验证的结果");
    const tip = miss.length ? `还可以更好：${miss.join("，")}。` : "结论、动作、结果都齐了，保持这个顺序。";
    const coach = document.createElement("div");
    coach.className = "chat-msg ai";
    coach.innerHTML = `<span class="chat-avatar">陪</span><div class="chat-body"><div class="coach-tip">${icon("spark")}<span>${escapeHTML(tip)}</span></div></div>`;
    $("#chatStream").appendChild(coach);
    input.value = "";
    state.interview.idx += 1;
    saveState();
    scrollChat();
    setTimeout(askNext, 700);
  }

  // 每帧都写 scrollTop 会强制同步重排整条对话（越长越贵），而流式写入是每帧一次。
  // 只有本来就贴着底部时才跟；用户往上翻的时候别把他拽回来。
  function scrollChat(force) {
    const stream = $("#chatStream");
    if (!stream) return;
    const nearBottom = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 120;
    if (force || nearBottom) stream.scrollTop = stream.scrollHeight;
  }

  function starOf(text) {
    return {
      S: text.length >= 18,
      T: /当时|需要|要求|因为|场景|上线|项目/.test(text),
      A: /我|负责|实现|编写|补充|设计/.test(text),
      R: /\d|降低|提升|覆盖|降到|完成/.test(text)
    };
  }

  function verdictOf(star) {
    const miss = Object.entries(star).filter(([, on]) => !on).map(([k]) => k);
    if (!miss.length) return "完整：情境、任务、行动、结果都在。";
    if (miss.includes("R")) return "讲了过程，缺一个可验证的结果。";
    if (miss.includes("A")) return "背景和结果有了，但「我做了什么」不清晰。";
    if (miss.includes("S") || miss.includes("T")) return "结论给得快，背景铺垫略薄（问题不大）。";
    return "回答偏短，展开一档会更有说服力。";
  }

  function finishInterview() {
    const it = state.interview;
    if (agentReady() && it.agentMode) { agentReview(); return; }
    state.interview.done = true;
    saveState();
    const results = it.qs.map((q, i) => {
      const answer = it.answers[i] || "（未作答）";
      return { q, answer, star: starOf(answer) };
    });
    const score = results.map(r => (r.star.S + r.star.T + r.star.A + r.star.R) * 2.5);
    const avg = score.length ? score.reduce((s, v) => s + v, 0) / score.length : 5;
    const groupAvg = indices => {
      const picked = indices.map(i => score[i]).filter(v => v !== undefined);
      return picked.length ? Math.round(picked.reduce((s, v) => s + v, 0) / picked.length) : Math.round(avg);
    };
    const methodIdx = results.map((r, i) => ["方法", "量化"].includes(r.q.layer) ? i : -1).filter(i => i >= 0);
    const behaviorIdx = results.map((r, i) => ["归因", "反思"].includes(r.q.layer) ? i : -1).filter(i => i >= 0);
    const logicRatio = it.answers.length ? it.answers.filter(t => analyzeAnswer(t).conclusion).length / it.answers.length : 0;
    const tech = groupAvg(methodIdx);
    const project = Math.round(avg);
    const behavior = groupAvg(behaviorIdx);
    const scores = {
      tech_depth: tech,
      project,
      logic: clamp(Math.round(logicRatio * 10) || 4, 3, 9),
      behavior,
      fit: clamp(Math.round((tech + project) / 2), 3, 9)
    };
    const total = totalOf(scores, interviewMeta);
    $("#reviewTotal").textContent = total;
    $("#reviewRadar").innerHTML = radarSVG(scores, interviewMeta, "#168e70");
    $("#reviewContext").textContent = `${it.scene} · ${it.rounds} 轮问答 · 岗位「${it.role}」`;
    $("#reviewList").innerHTML = results.map((r, i) => `
      <article class="review-item">
        <div class="review-item-head">
          <span class="review-index">${String(i + 1).padStart(2, "0")}</span>
          <div class="review-q">
            <strong>${escapeHTML(r.q.text)}</strong>
            <span class="review-verdict">${escapeHTML(verdictOf(r.star))}</span>
          </div>
          <div class="star-chips">${["S", "T", "A", "R"].map(k => `<span class="star-chip ${r.star[k] ? "on" : "off"}">${k}</span>`).join("")}</div>
        </div>
        <div class="review-detail">
          <blockquote>${escapeHTML(r.answer)}</blockquote>
          <p class="review-fix"><strong>下一次这样改：</strong>结论 →「我」的动作 → 挂一个数字。这道题关联 <button class="meta-chip fact" data-fact="${r.q.fact}">${r.q.fact} 简历事实</button>，不确定的话回简历模块核实。</p>
        </div>
      </article>`).join("");
    state.interview.reviewReady = true;
    if (!it.recorded) {
      it.recorded = true;
      recordHistory({
        scene: it.scene,
        rounds: (it.answers || []).length,
        total,
        scores,
        facts: (it.qs || []).length
      });
    }
    showInterviewView("review");
    showToast("面试结束，逐题复盘已生成");
  }

  // 「结束本场」= 结束并看复盘，不是把这一场悄悄丢掉。
  // 之前这里直接 state.interview = null：学生答完 N 轮，界面提示"点结束本场看复盘"，
  // 点下去却回到场景页，问答记录和复盘一起没了。
  async function endInterview() {
    const it = state.interview;
    if (!it) { showInterviewView("setup"); return; }
    if (it.done && it.reviewReady) { showInterviewView("review"); return; }
    if (it.reviewing) { showToast("复盘正在生成，稍等一下"); return; }
    const answered = (it.answers || []).length;
    if (!answered) {
      const quit = await askConfirm("这一场还没答过题，退出不会生成复盘。确定退出吗？", "退出");
      if (!quit) return;
      state.interview = null;
      showInterviewView("setup");
      return;
    }
    const ok = await askConfirm(`按已答的 ${answered} 题生成复盘，并结束这一场？`, "生成复盘");
    if (!ok) return;
    finishInterview();
  }

  // 事实编号 → 简历模块。硬编码的 E1–E6 只覆盖固定清单；
  // 模型建的清单可以到 E12，兜底清单又按真实来源给 source_module，
  // 所以先问清单，再回落到固定映射。
  function moduleOfFact(fact) {
    const item = (agentSheet || []).find(it => it && it.id === fact);
    const fromSheet = item && item.source_module;
    if (fromSheet === "internships" || fromSheet === "projects" || fromSheet === "skills") return fromSheet;
    return factModuleMap[fact] || "";
  }

  function jumpToFact(fact) {
    const moduleId = moduleOfFact(fact);
    if (!moduleId) {
      showToast(`${fact} 没对应到简历模块：这条可能是清单里补的事实，回编辑页核对一下`, "error");
      return;
    }
    if (!state.resume) {
      switchNav("resume");
      showToast("还没有简历，先选一种方式创建", "error");
      return;
    }
    state.selectedModule = moduleId;
    switchNav("resume");
    showResumeView("editor");
    const cat = $(`#cat-${moduleId}`);
    if (cat) {
      cat.classList.remove("flash");
      void cat.offsetWidth;
      cat.classList.add("flash");
      cat.scrollIntoView({ block: "nearest" });
    }
    const sec = $(`#sec-${moduleId}`);
    if (sec) {
      sec.classList.remove("flash");
      void sec.offsetWidth;
      sec.classList.add("flash");
      sec.scrollIntoView({ block: "center", behavior: "smooth" });
    }
    showToast(`已定位到「${modules.find(m => m.id === moduleId).label}」（${fact} 来源）`);
  }

  /* ============ 事件绑定 ============ */

  let previewZoom = 1;

  function selectModule(id) {
    if (!modules.some(m => m.id === id)) return;
    state.selectedModule = id;
    renderCatalog();
    renderPaper();
    renderEditPanel();
    saveState();
  }

  // 导出走服务端（/api/resume/optimize 直接吐 docx），不经过模型：
  // 生成简历是确定性动作，绕一趟对话只多花十几秒。
  async function exportResumeDocx() {
    if (!state.resume) {
      showToast("还没有简历可导出", "error");
      return;
    }
    const btn = $("#exportDocx");
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = "生成中…";
    try {
      const res = await fetch(apiBase() + "/api/resume/optimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...state.resume, _template: paperTemplate() })
      });
      if (!res.ok) {
        const raw = await res.text();
        let msg = `HTTP ${res.status}`;
        try { msg = JSON.parse(raw).detail || msg; } catch (_) { /* 不是 JSON 就用状态码 */ }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const basic = state.resume.basic || {};
      // 文件名收敛：去非法字符，并把「·」「/」这类分隔符统一成短横。
      // 「林可-后端开发工程师 · 上海.docx」里的「· 」会被部分网盘/邮件客户端截断或转义（N21）。
      const clean = s => String(s || "")
        .replace(/\s*[·•|｜/\\]\s*/g, "-")
        .replace(/[:*?"<>]/g, "")
        .replace(/\s+/g, " ")
        .replace(/-{2,}/g, "-")
        .replace(/^[-\s]+|[-\s]+$/g, "")
        .trim();
      const nm = clean(basic.name);
      const tg = clean(basic.target);
      const base = nm && tg ? `${nm}-${tg}` : (nm || tg || "简历");
      const name = base + ".docx";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      // 点完立刻摘掉节点并 2s 撤销 Blob，部分浏览器会在下载还没接管时就把数据丢掉
      // （表现是重新下载一次、文件名带 (2)(3)…，或文件 0 字节）。等下载真正开始后再清。
      setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 8000);
      showToast(`已导出 ${name}`);
    } catch (err) {
      showToast(`导出失败：${err && err.message ? err.message : err}`, "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = label;
    }
  }

  /* ============ 我的：个人数据页 ============ */

  const fmtDate = ts => { const d = new Date(ts); return `${d.getMonth() + 1}月${d.getDate()}日`; };
  const dayKey = ts => { const d = new Date(ts); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

  // 数字滚动：KPI 与状态卡共用，rAF 缓出
  function countUp(el, target, { suffix = "", duration = 750 } = {}) {
    const start = performance.now();
    const step = now => {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased) + suffix;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // 连续训练：今天没练不断签（从今天或昨天往前数）；best 取历史最长连跑
  function streakOf(list) {
    const days = [...new Set(list.map(h => dayKey(h.ts)))].sort();
    let best = 0, run = 0, prev = null;
    days.forEach(key => {
      const diff = new Date(key) - new Date(prev);
      run = prev && diff === 86400000 ? run + 1 : 1;
      best = Math.max(best, run);
      prev = key;
    });
    let current = 0;
    const cursor = new Date();
    if (!days.includes(dayKey(cursor.getTime()))) cursor.setDate(cursor.getDate() - 1);
    while (days.includes(dayKey(cursor.getTime()))) {
      current += 1;
      cursor.setDate(cursor.getDate() - 1);
    }
    return { current, best };
  }

  function profileResumeData() {
    if (!state.resume) return null;
    const scores = agentScores || computeScores(state.resume);
    const bullets = allBullets(state.resume);
    return {
      progress: overallProgress(state.resume),
      scores,
      bullets,
      unverified: bullets.filter(b => !/\d/.test(b)).length
    };
  }

  // E1–E6 状态点：对应模块有内容且要点都带数字 = 绿，有内容缺数字 = 黄，无内容 = 灰
  function factDotsData() {
    const r = state.resume;
    if (!r) return [];
    const bulletsOf = moduleId => moduleId === "skills"
      ? (r.skills || [])
      : (r[moduleId] || []).flatMap(x => x.bullets || []);
    return Object.entries(factModuleMap).map(([id, moduleId]) => {
      const bullets = bulletsOf(moduleId);
      const state = !bullets.length ? "empty" : bullets.every(b => /\d/.test(b)) ? "ok" : "warn";
      return { id, state };
    });
  }

  function donutSVG(pct, color = "#625bf6") {
    const r = 46, c = 2 * Math.PI * r;
    return `<svg viewBox="0 0 120 120" class="donut-svg">
      <circle cx="60" cy="60" r="${r}" fill="none" stroke="#edf0f7" stroke-width="12"/>
      <circle cx="60" cy="60" r="${r}" fill="none" stroke="${color}" stroke-width="12" stroke-linecap="round"
        class="donut-arc" transform="rotate(-90 60 60)"
        style="--arc:${(pct / 100) * c}; --circ:${c}"/>
      <text x="60" y="66" text-anchor="middle" class="donut-num">0%</text>
    </svg>`;
  }

  function trendSVG(list) {
    const pts = list.slice(-10);
    const w = 560, h = 190, px = 44, py = 30;
    const x = i => (pts.length === 1 ? w / 2 : px + i * (w - px * 2) / (pts.length - 1));
    const y = v => py + (1 - v / 100) * (h - py * 2);
    const coords = pts.map((p, i) => [x(i), y(p.total)]);
    const path = coords.map(([cx, cy], i) => `${i ? "L" : "M"}${cx.toFixed(1)} ${cy.toFixed(1)}`).join(" ");
    const gridY = [0, 50, 100].map(v =>
      `<line x1="${px - 14}" x2="${w - px / 2}" y1="${y(v)}" y2="${y(v)}" class="trend-grid"/>
       <text x="${px - 20}" y="${y(v) + 4}" class="trend-axis">${v}</text>`).join("");
    const dots = coords.map(([cx, cy], i) =>
      `<circle cx="${cx}" cy="${cy}" r="4.5" class="trend-dot" style="--i:${i}"/>`).join("");
    const dates = pts.length > 1
      ? `<text x="${coords[0][0]}" y="${h - 6}" class="trend-axis">${fmtDate(pts[0].ts)}</text>
         <text x="${coords[coords.length - 1][0]}" y="${h - 6}" text-anchor="end" class="trend-axis">${fmtDate(pts[pts.length - 1].ts)}</text>`
      : "";
    return `<svg viewBox="0 0 ${w} ${h}" class="trend-svg">${gridY}<path d="${path}" class="trend-path"/>${dots}${dates}</svg>`;
  }

  // 描线动画：插进 DOM 后量出路径长度，从右往左画出
  function animateTrend() {
    const path = $("#trendChart .trend-path");
    if (!path) return;
    const len = path.getTotalLength();
    if (!len) return;
    path.style.strokeDasharray = `${len}`;
    path.style.strokeDashoffset = `${len}`;
    requestAnimationFrame(() => {
      path.style.transition = "stroke-dashoffset 1.1s cubic-bezier(.3,.7,.3,1) .15s";
      path.style.strokeDashoffset = "0";
    });
  }

  function heatmapHTML(list) {
    const counts = {};
    list.forEach(h => { const k = dayKey(h.ts); counts[k] = (counts[k] || 0) + 1; });
    const cells = [];
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    for (let i = 55; i >= 0; i -= 1) {
      const d = new Date(today.getTime() - i * 86400000);
      const k = dayKey(d.getTime());
      const n = counts[k] || 0;
      cells.push(`<i class="heat-cell ${n > 1 ? "l2" : n ? "l1" : ""}" style="--i:${55 - i}" title="${k}${n ? ` · ${n} 场` : ""}"></i>`);
    }
    return `<div class="heatmap">${cells.join("")}</div><p class="heat-caption">近 8 周训练频率</p>`;
  }

  function sceneDonutHTML(list) {
    const colors = { 专业面: "#625bf6", 行为面: "#168e70", 压力面: "#e5a30d" };
    const counts = { 专业面: 0, 行为面: 0, 压力面: 0 };
    list.forEach(h => { if (counts[h.scene] != null) counts[h.scene] += 1; });
    const total = list.length;
    if (!total) return "";
    const r = 38, c = 2 * Math.PI * r;
    let acc = 0;
    const arcs = Object.entries(counts).filter(([, n]) => n > 0).map(([scene, n]) => {
      const frac = n / total;
      const seg = `<circle cx="50" cy="50" r="${r}" fill="none" stroke="${colors[scene]}" stroke-width="13"
        class="donut-arc" stroke-dashoffset="${-acc * c}" transform="rotate(-90 50 50)"
        style="--arc:${Math.max(frac * c - 1.5, 1).toFixed(1)}; --circ:${c}"/>`;
      acc += frac;
      return seg;
    }).join("");
    const legend = Object.entries(counts).map(([scene, n]) =>
      `<span><i style="background:${colors[scene]}"></i>${scene}<b>${n} 场</b></span>`).join("");
    return `<svg viewBox="0 0 100 100" class="scene-svg">${arcs}</svg><div class="scene-legend">${legend}</div>`;
  }

  function statusPanelHTML(list, rd) {
    const streak = streakOf(list);
    let weakest = null;
    if (list.length) {
      const sums = {}, counts = {};
      list.forEach(h => Object.entries(h.scores || {}).forEach(([k, v]) => {
        if (typeof v !== "number") return;
        sums[k] = (sums[k] || 0) + v;
        counts[k] = (counts[k] || 0) + 1;
      }));
      const avgs = Object.entries(sums).map(([k, s]) => [k, s / counts[k]]);
      if (avgs.length) {
        const [key, val] = avgs.sort((a, b) => a[1] - b[1])[0];
        const meta = interviewMeta.find(m => m[0] === key);
        weakest = { label: meta ? meta[1] : key, avg: Math.round(val) };
      }
    }
    const todo = !rd
      ? { text: "还没有简历数据，先创建一份，面试题都从简历里出。", jump: "entry", label: "去创建" }
      : rd.unverified
        ? { text: `有 <strong>${rd.unverified}</strong> 条经历要点缺可验证结果，建议先补上数字。`, jump: "editor", label: "去编辑" }
        : { text: "简历结构完整，事实全部有数字支撑。", jump: "setup", label: "去面试实战" };
    return `<div class="status-stack">
      <div class="status-block">
        <span class="s-num">${icon("spark")}<span data-count>${streak.current}</span><small>天连续</small></span>
        <p>最长 ${streak.best} 天 · 每天至少一场算连续</p>
      </div>
      ${weakest ? `<div class="status-block">
        <span class="s-num">${escapeHTML(weakest.label)}<small>均分 ${weakest.avg}/10</small></span>
        <div class="s-track"><span style="width:${Math.max(weakest.avg * 10, 6)}%"></span></div>
        <p>面试里最弱的一维，优先针对它练。</p>
      </div>` : ""}
      <div class="status-block">
        <span class="s-num s-todo">待办</span>
        <p>${todo.text}</p>
        <button type="button" class="btn ghost sm" data-jump="${todo.jump}">${todo.label}</button>
      </div>
    </div>`;
  }

  const emptyGuide = (text, jump, label) =>
    `<div class="data-empty"><svg aria-hidden="true"><use href="#i-spark"/></svg><span>${text}</span>
     <button type="button" class="btn ghost sm" data-jump="${jump}">${label}</button></div>`;

  function renderProfile() {
    const list = readHistory();
    const rd = profileResumeData();
    const streak = streakOf(list);
    const sessions = list.length;
    const avg = sessions ? Math.round(list.reduce((s, h) => s + (h.total || 0), 0) / sessions) : 0;
    const rounds = list.reduce((s, h) => s + (h.rounds || 0), 0);

    // 状态短句
    $("#profileStatusLine").textContent = sessions
      ? `最近一场「${list[sessions - 1].scene}」在 ${fmtDate(list[sessions - 1].ts)} · 已连续训练 ${streak.current} 天`
      : "完成第一场 AI 面试，这里就会长出你的数据";

    // KPI 条
    const kpis = [
      ["简历完成度", rd ? rd.progress : 0, "%"],
      ["面试场次", sessions, ""],
      ["平均表达分", sessions ? avg : 0, ""],
      ["累计问答轮数", rounds, ""],
      ["最长连续天数", streak.best, ""]
    ];
    $("#kpiStrip").innerHTML = kpis.map(([label, value, suffix]) => `
      <div class="kpi">
        <strong class="kpi-num" data-target="${value}" data-suffix="${suffix}">0${suffix}</strong>
        <span class="kpi-label">${label}</span>
      </div>`).join("");
    $$("#kpiStrip .kpi-num").forEach(el => countUp(el, Number(el.dataset.target), { suffix: el.dataset.suffix }));

    // 左：简历数据
    $("#resumeDonut").innerHTML = rd
      ? donutSVG(rd.progress) + `<p class="donut-cap">结构完成度 ${rd.progress}%</p>`
      : emptyGuide("还没有简历", "entry", "去创建");
    const donutNum = $("#resumeDonut .donut-num");
    if (donutNum && rd) countUp(donutNum, rd.progress, { suffix: "%" });
    $("#profileRadar").innerHTML = rd ? radarSVG(rd.scores, careerMeta) : "";
    $("#factDots").innerHTML = rd
      ? factDotsData().map((d, i) =>
          `<span class="fact-dot ${d.state}" style="--i:${i}" title="${d.id} · ${d.state === "ok" ? "结果可验证" : d.state === "warn" ? "有内容但缺数字" : "还没有对应内容"}">${d.id}</span>`).join("")
      : "";

    // 中：面试历史
    $("#trendChart").innerHTML = sessions
      ? trendSVG(list)
      : emptyGuide("还没有面试记录", "setup", "去练一场");
    $("#heatmapBox").innerHTML = sessions ? heatmapHTML(list) : "";
    $("#sceneDonut").innerHTML = sessions ? sceneDonutHTML(list) : "";
    animateTrend();

    // 右：当前状态
    $("#statusPanel").innerHTML = statusPanelHTML(list, rd);
    const streakEl = $("#statusPanel [data-count]");
    if (streakEl) countUp(streakEl, streak.current);

    // 场次记录（新→旧，最多 10 条）
    $("#historyList").innerHTML = sessions
      ? [...list].reverse().slice(0, 10).map((h, i) => `
          <div class="history-row" style="--i:${i}">
            <span class="h-date">${fmtDate(h.ts)}</span>
            <span class="h-scene">${escapeHTML(h.scene || "面试")}</span>
            <span class="h-meta">${h.rounds || 0} 轮 · 引用 ${h.facts || 0} 个事实</span>
            <strong class="h-total">${h.total || 0}<small> 分</small></strong>
          </div>`).join("") + (sessions > 10 ? `<p class="history-more">更早的 ${sessions - 10} 场已折叠，导出数据可查看全部</p>` : "")
      : emptyGuide("场次记录为空", "setup", "去练一场");
  }

  // 导出：简历状态 + 全部面试历史打包成 JSON
  function exportProfileData() {
    const payload = {
      exportedAt: new Date().toISOString(),
      resume: state.resume,
      history: readHistory()
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `简历陪练数据-${dayKey(Date.now())}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast("数据已导出为 JSON 文件");
  }

  async function clearProfileData() {
    const ok = await askConfirm("将清空本机的简历数据与全部面试历史，且无法恢复。确定清空吗？", "全部清空");
    if (!ok) return;
    [STORAGE_KEY, HISTORY_KEY, ...LEGACY_KEYS].forEach(key => localStorage.removeItem(key));
    state = clone(defaultState);
    renderGallery();
    renderProfile();
    showToast("已清空全部本地数据");
  }

  function bindEvents() {
    $$(".nav-item").forEach(item => item.addEventListener("click", () => switchNav(item.dataset.nav)));

    /* 简历入口：模板画廊 + 上传 */
    $("#tplGallery").addEventListener("click", event => {
      const card = event.target.closest("[data-template]");
      if (card) startFromTemplate(card.dataset.template);
    });
    $("#resumeFile").addEventListener("change", event => {
      const file = event.target.files[0];
      if (file) readResumeFile(file);
      event.target.value = "";
    });
    $("#dropzone").addEventListener("dragover", event => { event.preventDefault(); $("#dropzone").classList.add("drag"); });
    $("#dropzone").addEventListener("dragleave", () => $("#dropzone").classList.remove("drag"));
    $("#dropzone").addEventListener("drop", event => {
      event.preventDefault();
      $("#dropzone").classList.remove("drag");
      const file = event.dataTransfer.files[0];
      if (file) readResumeFile(file);
    });
    $("#parsePaste").addEventListener("click", () => {
      const text = $("#pasteResume").value.trim();
      if (!text) { showToast("先粘贴一段简历文本", "error"); return; }
      parseUpload("", text);
    });

    /* 编辑页 */
    $("#backEntry").addEventListener("click", () => showResumeView("entry"));
    $("#gotoAnalysis").addEventListener("click", () => {
      // 空简历进诊断页只会看到 0 分与空雷达，之前点了连提示都没有（N11）
      if (!state.resume || sectionsFilled(state.resume) === 0) {
        showToast("先上传、粘贴或填一份简历，才有五维可看", "error");
        return;
      }
      showResumeView("analysis");
    });
    // 版式下拉：只改 exportTemplate，不动简历内容
    $("#tplPicker").addEventListener("change", event => {
      setExportTemplate(event.target.value);
      showToast(`导出与预览已切到「${templateName()}」`);
    });
    $("#gotoInterview").addEventListener("click", () => { switchNav("interview"); showInterviewView("setup"); });
    $("#exportDocx").addEventListener("click", exportResumeDocx);
    $("#analysisBack").addEventListener("click", () => showResumeView("editor"));
    $("#analysisToInterview").addEventListener("click", () => { switchNav("interview"); showInterviewView("setup"); });

    /* 编辑页：模块目录 / 预览点选 */
    $("#moduleCatalog").addEventListener("click", event => {
      const item = event.target.closest("[data-module]");
      if (item) selectModule(item.dataset.module);
    });
    $("#previewScroll").addEventListener("click", event => {
      const sec = event.target.closest(".pp-sec[data-module]");
      if (sec) selectModule(sec.dataset.module);
    });

    /* 预览缩放 */
    $("#zoomGroup").addEventListener("click", event => {
      const btn = event.target.closest("[data-zoom]");
      if (!btn) return;
      previewZoom = Number(btn.dataset.zoom);
      $("#previewScroll").style.setProperty("--zoom", previewZoom);
      $$("#zoomGroup button").forEach(b => b.classList.toggle("active", b === btn));
    });

    $("#editPanel").addEventListener("input", event => {
      const path = event.target.dataset.path;
      if (!path) return;
      setPath(state.resume, path, event.target.value);
      // 要点里补上数字后，提示条要当场消失（原来只在重渲染时才刷新）
      const block = event.target.closest("[data-bullet]");
      if (block) {
        block.classList.toggle("no-result", !/\d/.test(event.target.value));
        autoGrow(event.target);
      }
      invalidateAgentScores();   // 简历一改，旧分数与旧清单全部作废
      renderCatalog();
      renderPaper();
      saveState();
    });
    $("#editPanel").addEventListener("change", event => {
      const path = event.target.dataset.path;
      if (path && event.target.tagName === "SELECT") {
        setPath(state.resume, path, event.target.value);
        invalidateAgentScores();
        saveState();
      }
    });
    $("#editPanel").addEventListener("click", handleEditActions);
    $("#editPanel").addEventListener("keydown", event => {
      if (event.key === "Enter" && event.target.id === "newSkill") { event.preventDefault(); $(`[data-action="add-skill"]`).click(); }
      if (event.key === "Enter" && event.target.id === "newCert") { event.preventDefault(); $(`[data-action="add-cert"]`).click(); }
    });

    /* 面试 */
    $("#sceneOptions").addEventListener("click", event => {
      const option = event.target.closest("[data-scene]");
      if (!option) return;
      state.selectedScene = option.dataset.scene;
      renderSceneOptions();
    });
    $("#startInterview").addEventListener("click", startInterview);
    $("#sendAnswer").addEventListener("click", sendAnswer);
    $("#answerInput").addEventListener("keydown", event => {
      if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendAnswer(); }
    });
    $("#answerInput").addEventListener("input", event => {
      event.target.style.height = "auto";
      event.target.style.height = `${Math.min(event.target.scrollHeight, 100)}px`;
    });
    $("#sampleAnswer").addEventListener("click", () => {
      const it = state.interview;
      if (!it) return;
      $("#answerInput").value = sampleAnswers[(it.answers || []).length % sampleAnswers.length];
      $("#answerInput").focus();
    });
    $("#quitInterview").addEventListener("click", endInterview);
    $("#reviewRestart").addEventListener("click", () => { state.interview = null; showInterviewView("setup"); });
    $("#reviewToResume").addEventListener("click", () => { switchNav("resume"); showResumeView(state.resume ? "editor" : "entry"); });

    /* 我的：导出 / 清空 / 页内跳转 */
    $("#exportData").addEventListener("click", exportProfileData);
    $("#clearData").addEventListener("click", clearProfileData);
    $("#profileView").addEventListener("click", event => {
      const jump = event.target.closest("[data-jump]")?.dataset.jump;
      if (!jump) return;
      if (jump === "editor") { switchNav("resume"); showResumeView("editor"); }
      else if (jump === "entry") { switchNav("resume"); showResumeView("entry"); }
      else if (jump === "setup") { switchNav("interview"); showInterviewView("setup"); }
    });

    /* 事实编号跳转（对话 + 复盘两处共用） */
    document.body.addEventListener("click", event => {
      const fact = event.target.closest("[data-fact]")?.dataset.fact;
      if (fact) jumpToFact(fact);
    });
  }

  /* ============ 启动 ============ */

  // 刷新后内存里的分数、证据、事实清单都没了，但服务端会话里还在。
  // 先走一次幂等 prepare（简历没变就不重存、不动旧结果），再把服务端状态取回来：
  // 否则同一份简历会被重新诊断一遍，面试前还要再多等几十秒。
  // 简历改过的话 prepare 会作废旧分数与旧清单，这里自然取不到东西，回落成重新诊断。
  async function restoreDiagnosis() {
    if (!window.CoachAgent || !state.resume) return false;
    try {
      await window.CoachAgent.prepare({
        resume: state.resume,
        role: (state.resume.basic && state.resume.basic.target) || ""
      });
      const ctx = await window.CoachAgent.session();
      if (!ctx || !ctx.career_scores || !Object.keys(ctx.career_scores).length) return false;
      agentScores = ctx.career_scores;
      agentTotal = ctx.career_total;
      agentEvidence = ctx.career_evidence || [];
      agentDiagMode = ctx.career_source === "rules" ? "fallback" : "";
      agentDiagSig = JSON.stringify(state.resume);
      agentSheet = (ctx.fact_items || []).length ? ctx.fact_items : null;
      agentGaps = ctx.top_gaps || [];
      if (state.resumeView === "analysis") renderAnalysis();
      return true;
    } catch (_) {
      return false;   // 服务端不通就交给正常诊断流程报错，不在这里静默吞掉
    }
  }

  // 刷新后复盘页只剩空壳：报告正文在服务端会话里，重新取一次再决定要不要留在这一页
  async function restoreReview() {
    if (!window.CoachAgent || !state.interview) { showInterviewView("setup"); return; }
    try {
      const ctx = await window.CoachAgent.session();
      if (ctx && ctx.report) { renderAgentReview(ctx.report); return; }
    } catch (_) { /* 读不到就按没有处理 */ }
    showInterviewView("setup");
  }

  function init() {
    renderGallery();
    bindEvents();
    if (!state.resume) { state.resumeView = "entry"; }
    restoring = !!state.resume;
    switchNav(state.nav === "interview" ? "interview" : "resume");
    // 对话流无法从 localStorage 还原，聊天页一律回设置页；
    // 复盘页有服务端报告可还原，别也一并踢回设置页
    if (state.interviewView === "chat") showInterviewView("setup");
    if (state.interviewView === "review") restoreReview();
    // 先看服务端有没有现成的诊断结果，没有才重新跑诊断
    restoreDiagnosis().finally(() => {
      restoring = false;
      if (!agentScores && state.resume && state.resumeView === "analysis") renderAnalysis();
      maybeAutoDiagnose();   // 就绪事件若晚于还原流程，这里补一次（内部会去重）
    });
  }

  init();
})();
