const $ = id => document.getElementById(id);
const SYNC_SELECTOR = "h1,h2,h3,h4,h5,h6,p,table,blockquote,.admonition,.manual-text-row,pre,ul,ol,li,img";
const EDITABLE_SELECTOR = "h1,h2,h3,h4,h5,h6,p,th,td,li,blockquote,.admonition,.manual-text-row,img";
const state = {
  documents: new Map(), activeId: null, saveTimer: null, workspace: null, workspaceSessions: new Map(),
  pickingWorkspace: false, openingWorkspaceFiles: new Set(),
  documentLoad: { token: 0, startedAt: 0, timer: null, hideTimer: null },
  preview: { token: 0, startedAt: 0, timer: null, hideTimer: null },
  visual: { token: 0, loadedId: null, selected: null, textTarget: null, headingPrefix: "", dirty: false },
  sync: { locked: false, unlockTimer: null, ratio: 0, index: 0 },
  composition: { projectId: null, sources: [], chapters: [], selectedId: null, yamlPath: null, output: "output/manual.html", dirty: false }
};

function toast(message) {
  const element = $("toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(element.timer);
  element.timer = setTimeout(() => element.classList.remove("show"), 2600);
}

function startDocumentProgress(label) {
  const token = ++state.documentLoad.token;
  clearInterval(state.documentLoad.timer);
  clearTimeout(state.documentLoad.hideTimer);
  state.documentLoad.startedAt = performance.now();
  const progress = $("documentProgress");
  const text = $("documentProgressText");
  progress.classList.remove("error", "hidden");
  const updateElapsed = () => {
    const elapsed = (performance.now() - state.documentLoad.startedAt) / 1000;
    text.textContent = `${label}を読み込んでいます… ${elapsed.toFixed(1)}秒`;
  };
  updateElapsed();
  state.documentLoad.timer = setInterval(updateElapsed, 100);
  return token;
}

function finishDocumentProgress(token, completed, message = "") {
  if (token !== state.documentLoad.token) return;
  clearInterval(state.documentLoad.timer);
  state.documentLoad.timer = null;
  const progress = $("documentProgress");
  if (!completed) {
    progress.classList.add("error");
    $("documentProgressText").textContent = `ファイルを読み込めません: ${message}`;
    state.documentLoad.hideTimer = setTimeout(() => progress.classList.add("hidden"), 5000);
    return;
  }
  const elapsed = (performance.now() - state.documentLoad.startedAt) / 1000;
  $("documentProgressText").textContent = `${message}（${elapsed.toFixed(1)}秒）`;
  state.documentLoad.hideTimer = setTimeout(() => progress.classList.add("hidden"), 1200);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) {}
    throw new Error(detail);
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response.text();
}

function activeDocument() { return state.documents.get(state.activeId); }

function renderDocumentList() {
  const nav = $("documents");
  nav.innerHTML = "";
  if (!state.documents.size) {
    nav.innerHTML = '<p class="empty">まだありません</p>';
    return;
  }
  for (const item of state.documents.values()) {
    const button = window.document.createElement("button");
    button.className = `document-button${item.session_id === state.activeId ? " active" : ""}`;
    button.textContent = item.filename;
    button.title = item.filename;
    button.onclick = () => activateDocument(item.session_id);
    nav.appendChild(button);
  }
}

function renderWorkspaceTree() {
  const container = $("workspaceTree");
  container.innerHTML = "";
  if (!state.workspace) return;
  const root = {};
  for (const path of state.workspace.files) {
    let node = root;
    const parts = path.split("/");
    parts.forEach((part, index) => {
      node[part] ||= { children: {}, file: index === parts.length - 1 ? path : null };
      node = node[part].children;
    });
  }
  const appendNodes = (nodes, parent) => {
    Object.entries(nodes).forEach(([name, node]) => {
      if (node.file) {
        const button = window.document.createElement("button");
        button.className = `tree-file${state.workspaceSessions.has(node.file) ? " open" : ""}`;
        button.textContent = `📄 ${name}`;
        button.title = node.file;
        button.onclick = () => openWorkspaceFile(node.file);
        parent.appendChild(button);
      } else {
        const details = window.document.createElement("details");
        details.open = true;
        const summary = window.document.createElement("summary");
        summary.textContent = `📁 ${name}`;
        details.appendChild(summary);
        appendNodes(node.children, details);
        parent.appendChild(details);
      }
    });
  };
  appendNodes(root, container);
}

function withScrollSyncLock(action) {
  state.sync.locked = true;
  clearTimeout(state.sync.unlockTimer);
  action();
  state.sync.unlockTimer = setTimeout(() => { state.sync.locked = false; }, 80);
}

function frameScrollRatio(frame) {
  const scrolling = frame?.contentDocument?.scrollingElement;
  if (!scrolling) return 0;
  const maximum = scrolling.scrollHeight - scrolling.clientHeight;
  return maximum > 0 ? scrolling.scrollTop / maximum : 0;
}

function scrollFrameToRatio(frame, ratio) {
  const scrolling = frame?.contentDocument?.scrollingElement;
  if (!scrolling) return;
  const maximum = Math.max(0, scrolling.scrollHeight - scrolling.clientHeight);
  scrolling.scrollTop = maximum * Math.max(0, Math.min(1, ratio));
}

function frameSyncElements(frame) {
  const article = frame?.contentDocument?.querySelector("article");
  if (!article) return [];
  const candidates = [...article.querySelectorAll(SYNC_SELECTOR)];
  return candidates.filter(element => {
    const parentAnchor = element.parentElement?.closest(SYNC_SELECTOR);
    return !parentAnchor || !article.contains(parentAnchor);
  });
}

function assignFrameSyncIndexes(frame) {
  const elements = frameSyncElements(frame);
  elements.forEach((element, index) => { element.dataset.manualToolSyncIndex = String(index); });
  return elements;
}

function frameIndexAtViewport(frame) {
  const elements = frameSyncElements(frame);
  if (!elements.length) return 0;
  let nearest = 0;
  let distance = Number.POSITIVE_INFINITY;
  elements.forEach((element, index) => {
    const current = Math.abs(element.getBoundingClientRect().top - 24);
    if (current < distance) { distance = current; nearest = index; }
  });
  return nearest;
}

function scrollFrameToIndex(frame, index) {
  const elements = frameSyncElements(frame);
  const target = elements[Math.max(0, Math.min(elements.length - 1, index))];
  if (target) target.scrollIntoView({ block: "start" });
}

function scrollEditorToRatio(ratio) {
  const editor = $("editor");
  const maximum = Math.max(0, editor.scrollHeight - editor.clientHeight);
  editor.scrollTop = maximum * Math.max(0, Math.min(1, ratio));
}

function synchronizeFromFrame(frame) {
  if (state.sync.locked) return;
  state.sync.ratio = frameScrollRatio(frame);
  state.sync.index = frameIndexAtViewport(frame);
  withScrollSyncLock(() => {
    [$("preview"), $("visualEditor")].forEach(other => {
      if (other !== frame) scrollFrameToIndex(other, state.sync.index);
    });
    scrollEditorToRatio(state.sync.ratio);
  });
}

function synchronizeFromEditor() {
  if (state.sync.locked) return;
  const editor = $("editor");
  const maximum = Math.max(0, editor.scrollHeight - editor.clientHeight);
  state.sync.ratio = maximum > 0 ? editor.scrollTop / maximum : 0;
  const anchors = frameSyncElements($("preview"));
  state.sync.index = anchors.length > 1 ? Math.round(state.sync.ratio * (anchors.length - 1)) : 0;
  withScrollSyncLock(() => {
    scrollFrameToRatio($("preview"), state.sync.ratio);
    scrollFrameToRatio($("visualEditor"), state.sync.ratio);
  });
}

function bindFrameScrollSync(frame) {
  assignFrameSyncIndexes(frame);
  scrollFrameToRatio(frame, state.sync.ratio);
  frame.contentWindow?.addEventListener("scroll", () => synchronizeFromFrame(frame), { passive: true });
}

function resolveEditableElement(target, article) {
  if (!article || !target || !article.contains(target)) return null;
  const cell = target.closest("th,td");
  const fixedBlock = target.closest(".admonition,.manual-text-row,blockquote");
  const listItem = target.closest("li");
  const regular = target.closest("h1,h2,h3,h4,h5,h6,p,img");
  const selected = cell || fixedBlock || listItem || regular;
  return selected && article.contains(selected) ? selected : null;
}

function listItemTextTarget(item) {
  return item.querySelector(":scope > p, :scope > .manual-list-text") || item;
}

