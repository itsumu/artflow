const appState = {
  asset: null,
  selectedStep: "contract_snapshot",
  previews: {},
  candidateAction: null,
  preview: { scale: 1, x: 0, y: 0, pointer: null, background: "white" },
};

const artifactUrl = (id) => `/artifact/${encodeURIComponent(id)}`;

function shortHash(hash) {
  return hash ? `${hash.slice(0, 12)}…` : "未找到";
}

function setResult(title, status, lead, output, tone = "") {
  document.querySelector("#resultTitle").textContent = title;
  const badge = document.querySelector("#resultStatus");
  badge.textContent = status;
  badge.className = `state-pill ${tone}`;
  document.querySelector("#resultLead").textContent = lead;
  document.querySelector("#resultOutput").textContent = output;
}

function commandOutput(result) {
  if (!result) return "未执行。";
  return [result.stdout, result.stderr].filter(Boolean).join("\n").trim() || "命令未产生输出。";
}

function machineReportOutput(result) {
  if (!result) return "未执行。";
  const lines = [];
  if (result.machine_interface) {
    lines.push(`机器报告：${result.machine_interface} · ${result.status || (result.ok ? "passed" : "failed")}`);
  }
  for (const check of result.checks || []) {
    lines.push(`${check.ok ? "✓" : "×"} ${check.label}`);
  }
  for (const asset of result.assets || []) {
    const canvas = Array.isArray(asset.canvas) ? `${asset.canvas[0]} × ${asset.canvas[1]}` : "未声明画布";
    const anchor = Array.isArray(asset.foot_anchor) ? ` · 脚点 (${asset.foot_anchor.join(", ")})` : "";
    const runtime = asset.runtime?.sha256 ? ` · PNG ${shortHash(asset.runtime.sha256)}` : "";
    lines.push(`资产：${asset.label || asset.id} · ${canvas}${anchor}${runtime}`);
  }
  const log = commandOutput(result);
  if (log !== "命令未产生输出。") lines.push("\n原始日志：\n" + log);
  return lines.join("\n");
}

function pipelineValidationOutput(validation) {
  if (!validation) return "尚未校验。";
  const lines = [
    `管线：${validation.pipeline_id} · ${validation.status}`,
    `步骤 ${validation.execution_order?.length || 0} 个 · 受控命令 ${validation.command_count || 0} 个 · 写入命令 ${validation.write_count || 0} 个`,
  ];
  for (const check of validation.checks || []) {
    lines.push(`${check.ok ? "✓" : "×"} ${check.label}`);
  }
  for (const error of validation.errors || []) {
    lines.push(`× ${error.path} · ${error.message}`);
  }
  for (const warning of validation.warnings || []) {
    lines.push(`! ${warning.path} · ${warning.message}`);
  }
  return lines.join("\n");
}

function environmentDiagnosticOutput(diagnostic) {
  if (!diagnostic) return "尚未诊断。";
  const lines = [
    `环境：${diagnostic.status || (diagnostic.ok ? "passed" : "failed")}`,
    "诊断不启动 Aseprite、Godot，也不创建权限探针文件。",
  ];
  for (const check of diagnostic.checks || []) {
    const mark = check.ok ? "✓" : check.blocking === false ? "!" : "×";
    const suffix = check.detail ? ` · ${check.detail}` : "";
    lines.push(`${mark} ${check.label}${suffix}`);
    for (const output of check.outputs || []) {
      lines.push(`  ${output.ok ? "✓" : "×"} ${output.asset_id || "目标"} · ${output.path || output.detail || "未声明"}`);
    }
  }
  return lines.join("\n");
}

function renderPipelineStatus(validation) {
  const badge = document.querySelector("#pipelineStatus");
  if (!validation) {
    badge.textContent = "未校验";
    badge.className = "state-pill is-warning";
    return;
  }
  badge.textContent = validation.ok ? "结构有效" : "结构有误";
  badge.className = `state-pill ${validation.ok ? "" : "is-error"}`;
}

