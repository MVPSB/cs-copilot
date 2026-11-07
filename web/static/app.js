/* 客服副驾工作台：登录、生成、采纳/修改/无用、计时、反馈 */
const $ = (id) => document.getElementById(id);
const api = {
  token: sessionStorage.getItem("token") || "",
  agent: JSON.parse(sessionStorage.getItem("agent") || "null"),
};

const state = {
  conversationId: null,
  replyOriginal: "",
  startedAt: null,
  timer: null,
  resultDone: false,
  reasons: new Set(),
};

/* ---------- 通用 ---------- */
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 1800);
}

async function request(path, body, method = "POST") {
  const res = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(api.token ? { Authorization: `Bearer ${api.token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const msg = typeof detail === "string" ? detail : detail?.message || `请求失败（${res.status}）`;
    const err = new Error(msg);
    err.status = res.status;
    err.conversationId = detail?.conversation_id;
    throw err;
  }
  return data;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------- 登录 ---------- */
function showApp() {
  $("login-view").classList.add("hidden");
  $("app-view").classList.remove("hidden");
  $("who").textContent = `${api.agent.agent_id} ${api.agent.name}`;
  $("avatar").textContent = api.agent.name.slice(0, 1);
  const mode = localStorage.getItem("mode") || "veteran";
  setMode(mode);
}

function logout() {
  api.token = "";
  api.agent = null;
  sessionStorage.clear();
  location.reload();
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("login-error");
  const btn = $("login-btn");
  err.classList.add("hidden");
  btn.disabled = true;
  btn.textContent = "登录中…";
  try {
    const data = await request("/api/login", {
      agent_id: $("agent-id").value.trim(),
      password: $("password").value,
    });
    api.token = data.token;
    api.agent = data;
    sessionStorage.setItem("token", data.token);
    sessionStorage.setItem("agent", JSON.stringify(data));
    syncWeeklyLink();
    showApp();
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove("hidden");
    $("agent-id").classList.add("invalid");
    $("password").classList.add("invalid");
  } finally {
    btn.disabled = false;
    btn.textContent = "登录";
  }
});

$("logout-btn").addEventListener("click", logout);

/* ---------- 模式 ---------- */
function setMode(level) {
  document.querySelectorAll("#mode button").forEach((b) => {
    b.classList.toggle("active", b.dataset.level === level);
  });
  $("mode-hint").textContent = level === "new" ? "新人模式 · 显示判断依据" : "老人模式 · 精简信息，快速采用";
  localStorage.setItem("mode", level);
}

document.querySelectorAll("#mode button").forEach((b) => {
  b.addEventListener("click", () => setMode(b.dataset.level));
});

/* ---------- 计时 ---------- */
function startTimer() {
  if (state.startedAt) return;
  state.startedAt = new Date();
  state.timer = setInterval(() => {
    $("aht-display").textContent = `${elapsed()}s`;
    $("status-aht").textContent = `本次 ${elapsed()}s`;
  }, 1000);
}

function elapsed() {
  return state.startedAt ? Math.max(0, Math.round((Date.now() - state.startedAt) / 1000)) : 0;
}

function stopTimer() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

/* ---------- 输入 ---------- */
const buyer = $("buyer-message");
buyer.addEventListener("focus", startTimer);
buyer.addEventListener("input", () => {
  $("char-count").textContent = buyer.value.length;
  $("generate-btn").disabled = !buyer.value.trim();
});
$("generate-btn").disabled = true;

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    if (!$("generate-btn").disabled) generate();
  }
});

/* ---------- 生成 ---------- */
async function generate() {
  const text = buyer.value.trim();
  if (!text) return;
  startTimer();
  stopTimer();

  $("generate-btn").disabled = true;
  $("generate-btn").textContent = "生成中…";
  $("center-hint").textContent = "正在整理答案";
  $("status-model").textContent = "生成中";
  $("result-area").innerHTML = skeleton();
  document.querySelector(".left").style.opacity = "0.48";
  $("result-area").classList.remove("has-result");

  try {
    const data = await request("/api/ask", {
      buyer_message: text,
      order_no: $("order-no").value.trim(),
      agent_level: document.querySelector("#mode button.active").dataset.level,
      scene_hint: $("scene").value,
      started_at: state.startedAt.toISOString(),
    });
    state.conversationId = data.conversation_id;
    state.replyOriginal = data.reply;
    state.resultDone = true;
    renderResult(data);
    addLog("建议已生成", `模型耗时 ${(data.latency_ms / 1000).toFixed(1)}s`);
  } catch (ex) {
    renderError(ex);
    addLog("生成失败", ex.message.slice(0, 40));
  } finally {
    $("generate-btn").disabled = false;
    $("generate-btn").textContent = "生成建议";
    document.querySelector(".left").style.opacity = "1";
  }
}

$("generate-btn").addEventListener("click", generate);

function skeleton() {
  return `
    <div class="status-row"><span>正在生成建议…</span></div>
    <div class="skeleton-card">
      <div class="skeleton-line" style="width: 51%"></div>
      <div class="skeleton-line" style="width: 45%"></div>
      <div class="skeleton-line" style="width: 36%"></div>
    </div>
    <div class="hint">生成完成后，可直接编辑或复制回复。</div>`;
}

let live = null;

function renderResult(data) {
  live = data;
  $("center-hint").textContent = "基于知识库";
  $("status-model").textContent = `${(data.latency_ms / 1000).toFixed(1)}s`;
  const evidence = (data.evidence || [])
    .map(
      (e) => `<div class="evidence-item"><span class="dot">▤</span><span>${escapeHtml(e)}</span></div>`
    )
    .join("");
  const escalate = data.escalate
    ? '<span class="tag danger">转主管</span>'
    : '<span class="tag muted">无需转主管</span>';
  const newcomer =
    document.querySelector("#mode button.active").dataset.level === "new" && data.explanation
      ? `<div class="notice"><b>为什么这么说：</b>${escapeHtml(data.explanation)}</div>`
      : "";

  $("result-area").innerHTML = `
    <div class="status-row">
      <span>已生成 · ${(data.latency_ms / 1000).toFixed(1)}s</span>
      <span class="spacer"></span>
      <span class="tag warn hidden" id="edited-tag">已修改</span>
    </div>
    <div class="field">
      <div class="section-head"><span class="title">建议回复</span><span class="hint">可直接修改</span></div>
      <textarea id="reply-editor">${escapeHtml(data.reply)}</textarea>
      <div class="ta-foot"><span>可拖至 8 行</span><span><span id="reply-count">${data.reply.length}</span> 字</span></div>
    </div>
    <div class="field">
      <span class="label">依据</span>
      <div class="evidence">${evidence || '<div class="hint">本次没有召回到知识库依据</div>'}</div>
    </div>
    ${newcomer}
    <div class="actions">
      <span class="tag ok">${escapeHtml(data.next_action)}</span>
      ${escalate}
    </div>
    <div class="field">
      <div class="actions">
        <button class="btn-primary" id="copy-btn" style="width:128px">复制</button>
        <button class="btn-secondary" id="save-btn" disabled>保存修改</button>
        <button class="btn-ghost" id="useless-btn-card">标记无用</button>
      </div>
      <span class="hint" id="action-hint">复制后计入采用；标记无用将记录原因。</span>
    </div>`;

  const editor = $("reply-editor");
  editor.addEventListener("input", () => {
    $("reply-count").textContent = editor.value.length;
    const dirty = editor.value !== state.replyOriginal;
    $("edited-tag").classList.toggle("hidden", !dirty);
    $("save-btn").disabled = !dirty;
    editor.classList.toggle("edited", dirty);
    $("action-hint").textContent = dirty
      ? "有未保存的修改，保存后计入修改采用。"
      : "复制后计入采用；标记无用将记录原因。";
  });

  $("copy-btn").addEventListener("click", () => submitResult("copied", editor.value, ""));
  $("save-btn").addEventListener("click", () =>
    submitResult("modified", editor.value, $("feedback-note").value.trim())
  );
  $("useless-btn-card").addEventListener("click", openPopover);
  $("result-area").classList.add("has-result");
}

function renderError(ex) {
  $("center-hint").textContent = "本次请求未完成";
  $("status-model").textContent = "—";
  $("result-area").innerHTML = `
    <div class="error-card">
      <div class="error-head">
        <div class="error-badge">!</div>
        <div class="error-title">生成失败</div>
      </div>
      <div class="hint">${escapeHtml(ex.message)}</div>
      <div class="actions">
        <button class="btn-primary" id="retry-btn" style="width:112px">重试</button>
        <button class="btn-secondary" id="manual-btn">手动回复</button>
      </div>
      <textarea id="manual-editor" class="hidden" placeholder="手动写回复，提交后记为修改采用"></textarea>
    </div>`;
  $("retry-btn").addEventListener("click", generate);
  $("manual-btn").addEventListener("click", () => $("manual-editor").classList.remove("hidden"));
}

/* ---------- 结果提交 ---------- */
async function submitResult(status, finalText, note) {
  if (!state.conversationId) return;
  const endedAt = new Date().toISOString();
  try {
    const data = await request("/api/result", {
      conversation_id: state.conversationId,
      status,
      final_text: finalText || "",
      note: note || "",
      ended_at: endedAt,
    });
    setSessionTag(status);
    state.finished = true;
    stopTimer();
    if (status === "copied") {
      try {
        await navigator.clipboard.writeText(finalText);
      } catch (_) {
        toast("已记录采纳，请手动复制");
      }
      toast("已复制，可粘贴到会话");
      addLog("已复制采用", `处理时长 ${data.aht_seconds ?? elapsed()}s`);
    } else if (status === "modified") {
      $("edited-tag")?.classList.add("hidden");
      $("save-btn").disabled = true;
      toast("已保存修改，计入修改采用");
      addLog("已修改保存", `编辑距离 ${data.edit_distance} 字`);
    } else {
      toast("已标记无用，原因已记录");
      addLog("标记无用", note || "未填备注");
    }
  } catch (ex) {
    toast(ex.message);
  }
}

function setSessionTag(status) {
  const tag = $("session-tag");
  const map = {
    copied: ["已采用", "tag ok"],
    modified: ["已修改采用", "tag ok"],
    useless: ["已标记无用", "tag muted"],
  };
  const [text, cls] = map[status] || ["待采用", "tag muted"];
  tag.className = cls;
  tag.textContent = text;
}

/* ---------- 反馈浮层 ---------- */
function openPopover() {
  state.reasons.clear();
  document.querySelectorAll("#reason-chips .chip").forEach((c) => c.classList.remove("on"));
  $("useless-note").value = "";
  $("popover").classList.remove("hidden");
  addLog("正在填写反馈", "确认后记录无用原因");
}

document.querySelectorAll("#reason-chips .chip").forEach((c) => {
  c.addEventListener("click", () => {
    const r = c.dataset.reason;
    if (state.reasons.has(r)) {
      state.reasons.delete(r);
      c.classList.remove("on");
    } else {
      state.reasons.add(r);
      c.classList.add("on");
    }
  });
});

$("popover-close").addEventListener("click", () => $("popover").classList.add("hidden"));
$("popover-cancel").addEventListener("click", () => $("popover").classList.add("hidden"));
$("popover-confirm").addEventListener("click", async () => {
  if (!state.conversationId) return;
  if (state.reasons.size === 0 && !$("useless-note").value.trim()) {
    toast("请至少选一个原因");
    return;
  }
  const note = [...state.reasons].join("、") + ($("useless-note").value.trim() ? "：" + $("useless-note").value.trim() : "");
  $("popover").classList.add("hidden");
  await submitResult("useless", "", note);
});

/* ---------- 状态栏反馈 ---------- */
$("useful-btn").addEventListener("click", () => sendFeedback(true));
$("useless-btn").addEventListener("click", () => sendFeedback(false));

async function sendFeedback(useful) {
  if (!state.conversationId) return toast("先生成一条建议");
  try {
    await request("/api/feedback", {
      conversation_id: state.conversationId,
      useful,
      note: $("feedback-note").value.trim(),
    });
    $("useful-btn").style.color = useful ? "var(--primary)" : "";
    $("useless-btn").style.color = useful ? "" : "var(--danger)";
    toast(useful ? "已记为有用" : "已记为没用");
  } catch (ex) {
    toast(ex.message);
  }
}

/* ---------- 操作记录 ---------- */
function addLog(title, detail) {
  const box = $("log");
  const empty = box.querySelector(".log-item .t")?.textContent === "· 尚无操作";
  if (empty) box.innerHTML = "";
  const div = document.createElement("div");
  div.className = "log-item";
  div.innerHTML = `<div class="t">· ${escapeHtml(title)}</div><div class="d">${escapeHtml(detail)}</div>`;
  box.appendChild(div);
}

/* ---------- 启动 ---------- */
function syncWeeklyLink() {
  const link = $("weekly-link");
  if (link) link.href = "/static/dashboard.html#t=" + encodeURIComponent(api.token || "");
}

if (api.token && api.agent) {
  syncWeeklyLink();
  showApp();
}


/* ---------- 关闭/切走页面时兜底记 abandoned ---------- */
window.addEventListener("pagehide", () => {
  if (!state.conversationId || !state.token || state.finished) return;
  const payload = { token: state.token, conversation_id: state.conversationId, status: "abandoned" };
  try {
    navigator.sendBeacon("/api/beacon", new Blob([JSON.stringify(payload)], { type: "application/json" }));
  } catch (_) {}
});
