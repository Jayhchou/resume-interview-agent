(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const STORAGE_KEY = "offscript-demo-v1";

  const stories = {
    project: {
      title: "校园二手交易平台",
      type: "技术项目",
      subtitle: "独立负责下单模块",
      description: "从一次重复下单的 bug 讲起：怎么定位、怎么取舍，以及你真正改变了什么。",
      tags: ["技术取舍", "个人贡献", "结果证据"],
      heat: 82,
      questions: [
        { kind: "开场 · 讲清选择", text: "如果只能保留一个项目，你会留下哪一个？" },
        { kind: "细节 · 追问取舍", text: "你说自己负责下单模块，最难的一次技术取舍是什么？" },
        { kind: "挑战 · 证明价值", text: "如果我现在质疑这只是课程作业，你会拿哪件事证明它的价值？" }
      ],
      samples: [
        "我会留下校园二手交易平台。它虽然不大，但我独立负责了下单模块，也遇见过真实用户重复点击造成的重复订单。",
        "最难的是要不要引入复杂框架。最后我没有加新组件，而是用数据库唯一约束和幂等键解决问题，因为团队只有四个人，维护成本必须可控。",
        "我会拿上线后的记录来证明。我们把重复下单从每天十几次降到零，接口测试从 8 条补到 26 条，这些结果都能在项目日志里查到。"
      ]
    },
    growth: {
      title: "公众号增长实验",
      type: "运营经历",
      subtitle: "负责内容 A/B 测试",
      description: "别只说“提升了阅读量”。讲清你先改了哪个变量，以及一次失败的实验教会了你什么。",
      tags: ["实验设计", "数据判断", "失败复盘"],
      heat: 67,
      questions: [
        { kind: "开场 · 找到变量", text: "说一次你用很小改动换来明显结果的经历。" },
        { kind: "细节 · 验证方法", text: "你提到做过内容测试，怎么确定增长不是运气？" },
        { kind: "挑战 · 面对失败", text: "如果去掉预算和既有粉丝，你的方法还成立吗？" }
      ],
      samples: [
        "我最明显的一次改动，是只调整校园公众号的标题结构。两周内平均阅读量提升了 38%，预算没有增加。",
        "我按相近选题分成两组，每次只改标题，不改发布时间和封面。连续做了六轮，其中四轮新版本更高，所以才判断不是偶然。",
        "成立，但效果会慢一些。方法依赖的是选题和标题测试，不依赖预算；没有既有粉丝时，我会先通过社群获取前一百个样本。"
      ]
    },
    event: {
      title: "跨年活动救场",
      type: "团队协作",
      subtitle: "临时接替现场统筹",
      description: "设备失效、嘉宾迟到、流程被打乱。讲一个你必须立刻做决定、没有标准答案的现场。",
      tags: ["临场应变", "协作推进", "压力表达"],
      heat: 74,
      questions: [
        { kind: "开场 · 进入现场", text: "讲一次计划突然失效，你必须马上接住局面的时候。" },
        { kind: "细节 · 还原决定", text: "现场那么乱，你先做了什么，为什么没有先处理设备？" },
        { kind: "挑战 · 接受质疑", text: "如果嘉宾没有迟到，你的调整会不会反而打乱原计划？" }
      ],
      samples: [
        "跨年活动开场前二十分钟，主屏幕突然黑屏，嘉宾又临时迟到。我当时是执行组成员，但主动接住了现场顺序调整。",
        "我先让主持人和乐队确认可上场状态，再安排技术组修屏幕。因为观众已经坐满，最怕的是冷场，设备反而不是唯一要先解决的事。",
        "会有这个风险，所以我没有取消任何环节，只把乐队暖场提前，并把嘉宾分享压缩五分钟。这个调整即使嘉宾准时到，也不会破坏主流程。"
      ]
    }
  };

  const defaultRecords = [
    { date: "05", month: "11 月", title: "公众号增长实验", note: "数据讲清了，但结论出现了两次", score: 81 },
    { date: "03", month: "11 月", title: "跨年活动救场", note: "临场动作明确，少用“然后”", score: 76 },
    { date: "01", month: "11 月", title: "校园二手交易平台", note: "个人贡献比上次更具体", score: 73 }
  ];

  let selectedStory = "project";
  let intensity = "direct";
  let questionIndex = 0;
  let answers = [];
  let timeLeft = 60;
  let timer = null;
  let paused = false;
  let voiceActive = false;
  let submitting = false;
  let toastTimer = null;
  let history = [...defaultRecords];

  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved) {
      if (stories[saved.selectedStory]) selectedStory = saved.selectedStory;
      if (["gentle", "direct", "pressure"].includes(saved.intensity)) intensity = saved.intensity;
      if (Array.isArray(saved.history) && saved.history.length) history = [...saved.history, ...defaultRecords].slice(0, 5);
    }
  } catch (_) { /* 保持默认演示状态 */ }

  function icon(name) { return `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`; }
  function escapeHTML(value = "") { return String(value).replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]); }
  function savePreferences() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ selectedStory, intensity, history: history.slice(0, 2) })); } catch (_) { /* Demo 无需强制持久化 */ }
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    const toast = $("#toast");
    $("span", toast).textContent = message;
    toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; }, 2600);
  }

  function switchView(view) {
    ["lobby", "session", "result", "stories", "records"].forEach(name => { $(`#${name}View`).hidden = name !== view; });
    const navView = ["session", "result"].includes(view) ? "lobby" : view;
    $$('[data-nav]').forEach(button => button.classList.toggle("active", button.dataset.nav === navView));
    if (view === "stories") renderLibrary();
    if (view === "records") renderRecords();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function buildWave(element, text = "") {
    const length = text.length;
    const charSeed = length ? text.charCodeAt(length % text.length) : 19;
    element.innerHTML = Array.from({ length: 54 }, (_, index) => {
      const height = 12 + ((index * 29 + length * 11 + charSeed) % 76);
      const delay = ((index % 9) * -.09).toFixed(2);
      return `<span style="--h:${height}%;--d:${delay}s"></span>`;
    }).join("");
  }

  function renderLobby() {
    $$("[data-story]").forEach(button => button.classList.toggle("active", button.dataset.story === selectedStory));
    $$("[data-intensity]").forEach(button => button.classList.toggle("active", button.dataset.intensity === intensity));
    const story = stories[selectedStory];
    $("#consoleTitle").textContent = `“${story.questions[0].text}”`;
    buildWave($("#lobbyWave"), story.title);
  }

  function questionForCurrent() {
    const story = stories[selectedStory];
    if (questionIndex === 2 && intensity === "gentle") {
      return { kind: "挑战 · 温和复盘", text: "这段经历里，如果重来一次，你最想保留哪一个做法？" };
    }
    if (questionIndex === 2 && intensity === "pressure") {
      const pressure = {
        project: "如果这些结果主要来自团队，你凭什么把它写进自己的简历？",
        growth: "38% 的增长听起来不错，但你怎么证明这不是平台给你的流量？",
        event: "你所谓的救场，会不会只是把别人的工作揽成了自己的功劳？"
      };
      return { kind: "挑战 · 直接质疑", text: pressure[selectedStory] };
    }
    return story.questions[questionIndex];
  }

  function startSession() {
    clearInterval(timer);
    questionIndex = 0;
    answers = [];
    submitting = false;
    switchView("session");
    renderQuestion();
  }

  function renderQuestion() {
    clearInterval(timer);
    const story = stories[selectedStory];
    const question = questionForCurrent();
    $("#sessionStoryName").textContent = story.title;
    $("#questionCounter").textContent = `QUESTION 0${questionIndex + 1} / 03`;
    $("#questionKind").textContent = question.kind;
    $("#liveQuestion").textContent = question.text;
    $("#answerInput").value = "";
    $("#answerInput").disabled = false;
    $("#submitAnswer").disabled = false;
    $("#submitAnswer").innerHTML = `完成这一题${icon("arrow")}`;
    $("#instantFeedback").textContent = "";
    $("#wordCount").textContent = "0 字";
    $("#pressureRule").textContent = intensity === "gentle" ? "温和追问，允许停顿，不评价口音，不替你说标准答案。" : intensity === "pressure" ? "直接质疑贡献与数据，练习在被挑战时仍然说清事实。" : "直接追问，不评价口音，不替你说标准答案。";
    $$("#followTrack li").forEach((item, index) => {
      item.classList.toggle("active", index === questionIndex);
      item.classList.toggle("done", index < questionIndex);
    });
    voiceActive = false;
    $("#voiceButton").classList.remove("active");
    $("#voiceButton span").textContent = "模拟语音";
    $("#sessionWave").classList.remove("playing");
    buildWave($("#sessionWave"), question.text);
    updateAnalysis("");
    timeLeft = 60;
    paused = false;
    $("#pauseTimer span").textContent = "暂停";
    updateTimer();
    timer = setInterval(() => {
      if (paused) return;
      timeLeft = Math.max(0, timeLeft - 1);
      updateTimer();
      if (timeLeft === 0) {
        clearInterval(timer);
        $("#instantFeedback").textContent = "时间到。不用继续想完美答案，把已经说清的部分完成就好。";
      }
    }, 1000);
    $("#answerInput").focus();
  }

  function updateTimer() {
    $("#timerValue").textContent = String(timeLeft).padStart(2, "0");
    $("#timerLine").style.width = `${timeLeft / 60 * 100}%`;
    $(".answer-timer").classList.toggle("urgent", timeLeft <= 10);
  }

  function analysisFor(text) {
    const conclusion = text.length >= 12 && /我|最|关键|结果|选择|证明|成立|风险/.test(text.slice(0, 35));
    const personal = /我|本人|主动|负责/.test(text);
    const evidence = /\d|提升|降低|增长|减少|零|结果|记录|查到|验证|完成/.test(text);
    return { conclusion, personal, evidence };
  }

  function updateAnalysis(text) {
    const analysis = analysisFor(text);
    Object.entries(analysis).forEach(([key, hit]) => { $(`[data-check="${key}"]`).classList.toggle("hit", hit); });
    const hits = Object.values(analysis).filter(Boolean).length;
    $("#answerMeter").style.width = `${Math.min(100, hits * 28 + Math.min(16, text.length / 8))}%`;
    let hint = "先说一句明确结论，教练会在这里观察你的表达结构。";
    if (text && !analysis.conclusion) hint = "先别解释背景。第一句先告诉我：你的选择或结论是什么？";
    else if (!analysis.personal && text) hint = "现在更像团队介绍。补一句：你本人具体做了哪个动作？";
    else if (!analysis.evidence && text) hint = "过程已经清楚。最后补一个结果、数字或可验证的变化。";
    else if (text && hits === 3) hint = "这句有结论、有动作、有证据。保持这个顺序。";
    $("#analysisHint").textContent = hint;
    $("#wordCount").textContent = `${text.length} 字`;
    buildWave($("#sessionWave"), text || questionForCurrent().text);
  }

  function answerFeedback(text, index) {
    const analysis = analysisFor(text);
    if (!analysis.conclusion) return "你讲了背景，但结论还可以更早。下一题试着先用一句话回答，再展开。";
    if (!analysis.personal) return "团队过程有了，个人动作还不够。下一题多说一个“我做了什么”。";
    if (!analysis.evidence) return "动作说清了，但结果还停在感受层。下一题试着补一个可验证的变化。";
    return index === 2 ? "结论、动作和证据都接住了。这就是这次训练要保留的表达顺序。" : "结论和动作都接住了。下一题继续，把证据说得更具体。";
  }

  function submitAnswer() {
    const input = $("#answerInput");
    const text = input.value.trim();
    if (!text) {
      $("#instantFeedback").textContent = "先写下一句真实回答，再完成这一题。";
      input.focus();
      return;
    }
    if (submitting) return;
    submitting = true;
    clearInterval(timer);
    answers.push(text);
    $("#instantFeedback").textContent = answerFeedback(text, questionIndex);
    input.disabled = true;
    $("#submitAnswer").disabled = true;
    $("#submitAnswer").textContent = "正在整理表达…";
    setTimeout(() => {
      submitting = false;
      questionIndex += 1;
      if (questionIndex >= 3) showResult();
      else renderQuestion();
    }, 650);
  }

  function calculateResult() {
    const rows = answers.map(answer => analysisFor(answer));
    const average = key => Math.round(rows.reduce((sum, row) => sum + (row[key] ? 86 : 52), 0) / rows.length);
    const conclusion = average("conclusion");
    const personal = average("personal");
    const evidence = average("evidence");
    return { conclusion, personal, evidence, total: Math.round(conclusion * .3 + personal * .3 + evidence * .4) };
  }

  function showResult() {
    clearInterval(timer);
    const result = calculateResult();
    switchView("result");
    const story = stories[selectedStory];
    $("#resultStoryName").textContent = story.type;
    $("#xrayMainScore").textContent = result.total;
    $("#resultHeadline").textContent = result.evidence >= 75 ? "这次，结论和证据都接住了。" : "这次，结论先说清了。";
    const bars = [["结论先行", result.conclusion], ["个人动作", result.personal], ["结果证据", result.evidence]];
    $("#xrayBars").innerHTML = bars.map(([label, value]) => `<div class="xray-row"><span>${label}</span><div><i style="width:${value}%"></i></div><strong>${value}</strong></div>`).join("");
    buildWave($("#resultWave"), answers.join(""));
    $("#resultTranscript").innerHTML = answers.map((answer, index) => {
      const question = index === 2 && intensity !== "direct" ? (index === 2 ? questionForResult(index) : stories[selectedStory].questions[index]) : stories[selectedStory].questions[index];
      return `<article class="transcript-item ${index === 0 ? "open" : ""}"><button aria-expanded="${index === 0}"><span>0${index + 1}</span><div><strong>${escapeHTML(question.text)}</strong><p>${escapeHTML(answerFeedback(answer, index))}</p></div>${icon("chevron")}</button><div class="transcript-detail"><blockquote>${escapeHTML(answer)}</blockquote><p><strong>下一次这样改：</strong>${escapeHTML(answerFeedback(answer, index))}</p></div></article>`;
    }).join("");
    if (result.evidence < 75) {
      $("#nextRepTitle").textContent = "把结果，放到过程前面。";
      $("#nextRepCopy").textContent = "你讲了过程，但“为什么值得做”出现得太晚。下一次先用一句话说结果，再回头解释。";
    } else if (result.personal < 75) {
      $("#nextRepTitle").textContent = "把“我们”，换成一个具体的“我”。";
      $("#nextRepCopy").textContent = "团队协作已经讲清楚。下一次只补一件事：哪一个关键动作由你亲自完成？";
    } else {
      $("#nextRepTitle").textContent = "同样的事实，再快 10 秒。";
      $("#nextRepCopy").textContent = "结构已经完整。下一次不换素材，只压缩背景，让结论和证据更早出现。";
    }
    $("#nextExample").textContent = `“${stories[selectedStory].samples[2]}”`;
    const record = { date: "06", month: "11 月", title: story.title, note: result.evidence >= 75 ? "结论与证据均已接住" : "下次先把结果放在前面", score: result.total };
    history = [record, ...history.filter(item => item.title !== record.title)].slice(0, 5);
    savePreferences();
  }

  function questionForResult(index) {
    const originalIndex = questionIndex;
    questionIndex = index;
    const question = questionForCurrent();
    questionIndex = originalIndex;
    return question;
  }

  function renderLibrary() {
    $("#storyLibrary").innerHTML = Object.entries(stories).map(([id, story], index) => `<article class="library-card"><div class="library-card-top"><span>STORY 0${index + 1}</span><small>${story.type}</small></div><h2>${story.title}</h2><p>${story.description}</p><div class="library-tags">${story.tags.map(tag => `<span>${tag}</span>`).join("")}</div><div class="heat-meter"><div><span>可被追问的细节密度</span><strong>${story.heat}</strong></div><span><i style="width:${story.heat}%"></i></span></div><button data-story-start="${id}">用这段开练${icon("arrow-up")}</button></article>`).join("");
  }

  function renderRecords() {
    $("#recordList").innerHTML = history.map(item => `<article class="record-item"><div class="record-date"><strong>${item.date}</strong><span>${item.month}</span></div><div><h3>${escapeHTML(item.title)}</h3><p>${escapeHTML(item.note)}</p></div><div class="record-result"><strong>${item.score}</strong><span>完整度</span></div></article>`).join("");
  }

  function exportResult() {
    const story = stories[selectedStory];
    const result = calculateResult();
    const lines = ["# 不背稿 OFFSCRIPT · 训练卡", "", `- 素材：${story.title}`, `- 追问强度：${intensity}`, `- 表达完整度：${result.total}`, `- 结论先行：${result.conclusion}`, `- 个人动作：${result.personal}`, `- 结果证据：${result.evidence}`, "", "## 三问三答", ""];
    answers.forEach((answer, index) => {
      const question = index === 2 ? questionForResult(index) : story.questions[index];
      lines.push(`### Q${index + 1} ${question.text}`, "", answer, "", `反馈：${answerFeedback(answer, index)}`, "");
    });
    lines.push("## 下一次只练一个动作", "", $("#nextRepTitle").textContent, "", $("#nextRepCopy").textContent);
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `OFFSCRIPT_${story.title}_训练卡.md`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast("训练卡已保存为 Markdown");
  }

  function bindEvents() {
    $$('[data-nav]').forEach(button => button.addEventListener("click", () => {
      clearInterval(timer);
      switchView(button.dataset.nav);
      if (button.dataset.nav === "lobby") renderLobby();
    }));
    $$('[data-story]').forEach(button => button.addEventListener("click", () => {
      selectedStory = button.dataset.story;
      savePreferences();
      renderLobby();
    }));
    $$('[data-intensity]').forEach(button => button.addEventListener("click", () => {
      intensity = button.dataset.intensity;
      savePreferences();
      renderLobby();
    }));
    $("#storyLibrary").addEventListener("click", event => {
      const button = event.target.closest("[data-story-start]");
      if (!button) return;
      selectedStory = button.dataset.storyStart;
      savePreferences();
      renderLobby();
      startSession();
    });
    $("#startSession").addEventListener("click", startSession);
    $("#quitSession").addEventListener("click", () => { clearInterval(timer); switchView("lobby"); renderLobby(); });
    $("#pauseTimer").addEventListener("click", () => {
      paused = !paused;
      $("#pauseTimer span").textContent = paused ? "继续" : "暂停";
      $("#instantFeedback").textContent = paused ? "计时已暂停。准备好后继续。" : "";
    });
    $("#answerInput").addEventListener("input", event => updateAnalysis(event.target.value));
    $("#sampleAnswer").addEventListener("click", () => {
      const input = $("#answerInput");
      input.value = stories[selectedStory].samples[questionIndex];
      updateAnalysis(input.value);
      input.focus();
      showToast("示例已填入，可以改成你自己的话");
    });
    $("#voiceButton").addEventListener("click", () => {
      voiceActive = !voiceActive;
      $("#voiceButton").classList.toggle("active", voiceActive);
      $("#voiceButton span").textContent = voiceActive ? "完成语音" : "模拟语音";
      $("#sessionWave").classList.toggle("playing", voiceActive);
      if (!voiceActive) {
        if (!$("#answerInput").value.trim()) {
          $("#answerInput").value = stories[selectedStory].samples[questionIndex];
          updateAnalysis($("#answerInput").value);
        }
        showToast("模拟语音已转成文字（未调用真实麦克风）");
      }
    });
    $("#submitAnswer").addEventListener("click", submitAnswer);
    $("#answerInput").addEventListener("keydown", event => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitAnswer();
    });
    $("#resultTranscript").addEventListener("click", event => {
      const button = event.target.closest(".transcript-item > button");
      if (!button) return;
      const item = button.parentElement;
      item.classList.toggle("open");
      button.setAttribute("aria-expanded", item.classList.contains("open"));
    });
    $("#trainAgain").addEventListener("click", startSession);
    $("#backLobby").addEventListener("click", () => { switchView("lobby"); renderLobby(); });
    $("#exportResult").addEventListener("click", exportResult);
  }

  function init() {
    buildWave($("#lobbyWave"), "OFFSCRIPT");
    buildWave($("#sessionWave"), "ANSWER");
    buildWave($("#resultWave"), "RESULT");
    renderLobby();
    renderLibrary();
    renderRecords();
    bindEvents();
    switchView("lobby");
  }

  init();
})();