function renderRunState(runState) {
  const state = runState.state;
  const latest = runState.latest;
  const label = {
    not_run: "未运行",
    running: "运行中",
    verified: "已验证",
    stale: "已过期",
    failed: "失败",
    interrupted: "已中断",
    cancelled: "已取消",
  }[state] || state;
  const warning = ["not_run", "stale", "interrupted", "cancelled"].includes(state);
  const failed = state === "failed";
  const badge = document.querySelector("#runState");
  const retryButton = document.querySelector("#retryExportButton");
  badge.textContent = label;
  badge.className = `state-pill ${failed ? "is-error" : warning ? "is-warning" : ""}`;
  retryButton.hidden = !["failed", "interrupted", "cancelled", "stale"].includes(state);
  const summary = document.querySelector("#verifiedVersion");
  const lead = document.querySelector("#runLead");
  const output = document.querySelector("#runOutput");
  if (!latest) {
    summary.textContent = "尚无已验证版本。";
    lead.textContent = "导出并通过严格视觉验证后，会在此记录完整的可追溯版本。";
    output.textContent = "尚无运行记录。";
    return;
  }
  const latestHash = latest.final_fingerprint?.runtime_sha256;
  summary.textContent = state === "verified"
    ? `最新已验证版本 · ${latest.finished_at} · 运行时 PNG ${shortHash(latestHash)}`
    : state === "stale"
      ? "输入或运行时 PNG 已变化，上一版验证结果已过期。"
      : `最近一次运行：${label} · ${latest.finished_at || latest.started_at}`;
  lead.textContent = latest.message || "运行信息已保存到本机账本。";
  output.textContent = JSON.stringify(latest, null, 2);
}

function artifactById(id) {
  return appState.asset.artifacts.find((artifact) => artifact.id === id);
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

function renderContract(asset) {
  const summary = [
    ["合同状态", asset.production_state],
    ["画布", `${asset.canvas[0]} × ${asset.canvas[1]}`],
    ["脚点", `(${asset.foot_anchor[0]}, ${asset.foot_anchor[1]})`],
    ["Alpha", `${asset.alpha_bounds[2]} × ${asset.alpha_bounds[3]} @ (${asset.alpha_bounds[0]}, ${asset.alpha_bounds[1]})`],
    ["运行时路径", asset.runtime_path],
  ];
  document.querySelector("#contractSummary").replaceChildren(...summary.flatMap(([label, value]) => {
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    return [term, detail];
  }));
  document.querySelector("#canvasValue").textContent = `${asset.canvas[0]} × ${asset.canvas[1]}`;
  document.querySelector("#anchorValue").textContent = `(${asset.foot_anchor[0]}, ${asset.foot_anchor[1]})`;
  document.querySelector("#alphaValue").textContent = `${asset.alpha_bounds[2]} × ${asset.alpha_bounds[3]} @ (${asset.alpha_bounds[0]}, ${asset.alpha_bounds[1]})`;
}

function renderArtifacts(artifacts) {
  const list = document.querySelector("#artifactList");
  const template = document.querySelector("#artifactTemplate");
  list.replaceChildren(...artifacts.filter((artifact) => artifact.kind !== "test").map((artifact) => {
    const row = template.content.firstElementChild.cloneNode(true);
    row.querySelector(".artifact-label").textContent = artifact.label;
    row.querySelector(".artifact-path").textContent = artifact.path;
    row.querySelector(".artifact-hash").textContent = artifact.exists ? `SHA-256 ${shortHash(artifact.sha256)}` : "文件缺失";
    const link = row.querySelector(".artifact-open");
    if (artifact.exists) {
      link.href = artifactUrl(artifact.id);
      link.textContent = artifact.kind === "image" ? "预览" : "查看";
    } else {
      link.removeAttribute("href");
      link.textContent = "缺失";
      link.setAttribute("aria-disabled", "true");
    }
    return row;
  }));
}

function stepDescription(step) {
  if (step.id === "contract_snapshot") return "读取建筑合同、Godot catalog 和严格测试断言，形成此次检查的输入快照。";
  if (step.id === "pose_board_evidence") return "展示已通过的 3×3 中央目标草图及其提示词记录；本步骤不生成或修改图像。";
  if (step.id === "cutout_evidence") return "展示已批准的纯色键切图原图；后续动作会锁定这张图的 SHA-256。";
  if (step.id === "normalize_candidate") return "人工确认原图后，从全分辨率色键图先生成二值硬 Alpha，再按同一变换采样 1× 与 8× 候选。";
  if (step.id === "hard_alpha_review") return "检查切图轮廓是否贴合对象；本步骤不会生成 Aseprite 或修改正式源。";
  if (step.id === "build_source_candidate") return "人工确认硬 Alpha 后，生成单层 Aseprite 候选、1×/2×/灰度/棋盘审阅图；不会覆盖正式源。";
  if (step.id === "source_candidate_review") return "检查项目描边、体量、脚点和棋盘遮挡，确认后才允许提升正式源。";
  if (step.id === "promote_source") return "归档当前正式源，并把已确认的 Aseprite 候选提升为新的正式源；尚不导出运行时 PNG。";
  if (step.id === "contract_verify") return "导出前只读检查：确认合同、源文件、catalog 和固定测试断言无漂移；运行时 PNG 可暂时缺失，因为它是下一步的输出。";
  if (step.id === "export") return "写入型步骤：导出正式运行时 PNG；导出后仍会执行完整 PNG 与 Godot 严格验证。必须由操作者在确认框中明确同意，才会覆写运行时资源。";
  if (step.id === "runtime_verify") return "导出后才运行 Godot 严格视觉测试；一期先显示其依赖关系，不在 dry-run 中启动 Godot。";
  return "项目适配器定义的步骤。";
}

function renderPipeline(steps) {
  const list = document.querySelector("#pipelineSteps");
  list.replaceChildren(...steps.map((step, index) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = `pipeline-step ${step.id === appState.selectedStep ? "is-selected" : ""} ${step.requires_approval ? "requires-confirmation" : ""}`;
    button.dataset.stepId = step.id;
    button.innerHTML = `<span class="step-number">${String(index + 1).padStart(2, "0")}</span><span class="step-name"></span><span class="step-kind"></span>`;
    button.querySelector(".step-name").textContent = step.label;
    button.querySelector(".step-kind").textContent = step.requires_approval ? "需要人工确认" : step.kind === "command" ? "受控命令" : "只读证据";
    button.addEventListener("click", () => {
      appState.selectedStep = step.id;
      renderPipeline(appState.asset.pipeline);
      renderStepDetail(step);
    });
    item.append(button);
    return item;
  }));
  const selected = steps.find((step) => step.id === appState.selectedStep) || steps[0];
  renderStepDetail(selected);
}