function listItemText(item, target) {
  if (target !== item || !item.querySelector(":scope > ul, :scope > ol")) return target.textContent || "";
  const copy = item.cloneNode(true);
  copy.querySelectorAll(":scope > ul, :scope > ol").forEach(list => list.remove());
  return copy.textContent || "";
}

function replaceListItemText(item, text) {
  const target = listItemTextTarget(item);
  if (target !== item || !item.querySelector(":scope > ul, :scope > ol")) {
    target.textContent = text;
    return target;
  }
  const nestedList = item.querySelector(":scope > ul, :scope > ol");
  [...item.childNodes].forEach(node => {
    if (!(node.nodeType === Node.ELEMENT_NODE && node.matches("ul,ol"))) node.remove();
  });
  const marker = item.ownerDocument.createElement("span");
  marker.className = "manual-list-text";
  marker.textContent = text;
  item.insertBefore(marker, nestedList);
  return marker;
}

function editableElementIndex(frame, element) {
  const article = frame?.contentDocument?.querySelector("article");
  return article ? [...article.querySelectorAll(EDITABLE_SELECTOR)].indexOf(element) : -1;
}

async function openVisualEditorAt(editIndex, syncIndex) {
  state.sync.index = Math.max(0, syncIndex);
  const loaded = await showVisualEditor();
  if (!loaded) return;
  const frame = $("visualEditor");
  scrollFrameToIndex(frame, state.sync.index);
  const article = frame.contentDocument?.querySelector("article");
  const target = article ? [...article.querySelectorAll(EDITABLE_SELECTOR)][editIndex] : null;
  if (target) selectVisualElement(target);
}

function bindPreviewSelection(frame) {
  const article = frame.contentDocument?.querySelector("article");
  if (!article) return;
  frame.contentDocument.addEventListener("click", event => {
    const selected = resolveEditableElement(event.target, article);
    if (!selected) return;
    event.preventDefault();
    const syncAnchor = selected.closest("[data-manual-tool-sync-index]");
    const syncIndex = Number.parseInt(syncAnchor?.dataset.manualToolSyncIndex || "0", 10);
    openVisualEditorAt(editableElementIndex(frame, selected), syncIndex);
  }, true);
}

function sourceLineText(line) {
  const plain = (line.trim().startsWith("|") ? line.replace(/\|/g, " ") : line).trim()
    .replace(/^\s{0,3}#{1,6}\s*/, "")
    .replace(/^\s*(?:>\s*|[-+*]\s+|\d+[.)]\s+)/, "")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_`~]/g, "");
  const parsed = new DOMParser().parseFromString(plain, "text/html");
  return (parsed.body.textContent || "").replace(/\s+/g, "");
}

function previewIssueTarget(frame, lines, lineIndex) {
  const article = frame?.contentDocument?.querySelector("article");
  if (!article) return null;
  const candidates = [...article.querySelectorAll("h1,h2,h3,h4,h5,h6,p,li,th,td,pre,table,blockquote,.admonition")]
    .filter(element => !element.closest(".toc"));
  // Separator and closing-tag lines belong to the preceding visible content.
  for (let index = lineIndex; index >= 0; index--) {
    const text = sourceLineText(lines[index]);
    if (!text || /^[|:=-]+$/.test(text)) continue;
    const matches = candidates.filter(element =>
      (element.textContent || "").replace(/[*_`~\s]/g, "").includes(text)
    );
    const leaves = matches.filter(element => !matches.some(other => other !== element && element.contains(other)));
    if (!leaves.length) return null;
    const occurrence = lines.slice(0, index).filter(line => sourceLineText(line) === text).length;
    return leaves[Math.min(occurrence, leaves.length - 1)];
  }
  return null;
}

function goToIssue(issue) {
  if (!issue.line) { toast("この指摘は文書全体が対象です"); return; }
  const editor = $("editor");
  const lines = editor.value.split("\n");
  const lineIndex = Math.max(0, Math.min(lines.length - 1, issue.line - 1));
  if (!$("previewPanel").classList.contains("hidden")) {
    if ($("preview").dataset.sourceMarkdown !== editor.value) {
      toast("元データが変更されています。プレビューを再表示してください"); return;
    }
    const target = previewIssueTarget($("preview"), lines, lineIndex);
    if (!target) { toast(`プレビュー内で特定できません。元データの行 ${issue.line} を確認してください`); return; }
    withScrollSyncLock(() => target.scrollIntoView({ block: "center" }));
    target.animate(
      [{ outline: "3px solid #f59e0b" }, { outline: "3px solid transparent" }],
      { duration: 1800 }
    );
    return;
  }
  const start = lines.slice(0, lineIndex).reduce((length, line) => length + line.length + 1, 0);
  editor.setSelectionRange(start, start + lines[lineIndex].length);
  activatePanel("editPanel");
  editor.focus({ preventScroll: true });
  const lineHeight = Number.parseFloat(getComputedStyle(editor).lineHeight);
  editor.scrollTop = Math.max(0, lineIndex * lineHeight - editor.clientHeight / 2);
  updateLineNumbers();
  synchronizeFromEditor();
}

function updateLineNumbers() {
  const editor = $("editor");
  const count = editor.value.split("\n").length;
  const numbers = $("lineNumberContent");
  if (numbers.dataset.count !== String(count)) {
    numbers.textContent = Array.from({ length: count }, (_, index) => index + 1).join("\n");
    numbers.dataset.count = String(count);
  }
  numbers.style.transform = `translateY(-${editor.scrollTop}px)`;
}

function renderIssues() {
  const document = activeDocument();
  const issues = document?.issues || [];
  $("downloadIssueReport").disabled = !document;
  $("issueCount").textContent = `${issues.length}件`;
  const container = $("issues");
  container.innerHTML = "";
  if (!issues.length) {
    container.innerHTML = '<p class="empty" style="padding:16px">指摘はありません。</p>';
    return;
  }
  for (const issue of issues) {
    const item = window.document.createElement("article");
    item.className = "issue";
    item.tabIndex = issue.line ? 0 : -1;
    if (issue.line) {
      item.classList.add("issue-navigable");
      item.onclick = () => goToIssue(issue);
      item.onkeydown = event => {
        if (event.target === item && ["Enter", " "].includes(event.key)) { event.preventDefault(); goToIssue(issue); }
      };
    }
    item.innerHTML = `<div class="issue-head"><span class="badge ${issue.level}">${issue.level}</span><small>${issue.line ? `行 ${issue.line}` : "文書全体"}</small></div><p></p><div class="issue-actions"></div>`;
    item.querySelector("p").textContent = issue.message;
    const actions = item.querySelector(".issue-actions");
    if (issue.replacement !== null) {
      const apply = window.document.createElement("button");
      apply.textContent = "修正を適用";
      apply.onclick = event => { event.stopPropagation(); applyIssue(issue.id); };
      actions.appendChild(apply);
    }
    const ignore = window.document.createElement("button");
    ignore.textContent = "無視";
    ignore.onclick = event => { event.stopPropagation(); ignoreIssue(issue.id); };
    actions.appendChild(ignore);
    container.appendChild(item);
  }
}

function clearVisualSelection() {
  state.visual.selected?.classList.remove("manual-tool-selected");
  state.visual.selected = null;
  state.visual.textTarget = null;
  state.visual.headingPrefix = "";
  $("selectedElementType").textContent = "未選択";
  $("propertyHelp").classList.remove("hidden");
  $("headingNumberField").classList.add("hidden");
  $("elementTextField").classList.add("hidden");
  $("elementFontSizeField").classList.add("hidden");
  $("elementBoldField").classList.add("hidden");
  $("textRowUnderlineField").classList.add("hidden");
  $("imageReplacementField").classList.add("hidden");
  $("blockToolsField").classList.add("hidden");
  $("imageToolsField").classList.add("hidden");
  $("tableToolsField").classList.add("hidden");
  $("insertTableField").classList.add("hidden");
  $("deleteSelectedImage").classList.add("hidden");
  $("deleteSelectedBlock").classList.add("hidden");
  $("applyVisualChange").disabled = true;
  $("replacementImage").value = "";
  $("insertImage").value = "";
  $("elementFontSize").value = "";
  $("elementBold").checked = false;
  $("textRowUnderline").value = "none";
  $("textRowUnderlineColor").value = "#17365d";
  $("tableCellWidth").value = "";
  $("tableCellHeight").value = "";
  $("tableCellBackground").value = "#fff2cc";
}

