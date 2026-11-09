/* = 智能体运行时  端侧决策循环 +
   职责边界：这里只跑「想 → 调工具 → 看结果 → 再想」的循环，并把事件抛给界面。
   一切确定性判断（分数、编号、证据强度、报告总分）都在服务端工具里，前端不复算。
*/
(() => {
  "use strict";

  const SID_KEY = "coach-agent-sid";
  const CONV_KEY = "coach-agent-conv";

  const cfg = () => window.AGENT_CONFIG || {};
  const rand = () => (window.crypto && crypto.randomUUID ? crypto.randomUUID() : "s" + Math.random().toString(36).slice(2) + Date.now());

  let sessionId = localStorage.getItem(SID_KEY);
  if (!sessionId) {
    sessionId = rand();
    localStorage.setItem(SID_KEY, sessionId);
  }
  let conversationId = localStorage.getItem(CONV_KEY);
  if (!conversationId) {
    conversationId = rand();
    localStorage.setItem(CONV_KEY, conversationId);
  }

  let cloud = null;
  let modelId = "";
  let modelName = "";
  let ready = false;
  let reason = "未初始化";
  let busy = false;
  let currentTask = null;   // 正在跑的那一轮：下一轮要等它收尾，而不是直接报忙
  let abortCtrl = null;
  let history = [];   // 跨轮文本上下文（只存 user / assistant 文本，工具消息不跨轮）

  /* ---------- 与后端通信 ---------- */

  function apiBase() {
    if (cfg().apiBase) return cfg().apiBase.replace(/\/$/, "");
    if (location.protocol === "file:") return "http://127.0.0.1:8000";
    const host = location.hostname;
    const local = host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" || host.endsWith(".local");
    if (!local) return "";                                  // 线上：页面与接口同源，直接打相对路径
    if (location.port === "8000") return "";                 // 本机 FastAPI 直接服务页面
    return `${location.protocol}//${host}:8000`;             // 本机静态服务器（4174 等）另起后端
  }

  /* conversationId 会被 SDK 塞进 `X-Conversation-ID` 请求头（见 vendor SDK 的
     createStreaming）。这个头不在 CORS 安全清单里，跨源时浏览器必然先发预检；
     网关的 Allow-Headers 里没有它，预检就被拒，整个请求在浏览器层面直接失败，
     前端只能看到一句 Failed to fetch。会话分组只是锦上添花，跨源就不带。 */
  function cloudOrigin() {
    try { return new URL((window.APP_CONFIG || {}).endpoint || "").origin; } catch (_) { return ""; }
  }

  function canSendConversationId() {
    const origin = cloudOrigin();
    return !!origin && origin === location.origin;
  }

  async function http(path, options = {}) {
    // GET 不带 body 就别带 Content-Type：application/json 不在 CORS 安全清单里，
    // 跨源（页面 4174 / 接口 8000）时会给每个 GET 多加一次预检往返。
    const headers = options.body ? { "Content-Type": "application/json" } : {};
    const res = await fetch(apiBase() + path, { headers, ...options });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (_) { data = { detail: text }; }
    if (!res.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${res.status}`);
    return data;
  }

  const manifest = (module) => http(`/api/agent/manifest?module=${encodeURIComponent(module)}&session_id=${encodeURIComponent(sessionId)}`);
  // 预置：存档 / 锁岗这类没有判断空间的动作先让服务端做掉，模型开场就能直接判分
  const prepare = (body) => http("/api/agent/prepare", { method: "POST", body: JSON.stringify(Object.assign({ session_id: sessionId }, body)) });
  const callTool = (name, args) => http("/api/agent/tool", { method: "POST", body: JSON.stringify({ session_id: sessionId, name, args: args || {} }) });
  // 开新一场面试：服务端清空上一场的轮次/计数器（前端不复算这些）
  const resetServerInterview = (body) => http(
    `/api/agent/session/${encodeURIComponent(sessionId)}/interview/start`,
    { method: "POST", body: JSON.stringify(body || {}) }
  );
  // 学生原话直接落库：模型那一路（log_interview_turn 带 answer）经常被跳过，
  // answered 不涨 → 轮次不前进、复盘少题。前端手里有原话，补这一道。
  const recordAnswer = (answer) => http(
    `/api/agent/session/${encodeURIComponent(sessionId)}/interview/answer`,
    { method: "POST", body: JSON.stringify({ answer }) }
  );
  // 会话重灌：服务端进程被回收/换实例后，简历与本场问答都不在了。
  // 关键步骤（生成复盘）之前灌一次，学生手里的数据就是兜底副本。
  const hydrate = (body) => http(
    `/api/agent/session/${encodeURIComponent(sessionId)}/hydrate`,
    { method: "POST", body: JSON.stringify(body || {}) }
  );

  /* ---------- 云端模型 ---------- */

  // 真打一次流式请求探活：拿到任意一个 chunk 就算通，超时没吐字节就判不可达。
  // 不许用「模型目录能列出」代替——那只证明网关的 models 路由可达。
  async function probe(ms = 12000) {
    const ctrl = new AbortController();
    let timer = null;
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => {
        ctrl.abort();   // 尽力取消，SDK 不认 signal 时靠下面这层兜住
        reject(new Error(`云端模型 ${Math.round(ms / 1000)} 秒内没有响应`));
      }, ms);
    });
    const firstChunk = (async () => {
      const stream = cloud.llm.chat.completions.create({
        model: modelId,
        messages: [{ role: "user", content: "ping" }],
        stream: true,
        temperature: 0,
        signal: ctrl.signal
      });
      for await (const _chunk of stream) return true;
      return false;
    })();
    try {
      // 只靠 signal 不够：SDK 若不透传 AbortSignal，for-await 会一直挂着，
      // 页面就永远停在「初始化中」。这里用竞速硬兜一个上限。
      const got = await Promise.race([firstChunk, deadline]);
      if (!got) throw new Error(`云端模型 ${Math.round(ms / 1000)} 秒内没有响应`);
    } finally {
      clearTimeout(timer);
      firstChunk.catch(() => { /* 超时后才失败，属于预期 */ });
    }
  }

  async function init() {
    reason = "初始化中";
    try {
      if (!window.WorkBuddyCloud) throw new Error("云 SDK 未加载，检查 index.html 里的 SDK script 是否被拦截");
      const pub = window.APP_CONFIG || {};
      if (!pub.endpoint || !pub.publishableKey) throw new Error("缺 publicConfig：config.js 未生成或字段不全");
      cloud = window.WorkBuddyCloud.createWorkBuddyCloud({
        endpoint: pub.endpoint,
        oauthRelayBaseUrl: pub.oauthRelayBaseUrl,
        publishableKey: pub.publishableKey
      });
      // 先确认后端在线：否则循环跑到一半才发现工具断了，前端只会显示一句 Failed to fetch
      await http("/api/health");
      const models = await cloud.llm.models.list();
      const usable = (models || []).filter((m) => m.disabled !== true);
      if (!usable.length) throw new Error("模型目录为空：该应用还没有可用模型");
      // 显式声明支持工具调用的优先；网关没给这个字段时（undefined）不能直接判死，
      // 否则整条智能体链路会因为少一个可选字段而全线不可用。
      const declared = usable.filter((m) => m.supportsToolCall === true);
      const pool = declared.length ? declared : usable.filter((m) => m.supportsToolCall !== false);
      const picked = cfg().model
        ? (usable.find((m) => m.id === cfg().model) || pool[0])
        : pool[0];
      if (!picked) throw new Error("当前模型目录里没有支持工具调用的模型，智能体无法运行");
      modelId = picked.id;
      modelName = picked.name || picked.id;
      // models.list 能通，不代表 chat 能通：两者走的头与预检策略不同。
      // 之前就是这里静默失败，界面却一直显示「就绪」，等到诊断才暴露。
      try {
        await probe();
      } catch (first) {
        await new Promise(r => setTimeout(r, 1500));   // 网络抖动给一次机会，别一次失败就降级
        try { await probe(); } catch (_) { throw first; }
      }
      ready = true;
      reason = "就绪";
    } catch (err) {
      ready = false;
      const raw = err && err.message ? err.message : String(err);
      // Failed to fetch 是浏览器对预检失败的笼统说法，背后通常没有可用信息，
      // 这里补一句人话，免得测试时只能对着一句英文猜。
      reason = /failed to fetch|network ?error|load failed/i.test(raw)
        ? `浏览器无法直连云模型（跨源请求被拦：${raw}）`
        : raw;
    }
    window.dispatchEvent(new CustomEvent("coach-agent-status", { detail: { ready, reason, model: modelName } }));
    return { ready, reason, model: modelName };
  }

  /* ---------- 流式调用（工具调用分片按 index 归并） ---------- */

  // 网关 5xx / 网络抖动是偶发的：还没吐出任何内容时重试，吐过就不能重试（会重复文本）
  const NONRETRY = /auth_|quota_|invalid|request_stream_required|\b(400|401|403|404)\b/i;

  function errText(err) {
    if (!err) return "未知错误";
    // 网关有时把结构化错误塞在 err.error 里，直接 String() 会变成 [object Object]
    const flat = (v) => {
      if (v == null) return "";
      if (typeof v === "string") return v.trim();
      if (typeof v === "object") return String(v.message || v.msg || v.detail || "").trim();
      return String(v).trim();
    };
    const parts = [err.message, err.code, err.type, err.error, err.status ? `HTTP ${err.status}` : ""]
      .map(flat)
      .filter((v, i, a) => v && a.indexOf(v) === i);
    return parts.length ? parts.join(" · ") : String(err);
  }

  async function streamChat(options) {
    const { onText } = options;
    let lastErr = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      let emitted = false;
      try {
        return await streamOnce(Object.assign({}, options, {
          onText: (t) => { emitted = true; if (onText) onText(t); }
        }));
      } catch (err) {
        lastErr = err;
        const msg = errText(err);
        const aborted = (abortCtrl && abortCtrl.signal && abortCtrl.signal.aborted) || /abort/i.test(msg);
        if (aborted || emitted || attempt === 2 || NONRETRY.test(msg)) throw err;
        await new Promise(r => setTimeout(r, 900 * (attempt + 1)));
      }
    }
    throw lastErr;
  }

  // 单次流式调用的「静默死线」：多久没有新 chunk 就判死。
  // 没有这道闸，网关半路不发 [DONE] 时 for-await 会永远挂着：
  // 调用方的 promise 不 settle，界面就停在「生成中」，用户只能刷新。
  const STALL_MS = () => cfg().stallMs || 30000;

  async function streamOnce({ messages, tools, onText }) {
    abortCtrl = new AbortController();
    const params = {
      model: modelId,
      messages,
      stream: true,
      temperature: cfg().temperature == null ? 0.2 : cfg().temperature,
      signal: abortCtrl.signal
    };
    if (canSendConversationId()) params.conversationId = conversationId;
    if (tools && tools.length) params.tools = tools;

    let content = "";
    const acc = new Map();

    // 静默看门狗：每收到一个 chunk 就重置。超时先 abort，再硬 reject 兜住
    // 「SDK 不认 signal」的情况。
    let idleTimer = null;
    let rejectStall = null;
    const stall = new Promise((_, reject) => { rejectStall = reject; });
    const arm = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        try { abortCtrl && abortCtrl.abort(); } catch (_) { /* 忽略 */ }
        if (rejectStall) rejectStall(new Error(`模型 ${Math.round(STALL_MS() / 1000)} 秒没有输出，已中断这一轮`));
      }, STALL_MS());
    };

    const consume = (async () => {
      arm();
      for await (const chunk of cloud.llm.chat.completions.create(params)) {
        arm();
        const choice = chunk.choices && chunk.choices[0];
        if (!choice) continue;
        const delta = choice.delta || {};
        if (delta.content) {
          content += delta.content;
          if (onText) onText(delta.content);
        }
        if (delta.tool_calls) {
          for (const frag of delta.tool_calls) {
            const cur = acc.get(frag.index) || { id: "", type: "function", function: { name: "", arguments: "" } };
            if (frag.id) cur.id = frag.id;
            if (frag.function && frag.function.name) cur.function.name = frag.function.name;
            if (frag.function && frag.function.arguments) cur.function.arguments += frag.function.arguments;
            acc.set(frag.index, cur);
          }
        }
      }
      return true;
    })();

    try {
      await Promise.race([consume, stall]);
    } finally {
      clearTimeout(idleTimer);
      // 竞速落败的那一路可能稍后才 reject：挂个空 catch，别变成 unhandled rejection
      consume.catch(() => { /* 已按超时处理 */ });
    }

    const toolCalls = [...acc.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([, v]) => v)
      .filter((t) => t.function.name);
    toolCalls.forEach((t) => { if (!t.id) t.id = "call_" + Math.random().toString(36).slice(2); });

    return { content, toolCalls };
  }

  /* ---------- 工具结果 → 界面事件 ---------- */

  function parseArgs(call) {
    try { return JSON.parse(call.function.arguments || "{}"); } catch (_) { return {}; }
  }

  function deriveEvents(name, args, payload, onEvent) {
    if (!payload || payload.ok === false) return;
    if (name === "score_career") {
      // 证据以服务端核验过的为准（quote 必须能在简历原文里逐字找到），
      // 模型自己写在参数里但核验不过的，不进界面。
      const verified = payload.evidence || null;
      onEvent({ type: "scores", scores: payload.scores, total: payload.total, level: payload.level, unstable: payload.unstable, evidence: verified || args.evidence || [] });
    }
    if (name === "build_fact_sheet") {
      onEvent({ type: "sheet", items: payload.items || [], top_gaps: payload.top_gaps || [], version: payload.sheet_version });
    }
    if (name === "log_interview_turn" && !String(args.answer || "").trim()) {
      onEvent({ type: "question", fact_id: args.fact_id, layer: args.layer, question: args.question, round_no: payload.round_no, rounds_planned: payload.rounds_planned, warned: (payload.warnings || []).length });
    }
    if (name === "save_report") {
      onEvent({ type: "report", report_id: payload.report_id, total: payload.total, level: payload.match_level });
    }
    if (name === "export_resume_docx") {
      onEvent({ type: "download", path: apiBase() + payload.download_path });
    }
    if (name === "validate_rewrite" && payload.ok === true && (payload.violations || []).length) {
      onEvent({ type: "violation", violations: payload.violations });
    }
  }

  /* ---------- 主循环 ---------- */

  // 诊断刚出清单、模型还在收尾时用户就点了面试：这里等上一轮结束再开始。
  // 直接报"上一轮还没结束"只会让界面显示"本轮没有拿到问题"，学生不知道发生了什么。
  async function runTask(options) {
    // 只等一次，并且带上限：原来这里是「循环 40 次 await 同一个 promise」，
    // 一旦那一轮的 promise 永不 settle（网关半路断流），这里就跟着死等，
    // 复盘的 promise 也不会 settle，界面永远停在「生成中」。
    if (busy && currentTask) {
      const pending = currentTask;
      const waitMs = cfg().waitMs || 45000;
      await Promise.race([
        pending.catch(() => { /* 上一轮失败不影响这一轮 */ }),
        new Promise(r => setTimeout(r, waitMs))
      ]);
    }
    if (busy) {
      try { options.onEvent && options.onEvent({ type: "error", message: "上一轮还没结束，请稍后重试" }); } catch (_) {}
      return null;
    }
    // 这里到 runTaskInner 置 busy 之间没有 await，是原子的：
    // 并发调用只可能有一个穿过上面那道门。检查若放在 runTaskInner 里，
    // 失败的那一路会把自己的空 promise 写进 currentTask，把真正在跑的那轮弄丢。
    const task = runTaskInner(options);
    currentTask = task;
    try {
      return await task;
    } finally {
      if (currentTask === task) currentTask = null;
    }
  }

  async function runTaskInner({ module, userText, onEvent, stopOn, prepareSession }) {
    const emit = (e) => {
      try { onEvent && onEvent(e); } catch (_) { /* 界面异常不打断循环 */ }
      try { if (stopOn && stopOn(e)) stopped = true; } catch (_) { /* 判定异常忽略 */ }
    };
    let stopped = false;

    if (!ready) { emit({ type: "error", message: reason || "云模型未就绪" }); return null; }

    busy = true;
    const toolTrace = [];
    try {
      const t0 = Date.now();
      const plan = prepareSession
        ? await prepare(Object.assign({ module }, prepareSession))
        : await manifest(module);
      emit({ type: "stage", stage: plan.stage, model: modelName, toolCount: plan.tools.length, prepared: plan.prepared || [], ms: Date.now() - t0 });

      const messages = [{ role: "system", content: plan.system }];
      history.slice(-8).forEach((m) => messages.push(m));
      messages.push({ role: "user", content: userText });

      const maxRounds = cfg().maxRounds || 6;
      for (let round = 0; round < maxRounds; round++) {
        let printed = false;
        const step = await streamChat({
          messages,
          tools: plan.tools,
          onText: (t) => { printed = true; emit({ type: "text", text: t }); }
        });

        if (!step.toolCalls.length) {
          messages.push({ role: "assistant", content: step.content });
          history.push({ role: "user", content: userText }, { role: "assistant", content: step.content });
          history = history.slice(-12);
          emit({ type: "done", content: step.content, rounds: round, tools: toolTrace });
          return step.content;
        }

        messages.push({ role: "assistant", content: step.content || "", tool_calls: step.toolCalls });

        for (const call of step.toolCalls) {
          const args = parseArgs(call);
          emit({ type: "tool", name: call.function.name, args });
          let payload;
          try {
            const res = await callTool(call.function.name, args);
            payload = res.result || res;
          } catch (err) {
            payload = { ok: false, error: err.message };
          }
          // 会话可能落在另一实例上（发布/扩容时会出现），表现为"还没有保存简历"。
          // 遇到就补一次预置再重放这次调用，别让模型自己去 save_resume 绕一圈。
          if (prepareSession && payload && payload.ok === false && /还没有保存简历/.test(String(payload.error || ""))) {
            try {
              await prepare(Object.assign({ module }, prepareSession));
              const retry = await callTool(call.function.name, args);
              payload = retry.result || retry;
            } catch (_) { /* 兜底失败就按原错误返回 */ }
          }
          toolTrace.push({ name: call.function.name, ok: payload.ok !== false, error: payload.error || "" });
          emit({ type: "toolResult", name: call.function.name, payload });
          deriveEvents(call.function.name, args, payload, emit);
          messages.push({ role: "tool", tool_call_id: call.id, content: JSON.stringify(payload) });
        }

        // 目标已达成（例如题目已经出好）就收工，不再让模型继续空转
        if (stopped) {
          // 早停轮同样要进历史：否则下一轮发回答时，模型看不到上一题问了什么，
          // 追问「你刚才说的那点」就接不上，只能靠服务端状态猜。
          const asked = step.toolCalls
            .map(parseArgs)
            .filter((a) => String(a.question || "").trim() && !String(a.answer || "").trim())
            .map((a) => String(a.question).trim());
          const said = [String(step.content || "").trim()].concat(asked).filter(Boolean).join("\n");
          history.push({ role: "user", content: userText }, { role: "assistant", content: said || "（已出题）" });
          history = history.slice(-12);
          emit({ type: "done", content: "", rounds: round, tools: toolTrace, stoppedEarly: true });
          return "";
        }
      }

      emit({ type: "done", content: "（本轮工具调用达到上限，请继续下一步）", rounds: maxRounds, tools: toolTrace });
      return null;
    } catch (err) {
      emit({ type: "error", message: errText(err) });
      return null;
    } finally {
      busy = false;
      abortCtrl = null;
    }
  }

  /* ---------- 三个业务入口 ---------- */

  function resumeSummary(resume) {
    return JSON.stringify(resume || {}, null, 0);
  }

  function diagnose({ resume, role, jd, onEvent }) {
    let scored = false;
    const track = (e) => {
      if (e && e.type === "scores") scored = true;
      try { onEvent && onEvent(e); } catch (_) { /* 界面异常不打断 */ }
    };
    const text = [
      "学生已完成结构化录入。服务端已经按这份 JSON 存档并锁定岗位（见会话状态），不必再调 save_resume / lock_jd。",
      `目标岗位：${role || (resume && resume.basic && resume.basic.target) || "未填写"}`,
      jd ? `岗位 JD：${jd}` : "岗位 JD：未提供（按岗位基线库处理）",
      "结构化简历 JSON：",
      resumeSummary(resume),
      "请直接执行：五维打分并给原文证据 → 提交 score_career → 建事实清单。"
    ].join("\n");
    return runTask({
      module: "diagnosis",
      userText: text,
      onEvent: track,
      prepareSession: { resume, target_role: role || "", jd_text: jd || "" }
    }).then((res) => {
      // 模型只说话不动手（例如跑去问学生补字段）时，补一次明确指令再收工。
      // 只补一次：第二次仍不打分就交给调用方走"诊断中断"的回落，避免死循环。
      if (scored || res === null) return res;
      return runTask({
        module: "diagnosis",
        userText: "继续执行诊断：直接调用 score_career 提交五维分。证据的 quote 要复制简历里本人写的整句"
          + "（不要用技能清单拼串或字段名），每个 ≤6 分的维度至少一条；拿到结果后再调用 build_fact_sheet。",
        onEvent: track
      });
    });
  }

  function interviewStart({ scene, role, rounds, onEvent }) {
    const text = `开始面试。场景：${scene}；岗位：${role}；计划 ${rounds} 轮。请按流程出第一题（只问一个问题，标注事实编号与层级）。`;
    // 先让服务端清掉上一场的轮次与计数器。少了这一步，同一会话里的第二场会接着
    // 上一场数下去：界面直接显示「第 6 / 5 轮」，第一题就被判 reached_limit。
    return resetServerInterview({ scene, role, rounds })
      .catch(() => null)   // 没有清单时服务端会拒，留给这一轮的诊断去处理
      .then(() => runTask({ module: "interview", userText: text, onEvent, stopOn: (e) => e.type === "question" }));
  }

  function interviewAnswer({ answer, onEvent }) {
    return runTask({ module: "interview", userText: `学生的回答：${answer}`, onEvent });
  }

  // 兜底：上一轮只点评没出题时，单独要一道题
  function interviewNext({ onEvent }) {
    return runTask({ module: "interview", userText: "现在出下一题：先调用 log_interview_turn（只传 fact_id / layer / question）拿到 ok，再把这道题写进正文；不要复述上一轮点评。", onEvent, stopOn: (e) => e.type === "question" });
  }

  function review({ onEvent }) {
    return runTask({ module: "review", userText: "本场结束，请生成复盘报告。", onEvent });
  }

  async function resetSession() {
    try { await http(`/api/agent/session/${encodeURIComponent(sessionId)}/reset`, { method: "POST" }); } catch (_) { /* 忽略 */ }
    history = [];
    conversationId = rand();
    localStorage.setItem(CONV_KEY, conversationId);
  }

  async function session() {
    return http(`/api/agent/session/${encodeURIComponent(sessionId)}`);
  }

  window.CoachAgent = {
    init,
    diagnose,
    prepare,          // 刷新后用幂等预置核对服务端状态（简历没变就不会重存）
    interviewStart,
    interviewAnswer,
    interviewNext,
    recordAnswer,
    hydrate,
    review,
    resetSession,
    session,
    callTool,
    abort: () => { if (abortCtrl) abortCtrl.abort(); },
    status: () => ({ ready, reason, model: modelName, sessionId, api: apiBase() }),
    get ready() { return ready; }
  };

  // 页面加载即自检，界面据此决定「智能体模式 / 本地演示模式」
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { init(); });
  } else {
    init();
  }
})();