function renderStepDetail(step) {
  const container = document.querySelector("#stepDetail");
  const command = step.command ? `命令：<code>artctl ${step.command.join(" ")}</code>` : "不执行命令。";
  const approval = step.requires_approval ? "需要先确认精确产物版本，才允许进入此步骤。" : "可安全纳入预检或 dry-run。";
  const locks = Array.isArray(step.locks) && step.locks.length
    ? `执行时独占资源：<code>${step.locks.join(" · ")}</code>。`
    : "此步骤不占用写入资源锁。";
  container.innerHTML = `<h3>${step.label}</h3><p>${stepDescription(step)} ${command} ${approval} ${locks}</p>`;
}

function showPreview(name) {
  const artifactId = appState.previews[name];
  const artifact = artifactById(artifactId);
  if (!artifact || !artifact.exists) return;
  document.querySelector("#previewTitle").textContent = artifact.label;
  document.querySelector("#previewImage").src = `${artifactUrl(artifact.id)}?v=${artifact.sha256}`;
  document.querySelector("#previewImage").alt = `${artifact.label}：${appState.asset.asset.label}`;
  document.querySelector("#previewCaption").textContent = `${artifact.path} · SHA-256 ${shortHash(artifact.sha256)}`;
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.preview === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  fitPreview();
}