function resetVisualEditor() {
  state.visual.token += 1;
  state.visual.loadedId = null;
  state.visual.dirty = false;
  clearVisualSelection();
  $("saveVisualHtml").disabled = true;
  const frame = $("visualEditor");
  if (frame) frame.srcdoc = "";
}

function splitHeadingNumber(text) {
  const match = text.match(/^((?:[0-9０-９]+[.．])+\s*)/);
  return match ? { prefix: match[1], title: text.slice(match[1].length) } : { prefix: "", title: text };
}

function selectVisualElement(target) {
  const frameDocument = $("visualEditor").contentDocument;
  const article = frameDocument?.querySelector("article");
  const selected = resolveEditableElement(target, article);
  if (!selected) return;

  clearVisualSelection();
  state.visual.selected = selected;
  selected.classList.add("manual-tool-selected");
  const syncAnchor = selected.closest("[data-manual-tool-sync-index]");
  if (syncAnchor) {
    state.sync.index = Number.parseInt(syncAnchor.dataset.manualToolSyncIndex, 10) || 0;
    const anchors = frameSyncElements($("visualEditor"));
    state.sync.ratio = anchors.length > 1 ? state.sync.index / (anchors.length - 1) : 0;
    withScrollSyncLock(() => {
      scrollFrameToIndex($("preview"), state.sync.index);
      scrollEditorToRatio(state.sync.ratio);
    });
  }
  $("propertyHelp").classList.add("hidden");
  $("applyVisualChange").disabled = false;
  $("blockToolsField").classList.remove("hidden");
  $("imageToolsField").classList.remove("hidden");
  $("insertTableField").classList.remove("hidden");

  if (selected.matches("img")) {
    $("selectedElementType").textContent = "画像";
    $("imageReplacementField").classList.remove("hidden");
    $("deleteSelectedImage").classList.remove("hidden");
    return;
  }

  let type = "本文";
  let textTarget = selected;
  if (selected.matches("h1,h2,h3,h4,h5,h6")) {
    type = "見出し";
    const heading = splitHeadingNumber(selected.textContent || "");
    state.visual.headingPrefix = heading.prefix;
    $("headingNumber").value = heading.prefix.trim() || "（番号なし）";
    $("headingNumberField").classList.remove("hidden");
    $("elementText").value = heading.title;
  } else if (selected.matches("th,td")) {
    type = "表セル";
    $("elementText").value = selected.textContent || "";
    $("tableToolsField").classList.remove("hidden");
    const merged = Boolean(selected.closest("table")?.querySelector('[rowspan]:not([rowspan="1"]),[colspan]:not([colspan="1"])'));
    ["applyTableColumnWidth", "applyTableRowHeight", "insertRowBefore", "insertRowAfter", "deleteTableRow", "insertColumnBefore", "insertColumnAfter", "deleteTableColumn"].forEach(id => { $(id).disabled = merged; });
    $("mergedTableNotice").classList.toggle("hidden", !merged);
    $("tableCellWidth").value = cellPointValue(selected, "width") || "";
    $("tableCellHeight").value = cellPointValue(selected, "height") || "";
    const background = selected.dataset.manualToolCellBackground || selected.style.backgroundColor || selected.ownerDocument.defaultView.getComputedStyle(selected).backgroundColor;
    const backgroundHex = cssColorToHex(background);
    if (backgroundHex) $("tableCellBackground").value = backgroundHex;
  } else if (selected.matches("li")) {
    type = "リスト項目";
    textTarget = listItemTextTarget(selected);
    $("elementText").value = listItemText(selected, textTarget);
  } else if (selected.matches(".admonition,.manual-text-row,blockquote")) {
    type = selected.matches(".manual-text-row") ? "文字列行" : "Note / Warning";
    textTarget = selected.querySelector("p:not(.admonition-title)") || selected.querySelector("p") || selected;
    $("elementText").value = textTarget.textContent || "";
  } else {
    $("elementText").value = selected.textContent || "";
  }
  state.visual.textTarget = textTarget;
  $("selectedElementType").textContent = type;
  $("elementTextField").classList.remove("hidden");
  $("elementFontSizeField").classList.remove("hidden");
  $("elementBoldField").classList.remove("hidden");
  const fontMarker = textTarget.matches(".manual-font-size,.manual-bold") ? textTarget : textTarget.querySelector(".manual-font-size,.manual-bold");
  $("elementFontSize").value = fontMarker?.classList.contains("manual-font-size") ? fontMarker.dataset.manualToolFontSize || fontMarker.style.fontSize.replace(/pt$/i, "") : "";
  $("elementBold").checked = Boolean(fontMarker?.classList.contains("manual-bold"));
  if (selected.matches("p,.manual-text-row")) {
    $("textRowUnderlineField").classList.remove("hidden");
    const underline = selected.dataset.manualToolUnderline || (/3(?:\.0)?pt/i.test(selected.style.borderBottomWidth) ? "thick" : /1(?:\.0)?pt/i.test(selected.style.borderBottomWidth) ? "thin" : "none");
    $("textRowUnderline").value = ["thin", "thick"].includes(underline) ? underline : "none";
    const underlineColor = cssColorToHex(selected.dataset.manualToolUnderlineColor || selected.style.borderBottomColor);
    if (underlineColor) $("textRowUnderlineColor").value = underlineColor;
  }
  if (selected.matches("p,.admonition,.manual-text-row,blockquote")) $("deleteSelectedBlock").classList.remove("hidden");
}

function bindVisualEditor() {
  const frame = $("visualEditor");
  const frameDocument = frame.contentDocument;
  if (!frameDocument?.querySelector("article")) return;
  const style = frameDocument.createElement("style");
  style.setAttribute("data-manual-tool-editor-style", "");
  style.textContent = `article h1,article h2,article h3,article h4,article h5,article h6,article p,article th,article td,article li,article blockquote,article .admonition,article .manual-text-row,article img{cursor:pointer} article h1:hover,article h2:hover,article h3:hover,article h4:hover,article h5:hover,article h6:hover,article p:hover,article th:hover,article td:hover,article li:hover,article blockquote:hover,article .admonition:hover,article .manual-text-row:hover,article img:hover{outline:2px dashed #2684ff;outline-offset:2px}.manual-tool-selected{outline:3px solid #f59e0b!important;outline-offset:3px!important}`;
  frameDocument.head.appendChild(style);
  bindFrameScrollSync(frame);
  frameDocument.addEventListener("click", event => {
    event.preventDefault();
    selectVisualElement(event.target);
  }, true);
}

