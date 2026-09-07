"use strict";
const $ = id => document.getElementById(id);
const token = location.pathname.split("/")[1];
const systemColumns = new Set(["source_eml", "_status", "_error", "subject", "from", "to", "date", "docx_filename"]);
let dataset = "", columns = [], originalColumns = [], summary = null;
let page = 0, originalView = false, busy = false, dirty = false, stopped = false;
let previewVersion = 0, previewTimer = null, editIndex = null;
let optionsDirty = false, previewValid = false, activeTab = "tables", detailsPage = 0, detailsVersion = 0;
let outputTouched = false;
let preferredColumnWidth = 280, columnDrag = null;
const optionIds = {save_mail: "opt-mail", save_attachments: "opt-attachments", extract_text: "opt-text",
  extract_tables: "opt-tables", email_tables: "opt-email-tables", docx_tables: "opt-docx-tables"};
const getOptions = () => Object.fromEntries(Object.entries(optionIds).map(([key, id]) => [key, $(id).checked]));
const presetOptions = name => ({save_mail: name !== "tables", save_attachments: name !== "tables",
  extract_text: name === "all", extract_tables: name !== "attachments", email_tables: true, docx_tables: true});
const hasTables = () => Boolean(dataset && summary?.options.extract_tables);
const canExport = () => Boolean(dataset && !busy && !optionsDirty &&
  (!hasTables() || (previewValid && columns.some(c => c.enabled))));

function updatePresets() {
  const options = getOptions();
  for (const name of ["attachments", "tables", "all"]) {
    const preset = presetOptions(name);
    $("preset-" + name).setAttribute("aria-pressed", String(Object.keys(optionIds).every(key => options[key] === preset[key])));
  }
}
function updateOutputPlan() {
  const opts = getOptions(), results = [];
  if (opts.save_mail) results.push("메일 정보와 본문");
  if (opts.save_attachments) results.push("첨부파일 원본");
  if (opts.extract_text) results.push("첨부파일 텍스트");
  if (opts.extract_tables) results.push("Excel 표");
  $("output-plan").textContent = results.length ? `저장할 결과: ${results.join(" · ")} · 메일 요약 · 처리 기록` : "실행할 기능을 하나 이상 선택해 주세요.";
}
function optionsChanged() {
  optionsDirty = Boolean(dataset && Object.keys(optionIds).some(key => getOptions()[key] !== summary.options[key]));
  $("opt-email-tables").disabled = busy || !$("opt-tables").checked;
  $("opt-docx-tables").disabled = busy || !$("opt-tables").checked;
  $("reanalyze").disabled = busy || !dataset || !optionsDirty;
  $("export").disabled = !canExport();
  updatePresets();
  updateOutputPlan();
  if (optionsDirty) notice("실행 옵션이 변경되었습니다. 현재 목록은 이전 분석 결과입니다. ‘선택한 옵션으로 다시 분석’을 눌러 주세요.");
  else notice("");
}
function applyPreset(name) {
  const values = presetOptions(name);
  for (const [key, id] of Object.entries(optionIds)) $(id).checked = values[key];
  optionsChanged();
}