async function loadAsset({ preserveResult = false } = {}) {
  if (!preserveResult) setResult("正在刷新证据", "读取中", "从项目合同、源文件和运行时资源读取当前状态。", "");
  const response = await fetch("/api/asset/fire_tower", { cache: "no-store" });
  if (!response.ok) throw new Error(`读取资产失败：${response.status}`);
  appState.asset = await response.json();
  appState.previews = { board: "board_preview", hard_alpha: "hard_alpha_8x", candidate: "candidate_board_1x", runtime: "runtime", review: "review_2x" };
  const { asset, health } = appState.asset;
  document.querySelector("#assetState").textContent = health.ok ? "合同已读取" : "缺少产物";
  document.querySelector("#assetState").className = `state-pill ${health.ok ? "" : "is-error"}`;
  document.querySelector("#railStatus").style.background = health.ok ? "var(--green)" : "var(--red)";
  document.querySelector("#assetSubtitle").textContent = health.ok
    ? `合同为唯一事实来源；已发现 ${appState.asset.artifacts.filter((entry) => entry.exists).length} 项可追溯证据。`
    : `缺少：${health.missing_artifacts.join("、")}`;
  renderContract(asset);
  renderArtifacts(appState.asset.artifacts);
  renderPipeline(appState.asset.pipeline);
  document.querySelector("#buildCandidateButton").disabled = !artifactById("hard_alpha_1x")?.exists;
  document.querySelector("#promoteCandidateButton").disabled = !artifactById("source_candidate")?.exists;
  showPreview("board");
  await loadSnapshot();
  await loadRunState();
  if (!preserveResult) setResult("等待操作", "只读", "dry-run 只展开流程计划；单独的合同验证会执行完整 artctl verify buildings。", "尚未执行命令。");
}

async function loadSnapshot() {
  const response = await fetch("/api/snapshot/fire_tower", { cache: "no-store" });
  if (!response.ok) throw new Error(`读取快照失败：${response.status}`);
  const snapshot = await response.json();
  document.querySelector("#snapshotOutput").textContent = JSON.stringify(snapshot, null, 2);
}

async function loadRunState() {
  const response = await fetch("/api/runs/fire_tower", { cache: "no-store" });
  if (!response.ok) throw new Error(`读取运行账本失败：${response.status}`);
  renderRunState(await response.json());
}

async function runDryRun() {
  const button = document.querySelector("#dryRunButton");
  button.disabled = true;
  button.textContent = "规划中…";
  try {
    const response = await fetch("/api/dry-run/fire_tower", { cache: "no-store" });
    const result = await response.json();
    renderPipelineStatus(result.pipeline_validation);
    if (!result.safe) {
      setResult(
        "dry-run 被预检阻止",
        "失败",
        "未启动 Aseprite、Godot 或导出；请先修复环境或声明式管线定义。",
        `${environmentDiagnosticOutput(result.environment)}\n\n${pipelineValidationOutput(result.pipeline_validation)}`,
        "is-error",
      );
      return;
    }
    const lines = result.steps.map((step, index) => {
      const command = step.argv ? `\n   ${step.argv.join(" ")}` : "";
      const policy = step.blocked ? "需人工确认，未执行" : step.will_run ? "可执行的只读验证" : "仅列出";
      return `${String(index + 1).padStart(2, "0")}. ${step.label} · ${policy}${command}`;
    });
    setResult(
      "dry-run 计划已生成",
      "安全",
      "环境、管线结构、白名单和审批门均已通过；未启动 Aseprite、Godot 或导出。",
      `${environmentDiagnosticOutput(result.environment)}\n\n${pipelineValidationOutput(result.pipeline_validation)}\n\n${lines.join("\n")}`,
    );
  } catch (error) {
    setResult("dry-run 失败", "错误", "无法读取安全执行计划。", String(error), "is-error");
  } finally {
    button.disabled = false;
    button.textContent = "运行 dry-run";
  }
}

async function diagnoseEnvironment() {
  const button = document.querySelector("#diagnoseEnvironmentButton");
  button.disabled = true;
  button.textContent = "诊断中…";
  setResult("正在诊断本机环境", "运行中", "只检查路径、可执行权限、合同和目录权限；不会启动 Aseprite 或 Godot。", "");
  try {
    const response = await fetch("/api/diagnostics/fire_tower", { cache: "no-store" });
    const diagnostic = await response.json();
    setResult(
      diagnostic.ok ? "本机环境可执行" : "本机环境需要修复",
      diagnostic.ok ? "通过" : "失败",
      diagnostic.ok
        ? "导出环境已满足一期 canary 的前置条件；PyYAML 若标为提示，不影响当前 JSON 管线。"
        : "尚未启动任何创作工具或导出；请按失败项修复环境后再运行。",
      environmentDiagnosticOutput(diagnostic),
      diagnostic.ok ? "" : "is-error",
    );
  } catch (error) {
    setResult("环境诊断失败", "错误", "无法读取本机执行环境。", String(error), "is-error");
  } finally {
    button.disabled = false;
    button.textContent = "诊断环境";
  }
}