async function refreshVisualEditor(sessionId, markdown) {
  const token = ++state.visual.token;
  clearVisualSelection();
  $("saveVisualHtml").disabled = true;
  try {
    const html = await api(`/api/documents/${sessionId}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown })
    });
    if (token !== state.visual.token || state.activeId !== sessionId) return;
    const frame = $("visualEditor");
    const loaded = await new Promise(resolve => { frame.onload = () => {
      if (token !== state.visual.token || state.activeId !== sessionId) { resolve(false); return; }
      state.visual.loadedId = sessionId;
      state.visual.dirty = false;
      bindVisualEditor();
      resolve(true);
    }; frame.srcdoc = html; });
    return loaded;
  } catch (error) {
    toast(`編集ビューを表示できません: ${error.message}`);
    return false;
  }
}

async function showVisualEditor() {
  const item = activeDocument();
  if (!item) return false;
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
  item.markdown = $("editor").value;
  if (state.visual.loadedId !== item.session_id) {
    if (!await refreshVisualEditor(item.session_id, item.markdown)) return false;
  }
  activatePanel("visualEditPanel");
  scrollFrameToIndex($("visualEditor"), state.sync.index);
  return true;
}

async function applyVisualChange() {
  const selected = state.visual.selected;
  if (!selected) return;
  const fontSize = $("elementFontSize").value.trim();
  if (!selected.matches("img") && fontSize) {
    const parsed = Number.parseFloat(fontSize);
    if (!Number.isFinite(parsed) || parsed < 6 || parsed > 72) { toast("フォントサイズは6～72ptで指定してください"); return; }
  }
  if (selected.matches("img")) {
    const file = $("replacementImage").files[0];
    if (!file) { toast("差し替える画像を選択してください"); return; }
    const form = new FormData();
    form.append("file", file);
    try {
      const uploaded = await api(`/api/documents/${state.activeId}/assets/images`, { method: "POST", body: form });
      selected.setAttribute("src", uploaded.preview_url);
      selected.setAttribute("data-manual-tool-asset-path", uploaded.path);
    } catch (error) { toast(error.message); return; }
  } else if (selected.matches("h1,h2,h3,h4,h5,h6")) {
    selected.textContent = `${state.visual.headingPrefix}${$("elementText").value}`;
  } else if (selected.matches("li")) {
    state.visual.textTarget = replaceListItemText(selected, $("elementText").value);
  } else if (state.visual.textTarget) {
    state.visual.textTarget.textContent = $("elementText").value;
  }
  if (!selected.matches("img") && state.visual.textTarget) applyTextFontSize(state.visual.textTarget);
  if (selected.matches("p,.manual-text-row")) applyTextBlockUnderline(selected);
  state.visual.dirty = true;
  $("saveVisualHtml").disabled = false;
  $("saveState").textContent = "未保存";
  toast("編集ビューへ反映しました");
}

function applyTextFontSize(target) {
  const raw = $("elementFontSize").value.trim();
  const bold = $("elementBold").checked;
  if (!raw && !bold) return;
  const marker = target.ownerDocument.createElement("span");
  if (raw) {
    const size = Number.parseFloat(raw);
    const normalized = String(Math.round(size * 2) / 2);
    marker.classList.add("manual-font-size");
    marker.dataset.manualToolFontSize = normalized;
    marker.style.fontSize = `${normalized}pt`;
  }
  if (bold) {
    marker.classList.add("manual-bold");
    marker.style.fontWeight = "700";
  }
  while (target.firstChild) marker.appendChild(target.firstChild);
  target.appendChild(marker);
}

function applyTextBlockUnderline(row) {
  const mode = $("textRowUnderline").value;
  delete row.dataset.manualToolUnderline;
  delete row.dataset.manualToolUnderlineColor;
  row.style.removeProperty("border-bottom");
  if (row.matches("p")) row.classList.remove("manual-underlined-block");
  if (mode === "none") return;
  const color = $("textRowUnderlineColor").value.toLowerCase();
  if (row.matches("p")) row.classList.add("manual-underlined-block");
  row.dataset.manualToolUnderline = mode;
  row.dataset.manualToolUnderlineColor = color;
  row.style.borderBottom = `${mode === "thick" ? 3 : 1}pt solid ${color}`;
}

function markVisualStructureDirty(message) {
  state.visual.dirty = true;
  $("saveVisualHtml").disabled = false;
  $("saveState").textContent = "未保存";
  assignFrameSyncIndexes($("visualEditor"));
  if (message) toast(message);
}

async function uploadVisualImage(input) {
  const file = input.files[0];
  if (!file) { toast("追加する画像を選択してください"); return null; }
  const form = new FormData();
  form.append("file", file);
  try {
    return await api(`/api/documents/${state.activeId}/assets/images`, { method: "POST", body: form });
  } catch (error) {
    toast(error.message);
    return null;
  }
}

function selectedBlockAnchor() {
  const selected = state.visual.selected;
  if (!selected) return null;
  if (selected.matches("th,td")) return selected.closest("table");
  if (selected.matches("li")) return selected.closest("ul,ol");
  if (selected.matches("img")) return selected.closest("p,figure") || selected;
  return selected;
}

function openInsertTextDialog() {
  if (!selectedBlockAnchor()) return;
  $("newTextRowContent").value = "";
  $("newTextRowPosition").value = "after";
  $("newTextRowHasBackground").checked = false;
  $("newTextRowColorField").classList.add("hidden");
  $("insertTextDialog").showModal();
  $("newTextRowContent").focus();
}

function insertTextRow() {
  const anchor = selectedBlockAnchor();
  const text = $("newTextRowContent").value;
  if (!anchor?.parentElement) { $("insertTextDialog").close(); return; }
  if (!text.trim()) { toast("追加する文字列を入力してください"); return; }
  const document = anchor.ownerDocument;
  const row = document.createElement("div");
  row.className = "manual-text-row";
  if ($("newTextRowHasBackground").checked) {
    const color = $("newTextRowColor").value.toLowerCase();
    row.dataset.manualToolBackground = color;
    row.style.backgroundColor = color;
  }
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  row.appendChild(paragraph);
  anchor.insertAdjacentElement($("newTextRowPosition").value === "before" ? "beforebegin" : "afterend", row);
  $("insertTextDialog").close();
  markVisualStructureDirty("文字列行を追加しました");
  selectVisualElement(row);
}

function deleteSelectedBlock() {
  const selected = state.visual.selected;
  if (!selected?.matches("p,.admonition,.manual-text-row,blockquote")) return;
  selected.remove();
  clearVisualSelection();
  markVisualStructureDirty("選択ブロックを削除しました");
}

async function insertImageAtSelection(position) {
  const anchor = selectedBlockAnchor();
  if (!anchor?.parentElement) return;
  const uploaded = await uploadVisualImage($("insertImage"));
  if (!uploaded) return;
  const paragraph = anchor.ownerDocument.createElement("p");
  const image = anchor.ownerDocument.createElement("img");
  image.setAttribute("src", uploaded.preview_url);
  image.setAttribute("data-manual-tool-asset-path", uploaded.path);
  image.setAttribute("alt", "");
  paragraph.appendChild(image);
  anchor.insertAdjacentElement(position === "before" ? "beforebegin" : "afterend", paragraph);
  markVisualStructureDirty("画像を追加しました");
  selectVisualElement(image);
}

function deleteSelectedImage() {
  const image = state.visual.selected;
  if (!image?.matches("img")) return;
  const parent = image.parentElement;
  if (parent?.matches("p,figure") && parent.children.length === 1 && !parent.textContent.trim()) parent.remove();
  else image.remove();
  clearVisualSelection();
  markVisualStructureDirty("画像を削除しました");
}

function editableTableCell() {
  const cell = state.visual.selected;
  if (!cell?.matches("th,td")) return null;
  const table = cell.closest("table");
  if (!table || table.querySelector('[rowspan]:not([rowspan="1"]),[colspan]:not([colspan="1"])')) return null;
  return cell;
}

function cellPointValue(cell, dimension) {
  const dataName = dimension === "width" ? "manualToolCellWidth" : "manualToolCellHeight";
  if (cell.dataset[dataName]) return cell.dataset[dataName];
  const match = (cell.getAttribute("style") || "").match(new RegExp(`(?:^|;)\\s*${dimension}\\s*:\\s*(\\d+(?:\\.\\d+)?)pt(?:;|$)`, "i"));
  return match?.[1] || "";
}

function normalizedTablePointInput(id) {
  const raw = $(id).value.trim();
  if (!raw) return null;
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) && value >= 6 && value <= 720 ? String(Math.round(value * 2) / 2) : undefined;
}

function setCellPointSize(cell, width = undefined, height = undefined) {
  if (width !== undefined) {
    delete cell.dataset.manualToolCellWidth;
    cell.style.removeProperty("width");
    cell.style.removeProperty("min-width");
    if (width) {
      cell.dataset.manualToolCellWidth = width;
      cell.style.width = `${width}pt`;
      cell.style.minWidth = `${width}pt`;
    }
  }
  if (height !== undefined) {
    delete cell.dataset.manualToolCellHeight;
    cell.style.removeProperty("height");
    if (height) {
      cell.dataset.manualToolCellHeight = height;
      cell.style.height = `${height}pt`;
    }
  }
}

function refreshPointSizedTable(table) {
  const hasPointSize = [...table.querySelectorAll("th,td")].some(cell => cellPointValue(cell, "width") || cellPointValue(cell, "height"));
  table.classList.toggle("manual-table-points", hasPointSize);
}

function applyTableColumnWidth() {
  const cell = state.visual.selected;
  const table = cell?.closest("table");
  if (!table) return;
  const width = normalizedTablePointInput("tableCellWidth");
  if (width === undefined) { toast("列の横幅は6～720ptで指定してください"); return; }
  table.classList.remove("manual-table-uniform", "manual-table-compact");
  const columnIndex = cell.cellIndex;
  [...table.rows].forEach(row => {
    const target = row.cells[columnIndex];
    if (target) setCellPointSize(target, width, undefined);
  });
  refreshPointSizedTable(table);
  markVisualStructureDirty("選択列の横幅を変更しました");
  selectVisualElement(cell);
}

function applyTableRowHeight() {
  const cell = state.visual.selected;
  const table = cell?.closest("table");
  if (!table) return;
  const height = normalizedTablePointInput("tableCellHeight");
  if (height === undefined) { toast("行の縦幅は6～720ptで指定してください"); return; }
  table.classList.remove("manual-table-uniform", "manual-table-compact");
  [...cell.parentElement.cells].forEach(target => setCellPointSize(target, undefined, height));
  refreshPointSizedTable(table);
  markVisualStructureDirty("選択行の縦幅を変更しました");
  selectVisualElement(cell);
}

function cssColorToHex(color) {
  if (/^#[0-9a-f]{6}$/i.test(color || "")) return color.toLowerCase();
  const match = (color || "").match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)$/i);
  if (match?.[4] === "0") return null;
  return match ? `#${match.slice(1, 4).map(value => Number(value).toString(16).padStart(2, "0")).join("")}` : null;
}

function applyTableCellBackground() {
  const cell = state.visual.selected;
  if (!cell?.matches("th,td")) return;
  const color = $("tableCellBackground").value.toLowerCase();
  cell.dataset.manualToolCellBackground = color;
  cell.style.backgroundColor = color;
  markVisualStructureDirty("セルの背景色を変更しました");
  selectVisualElement(cell);
}

function clearTableCellBackground() {
  const cell = state.visual.selected;
  if (!cell?.matches("th,td")) return;
  cell.dataset.manualToolCellBackground = "transparent";
  cell.style.backgroundColor = "transparent";
  markVisualStructureDirty("セルの背景色を削除しました");
  selectVisualElement(cell);
}

function copyCellPointSize(source, target) {
  setCellPointSize(target, cellPointValue(source, "width") || null, cellPointValue(source, "height") || null);
}

function insertTableRow(position) {
  const cell = editableTableCell();
  if (!cell) return;
  const row = cell.parentElement;
  const added = row.cloneNode(false);
  [...row.cells].forEach(source => {
    const target = source.ownerDocument.createElement(source.tagName.toLowerCase());
    copyCellPointSize(source, target);
    added.appendChild(target);
  });
  row.insertAdjacentElement(position === "before" ? "beforebegin" : "afterend", added);
  markVisualStructureDirty("表へ行を追加しました");
  selectVisualElement(added.cells[Math.min(cell.cellIndex, added.cells.length - 1)]);
}

function deleteTableRow() {
  const cell = editableTableCell();
  if (!cell) return;
  const row = cell.parentElement;
  const table = row.closest("table");
  const rows = [...table.rows];
  if (rows.length === 1) {
    table.remove();
    clearVisualSelection();
  } else {
    const rowIndex = rows.indexOf(row);
    const next = rows[rowIndex + 1] || rows[rowIndex - 1];
    row.remove();
    refreshPointSizedTable(table);
    selectVisualElement(next.cells[Math.min(cell.cellIndex, next.cells.length - 1)]);
  }
  markVisualStructureDirty("表の行を削除しました");
}

function insertTableColumn(position) {
  const cell = editableTableCell();
  if (!cell) return;
  const table = cell.closest("table");
  const columnIndex = cell.cellIndex;
  [...table.rows].forEach(row => {
    const neighbor = row.cells[Math.min(columnIndex, row.cells.length - 1)];
    const added = row.ownerDocument.createElement(neighbor?.tagName.toLowerCase() || "td");
    if (neighbor) copyCellPointSize(neighbor, added);
    if (!neighbor || (position === "after" && columnIndex >= row.cells.length - 1)) row.appendChild(added);
    else row.insertBefore(added, position === "before" ? neighbor : neighbor.nextSibling);
  });
  markVisualStructureDirty("表へ列を追加しました");
  const selectedRow = cell.parentElement;
  const targetIndex = position === "before" ? columnIndex : columnIndex + 1;
  selectVisualElement(selectedRow.cells[targetIndex]);
}

function deleteTableColumn() {
  const cell = editableTableCell();
  if (!cell) return;
  const table = cell.closest("table");
  const columnIndex = cell.cellIndex;
  const rows = [...table.rows];
  const maximumColumns = Math.max(...rows.map(row => row.cells.length));
  if (maximumColumns === 1) {
    table.remove();
    clearVisualSelection();
  } else {
    rows.forEach(row => row.cells[columnIndex]?.remove());
    refreshPointSizedTable(table);
    const targetRow = rows.find(row => row.isConnected && row.cells.length);
    if (targetRow) selectVisualElement(targetRow.cells[Math.min(columnIndex, targetRow.cells.length - 1)]);
  }
  markVisualStructureDirty("表の列を削除しました");
}

function insertTableAfterSelection() {
  const anchor = selectedBlockAnchor();
  if (!anchor?.parentElement) return;
  const rows = Math.max(1, Math.min(50, Number.parseInt($("newTableRows").value, 10) || 1));
  const columns = Math.max(1, Math.min(20, Number.parseInt($("newTableColumns").value, 10) || 1));
  const document = anchor.ownerDocument;
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (let column = 0; column < columns; column += 1) headRow.appendChild(document.createElement("th"));
  head.appendChild(headRow);
  table.appendChild(head);
  if (rows > 1) {
    const body = document.createElement("tbody");
    for (let row = 1; row < rows; row += 1) {
      const bodyRow = document.createElement("tr");
      for (let column = 0; column < columns; column += 1) bodyRow.appendChild(document.createElement("td"));
      body.appendChild(bodyRow);
    }
    table.appendChild(body);
  }
  anchor.insertAdjacentElement("afterend", table);
  markVisualStructureDirty("表を追加しました");
  selectVisualElement(table.rows[0].cells[0]);
}

function visualArticleHtml() {
  const article = $("visualEditor").contentDocument?.querySelector("article");
  if (!article) return null;
  const clone = article.cloneNode(true);
  clone.querySelectorAll(".manual-tool-selected").forEach(element => element.classList.remove("manual-tool-selected"));
  clone.querySelectorAll("img[data-manual-tool-asset-path]").forEach(image => {
    image.setAttribute("src", image.getAttribute("data-manual-tool-asset-path"));
    image.removeAttribute("data-manual-tool-asset-path");
  });
  return clone.innerHTML;
}

async function saveVisualHtml(showMessage = true) {
  const item = activeDocument();
  if (!item || !state.visual.dirty) return true;
  const html = visualArticleHtml();
  if (html === null) { toast("編集内容を取得できませんでした"); return false; }
  try {
    const payload = await api(`/api/documents/${item.session_id}/visual-edit`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html })
    });
    state.documents.set(payload.session_id, payload);
    $("editor").value = payload.markdown;
    updateLineNumbers();
    $("saveState").textContent = "保存済み";
    state.visual.dirty = false;
    $("saveVisualHtml").disabled = true;
    renderDocumentList();
    renderIssues();
    await refreshVisualEditor(payload.session_id, payload.markdown);
    if (showMessage) toast("HTML編集を保存しました");
    return true;
  } catch (error) {
    toast(error.message);
    return false;
  }
}

