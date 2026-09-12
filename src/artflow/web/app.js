const appState = {
  asset: null, assetId: null, token: "", selectedStep: null, previewId: null,
  plan: null, selectedRun: null, selectedAction: null, poll: null, loadVersion: 0,
  preview: { scale: 1, x: 0, y: 0, pointer: null, background: "white" },
};
const $ = (selector) => document.querySelector(selector);
const statusLabel = (state) => ({
  not_run: "未运行", queued: "排队中", running: "运行中", passed: "通过",
  succeeded: "完成", verified: "已验证", failed: "失败", stale: "已过期",
  interrupted: "已中断", cancelled: "已取消",
}[state] || state);
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
const artifactUrl = (id, aid=appState.assetId) => "/artifact/" + encodeURIComponent(aid) + "/" + encodeURIComponent(id);
const apiAsset = () => "/api/assets/" + encodeURIComponent(appState.assetId);
async function api(path, payload) {
  const response = await fetch(path, payload === undefined ? {cache: "no-store"} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Artflow-Token": appState.token},
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败：" + response.status);
  return data;
}
function errorMessage(error) { $("#resultLead").textContent = error.message; }
function safe(action) { return (...args) => Promise.resolve().then(() => action(...args)).catch(errorMessage); }
function isImageArtifact(artifact) {
  return artifact.kind === "image" || /\.(png|jpe?g|gif|webp|svg)$/i.test(artifact.path);
}
function showArtifact(id, reset=true) {
  const artifact = appState.asset.artifacts.find(a => a.id === id);
  if (!artifact || !artifact.exists) return;
  appState.previewId = id;
  $("#previewTitle").textContent = artifact.label;
  $("#previewCaption").textContent = artifact.path + " · SHA-256 " + artifact.sha256.slice(0,12);
  const url = artifactUrl(id) + "?v=" + artifact.sha256;
  const isImage = isImageArtifact(artifact);
  $("#previewViewport").hidden = !isImage;
  $("#otherPreview").hidden = isImage;
  $("#otherPreview").replaceChildren();
  if (isImage) {
    $("#previewImage").src = url;
    $("#previewImage").alt = artifact.label;
    if (reset) fitPreview();
  } else if (["audio", "video"].includes(artifact.kind)) {
    const media = node(artifact.kind);
    media.controls = true; media.src = url;
    $("#otherPreview").append(media);
  } else if (artifact.kind === "json" || /\.(json|md|txt|log)$/i.test(artifact.path)) {
    const pre = node("pre", "读取中…");
    $("#otherPreview").append(pre);
    fetch(url).then(response => response.text()).then(text => {
      if (appState.previewId === id) pre.textContent = text.slice(0, 65536);
    }).catch(error => { pre.textContent = error.message; });
  } else {
    const link = node("a", "下载 / 打开 " + artifact.label);
    link.href = url; link.target = "_blank"; link.rel = "noreferrer";
    $("#otherPreview").append(link);
  }
  document.querySelectorAll("[data-artifact-tab]").forEach(b => {
    const selected = b.dataset.artifactTab === id;
    b.classList.toggle("is-active", selected);
    b.setAttribute("aria-selected", String(selected));
  });
}
function artifactLink(aid) {
  const artifact = appState.asset.artifacts.find(a => a.id === aid);
  if (!artifact) return null;
  const button = node("button", artifact.label + (artifact.exists ? "" : "（尚未生成）"), "plain-button");
  button.disabled = !artifact.exists;
  button.addEventListener("click", () => showArtifact(aid));
  return button;
}
function renderStepOutputs(step, area) {
  const outputIds = step.outputs || [];
  if (!outputIds.length && step.kind === "read") return;
  const section = node("section", undefined, "step-output-section");
  section.append(node("p", outputIds.length ? "本步骤产物" : "运行结果", "step-output-title"));
  if (!outputIds.length) {
    section.append(node("p", "本步骤不生成独立文件，执行详情记录在下方运行报告中。", "step-output-empty"));
    area.append(section);
    return;
  }
  const grid = node("div", undefined, "step-output-grid");
  for (const aid of outputIds) {
    const artifact = appState.asset.artifacts.find(a => a.id === aid);
    if (!artifact) continue;
    const card = node("button", undefined, "step-output-card");
    card.type = "button";
    card.disabled = !artifact.exists;
    card.dataset.outputArtifact = aid;
    if (isImageArtifact(artifact) && artifact.exists) {
      const image = node("img");
      image.src = artifactUrl(aid) + "?v=" + artifact.sha256;
      image.alt = "";
      image.loading = "lazy";
      card.append(image);
    }
    const copy = node("span", undefined, "step-output-copy");
    copy.append(node("strong", artifact.label), node("small", artifact.exists ? "点击在预览区查看" : "尚未生成"));
    card.append(copy);
    if (artifact.exists) card.addEventListener("click", () => showArtifact(aid));
    grid.append(card);
  }
  section.append(grid);
  area.append(section);
}
function actionForStep(stepId) {
  const matches = Object.entries(appState.asset.pipeline.actions)
    .filter(([, action]) => action.steps.includes(stepId));
  return matches.find(([, action]) => action.steps.length === 1) || matches[0] || null;
}
function renderActionForStep(step, state) {
  const related = actionForStep(step.id);
  if (!related) {
    appState.selectedAction = null;
    $("#actionLabel").textContent = step.kind === "read" ? "查看与确认" : "无需执行";
    $("#actionDescription").textContent = step.kind === "read"
      ? "这是只读阶段，用于确认已有输入，不会启动制作命令。"
      : "这个步骤没有配置可执行操作。";
    $("#runActionButton").textContent = "本步骤无需执行";
    $("#runActionButton").disabled = true;
    return;
  }
  const [id, action] = related;
  appState.selectedAction = id;
  $("#actionLabel").textContent = action.label;
  $("#actionDescription").textContent = action.description || "按项目配置执行本步骤。";
  $("#runActionButton").textContent = ["passed", "succeeded", "verified"].includes(state)
    ? "重新执行“" + action.label + "”" : "查看“" + action.label + "”计划";
  $("#runActionButton").disabled = false;
}
function renderStep(id) {
  const step = appState.asset.pipeline.steps.find(s => s.id === id) || appState.asset.pipeline.steps[0];
  appState.selectedStep = step.id;
  const state = appState.asset.step_states[step.id] || "not_run";
  const area = $("#stepDetail"); area.replaceChildren();
  const heading = node("div", undefined, "step-detail-heading");
  heading.append(node("h3", step.label), node("span", statusLabel(state), "step-state step-state-" + state));
  area.append(heading);
  area.append(node("p", step.description || (step.kind === "read" ? "记录已有输入版本。" : "按项目配置执行制作工具。")));
  const inputs = step.inputs || [];
  if (inputs.length) {
    const group = node("div", "输入：", "step-artifacts");
    for (const aid of inputs) {
      const button = artifactLink(aid);
      if (button) group.append(button);
    }
    area.append(group);
  }
  renderStepOutputs(step, area);
  document.querySelectorAll("[data-step-id]").forEach(button => {
    const selected = button.dataset.stepId === step.id;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-current", selected ? "step" : "false");
  });
  renderActionForStep(step, state);
  document.querySelector(`[data-step-id="${CSS.escape(step.id)}"]`)?.scrollIntoView({block: "nearest", inline: "nearest"});
}
function renderRuns(runs) {
  const selected = appState.selectedRun;
  $("#runSelect").replaceChildren(...runs.map(r => {
    const opt = node("option", (r.legacy ? "旧记录 · " : "") + statusLabel(r.status) + " · " + r.operation + " · " + r.started_at);
    opt.value = r.run_id; return opt;
  }));
  const run = runs.find(r => r.run_id === selected) || runs[0];
  if (!run) return;
  appState.selectedRun = run.run_id; $("#runSelect").value = run.run_id;
  $("#cancelRun").hidden = !["queued", "running"].includes(run.status);
  $("#resultBadge").textContent = statusLabel(run.status);
  $("#resultBadge").className = "summary-badge summary-badge-" + run.status;
  $("#resultLead").textContent = statusLabel(run.status) + (run.message ? " · " + run.message : "");
  $("#resultOutput").textContent = (run.steps || []).map(s => [
    s.label || s.id, statusLabel(s.status), s.stdout, s.stderr,
    s.report ? JSON.stringify(s.report, null, 2) : "",
  ].filter(Boolean).join("\n")).join("\n\n") || JSON.stringify(run, null, 2);
}
async function loadAsset(id=appState.assetId) {
  const version = ++appState.loadVersion;
  const data = await api("/api/assets/" + encodeURIComponent(id));
  if (version !== appState.loadVersion) return;
  const switched = appState.assetId !== id;
  appState.assetId = id; appState.asset = data;
  if (switched) { appState.previewId = null; appState.selectedStep = null; appState.selectedRun = null; appState.selectedAction = null; }
  $("#assetTitle").textContent = data.asset.label;
  $("#assetKind").textContent = data.asset.kind;
  $("#breadcrumbs").textContent = data.project.label + " / " + data.asset.label;
  $("#publishedState").textContent = "已发布版本：" + statusLabel(data.published_state);
  document.querySelectorAll("[data-asset-id]").forEach(b => b.classList.toggle("is-selected", b.dataset.assetId === id));
  $("#metadata").replaceChildren(...Object.entries(data.asset.metadata).flatMap(([key,value]) => [
    node("dt", key), node("dd", typeof value === "object" ? JSON.stringify(value) : String(value)),
  ]));
  $("#artifactList").replaceChildren(...data.artifacts.map(a => {
    const row = node("article", undefined, "artifact-row");
    const copy = node("div", undefined, "artifact-copy");
    copy.append(node("strong", a.label), node("span", a.path, "artifact-path"),
      node("span", a.exists ? a.sha256.slice(0,12) : "尚未生成", "artifact-hash"));
    const button = node("button", "查看", "plain-button"); button.disabled = !a.exists;
    button.addEventListener("click", () => showArtifact(a.id)); row.append(copy, button); return row;
  }));
  $("#artifactCount").textContent = data.artifacts.length;
  const previews = data.asset.preview.filter(id => data.artifacts.some(a => a.id === id && a.exists));
  $("#previewTabs").replaceChildren(...previews.map(id => {
    const a = data.artifacts.find(a => a.id === id);
    const button = node("button", a.label, "tab"); button.dataset.artifactTab=id;
    button.setAttribute("role", "tab");
    button.addEventListener("click", () => showArtifact(id)); return button;
  }));
  const chosen = appState.previewId && data.artifacts.some(a=>a.id===appState.previewId && a.exists)
    ? appState.previewId : previews[0];
  if (chosen) showArtifact(chosen, switched || chosen !== appState.previewId);
  else { $("#previewImage").removeAttribute("src"); $("#previewTitle").textContent="尚无可预览产物"; $("#previewCaption").textContent="执行制作步骤后在这里查看输出。"; }
  $("#pipelineTitle").textContent = data.pipeline.label;
  $("#pipelineCount").textContent = data.pipeline.steps.length + " 个步骤";
  $("#pipelineStatus").textContent = data.validation.ok ? "结构有效" : "配置有误";
  $("#pipelineSteps").replaceChildren(...data.pipeline.steps.map((step,index) => {
    const li = node("li", undefined, "pipeline-item"); const button = node("button", undefined, "pipeline-step");
    const state = data.step_states[step.id] || "not_run";
    li.classList.add("step-state-" + state);
    button.dataset.stepId = step.id;
    button.classList.add("step-state-" + state);
    button.setAttribute("aria-label", (index + 1) + " " + step.label + "，" + statusLabel(state));
    button.append(node("span", String(index+1), "step-number"),
      node("span", step.label, "step-name"), node("span", statusLabel(state), "step-kind"));
    button.addEventListener("click", () => renderStep(step.id)); li.append(button); return li;
  }));
  renderStep(appState.selectedStep);
  renderRuns(data.runs);
  clearTimeout(appState.poll);
  if (data.runs.some(r=>["queued","running"].includes(r.status))) {
    appState.poll = setTimeout(safe(() => loadAsset()), 800);
  }
}
async function prepareAction(action) {
  const aid = appState.assetId;
  const plan = await api(apiAsset() + "/actions/" + encodeURIComponent(action) + "/plan", {});
  if (aid !== appState.assetId) return;
  appState.plan = plan;
  $("#planTitle").textContent = plan.label;
  $("#planDescription").textContent = plan.description;
  $("#planSteps").replaceChildren(...plan.steps.map(s=>node("li",s.label)));
  $("#planInputs").replaceChildren(...plan.checkpoints.map(a => {
    const artifact = appState.asset.artifacts.find(item => item.id === a.id);
    const entry = node("div");
    const link = node("a", artifact.label + " · " + (a.sha256?.slice(0,12)||"缺失"), "candidate-version");
    if (a.sha256) { link.href=artifactUrl(a.id); link.target="_blank"; link.rel="noreferrer"; }
    entry.append(link);
    if (artifact.kind === "image" && plan.reviewed_artifacts.includes(a.id) && a.sha256) {
      const img = node("img"); img.src=artifactUrl(a.id)+"?v="+a.sha256; img.alt=artifact.label;
      img.className="approval-preview"; entry.append(img);
    }
    return entry;
  }));
  $("#planOutputs").replaceChildren(...plan.writes.map(a=>node("p",a.path,"candidate-version")));
  if (!plan.writes.length) $("#planOutputs").textContent="本次不声明文件输出。";
  $("#planErrors").textContent=plan.errors.join("\n");
  $("#planJSON").textContent=JSON.stringify(plan,null,2);
  $("#confirmationLabel").hidden = !plan.requires_approval;
  $("#confirmation").hidden = !plan.requires_approval;
  $("#confirmationLabel").textContent="审阅输入后，输入 " + aid + " 确认当前版本";
  $("#confirmation").value=""; $("#confirmationError").textContent="";
  $("#submitPlan").disabled=!plan.ok;
  $("#planDialog").showModal();
}
$("#planForm").addEventListener("submit", async event => {
  event.preventDefault();
  const plan=appState.plan;
  $("#submitPlan").disabled=true;
  try {
    const run=await api("/api/assets/"+encodeURIComponent(plan.asset_id)+"/actions/"+encodeURIComponent(plan.action_id)+"/run",
      {token:plan.token,confirmation:$("#confirmation").value.trim()});
    appState.selectedRun=run.run_id; $("#planDialog").close(); await loadAsset();
  } catch(error) { $("#confirmationError").textContent=error.message; }
  finally { $("#submitPlan").disabled=!plan.ok; }
});
$("#closePlan").addEventListener("click",()=>$("#planDialog").close());
$("#refreshButton").addEventListener("click",safe(()=>loadAsset()));
$("#runActionButton").addEventListener("click", safe(() => {
  if (!appState.selectedAction) return;
  return prepareAction(appState.selectedAction);
}));
$("#runSelect").addEventListener("change",()=>{appState.selectedRun=$("#runSelect").value;renderRuns(appState.asset.runs);});
$("#cancelRun").addEventListener("click",safe(async()=>{await api("/api/runs/"+appState.selectedRun+"/cancel",{});await loadAsset();}));
$("#checkButton").addEventListener("click",safe(async()=>{
  const result=await api("/api/check");
  $("#resultLead").textContent=result.ok ? "项目配置与工具入口检查通过。" : "发现接入问题。";
  $("#resultOutput").textContent=JSON.stringify(result,null,2);
}));
async function boot() {
  const project=await api("/api/project"); appState.token=project.token;
  $("#projectName").textContent=project.project.label;
  $("#assetNav").replaceChildren(...project.assets.map(a=>{
    const button=node("button",a.label,"asset-choice");button.dataset.assetId=a.id;
    button.addEventListener("click",safe(()=>{ $("#planDialog").close(); return loadAsset(a.id); }));return button;
  }));
  initializePreviewControls(); await loadAsset(project.assets[0].id);
}
function previewViewport() {
  return document.querySelector("#previewViewport");
}

function clampPreview() {
  const viewport = previewViewport();
  const { width, height } = viewport.getBoundingClientRect();
  const { scale } = appState.preview;
  appState.preview.x = Math.min(0, Math.max(width * (1 - scale), appState.preview.x));
  appState.preview.y = Math.min(0, Math.max(height * (1 - scale), appState.preview.y));
}

function applyPreviewTransform() {
  clampPreview();
  const { scale, x, y } = appState.preview;
  document.querySelector("#previewStage").style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
}

function fitPreview() {
  appState.preview.scale = 1;
  appState.preview.x = 0;
  appState.preview.y = 0;
  applyPreviewTransform();
}

function setPreviewBackground(background) {
  appState.preview.background = background;
  const viewport = previewViewport();
  viewport.dataset.background = background;
  document.querySelectorAll(".background-choice").forEach((button) => {
    const selected = button.dataset.background === background;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  window.localStorage.setItem("artflow.preview.background", background);
}

function zoomPreview(nextScale, clientX = null, clientY = null) {
  const viewport = previewViewport();
  const bounds = viewport.getBoundingClientRect();
  const oldScale = appState.preview.scale;
  const scale = Math.min(4, Math.max(1, nextScale));
  if (scale === oldScale) return;
  const focusX = clientX === null ? bounds.width / 2 : clientX - bounds.left;
  const focusY = clientY === null ? bounds.height / 2 : clientY - bounds.top;
  appState.preview.x = focusX - ((focusX - appState.preview.x) * scale / oldScale);
  appState.preview.y = focusY - ((focusY - appState.preview.y) * scale / oldScale);
  appState.preview.scale = scale;
  applyPreviewTransform();
}

function initializePreviewControls() {
  const viewport = previewViewport();
  viewport.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoomPreview(appState.preview.scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15), event.clientX, event.clientY);
  }, { passive: false });
  viewport.addEventListener("pointerdown", (event) => {
    appState.preview.pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, originX: appState.preview.x, originY: appState.preview.y };
    viewport.setPointerCapture(event.pointerId);
    viewport.classList.add("is-dragging");
  });
  viewport.addEventListener("pointermove", (event) => {
    const pointer = appState.preview.pointer;
    if (!pointer || pointer.id !== event.pointerId) return;
    appState.preview.x = pointer.originX + event.clientX - pointer.x;
    appState.preview.y = pointer.originY + event.clientY - pointer.y;
    applyPreviewTransform();
  });
  const releasePointer = (event) => {
    if (appState.preview.pointer?.id !== event.pointerId) return;
    appState.preview.pointer = null;
    viewport.classList.remove("is-dragging");
  };
  viewport.addEventListener("pointerup", releasePointer);
  viewport.addEventListener("pointercancel", releasePointer);
  viewport.addEventListener("keydown", (event) => {
    if (event.key === "+" || event.key === "=") { event.preventDefault(); zoomPreview(appState.preview.scale * 1.15); }
    if (event.key === "-") { event.preventDefault(); zoomPreview(appState.preview.scale / 1.15); }
    if (event.key === "Home") { event.preventDefault(); fitPreview(); }
    const delta = 36;
    if (event.key === "ArrowLeft") appState.preview.x += delta;
    if (event.key === "ArrowRight") appState.preview.x -= delta;
    if (event.key === "ArrowUp") appState.preview.y += delta;
    if (event.key === "ArrowDown") appState.preview.y -= delta;
    if (event.key.startsWith("Arrow")) { event.preventDefault(); applyPreviewTransform(); }
  });
  document.querySelector("#zoomOutButton").addEventListener("click", () => zoomPreview(appState.preview.scale / 1.25));
  document.querySelector("#zoomInButton").addEventListener("click", () => zoomPreview(appState.preview.scale * 1.25));
  document.querySelector("#fitPreviewButton").addEventListener("click", fitPreview);
  document.querySelectorAll(".background-choice").forEach((button) => button.addEventListener("click", () => setPreviewBackground(button.dataset.background)));
  const savedBackground = window.localStorage.getItem("artflow.preview.background");
  setPreviewBackground(savedBackground === "black" ? "black" : "white");
}


safe(boot)();