async function validatePipeline() {
  const button = document.querySelector("#validatePipelineButton");
  button.disabled = true;
  button.textContent = "校验中…";
  try {
    const response = await fetch("/api/pipeline-check/fire_tower", { cache: "no-store" });
    const validation = await response.json();
    renderPipelineStatus(validation);
    setResult(
      validation.ok ? "管线定义有效" : "管线定义有误",
      validation.ok ? "通过" : "失败",
      validation.ok
        ? "DAG、输入来源、命令白名单、写入路径和审批门均可安全进入 dry-run。"
        : "未执行任何工具或导出；请根据结构化错误修复管线定义。",
      pipelineValidationOutput(validation),
      validation.ok ? "" : "is-error",
    );
  } catch (error) {
    renderPipelineStatus({ ok: false });
    setResult("管线校验失败", "错误", "无法读取声明式管线定义。", String(error), "is-error");
  } finally {
    button.disabled = false;
    button.textContent = "校验管线";
  }
}

async function verifyContract() {
  const button = document.querySelector("#verifyButton");
  button.disabled = true;
  button.textContent = "验证中…";
  setResult("正在验证建筑合同", "运行中", "正在执行允许的只读命令：artctl verify buildings。", "");
  try {
    const response = await fetch("/api/verify/fire_tower", { method: "POST" });
    const result = await response.json();
    setResult(
      result.ok ? "建筑合同验证通过" : "建筑合同验证失败",
      result.ok ? "通过" : "失败",
      `退出码 ${result.exit_code} · ${result.duration_ms} ms · ${result.machine_interface || "机器报告缺失"} · 未写入资产文件。`,
      machineReportOutput(result),
      result.ok ? "" : "is-error",
    );
  } catch (error) {
    setResult("建筑合同验证失败", "错误", "命令未能完成。", String(error), "is-error");
  } finally {
    button.disabled = false;
    button.textContent = "验证建筑合同";
  }
}

async function verifyVisuals() {
  const button = document.querySelector("#verifyVisualsButton");
  button.disabled = true;
  button.textContent = "验证中…";
  setResult("正在执行 Godot 严格视觉验证", "运行中", "正在执行受控命令：artctl verify visuals。", "");
  try {
    const response = await fetch("/api/verify-visuals/fire_tower", { method: "POST" });
    const result = await response.json();
    setResult(
      result.ok ? "Godot 严格视觉验证通过" : "Godot 严格视觉验证失败",
      result.ok ? "通过" : "失败",
      `退出码 ${result.exit_code} · ${result.duration_ms} ms · ${result.machine_interface || "机器报告缺失"} · 未导出或改写资源。`,
      machineReportOutput(result),
      result.ok ? "" : "is-error",
    );
  } catch (error) {
    setResult("Godot 严格视觉验证失败", "错误", "命令未能完成。", String(error), "is-error");
  } finally {
    button.disabled = false;
    button.textContent = "严格视觉验证";
    await loadRunState();
  }
}

async function retryExportFromPreflight() {
  const button = document.querySelector("#retryExportButton");
  button.disabled = true;
  button.textContent = "预检中…";
  setResult("正在为重试执行预检", "运行中", "先重新检查环境和建筑合同；不会启动导出。", "");
  try {
    const response = await fetch("/api/retry-preflight/fire_tower", { method: "POST" });
    const result = await response.json();
    const output = [
      "管线定义：",
      pipelineValidationOutput(result.pipeline_validation),
      "环境诊断：",
      environmentDiagnosticOutput(result.environment),
      "建筑合同预检：",
      machineReportOutput(result.preflight),
    ].filter(Boolean).join("\n\n");
    setResult(
      result.ok ? "重试预检通过" : "重试预检未通过",
      result.ok ? "通过" : "失败",
      result.message || "未启动导出。",
      output,
      result.ok ? "" : "is-error",
    );
    if (result.ok) exportRuntime();
  } catch (error) {
    setResult("重试预检失败", "错误", "无法读取重试预检结果。", String(error), "is-error");
  } finally {
    button.disabled = false;
    button.textContent = "从合同验证重试";
  }
}