function loadPayload(payload) {
  resetVisualEditor();
  state.documents.set(payload.session_id, payload);
  if (payload.relative_path) state.workspaceSessions.set(payload.relative_path, payload.session_id);
  state.activeId = payload.session_id;
  $("welcome").classList.add("hidden");
  $("editorArea").classList.remove("hidden");
  $("filename").textContent = payload.filename;
  $("editor").value = payload.markdown;
  updateLineNumbers();
  $("saveState").textContent = "保存済み";
  ["exportButton", "recheck"].forEach(id => $(id).disabled = false);
  renderDocumentList();
  renderWorkspaceTree();
  renderIssues();
  refreshPreview(payload.session_id, payload.markdown);
  requestAnimationFrame(() => window.dispatchEvent(new Event("manualtool:layout")));
}

async function activateDocument(id) {
  const current = activeDocument();
  if (current && current.session_id !== id) {
    if (state.visual.dirty && !await saveVisualHtml(false)) return;
    current.markdown = $("editor").value;
    clearTimeout(state.saveTimer);
    persistDocument(current, false);
  }
  const payload = state.documents.get(id);
  if (payload) loadPayload(payload);
}

function closeDocument(id) {
  const document = state.documents.get(id);
  if (!document) return;
  const wasActive = state.activeId === id;
  state.documents.delete(id);
  if (document.relative_path && state.workspaceSessions.get(document.relative_path) === id) {
    state.workspaceSessions.delete(document.relative_path);
  }
  if (!wasActive) {
    renderDocumentList();
    renderWorkspaceTree();
    return;
  }
  const next = state.documents.values().next().value;
  if (next) {
    loadPayload(next);
    return;
  }
  state.activeId = null;
  resetVisualEditor();
  $("editorArea").classList.add("hidden");
  $("welcome").classList.remove("hidden");
  $("preview").srcdoc = "";
  renderDocumentList();
  renderWorkspaceTree();
  renderIssues();
}