async function api(route, body) {
  const response = await fetch(`api/${route}`, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-EmailTools-Token": token}, body: JSON.stringify(body)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "요청을 처리하지 못했습니다.");
  return result;
}
function notice(message, type = "") {
  $("notice").textContent = message;
  $("notice").className = type;
  $("notice").hidden = !message;
}
function setBusy(value) {
  busy = value;
  if (!value) $("cancel-load").hidden = true;
  for (const id of ["demo", "empty-demo", "load-path", "choose-folder", "choose-files", "source-path"]) $(id).disabled = value;
  for (const id of ["reset", "column-search", "select-all", "select-none", "data-only", "add-column", "view-result", "view-original"]) $(id).disabled = value || !hasTables();
  for (const id of [...Object.values(optionIds), "preset-attachments", "preset-tables", "preset-all", "output-path"]) $(id).disabled = value;
  $("opt-email-tables").disabled = value || !$("opt-tables").checked;
  $("opt-docx-tables").disabled = value || !$("opt-tables").checked;
  $("reanalyze").disabled = value || !dataset || !optionsDirty;
  for (const kind of ["mails", "attachments", "tables"]) $("tab-" + kind).disabled = value || !dataset || (kind === "tables" && !hasTables());
  $("details-prev").disabled = value || detailsPage === 0;
  $("details-next").disabled = true;
  for (const control of $("column-list").querySelectorAll("button,input")) control.disabled = value;
  $("export").disabled = !canExport();
  $("shutdown").disabled = value;
  $("toggle-columns").disabled = value;
  $("workspace-resizer").setAttribute("aria-disabled", String(value));
  $("workspace-resizer").tabIndex = value ? -1 : 0;
  if (value) finishColumnResize();
  updatePresets();
}
function columnWidthLimit() {
  const available = $("table-workspace").clientWidth;
  return available && window.innerWidth > 800 ? Math.max(240, Math.min(420, available - 400)) : 420;
}
function setColumnWidth(width, remember = false) {
  const limit = columnWidthLimit(), adjusted = Math.round(Math.max(240, Math.min(limit, width)));
  if (remember) preferredColumnWidth = adjusted;
  $("table-workspace").style.setProperty("--column-width", `${adjusted}px`);
  $("workspace-resizer").setAttribute("aria-valuemax", String(limit));
  $("workspace-resizer").setAttribute("aria-valuenow", String(adjusted));
  $("workspace-resizer").setAttribute("aria-valuetext", `${adjusted}픽셀`);
}
function finishColumnResize(event) {
  if (!columnDrag || (event && event.pointerId !== columnDrag.pointerId)) return;
  const pointerId = columnDrag.pointerId;
  columnDrag = null;
  $("table-workspace").classList.remove("resizing");
  if ($("workspace-resizer").hasPointerCapture(pointerId)) $("workspace-resizer").releasePointerCapture(pointerId);
}
function toggleColumns() {
  if (busy) return;
  finishColumnResize();
  const collapsed = $("table-workspace").classList.toggle("columns-collapsed");
  $("toggle-columns").setAttribute("aria-expanded", String(!collapsed));
  $("toggle-columns-label").textContent = collapsed ? "열 설정 펼치기" : "열 설정 접기";
  if (!collapsed) setColumnWidth(preferredColumnWidth);
}
function originalSpecs() {
  return originalColumns.map(source => ({source, name: source, value: "", enabled: true}));
}
function visibleSpecs() { return originalView ? originalSpecs() : columns; }
function updateCounts() {
  if (!dataset) return;
  const selected = columns.filter(c => c.enabled);
  const added = selected.filter(c => c.source === null).length;
  const excluded = originalColumns.length - selected.filter(c => c.source !== null).length;
  $("metric-selected").textContent = selected.length;
  $("metric-changes").textContent = `원본 ${excluded}열 제외 · 사용자 ${added}열 추가`;
  $("included-count").textContent = `선택 ${selected.length}열`;
  $("excluded-count").textContent = `제외 ${excluded}열`;
  $("added-count").textContent = `추가 ${added}열`;
  $("view-note").textContent = originalView ? "원본 확인 중 · 저장은 선택한 구성을 사용합니다." : "선택 변경 시 즉시 반영";
  $("export-summary").textContent = `${summary.total}개 메일 · 첨부 ${summary.attachments}개` +
    (hasTables() ? ` · Excel ${selected.length}개 열` : " · 표 추출 미선택");
  if (!hasTables()) {
    $("metric-fields").textContent = "—";
    $("metric-selected").textContent = "—";
    $("metric-changes").textContent = "표 추출 미선택";
  }
}
function renderColumns() {
  const filter = $("column-search").value.trim().toLocaleLowerCase();
  const list = $("column-list"); list.replaceChildren();
  columns.forEach((column, index) => {
    if (!column.name.toLocaleLowerCase().includes(filter)) return;
    const row = document.createElement("div");
    row.className = `column-row${column.enabled ? "" : " excluded"}${column.source === null ? " custom" : ""}`;
    const label = document.createElement("label");
    const check = document.createElement("input"); check.type = "checkbox"; check.checked = column.enabled; check.disabled = busy;
    check.setAttribute("aria-label", `${column.name} 열 포함`);
    check.addEventListener("change", () => { column.enabled = check.checked; changed(); });
    const name = document.createElement("span"); name.className = "column-name"; name.textContent = column.name; name.title = column.name;
    label.append(check, name); row.append(label);
    const kind = document.createElement("span"); kind.className = "column-kind";
    kind.textContent = column.source === null ? "추가" : systemColumns.has(column.source) ? "메일" : "항목";
    row.append(kind);
    const actions = document.createElement("div"); actions.className = "row-actions";
    const action = (text, title, fn, disabled = false) => {
      const b = document.createElement("button"); b.textContent = text; b.title = title; b.setAttribute("aria-label", title); b.disabled = disabled || busy;
      b.addEventListener("click", fn); actions.append(b);
    };
    if (column.source === null) action("✎", `${column.name} 수정`, () => openColumn(index));
    action("↑", `${column.name} 위로 이동`, () => { [columns[index - 1], columns[index]] = [columns[index], columns[index - 1]]; changed(); }, index === 0);
    action("↓", `${column.name} 아래로 이동`, () => { [columns[index + 1], columns[index]] = [columns[index], columns[index + 1]]; changed(); }, index === columns.length - 1);
    row.append(actions); list.append(row);
  });
  if (!list.children.length) { const empty = document.createElement("p"); empty.className = "column-empty"; empty.textContent = "검색 결과가 없습니다."; list.append(empty); }
}
function changed() {
  dirty = true; page = 0;
  $("download-banner").hidden = true;
  // Editing columns always brings the user back to the actual export view.
  originalView = false; updateView(); renderColumns(); updateCounts(); schedulePreview();
}
function schedulePreview() {
  clearTimeout(previewTimer); previewVersion++;
  previewValid = false;
  $("export").disabled = true;
  previewTimer = setTimeout(refreshPreview, 100);
}
function showCell(title, value) {
  $("cell-title").textContent = title; $("cell-value").textContent = value || "(빈 값)"; $("cell-dialog").showModal();
}
async function refreshPreview() {
  if (!dataset || busy || stopped) return;
  if (!hasTables()) { $("export").disabled = !canExport(); return; }
  const version = ++previewVersion;
  if (!visibleSpecs().some(c => c.enabled)) {
    $("table-wrap").hidden = true; $("preview-footer").hidden = true;
    $("preview-empty").hidden = false;
    $("preview-empty").querySelector("h3").textContent = "저장할 열을 선택해 주세요";
    $("preview-empty").querySelector("p").textContent = "열 설정에서 원본 열을 선택하거나 사용자 열을 추가하세요.";
    $("preview-empty").querySelector(".empty-note").hidden = true;
    $("empty-demo").hidden = true; $("export").disabled = true; if (!optionsDirty) notice(""); return;
  }
  try {
    const data = await api("preview", {dataset, columns: visibleSpecs(), page});
    if (version !== previewVersion || stopped) return;
    $("preview-empty").hidden = true; $("table-wrap").hidden = false; $("preview-footer").hidden = false;
    const head = $("preview-table").querySelector("thead"), body = $("preview-table").querySelector("tbody");
    head.replaceChildren(); body.replaceChildren();
    const header = document.createElement("tr");
    const addedNames = new Set(originalView ? [] : columns.filter(c => c.source === null && c.enabled).map(c => c.name.trim()));
    for (const name of ["#", ...data.columns]) {
      const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = name;
      if (addedNames.has(name)) cell.className = "added-cell";
      header.append(cell);
    }
    head.append(header);
    data.rows.forEach((record, index) => {
      const row = document.createElement("tr"), number = document.createElement("td");
      number.textContent = data.page * data.page_size + index + 1;
      if (data.statuses[index] !== "OK") {
        const warn = document.createElement("button"); warn.className = "status-dot"; warn.textContent = "!";
        warn.title = data.statuses[index]; warn.setAttribute("aria-label", `${number.textContent}행 처리 상태 보기`);
        warn.addEventListener("click", () => showCell("처리 상태", `${data.statuses[index]}\n\n${data.errors[index] || "일부 본문 표 또는 DOCX 첨부가 없습니다. 추출된 값은 사용할 수 있습니다."}`)); number.append(warn);
      }
      row.append(number);
      for (const name of data.columns) {
        const cell = document.createElement("td"), value = record[name];
        if (addedNames.has(name)) cell.classList.add("added-cell");
        if (!value) cell.classList.add("empty-cell");
        const button = document.createElement("button"); button.className = "cell-content"; button.textContent = value || "—";
        button.title = value || "빈 값"; button.setAttribute("aria-label", `${name}: ${value || "빈 값"}`);
        button.addEventListener("click", () => showCell(name, value)); cell.append(button); row.append(cell);
      }
      body.append(row);
    });
    page = data.page;
    $("page-info").textContent = `${page * data.page_size + 1}–${Math.min((page + 1) * data.page_size, data.total)} / ${data.total}행`;
    $("prev-page").disabled = page === 0;
    $("next-page").disabled = (page + 1) * data.page_size >= data.total;
    // Validate the result selection even while the original view is displayed.
    if (originalView && columns.some(c => c.enabled)) await api("preview", {dataset, columns, page: 0});
    if (version !== previewVersion) return;
    previewValid = columns.some(c => c.enabled);
    $("export").disabled = !canExport();
    if (!optionsDirty) notice("");
  } catch (error) {
    if (version === previewVersion) { previewValid = false; notice(error.message, "error"); $("export").disabled = true; $("table-wrap").hidden = true; $("preview-footer").hidden = true; }
  }
}
function updateView() {
  $("view-result").classList.toggle("active", !originalView); $("view-original").classList.toggle("active", originalView);
  $("view-result").setAttribute("aria-pressed", String(!originalView)); $("view-original").setAttribute("aria-pressed", String(originalView));
  $("preview-description").textContent = originalView ? "원본의 모든 열을 확인합니다. 저장에는 선택한 열 구성을 사용합니다." : "지금 보는 열 구성 그대로 Excel에 저장됩니다.";
}
function installDataset(state) {
  dataset = state.dataset; summary = state; originalColumns = state.columns;
  columns = originalSpecs(); page = 0; originalView = false; dirty = false;
  optionsDirty = false; previewValid = false; detailsPage = 0;
  for (const [key, id] of Object.entries(optionIds)) $(id).checked = state.options[key];
  if (!outputTouched) $("output-path").value = state.output_suggestion;
  $("mail-tab-count").textContent = state.total;
  $("attachment-tab-count").textContent = state.attachments;
  $("source-label").textContent = state.label; $("source-label").title = state.label; $("demo-badge").hidden = !state.demo;
  $("metric-rows").textContent = state.total;
  $("metric-fields").textContent = state.columns.filter(c => !systemColumns.has(c)).length;
  $("metric-warnings").textContent = state.warnings + state.failures;
  $("metric-warning-detail").textContent = `정상 ${state.success} · 확인 ${state.warnings} · 실패 ${state.failures}`;
  $("change-bar").hidden = false; $("column-search").value = "";
  updateView(); setBusy(false); renderColumns(); updateCounts(); updateOutputPlan();
  showTab(hasTables() ? "tables" : "mails");
  if (hasTables()) schedulePreview();
  else { $("export").disabled = !canExport(); notice(""); }
}

function showTab(kind) {
  if (busy || (kind === "tables" && !hasTables())) return;
  activeTab = kind; detailsPage = 0;
  $("table-workspace").hidden = kind !== "tables";
  $("details-panel").hidden = kind === "tables";
  $("toggle-columns").hidden = kind !== "tables";
  finishColumnResize();
  if (kind === "tables") setColumnWidth(preferredColumnWidth);
  for (const item of ["mails", "attachments", "tables"]) {
    $("tab-" + item).classList.toggle("active", item === kind);
    $("tab-" + item).setAttribute("aria-pressed", String(item === kind));
  }
  if (kind !== "tables") refreshDetails();
}
async function refreshDetails() {
  if (!dataset || busy || activeTab === "tables") return;
  const version = ++detailsVersion, selectedDataset = dataset;
  try {
    const data = await api("details", {dataset, kind: activeTab, page: detailsPage});
    if (version !== detailsVersion || selectedDataset !== dataset || busy) return;
    const head = $("details-table").querySelector("thead"), body = $("details-table").querySelector("tbody");
    head.replaceChildren(); body.replaceChildren();
    $("details-title").textContent = activeTab === "mails" ? "메일 요약" : "첨부파일 목록";
    $("details-empty").hidden = data.total !== 0;
    const headers = data.rows.length ? Object.keys(data.rows[0]) : [];
    if (headers.length) {
      const row = document.createElement("tr");
      for (const name of ["#", ...headers]) { const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = name; row.append(cell); }
      head.append(row);
    }
    data.rows.forEach((record, i) => {
      const row = document.createElement("tr"), number = document.createElement("td");
      number.textContent = data.page * data.page_size + i + 1; row.append(number);
      for (const name of headers) {
        const cell = document.createElement("td"), button = document.createElement("button");
        button.className = "cell-content"; button.textContent = record[name] || "—";
        button.setAttribute("aria-label", `${name}: ${record[name] || "빈 값"}`);
        button.addEventListener("click", () => showCell(name, record[name])); cell.append(button); row.append(cell);
      }
      body.append(row);
    });
    detailsPage = data.page;
    $("details-page-info").textContent = data.total ? `${data.page * data.page_size + 1}–${Math.min((data.page + 1) * data.page_size, data.total)} / ${data.total}행` : "0행";
    $("details-prev").disabled = data.page === 0;
    $("details-next").disabled = (data.page + 1) * data.page_size >= data.total;
  } catch (error) { if (version === detailsVersion) notice(error.message, "error"); }
}
function mayReplace() { return !dirty || window.confirm("새 메일을 불러오면 현재 열 구성이 초기화됩니다. 계속할까요?"); }
async function loadData(request, approved = false) {
  if (busy || (!approved && !mayReplace())) return;
  setBusy(true); previewVersion++; detailsVersion++; clearTimeout(previewTimer);
  $("download-banner").hidden = true;
  try {
    await api("load", {...request, options: getOptions()});
    dataset = ""; columns = []; originalColumns = [];
    previewValid = false;
    $("details-table").querySelector("thead").replaceChildren();
    $("details-table").querySelector("tbody").replaceChildren();
    $("details-page-info").textContent = "분석 중";
    $("table-wrap").hidden = true; $("preview-footer").hidden = true;
    $("change-bar").hidden = true; $("column-list").replaceChildren();
    for (const id of ["metric-rows", "metric-fields", "metric-selected", "metric-warnings"]) $(id).textContent = "—";
    $("metric-changes").textContent = "불러오는 중…";
    $("metric-warning-detail").textContent = "분석 중";
    $("source-label").textContent = "EML을 분석하고 있습니다.";
    $("demo-badge").hidden = true;
    $("export-summary").textContent = "분석 후 열 구성을 선택해 주세요.";
    await pollLoad();
  } catch (error) { setBusy(false); notice(error.message, "error"); if (dataset) { renderColumns(); schedulePreview(); } }
}
async function pollLoad() {
  const state = await api("state");
  if (state.phase === "loading") {
    $("cancel-load").hidden = false;
    notice(state.progress, "loading"); await new Promise(resolve => setTimeout(resolve, 350)); return pollLoad();
  }
  if (state.phase === "ready") installDataset(state);
  else { setBusy(false); notice(state.error || "데이터를 불러오지 못했습니다.", "error"); }
}
async function loadFiles(fileList) {
  if (busy || !mayReplace()) return;
  const files = Array.from(fileList).filter(file => /\.eml$/i.test(file.name));
  if (!files.length) return notice("선택한 항목에 EML 파일이 없습니다. 폴더는 ‘폴더 선택’을 이용해 주세요.", "error");
  if (files.length > 5000 || files.reduce((sum, file) => sum + file.size, 0) > 64 * 1024 * 1024)
    return notice("5,000개 또는 64 MB를 넘는 데이터는 폴더 경로를 입력해서 불러와 주세요.", "error");
  setBusy(true); notice("선택한 파일을 읽는 중…", "loading");
  try {
    const payload = [];
    for (const file of files) {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(",")[1]);
        reader.onerror = () => reject(new Error(`${file.name} 파일을 읽지 못했습니다.`)); reader.readAsDataURL(file);
      });
      payload.push({name: file.webkitRelativePath || file.name, data});
    }
    setBusy(false); await loadData({files: payload}, true);
  } catch (error) { setBusy(false); notice(error.message, "error"); if (dataset) schedulePreview(); }
}
function openColumn(index = null) {
  editIndex = index;
  $("column-dialog-title").textContent = index === null ? "사용자 열 추가" : "사용자 열 수정";
  $("custom-name").value = index === null ? "" : columns[index].name;
  $("custom-value").value = index === null ? "" : columns[index].value;
  $("column-error").textContent = ""; $("column-dialog").showModal(); $("custom-name").focus();
}
$("column-form").addEventListener("submit", event => {
  event.preventDefault(); const name = $("custom-name").value.trim();
  if (!name || /[\r\n\x00-\x1f]/.test(name)) { $("column-error").textContent = "줄바꿈 없는 열 이름을 입력해 주세요."; return; }
  if (columns.some((c, i) => i !== editIndex && c.name.toLocaleLowerCase() === name.toLocaleLowerCase())) {
    $("column-error").textContent = "이미 있는 열 이름입니다. 제외한 열도 복원할 수 있으므로 다른 이름을 입력해 주세요."; return;
  }
  const value = {source: null, name, value: $("custom-value").value, enabled: true};
  if (editIndex === null) columns.push(value); else columns[editIndex] = value;
  $("column-dialog").close(); changed();
});
for (const id of ["close-column-dialog", "cancel-column"]) $(id).onclick = () => $("column-dialog").close();
$("close-cell-dialog").onclick = () => $("cell-dialog").close();
$("add-column").onclick = () => openColumn();
$("source-form").onsubmit = event => { event.preventDefault(); loadData({source: $("source-path").value}); };
for (const id of ["demo", "empty-demo"]) $(id).onclick = () => loadData({demo: true});
$("choose-folder").onclick = () => $("folder-input").click();
$("choose-files").onclick = () => $("files-input").click();
for (const id of ["folder-input", "files-input"]) $(id).onchange = event => { loadFiles(event.target.files); event.target.value = ""; };
const dropzone = document.querySelector(".source-card");
dropzone.addEventListener("dragover", event => { event.preventDefault(); if (!busy) dropzone.classList.add("dragging"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragging"));
dropzone.addEventListener("drop", event => { event.preventDefault(); dropzone.classList.remove("dragging"); loadFiles(event.dataTransfer.files); });
window.addEventListener("dragover", event => event.preventDefault());
window.addEventListener("drop", event => event.preventDefault());
$("column-search").oninput = renderColumns;
$("reset").onclick = () => { if (window.confirm("사용자 열과 순서를 초기화하고 모든 원본 열을 복원할까요?")) { columns = originalSpecs(); changed(); } };
$("select-all").onclick = () => { columns.forEach(c => c.enabled = true); changed(); };
$("select-none").onclick = () => { columns.forEach(c => c.enabled = false); changed(); };
$("data-only").onclick = () => { columns.forEach(c => c.enabled = c.source === null || !systemColumns.has(c.source)); changed(); };
$("view-result").onclick = () => { originalView = false; page = 0; updateView(); updateCounts(); schedulePreview(); };
$("view-original").onclick = () => { originalView = true; page = 0; updateView(); updateCounts(); schedulePreview(); };
$("prev-page").onclick = () => { page--; schedulePreview(); };
$("next-page").onclick = () => { page++; schedulePreview(); };
for (const kind of ["mails", "attachments", "tables"]) $("tab-" + kind).onclick = () => showTab(kind);
$("details-prev").onclick = () => { detailsPage--; refreshDetails(); };
$("details-next").onclick = () => { detailsPage++; refreshDetails(); };
$("toggle-columns").onclick = toggleColumns;
$("workspace-resizer").addEventListener("pointerdown", event => {
  if (busy || !event.isPrimary || event.button !== 0 || window.innerWidth <= 800 || $("table-workspace").classList.contains("columns-collapsed")) return;
  event.preventDefault();
  columnDrag = {pointerId: event.pointerId, x: event.clientX, width: Number($("workspace-resizer").getAttribute("aria-valuenow"))};
  $("workspace-resizer").setPointerCapture(event.pointerId);
  $("workspace-resizer").focus();
  $("table-workspace").classList.add("resizing");
});
$("workspace-resizer").addEventListener("pointermove", event => {
  if (columnDrag?.pointerId === event.pointerId) setColumnWidth(columnDrag.width + event.clientX - columnDrag.x, true);
});
for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) $("workspace-resizer").addEventListener(type, finishColumnResize);
$("workspace-resizer").addEventListener("keydown", event => {
  if (busy || window.innerWidth <= 800) return;
  const current = Number($("workspace-resizer").getAttribute("aria-valuenow"));
  const widths = {ArrowLeft: current - 16, ArrowRight: current + 16, Home: 240, End: columnWidthLimit()};
  if (!(event.key in widths)) return;
  event.preventDefault(); setColumnWidth(widths[event.key], true);
});
new ResizeObserver(() => {
  if (window.innerWidth <= 800) finishColumnResize();
  setColumnWidth(preferredColumnWidth);
}).observe($("table-workspace"));
for (const id of Object.values(optionIds)) $(id).onchange = optionsChanged;
for (const name of ["attachments", "tables", "all"]) $("preset-" + name).onclick = () => applyPreset(name);
$("reanalyze").onclick = () => loadData({reuse: true});
$("cancel-load").onclick = async () => {
  $("cancel-load").disabled = true;
  try { await api("cancel", {}); notice("현재 메일 처리를 마치고 분석을 중지합니다.", "loading"); }
  catch (error) { notice(error.message, "error"); }
  finally { $("cancel-load").disabled = false; }
};
$("output-path").oninput = () => { outputTouched = true; };
$("export").onclick = async () => {
  if (!canExport()) return;
  setBusy(true); notice("선택한 기능의 결과를 저장하는 중…", "loading");
  try {
    const result = await api("export", {dataset, columns, options: getOptions(), output: $("output-path").value});
    $("download-link").href = result.download; $("log-link").href = result.log;
    $("download-link").textContent = result.download.endsWith("/xlsx") ? "Excel 다시 받기" : "결과 ZIP 다시 받기";
    $("archive-link").href = result.archive;
    $("excel-link").hidden = !result.excel || result.download.endsWith("/xlsx");
    if (result.excel) $("excel-link").href = result.excel;
    $("download-message").textContent = `${result.total}개 메일의 결과가 준비되었습니다.` + (result.columns ? ` Excel ${result.columns}개 열을 저장했습니다.` : "");
    $("saved-location").textContent = $("output-path").value.trim() ? `저장 위치: ${result.output_path}` : "브라우저 다운로드로 보관하세요. 임시 결과는 프로그램 종료 시 정리됩니다.";
    $("download-banner").hidden = false; $("download-link").click(); dirty = false; notice("");
  } catch (error) { notice(error.message, "error"); }
  finally { setBusy(false); renderColumns(); $("export").disabled = !canExport(); if (activeTab !== "tables") refreshDetails(); }
};
$("shutdown").onclick = async () => {
  if (!window.confirm("프로그램을 종료할까요? 저장하지 않은 열 구성은 사라집니다.")) return;
  try { await api("shutdown", {}); stopped = true; setBusy(true); notice("프로그램이 종료되었습니다. 이 탭을 닫아도 됩니다."); }
  catch (error) { notice(error.message, "error"); }
};
window.addEventListener("beforeunload", event => { if (dirty && !stopped) { event.preventDefault(); event.returnValue = ""; } });
(async () => {
  updatePresets();
  setColumnWidth(preferredColumnWidth);
  updateOutputPlan();
  try {
    const state = await api("state");
    if (state.phase === "ready") installDataset(state);
    else if (state.phase === "loading") { setBusy(true); await pollLoad(); }
    else if (state.initial_source) { $("source-path").value = state.initial_source; await loadData({source: state.initial_source}); }
  } catch (error) { notice(`프로그램에 연결하지 못했습니다. BAT 파일로 다시 시작해 주세요. ${error.message}`, "error"); }
})();