async function exportRuntime() {
  const dialog = document.querySelector("#exportDialog");
  document.querySelector("#exportConfirmation").value = "";
  document.querySelector("#exportConfirmationError").textContent = "";
  dialog.showModal();
  document.querySelector("#exportConfirmation").focus();
}

async function runConfirmedExport(confirmation) {
  const button = document.querySelector("#exportButton");
  button.disabled = true;
  button.textContent = "导出中…";
  setResult("正在导出运行时 PNG", "运行中", "先检查环境和建筑合同；通过后才执行受控的 artctl export building fire_tower。", "");
  try {
    const response = await fetch("/api/export/fire_tower", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation }),
    });
    const result = await response.json();
    const output = [
      "环境诊断：",
      environmentDiagnosticOutput(result.environment),
      "管线定义：",
      pipelineValidationOutput(result.pipeline_validation),
      `建筑合同预检：${result.preflight?.ok ? "通过" : "失败"}`,
      machineReportOutput(result.preflight),
      "运行时 PNG 导出：",
      machineReportOutput(result.export),
      `Godot 严格视觉验证：${result.visual_verify?.ok ? "通过" : "未通过"}`,
      machineReportOutput(result.visual_verify),
    ].filter(Boolean).join("\n\n");
    setResult(
      result.ok ? "导出与严格视觉验证完成" : "导出或严格视觉验证失败",
      result.ok ? "通过" : "失败",
      result.ok ? `总耗时 ${result.run?.duration_ms} ms · 已更新运行时 PNG 并完成严格视觉验证。` : "预检、导出或严格视觉验证失败；请根据输出修复后重试。",
      output || "命令未产生输出。",
      result.ok ? "" : "is-error",
    );
    await loadAsset({ preserveResult: true });
  } catch (error) {
    setResult("运行时 PNG 导出失败", "错误", "命令未能完成。", String(error), "is-error");
  } finally {
    button.disabled = false;
    button.textContent = "导出运行时 PNG…";
  }
}

const candidateActions = {
  normalize: {
    button: "normalizeCandidateButton",
    endpoint: "/api/candidate-normalize/fire_tower",
    artifact: "cutout",
    title: "批准原图并生成硬 Alpha",
    description: "确认当前纯色键原图已经通过视觉审阅。此操作只生成版本化硬 Alpha 候选，不会创建正式源或导出运行时 PNG。",
    running: "正在生成硬 Alpha 候选",
  },
  source: {
    button: "buildCandidateButton",
    endpoint: "/api/candidate-source/fire_tower",
    artifact: "hard_alpha_1x",
    title: "批准切图并生成 Aseprite 候选源",
    description: "确认当前硬 Alpha 轮廓贴合目标。此操作生成候选源和审阅图，不会覆盖正式 Aseprite 源。",
    running: "正在生成 Aseprite 候选源",
  },
  promote: {
    button: "promoteCandidateButton",
    endpoint: "/api/candidate-promote/fire_tower",
    artifact: "source_candidate",
    title: "批准候选并提升为正式源",
    description: "确认当前候选源的描边、体量、脚点与棋盘预览均通过。旧正式源会先归档；本步骤尚不导出运行时 PNG。",
    running: "正在提升正式 Aseprite 源",
  },
};

function openCandidateAction(actionId) {
  const action = candidateActions[actionId];
  const artifact = artifactById(action.artifact);
  if (!artifact?.exists) {
    setResult("无法进入人工门禁", "缺少产物", `需要先生成：${artifact?.label || action.artifact}。`, "未执行命令。", "is-error");
    return;
  }
  appState.candidateAction = actionId;
  document.querySelector("#candidateDialogTitle").textContent = action.title;
  document.querySelector("#candidateDialogDescription").textContent = action.description;
  document.querySelector("#candidateDialogArtifact").textContent = `${artifact.path} · SHA-256 ${artifact.sha256}`;
  document.querySelector("#candidateConfirmation").value = "";
  document.querySelector("#candidateConfirmationError").textContent = "";
  document.querySelector("#candidateDialog").showModal();
  document.querySelector("#candidateConfirmation").focus();
}