async function pickWorkspace() {
  if (state.pickingWorkspace) return;
  state.pickingWorkspace = true;
  $("openFolder").disabled = true;
  toast("フォルダを選択してください");
  try {
    const result = await api("/api/workspaces/pick", { method: "POST" });
    if (result.cancelled) { toast("フォルダ選択をキャンセルしました"); return; }
    state.workspace = result;
    state.workspaceSessions.clear();
    $("workspaceInfo").classList.remove("hidden");
    $("workspaceName").textContent = result.name;
    $("workspacePath").textContent = result.path;
    $("workspacePath").title = result.path;
    renderWorkspaceTree();
    toast(`${result.files.length}件の対応文書が見つかりました`);
  } catch (error) { toast(error.message); }
  finally {
    state.pickingWorkspace = false;
    $("openFolder").disabled = false;
  }
}

async function openWorkspaceFile(relativePath) {
  const existing = state.workspaceSessions.get(relativePath);
  if (existing && state.documents.has(existing)) {
    activateDocument(existing);
    return;
  }
  if (state.openingWorkspaceFiles.size) return;
  state.openingWorkspaceFiles.add(relativePath);
  const progressToken = startDocumentProgress(relativePath);
  const encoded = relativePath.split("/").map(encodeURIComponent).join("/");
  try {
    const payload = await api(`/api/workspaces/${state.workspace.workspace_id}/documents/${encoded}`, { method: "POST" });
    loadPayload(payload);
    finishDocumentProgress(progressToken, true, `${payload.filename}を読み込みました`);
  } catch (error) {
    finishDocumentProgress(progressToken, false, error.message);
    toast(error.message);
  } finally {
    state.openingWorkspaceFiles.delete(relativePath);
  }
}

function startPreviewProgress() {
  const token = ++state.preview.token;
  clearInterval(state.preview.timer);
  clearTimeout(state.preview.hideTimer);
  state.preview.startedAt = performance.now();
  const progress = $("previewProgress");
  const text = $("previewProgressText");
  progress.classList.remove("error");
  progress.classList.remove("hidden");
  const updateElapsed = () => {
    const elapsed = (performance.now() - state.preview.startedAt) / 1000;
    text.textContent = `プレビューを生成しています… ${elapsed.toFixed(1)}秒`;
  };
  updateElapsed();
  state.preview.timer = setInterval(updateElapsed, 100);
  return token;
}

function finishPreviewProgress(token, completed, errorMessage = "") {
  if (token !== state.preview.token) return;
  clearInterval(state.preview.timer);
  state.preview.timer = null;
  const progress = $("previewProgress");
  if (!completed) {
    if (errorMessage) {
      progress.classList.add("error");
      $("previewProgressText").textContent = `プレビューを表示できません: ${errorMessage}`;
    } else {
      progress.classList.add("hidden");
    }
    return;
  }
  const elapsed = (performance.now() - state.preview.startedAt) / 1000;
  $("previewProgressText").textContent = `プレビューを表示しました（${elapsed.toFixed(1)}秒）`;
  state.preview.hideTimer = setTimeout(() => progress.classList.add("hidden"), 1200);
}

function discardPendingPreviewFrames() {
  document.querySelectorAll("#previewPanel .preview-frame-pending").forEach(frame => frame.remove());
}

function stagePreviewFrame(preview, token, sessionId) {
  if (token !== state.preview.token || state.activeId !== sessionId) return;
  discardPendingPreviewFrames();
  const current = $("preview");
  const frame = window.document.createElement("iframe");
  frame.className = "preview-frame-pending";
  frame.dataset.sourceMarkdown = $("editor").value;
  frame.title = "HTMLプレビュー";
  frame.setAttribute("sandbox", "allow-same-origin");
  frame.hidden = true;
  frame.addEventListener("load", () => {
    if (token !== state.preview.token || state.activeId !== sessionId) {
      frame.remove();
      return;
    }
    current.remove();
    frame.id = "preview";
    frame.classList.remove("preview-frame-pending");
    frame.hidden = false;
    bindFrameScrollSync(frame);
    bindPreviewSelection(frame);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (token === state.preview.token && state.activeId === sessionId) {
        finishPreviewProgress(token, true);
      }
    }));
  }, { once: true });
  current.insertAdjacentElement("afterend", frame);
  frame.srcdoc = preview;
}

async function refreshPreview(sessionId, markdown) {
  const token = startPreviewProgress();
  try {
    const preview = await api(`/api/documents/${sessionId}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown })
    });
    if (token !== state.preview.token || state.activeId !== sessionId) return;
    if (!preview.trim()) throw new Error("生成結果が空でした。もう一度お試しください。");
    if ($("editor").value !== markdown) {
      finishPreviewProgress(token, false, "元データが変更されています。プレビューを再表示してください");
      return;
    }
    stagePreviewFrame(preview, token, sessionId);
  } catch (error) {
    finishPreviewProgress(token, false, error.message);
    if (state.activeId === sessionId) toast(error.message);
  }
}

async function exportDocument() {
  const item = activeDocument();
  if (!item) return;
  if (state.visual.dirty && !await saveVisualHtml(false)) return;
  item.markdown = $("editor").value;
  if (!await persistDocument(item, false)) return;
  toast("書き出し先を選択してください");
  try {
    const result = await api(`/api/documents/${item.session_id}/export`, { method: "POST" });
    if (result.cancelled) {
      toast("書き出しをキャンセルしました");
      return;
    }
    closeDocument(item.session_id);
    toast(`書き出しました: ${result.output_dir}`);
  } catch (error) { toast(error.message); }
}

async function persistDocument(item, showMessage) {
  try {
    const payload = await api(`/api/documents/${item.session_id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown: item.markdown })
    });
    state.documents.set(payload.session_id, payload);
    renderDocumentList();
    if (state.activeId === payload.session_id) {
      $("saveState").textContent = "保存済み";
      state.visual.loadedId = null;
      renderIssues();
    }
    if (showMessage) toast("保存と再チェックが完了しました");
    return true;
  } catch (error) {
    toast(error.message);
    return false;
  }
}

async function saveAndLint(showMessage = false) {
  const item = activeDocument();
  if (!item) return false;
  if (state.visual.dirty) return saveVisualHtml(showMessage);
  item.markdown = $("editor").value;
  return persistDocument(item, showMessage);
}

async function flushActiveDocument() {
  const document = activeDocument();
  if (!document) return null;
  if (state.visual.dirty && !await saveVisualHtml(false)) return null;
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
  document.markdown = $("editor").value;
  return await persistDocument(document, false) ? document : null;
}

async function applyIssue(id) {
  const document = await flushActiveDocument();
  if (!document) return;
  try {
    loadPayload(await api(`/api/documents/${document.session_id}/issues/${encodeURIComponent(id)}/apply`, { method: "POST" }));
    toast("修正を適用しました");
  } catch (error) { toast(error.message); }
}

async function ignoreIssue(id) {
  const document = await flushActiveDocument();
  if (!document) return;
  try {
    loadPayload(await api(`/api/documents/${document.session_id}/issues/${encodeURIComponent(id)}/ignore`, { method: "POST" }));
  } catch (error) { toast(error.message); }
}

async function showPreview() {
  const document = activeDocument();
  if (!document) return;
  await refreshPreview(document.session_id, $("editor").value);
  activatePanel("previewPanel");
}

function activatePanel(panelId) {
  document.querySelectorAll(".panel").forEach(panel => panel.classList.toggle("hidden", panel.id !== panelId));
  document.querySelectorAll(".tab").forEach(tab => tab.classList.toggle("active", tab.dataset.panel === panelId));
  const visual = panelId === "visualEditPanel";
  document.querySelector(".issues-panel").classList.toggle("hidden", visual);
  $("elementProperties").classList.toggle("hidden", !visual);
}

function initializePaneResizer(sidebar = false) {
  const split = sidebar ? $("documentEditorScreen") : document.querySelector(".split");
  const resizer = $(sidebar ? "sidebarResizer" : "paneResizer");
  const storageKey = sidebar ? "manualToolSidebarWidth" : "manualToolIssuesWidth";
  const property = sidebar ? "--sidebar-width" : "--issues-width";
  const minimum = sidebar ? 180 : 260;
  const defaultWidth = sidebar ? 260 : 360;
  const maximumWidth = () => sidebar ? Math.max(minimum, split.clientWidth - 640) : Math.max(minimum, split.clientWidth - 367);
  const clampWidth = width => {
    const maximum = maximumWidth();
    return Math.min(maximum, Math.max(minimum, width));
  };
  const setWidth = width => {
    const next = clampWidth(width);
    split.style.setProperty(property, `${next}px`);
    resizer.setAttribute("aria-valuenow", String(Math.round(next)));
    resizer.setAttribute("aria-valuemax", String(Math.round(maximumWidth())));
    return next;
  };
  const saved = Number.parseInt(localStorage.getItem(storageKey), 10);
  if (Number.isFinite(saved)) {
    split.style.setProperty(property, `${Math.max(minimum, saved)}px`);
    resizer.setAttribute("aria-valuenow", String(Math.max(minimum, saved)));
  }
  const fitToLayout = () => {
    if (!split.clientWidth) return;
    const current = Number.parseInt(getComputedStyle(split).getPropertyValue(property), 10) || defaultWidth;
    setWidth(current);
  };
  window.addEventListener("resize", fitToLayout);
  window.addEventListener("manualtool:layout", fitToLayout);

  let dragging = false;
  resizer.addEventListener("pointerdown", event => {
    dragging = true;
    resizer.setPointerCapture(event.pointerId);
    resizer.classList.add("dragging");
    document.body.classList.add("resizing");
  });
  resizer.addEventListener("pointermove", event => {
    if (!dragging) return;
    const bounds = split.getBoundingClientRect();
    setWidth(sidebar ? event.clientX - bounds.left : bounds.right - event.clientX);
  });
  const finishDrag = event => {
    if (!dragging) return;
    dragging = false;
    if (resizer.hasPointerCapture(event.pointerId)) resizer.releasePointerCapture(event.pointerId);
    resizer.classList.remove("dragging");
    document.body.classList.remove("resizing");
    const width = Number.parseInt(getComputedStyle(split).getPropertyValue(property), 10);
    localStorage.setItem(storageKey, String(width));
  };
  resizer.addEventListener("pointerup", finishDrag);
  resizer.addEventListener("pointercancel", finishDrag);
  resizer.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const current = Number.parseInt(getComputedStyle(split).getPropertyValue(property), 10) || defaultWidth;
    const next = setWidth(current + (event.key === "ArrowLeft" ? (sidebar ? -24 : 24) : (sidebar ? 24 : -24)));
    localStorage.setItem(storageKey, String(next));
  });
}

function showMode(screenId, title, actionsId = null) {
  ["modeChooser", "compositionScreen", "documentEditorScreen"].forEach(id => $(id).classList.toggle("hidden", id !== screenId));
  ["documentActions", "compositionActions"].forEach(id => $(id).classList.toggle("hidden", id !== actionsId));
  $("homeButton").classList.toggle("hidden", screenId === "modeChooser");
  $("modeTitle").textContent = title;
}

function allCompositionNodes(nodes = state.composition.chapters, result = []) {
  nodes.forEach(node => { result.push(node); allCompositionNodes(node.children || [], result); });
  return result;
}

function locateCompositionNode(id, nodes = state.composition.chapters, parent = null, depth = 0) {
  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index];
    const info = { node, array: nodes, index, parent, depth };
    if (node.id === id) return info;
    const nested = locateCompositionNode(id, node.children || [], info, depth + 1);
    if (nested) return nested;
  }
  return null;
}

function uniqueCompositionId(base) {
  const used = new Set(allCompositionNodes().map(node => node.id));
  let candidate = base || "section";
  let suffix = 2;
  while (used.has(candidate)) { candidate = `${base}-${suffix}`; suffix += 1; }
  return candidate;
}

function createCompositionNode(source) {
  return { id: uniqueCompositionId(source.suggested_id), title: source.title, file: source.file, numbered: true, children: [] };
}

function markCompositionDirty() {
  if (!state.composition.projectId) return;
  state.composition.dirty = true;
  if (state.composition.yamlPath) {
    $("compositionYaml").textContent = `${state.composition.yamlPath}（未保存の変更あり）`;
  }
  $("compositionBuildResult").innerHTML = '<p class="empty">変更した構成をYAMLへ保存してから構築してください</p>';
  $("buildManualYaml").disabled = true;
}

function showCompositionIssues(issues = []) {
  const container = $("compositionErrors");
  if (!issues.length) {
    container.innerHTML = '<p class="empty">構成エラーはありません</p>';
    return;
  }
  container.innerHTML = "";
  issues.forEach(issue => {
    const item = document.createElement("div");
    item.className = "validation-issue";
    item.innerHTML = "<strong></strong><span></span>";
    item.querySelector("strong").textContent = issue.code || "ERROR";
    item.querySelector("span").textContent = `${issue.location ? `${issue.location}: ` : ""}${issue.message}`;
    container.appendChild(item);
  });
}

function previewCompositionSource(file) {
  if (!file || !state.composition.projectId) return;
  const encoded = file.split("/").map(encodeURIComponent).join("/");
  $("sourcePreview").src = `/api/manual-editor/${state.composition.projectId}/preview/${encoded}`;
  $("previewSourceName").textContent = file;
}

function renderComposition() {
  const usedFiles = new Set(allCompositionNodes().filter(node => node.file).map(node => node.file));
  $("unusedCount").textContent = `${usedFiles.size}/${state.composition.sources.length}件`;
  const sourceList = $("unusedSources");
  sourceList.innerHTML = "";
  if (!state.composition.sources.length) sourceList.innerHTML = '<p class="empty">HTMLフォルダを選択してください</p>';
  state.composition.sources.forEach(source => {
    const row = document.createElement("div");
    row.className = "source-item";
    const label = document.createElement("span");
    label.textContent = source.title;
    label.title = source.file;
    label.onclick = () => previewCompositionSource(source.file);
    const add = document.createElement("button");
    add.textContent = usedFiles.has(source.file) ? "構成済み" : "追加";
    add.disabled = usedFiles.has(source.file);
    add.onclick = () => {
      const node = createCompositionNode(source);
      state.composition.chapters.push(node);
      state.composition.selectedId = node.id;
      previewCompositionSource(source.file);
      markCompositionDirty();
      renderComposition();
    };
    row.append(label, add);
    sourceList.appendChild(row);
  });

  const structure = $("manualStructure");
  structure.innerHTML = "";
  const renderNodes = (nodes, prefix = [], depth = 0, startingIndex = 0) => {
    let numberedIndex = startingIndex;
    nodes.forEach(node => {
      if (node.numbered !== false) numberedIndex += 1;
      const number = node.numbered !== false ? [...prefix, numberedIndex] : prefix;
      const button = document.createElement("div");
      button.className = `structure-item${node.id === state.composition.selectedId ? " selected" : ""}`;
      button.style.setProperty("--depth", depth);
      button.innerHTML = '<input class="structure-numbered" type="checkbox" title="章番号を付ける"><strong class="structure-number"></strong><span class="structure-name"></span>';
      const numbered = button.querySelector("input");
      numbered.dataset.nodeId = node.id;
      numbered.checked = node.numbered !== false;
      numbered.onclick = event => event.stopPropagation();
      numbered.onchange = event => {
        event.stopPropagation();
        node.numbered = numbered.checked;
        markCompositionDirty();
        renderComposition();
      };
      button.querySelector(".structure-number").textContent = node.numbered !== false ? `${number.join(".")}.` : "-";
      const name = button.querySelector(".structure-name");
      name.textContent = node.title;
      name.title = node.file || "グループ項目";
      if (!node.file) name.classList.add("group");
      button.onclick = () => {
        state.composition.selectedId = node.id;
        if (node.file) previewCompositionSource(node.file);
        renderComposition();
      };
      structure.appendChild(button);
      const source = state.composition.sources.find(item => item.file === node.file);
      const childStartingIndex = node.numbered !== false ? Number(source?.direct_heading_count || 0) : 0;
      renderNodes(node.children || [], number, depth + 1, childStartingIndex);
    });
  };
  renderNodes(state.composition.chapters);
  if (!state.composition.chapters.length) structure.innerHTML = '<p class="empty">構成は空です</p>';

  const selected = locateCompositionNode(state.composition.selectedId);
  $("nodeTitle").disabled = !selected;
  $("nodeTitle").value = selected?.node.title || "";
  ["moveUp", "moveDown", "indentNode", "outdentNode", "removeNode"].forEach(id => $(id).disabled = !selected);
  $("addGroup").disabled = !state.composition.projectId;
  $("saveManualYaml").disabled = !state.composition.projectId;
  $("buildManualYaml").disabled = !state.composition.yamlPath || state.composition.dirty;
}