async function runCandidateAction(actionId, confirmation) {
  const action = candidateActions[actionId];
  const artifact = artifactById(action.artifact);
  const button = document.querySelector(`#${action.button}`);
  button.disabled = true;
  setResult(action.running, "运行中", "输入 SHA-256 已锁定；产物变化时服务器会拒绝继续。", "");
  try {
    const response = await fetch(action.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation, artifact_sha256: artifact.sha256 }),
    });
    const payload = await response.json();
    const result = payload.result;
    setResult(
      payload.ok ? `${action.title}完成` : `${action.title}失败`,
      payload.ok ? "通过" : "失败",
      payload.ok ? "候选产物已生成并登记；请在预览区审阅后再进入下一道门。" : (payload.error || "未通过环境、管线或 artctl 检查。"),
      [pipelineValidationOutput(payload.pipeline_validation), environmentDiagnosticOutput(payload.environment), machineReportOutput(result)].filter(Boolean).join("\n\n"),
      payload.ok ? "" : "is-error",
    );
    await loadAsset({ preserveResult: true });
    if (payload.ok && actionId === "normalize") showPreview("hard_alpha");
    if (payload.ok && actionId === "source") showPreview("candidate");
  } catch (error) {
    setResult(`${action.title}失败`, "错误", "命令未能完成。", String(error), "is-error");
  } finally {
    button.disabled = false;
  }
}

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => showPreview(tab.dataset.preview)));
document.querySelector("#dryRunButton").addEventListener("click", runDryRun);
document.querySelector("#diagnoseEnvironmentButton").addEventListener("click", diagnoseEnvironment);
document.querySelector("#validatePipelineButton").addEventListener("click", validatePipeline);
document.querySelector("#verifyButton").addEventListener("click", verifyContract);
document.querySelector("#verifyVisualsButton").addEventListener("click", verifyVisuals);
document.querySelector("#retryExportButton").addEventListener("click", retryExportFromPreflight);
document.querySelector("#exportButton").addEventListener("click", exportRuntime);
document.querySelector("#normalizeCandidateButton").addEventListener("click", () => openCandidateAction("normalize"));
document.querySelector("#buildCandidateButton").addEventListener("click", () => openCandidateAction("source"));
document.querySelector("#promoteCandidateButton").addEventListener("click", () => openCandidateAction("promote"));
document.querySelector("#cancelExportButton").addEventListener("click", () => document.querySelector("#exportDialog").close());
document.querySelector("#exportForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const confirmation = document.querySelector("#exportConfirmation").value.trim();
  if (confirmation !== appState.asset.asset.id) {
    document.querySelector("#exportConfirmationError").textContent = `请输入 ${appState.asset.asset.id} 才能确认。`;
    return;
  }
  document.querySelector("#exportDialog").close();
  runConfirmedExport(confirmation);
});
document.querySelector("#cancelCandidateButton").addEventListener("click", () => document.querySelector("#candidateDialog").close());
document.querySelector("#candidateForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const confirmation = document.querySelector("#candidateConfirmation").value.trim();
  if (confirmation !== appState.asset.asset.id) {
    document.querySelector("#candidateConfirmationError").textContent = `请输入 ${appState.asset.asset.id} 才能确认。`;
    return;
  }
  const actionId = appState.candidateAction;
  document.querySelector("#candidateDialog").close();
  runCandidateAction(actionId, confirmation);
});
document.querySelector("#refreshButton").addEventListener("click", () => loadAsset().catch((error) => setResult("刷新失败", "错误", "无法读取当前项目状态。", String(error), "is-error")));

initializePreviewControls();
loadAsset().catch((error) => setResult("无法加载 Fire Tower", "错误", "请检查项目适配配置及本地文件状态。", String(error), "is-error"));