function loadCompositionPayload(payload) {
  state.composition.projectId = payload.project_id;
  state.composition.sources = payload.sources || [];
  state.composition.yamlPath = payload.yaml_path || null;
  state.composition.dirty = false;
  if (payload.definition) {
    state.composition.chapters = payload.definition.chapters || [];
    state.composition.output = payload.definition.manual.output || "output/manual.html";
    $("manualTitle").value = payload.definition.manual.title || "";
  } else {
    state.composition.chapters = state.composition.sources.map(source => createCompositionNode(source));
    state.composition.output = "output/manual.html";
  }
  state.composition.selectedId = null;
  $("compositionSource").textContent = payload.source_path;
  $("compositionSource").title = payload.source_path;
  $("compositionYaml").textContent = payload.yaml_path || "未保存";
  showCompositionIssues(payload.issues || []);
  renderComposition();
}

async function pickCompositionSource() {
  try {
    const payload = await api("/api/manual-editor/pick-source", { method: "POST" });
    if (!payload.cancelled) loadCompositionPayload(payload);
  } catch (error) { toast(error.message); }
}

function syncCompositionNumberingFromInputs() {
  document.querySelectorAll(".structure-numbered[data-node-id]").forEach(input => {
    const selected = locateCompositionNode(input.dataset.nodeId);
    if (selected) selected.node.numbered = input.checked;
  });
}

async function saveCompositionYaml() {
  if (!state.composition.projectId) return;
  syncCompositionNumberingFromInputs();
  try {
    const result = await api(`/api/manual-editor/${state.composition.projectId}/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: $("manualTitle").value, chapters: state.composition.chapters, output: state.composition.output })
    });
    showCompositionIssues(result.issues || []);
    if (result.saved) {
      state.composition.yamlPath = result.yaml_path;
      state.composition.dirty = false;
      $("compositionYaml").textContent = result.yaml_path;
      $("compositionBuildResult").innerHTML = '<p class="empty">保存済みYAMLから完成版を構築できます</p>';
      renderComposition();
      toast("manual.yamlを保存しました");
    } else {
      toast("構成エラーを修正してください");
    }
  } catch (error) { toast(error.message); }
}

function addCompositionGroup() {
  const id = uniqueCompositionId("group");
  state.composition.chapters.push({ id, title: "新しいグループ", file: null, children: [] });
  state.composition.selectedId = id;
  markCompositionDirty();
  renderComposition();
  $("nodeTitle").focus();
  $("nodeTitle").select();
}

function moveCompositionNode(direction) {
  const info = locateCompositionNode(state.composition.selectedId);
  if (!info) return;
  const target = info.index + direction;
  if (target < 0 || target >= info.array.length) return;
  [info.array[info.index], info.array[target]] = [info.array[target], info.array[info.index]];
  markCompositionDirty();
  renderComposition();
}

function indentCompositionNode() {
  const info = locateCompositionNode(state.composition.selectedId);
  if (!info || info.index === 0) return;
  if (info.depth >= 2) { toast("構成は3階層までです"); return; }
  const parent = info.array[info.index - 1];
  info.array.splice(info.index, 1);
  parent.children ||= [];
  parent.children.push(info.node);
  markCompositionDirty();
  renderComposition();
}

function outdentCompositionNode() {
  const info = locateCompositionNode(state.composition.selectedId);
  if (!info?.parent) return;
  const parentInfo = info.parent;
  info.array.splice(info.index, 1);
  parentInfo.array.splice(parentInfo.index + 1, 0, info.node);
  markCompositionDirty();
  renderComposition();
}

function removeCompositionNode() {
  const info = locateCompositionNode(state.composition.selectedId);
  if (!info) return;
  info.array.splice(info.index, 1);
  state.composition.selectedId = null;
  markCompositionDirty();
  renderComposition();
}

async function runManualBuild() {
  if (!state.composition.projectId || !state.composition.yamlPath || state.composition.dirty) {
    toast("現在の構成をYAMLへ保存してから構築してください");
    return;
  }
  const resultBox = $("compositionBuildResult");
  resultBox.innerHTML = '<p>構築しています…</p>';
  try {
    const result = await api(`/api/manual-editor/${state.composition.projectId}/build`, { method: "POST" });
    if (!result.success) {
      resultBox.innerHTML = '<p class="build-error">構成エラーがあります。</p>';
      result.issues.forEach(issue => {
        const row = document.createElement("div");
        row.className = "validation-issue";
        row.textContent = `${issue.location}: ${issue.message}`;
        resultBox.appendChild(row);
      });
      return;
    }
    resultBox.innerHTML = `<p class="build-success">構築が完了しました</p><p>出力: <strong></strong></p><p>見出し: ${result.heading_count}件</p>`;
    resultBox.querySelector("strong").textContent = result.output_path;
  } catch (error) { resultBox.innerHTML = `<p class="build-error"></p>`; resultBox.querySelector("p").textContent = error.message; }
}

$("openFolder").onclick = pickWorkspace;
$("exportButton").onclick = exportDocument;
$("downloadIssueReport").onclick = () => {
  const item = activeDocument();
  if (item) window.location.assign(`/api/documents/${item.session_id}/download/report-markdown`);
};
$("editor").addEventListener("input", () => {
  updateLineNumbers();
  const item = activeDocument();
  if (item) item.markdown = $("editor").value;
  state.visual.loadedId = null;
  $("saveState").textContent = "未保存";
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => saveAndLint(false), 900);
});
$("editor").addEventListener("scroll", () => {
  updateLineNumbers();
  synchronizeFromEditor();
}, { passive: true });
$("recheck").onclick = () => saveAndLint(true);
document.querySelectorAll(".tab").forEach(tab => tab.onclick = async () => {
  if (tab.dataset.panel === "visualEditPanel") { await showVisualEditor(); return; }
  if (state.visual.dirty && !await saveVisualHtml(false)) return;
  if (tab.dataset.panel === "previewPanel") await showPreview();
  else activatePanel(tab.dataset.panel);
});
$("applyVisualChange").onclick = applyVisualChange;
$("saveVisualHtml").onclick = () => saveVisualHtml(true);
$("openInsertTextDialog").onclick = openInsertTextDialog;
$("cancelInsertText").onclick = () => $("insertTextDialog").close();
$("confirmInsertText").onclick = insertTextRow;
$("newTextRowHasBackground").onchange = event => $("newTextRowColorField").classList.toggle("hidden", !event.target.checked);
$("deleteSelectedBlock").onclick = deleteSelectedBlock;
$("applyTableColumnWidth").onclick = applyTableColumnWidth;
$("applyTableRowHeight").onclick = applyTableRowHeight;
$("applyTableCellBackground").onclick = applyTableCellBackground;
$("clearTableCellBackground").onclick = clearTableCellBackground;
$("insertImageBefore").onclick = () => insertImageAtSelection("before");
$("insertImageAfter").onclick = () => insertImageAtSelection("after");
$("deleteSelectedImage").onclick = deleteSelectedImage;
$("insertRowBefore").onclick = () => insertTableRow("before");
$("insertRowAfter").onclick = () => insertTableRow("after");
$("deleteTableRow").onclick = deleteTableRow;
$("insertColumnBefore").onclick = () => insertTableColumn("before");
$("insertColumnAfter").onclick = () => insertTableColumn("after");
$("deleteTableColumn").onclick = deleteTableColumn;
$("insertTableAfter").onclick = insertTableAfterSelection;
$("homeButton").onclick = () => showMode("modeChooser", "ローカル・マニュアルツール");
$("chooseComposition").onclick = () => showMode("compositionScreen", "マニュアル編集", "compositionActions");
$("chooseDocumentEditor").onclick = () => showMode("documentEditorScreen", "個別ファイル編集", "documentActions");
$("pickHtmlFolder").onclick = pickCompositionSource;
$("saveManualYaml").onclick = saveCompositionYaml;
$("addGroup").onclick = addCompositionGroup;
$("moveUp").onclick = () => moveCompositionNode(-1);
$("moveDown").onclick = () => moveCompositionNode(1);
$("indentNode").onclick = indentCompositionNode;
$("outdentNode").onclick = outdentCompositionNode;
$("removeNode").onclick = removeCompositionNode;
$("nodeTitle").addEventListener("change", event => {
  const selected = locateCompositionNode(state.composition.selectedId);
  if (selected) { selected.node.title = event.target.value; markCompositionDirty(); renderComposition(); }
});
$("manualTitle").addEventListener("input", markCompositionDirty);
$("buildManualYaml").onclick = runManualBuild;
initializePaneResizer();
initializePaneResizer(true);
updateLineNumbers();
