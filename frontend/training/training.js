const API = "../../backend/api/training.php";
const MAX_FILE_SIZE = 10 * 1024 * 1024;
const $ = (id) => document.getElementById(id);
const canvas = $("imageCanvas");
const context = canvas.getContext("2d");
let classes = [];
let samples = [];
let annotations = [];
let currentImage = null;
let currentFile = null;
let previewObjectUrl = null;
let editingId = null;
let pendingFiles = [];
let pendingIndex = 0;
let dragStart = null;
let dragEnd = null;
let pollTimer = null;
let currentJobId = null;
let availableModels = [];

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const raw = await response.text();
  let payload;
  try {
    payload = JSON.parse(raw.replace(/^\uFEFF/, "").trim());
  } catch {
    throw new Error(`เซิร์ฟเวอร์ส่งคำตอบที่ไม่ใช่ JSON (HTTP ${response.status})`);
  }
  if (!response.ok || !payload.success)
    throw new Error(payload.message || `คำขอไม่สำเร็จ (HTTP ${response.status})`);
  return payload.data;
}

function colorFor(className) {
  const index = Math.max(0, classes.indexOf(className));
  return `hsl(${(index * 137.508) % 360} 85% 48%)`;
}

function canvasPoint(event) {
  const bounds = canvas.getBoundingClientRect();
  return [
    Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
    Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
  ];
}

function drawCanvas() {
  if (!currentImage) return;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(currentImage, 0, 0, canvas.width, canvas.height);
  annotations.forEach(({ class_name: className, box }, index) => {
    const [x1, y1, x2, y2] = box;
    const left = x1 * canvas.width;
    const top = y1 * canvas.height;
    const width = (x2 - x1) * canvas.width;
    const height = (y2 - y1) * canvas.height;
    const color = colorFor(className);
    context.lineWidth = Math.max(2, canvas.width / 500);
    context.strokeStyle = color;
    context.fillStyle = color;
    context.strokeRect(left, top, width, height);
    const label = `${index + 1}. ${className}`;
    context.font = `bold ${Math.max(12, canvas.width / 65)}px sans-serif`;
    const labelWidth = context.measureText(label).width + 10;
    const labelHeight = Math.max(20, canvas.width / 45);
    const labelTop = Math.max(0, top - labelHeight);
    context.fillRect(left, labelTop, labelWidth, labelHeight);
    context.fillStyle = "#fff";
    context.fillText(label, left + 5, labelTop + labelHeight * 0.72);
  });
  if (dragStart && dragEnd) {
    const left = Math.min(dragStart[0], dragEnd[0]) * canvas.width;
    const top = Math.min(dragStart[1], dragEnd[1]) * canvas.height;
    const width = Math.abs(dragEnd[0] - dragStart[0]) * canvas.width;
    const height = Math.abs(dragEnd[1] - dragStart[1]) * canvas.height;
    context.save();
    context.strokeStyle = colorFor($("classSelect").value);
    context.lineWidth = Math.max(2, canvas.width / 500);
    context.setLineDash([8, 5]);
    context.strokeRect(left, top, width, height);
    context.restore();
  }
  renderAnnotationList();
}

function setImage(source, file = null) {
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = source.startsWith("blob:") ? source : null;
  currentFile = file;
  const image = new Image();
  image.onload = () => {
    currentImage = image;
    const scale = Math.min(1, 1400 / Math.max(image.naturalWidth, image.naturalHeight));
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    $("canvasWrap").hidden = false;
    drawCanvas();
    updateEditorState();
  };
  image.onerror = () => setEditorMessage("อ่านภาพไม่ได้ เลือกไฟล์ภาพใหม่อีกครั้ง", true);
  image.src = source;
}

function showQueuedFile() {
  const file = pendingFiles[pendingIndex];
  if (!file) return;
  editingId = null;
  annotations = [];
  currentImage = null;
  dragStart = null;
  dragEnd = null;
  $("canvasWrap").hidden = true;
  context.clearRect(0, 0, canvas.width, canvas.height);
  renderAnnotationList();
  setImage(URL.createObjectURL(file), file);
  updateEditorState();
}

async function uploadPendingBatch(files) {
  const input = $("imageInput");
  const status = $("bulkUploadMessage");
  const failures = [];
  let uploadedCount = 0;
  let pendingRouteUnavailable = false;
  input.disabled = true;
  $("startTraining").disabled = true;
  status.className = "small text-body-secondary mb-3";
  for (let index = 0; index < files.length; index += 1) {
    const file = files[index];
    status.textContent = "กำลังอัปโหลด " + (index + 1) + "/" + files.length + " · " + file.name;
    const form = new FormData();
    form.append("image", file, file.name);
    try {
      await requestJson(API + "?action=pending-image", { method: "POST", body: form });
      uploadedCount += 1;
    } catch (error) {
      if (error.message === "ไม่พบ endpoint ที่ร้องขอ") {
        pendingRouteUnavailable = true;
        break;
      }
      failures.push(file.name + ": " + error.message);
    }
  }
  await loadDataset();
  input.disabled = false;
  if (pendingRouteUnavailable) {
    status.textContent = "AI service ยังไม่มี API อัปโหลดเป็นชุด · หยุด service เดิมแล้วรัน python ai/app.py ใหม่";
    status.className = "small text-danger mb-3";
  } else if (failures.length) {
    status.textContent = "อัปโหลดสำเร็จ " + uploadedCount + "/" + files.length
      + " ภาพ · " + failures.join(" · ");
    status.className = "small text-danger mb-3";
  } else {
    status.textContent = "อัปโหลดครบ " + files.length + " ภาพแล้ว · คลิก “ติดป้ายกำกับ” ในรายการภาพก่อน Fine-tune";
    status.className = "small text-success mb-3";
  }
}

function setEditorMessage(message, isError = false) {
  $("editorMessage").textContent = message;
  $("editorMessage").className = `small mt-2 ${isError ? "text-danger" : "text-body-secondary"}`;
}

function updateEditorState() {
  const canSave = !!currentImage && !!currentFile && annotations.length > 0;
  const canUpdate = !!currentImage && !!editingId && annotations.length > 0;
  $("saveImage").disabled = !(canSave || canUpdate);
  $("saveImage").textContent = editingId
    ? "บันทึกป้ายกำกับ"
    : pendingFiles.length > 1 && pendingIndex < pendingFiles.length - 1
      ? "บันทึกและไปภาพถัดไป" : "บันทึกภาพและป้ายกำกับ";
  $("undoBox").disabled = annotations.length === 0;
  $("cancelEdit").hidden = !editingId && pendingFiles.length === 0;
  $("cancelEdit").textContent = editingId ? "ยกเลิกแก้ไข" : "ยกเลิกชุดภาพ";
  $("skipImage").hidden = pendingFiles.length < 2;
  const queueProgress = pendingFiles.length > 1
    ? `ภาพ ${pendingIndex + 1}/${pendingFiles.length} · ` : "";
  if (!currentImage) setEditorMessage(queueProgress + "เลือกภาพก่อนเริ่มวาดกรอบ");
  else if (!$("classSelect").value) setEditorMessage(queueProgress + "เลือกคลาสสินค้า แล้วลากกรอบครอบสินค้าแต่ละชิ้น");
  else setEditorMessage(queueProgress + `ลากกรอบครอบสินค้า · บันทึกแล้ว ${annotations.length} กรอบ`);
}

function renderAnnotationList() {
  const list = $("annotationList");
  list.replaceChildren();
  annotations.forEach(({ class_name: className }, index) => {
    const row = document.createElement("div");
    row.className = "list-group-item d-flex justify-content-between align-items-center gap-3 py-2";
    const label = document.createElement("span");
    label.textContent = `${index + 1}. ${className}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn-outline-danger btn-sm";
    remove.textContent = "ลบกรอบ";
    remove.setAttribute("aria-label", `ลบกรอบ ${index + 1} ${className}`);
    remove.onclick = () => {
      annotations.splice(index, 1);
      drawCanvas();
      updateEditorState();
    };
    row.append(label, remove);
    list.append(row);
  });
}

canvas.addEventListener("pointerdown", (event) => {
  if (!currentImage || !$("classSelect").value) return;
  event.preventDefault();
  canvas.setPointerCapture(event.pointerId);
  dragStart = canvasPoint(event);
  dragEnd = dragStart;
  drawCanvas();
});
canvas.addEventListener("pointermove", (event) => {
  if (!dragStart) return;
  dragEnd = canvasPoint(event);
  drawCanvas();
});
canvas.addEventListener("pointerup", (event) => {
  if (!dragStart) return;
  dragEnd = canvasPoint(event);
  const x1 = Math.min(dragStart[0], dragEnd[0]);
  const y1 = Math.min(dragStart[1], dragEnd[1]);
  const x2 = Math.max(dragStart[0], dragEnd[0]);
  const y2 = Math.max(dragStart[1], dragEnd[1]);
  dragStart = null;
  dragEnd = null;
  if ((x2 - x1) * canvas.width < 8 || (y2 - y1) * canvas.height < 8) {
    drawCanvas();
    return;
  }
  annotations.push({ class_name: $("classSelect").value, box: [x1, y1, x2, y2] });
  drawCanvas();
  updateEditorState();
});
canvas.addEventListener("pointercancel", () => {
  dragStart = null;
  dragEnd = null;
  drawCanvas();
});

$("imageInput").addEventListener("change", async (event) => {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;
  const invalidFile = files.find((file) =>
    !["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > MAX_FILE_SIZE
  );
  if (invalidFile) {
    const reason = !["image/jpeg", "image/png", "image/webp"].includes(invalidFile.type)
      ? "รองรับภาพ JPG, PNG และ WEBP"
      : "ภาพแต่ละไฟล์ต้องมีขนาดไม่เกิน 10 MB";
    return setEditorMessage(invalidFile.name + ": " + reason, true);
  }
  if ((annotations.length || editingId || pendingFiles.length > 1)
      && !confirm("ยกเลิกงานภาพปัจจุบัน แล้วเลือกชุดภาพใหม่หรือไม่?")) return;
  if (files.length > 1) {
    resetEditor();
    await uploadPendingBatch(files);
    return;
  }
  pendingFiles = files;
  pendingIndex = 0;
  showQueuedFile();
});
$("classSelect").addEventListener("change", updateEditorState);
$("undoBox").addEventListener("click", () => {
  annotations.pop();
  drawCanvas();
  updateEditorState();
});
$("cancelEdit").addEventListener("click", () => {
  const canceledQueue = pendingFiles.length > 0;
  resetEditor();
  if (canceledQueue) $("datasetMessage").textContent = "ยกเลิกชุดภาพแล้ว";
});
$("skipImage").addEventListener("click", () => {
  if (pendingFiles.length < 2) return;
  const skippedName = pendingFiles[pendingIndex].name;
  if (pendingIndex + 1 < pendingFiles.length) {
    pendingIndex += 1;
    showQueuedFile();
    $("datasetMessage").textContent = "ข้าม " + skippedName + " แล้ว";
  } else {
    resetEditor();
    $("datasetMessage").textContent = "ข้าม " + skippedName + " แล้ว · จบชุดภาพ";
  }
});

function resetEditor() {
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = null;
  currentImage = null;
  currentFile = null;
  editingId = null;
  pendingFiles = [];
  pendingIndex = 0;
  annotations = [];
  dragStart = null;
  dragEnd = null;
  $("canvasWrap").hidden = true;
  context.clearRect(0, 0, canvas.width, canvas.height);
  renderAnnotationList();
  updateEditorState();
}

$("saveImage").addEventListener("click", async () => {
  if (!annotations.length) return setEditorMessage("วาดกรอบสินค้าอย่างน้อย 1 กรอบ", true);
  const button = $("saveImage");
  button.disabled = true;
  $("imageInput").disabled = true;
  $("skipImage").disabled = true;
  $("cancelEdit").disabled = true;
  const wasEditing = Boolean(editingId);
  try {
    let result;
    if (editingId) {
      result = await requestJson(`${API}?action=annotations&id=${encodeURIComponent(editingId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ annotations }),
      });
    } else {
      const form = new FormData();
      form.append("image", currentFile, currentFile.name);
      form.append("annotations", JSON.stringify(annotations));
      result = await requestJson(`${API}?action=image`, { method: "POST", body: form });
    }
    if (wasEditing) {
      resetEditor();
      $("datasetMessage").textContent = "บันทึกป้ายกำกับ " + result.filename + " แล้ว";
    } else if (pendingFiles.length > 1 && pendingIndex + 1 < pendingFiles.length) {
      pendingIndex += 1;
      showQueuedFile();
      $("datasetMessage").textContent = "บันทึก " + result.filename + " แล้ว · กำลังทำภาพ "
        + (pendingIndex + 1) + "/" + pendingFiles.length;
    } else {
      resetEditor();
      $("datasetMessage").textContent = "บันทึก " + result.filename + " แล้ว";
    }
    await loadDataset();
  } catch (error) {
    setEditorMessage(error.message, true);
  } finally {
    $("imageInput").disabled = false;
    $("skipImage").disabled = false;
    $("cancelEdit").disabled = false;
    updateEditorState();
  }
});

async function openSample(id) {
  if ((annotations.length || editingId || pendingFiles.length > 1)
      && !confirm("ยกเลิกงานภาพปัจจุบัน แล้วเปิดภาพชุดฝึกนี้หรือไม่?")) return;
  try {
    const sample = await requestJson(`${API}?action=image&id=${encodeURIComponent(id)}`);
    pendingFiles = [];
    pendingIndex = 0;
    editingId = sample.id;
    annotations = sample.annotations;
    setImage(sample.image);
    $("datasetMessage").textContent = `กำลังแก้ป้ายกำกับ ${sample.filename}`;
  } catch (error) {
    $("datasetMessage").textContent = `เปิดภาพไม่ได้: ${error.message}`;
  }
}

async function loadDataset() {
  try {
    const [rows, classList] = await Promise.all([
      requestJson(`${API}?action=images`),
      classes.length ? Promise.resolve(classes) : requestJson(`${API}?action=classes`),
    ]);
    classes = classList;
    const select = $("classSelect");
    const selected = select.value;
    select.replaceChildren(new Option("เลือกคลาสสินค้า", ""));
    classes.forEach((name) => select.append(new Option(name, name)));
    select.value = classes.includes(selected) ? selected : "";
    select.disabled = classes.length === 0;
    samples = rows;
    const targetSelect = $("fineTuneClass");
    const previousTarget = targetSelect.value;
    targetSelect.replaceChildren(new Option("เลือกคลาสเป้าหมาย", ""));
    classes.forEach((name) => targetSelect.append(new Option(name, name)));
    const labeledClasses = classes.filter((name) =>
      samples.some((row) => (row.class_counts?.[name] || 0) > 0)
    );
    targetSelect.value = classes.includes(previousTarget)
      ? previousTarget
      : labeledClasses.length === 1 ? labeledClasses[0] : "";
    targetSelect.disabled = classes.length === 0
      || ["queued", "running"].includes(window.latestTrainingStatus);
    renderDataset();
    updateEditorState();
  } catch (error) {
    $("datasetSummary").textContent = `โหลดชุดฝึกไม่ได้: ${error.message}`;
    $("trainingReadiness").textContent = "ตรวจว่า AI service ทำงานอยู่ แล้วกดรีเฟรช";
  }
}

function renderDataset() {
  const labeledCount = samples.filter((row) => row.annotation_count > 0).length;
  const pendingCount = samples.length - labeledCount;
  const totalBoxes = samples.reduce((sum, row) => sum + row.annotation_count, 0);
  const targetClass = $("fineTuneClass").value;
  const targetImageCount = targetClass
    ? samples.filter((row) => (row.class_counts?.[targetClass] || 0) > 0).length
    : 0;
  $("datasetSummary").textContent = `${samples.length} ภาพ · ติดป้ายแล้ว ${labeledCount} · รอติดป้าย ${pendingCount} · ${totalBoxes} กรอบสินค้า`;
  $("trainingReadiness").textContent = !targetClass
    ? "เลือกคลาสเป้าหมายที่จะ Fine-tune"
    : targetImageCount < 4
      ? `คลาส ${targetClass} มีภาพติดป้าย ${targetImageCount}/4 ภาพ · ต้องมีอย่างน้อย 4 ภาพ`
      : `${targetImageCount} ภาพของ ${targetClass} พร้อมฝึก · คลาสอื่นจะคงน้ำหนักเดิม`;
  $("startTraining").disabled = !targetClass || targetImageCount < 4
    || ["queued", "running"].includes(window.latestTrainingStatus);

  const totals = Object.fromEntries(classes.map((name) => [name, 0]));
  samples.forEach((row) => Object.entries(row.class_counts).forEach(([name, count]) => {
    totals[name] = (totals[name] || 0) + count;
  }));
  const coverage = $("classCoverage");
  coverage.replaceChildren();
  classes.forEach((name) => {
    const item = document.createElement("div");
    item.className = "coverage-item";
    item.textContent = `${name}: ${totals[name] || 0}`;
    item.title = `${name} · ${totals[name] || 0} กรอบ`;
    coverage.append(item);
  });

  const list = $("imageList");
  list.replaceChildren();
  if (!samples.length) {
    const empty = document.createElement("p");
    empty.className = "small text-body-secondary mb-0";
    empty.textContent = "ยังไม่มีภาพในชุดฝึก";
    list.append(empty);
    return;
  }
  samples.forEach((sample) => {
    const row = document.createElement("div");
    row.className = "list-group-item d-flex justify-content-between align-items-center gap-3";
    const detail = document.createElement("div");
    detail.className = "min-w-0";
    const name = document.createElement("strong");
    name.className = "d-block text-truncate";
    name.textContent = sample.filename;
    const count = document.createElement("small");
    count.className = "text-body-secondary";
    count.textContent = sample.annotation_count > 0
      ? `${sample.annotation_count} กรอบ · ${sample.width}×${sample.height}`
      : `รอติดป้ายกำกับ · ${sample.width}×${sample.height}`;
    detail.append(name, count);
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "btn btn-outline-primary btn-sm flex-shrink-0";
    edit.textContent = sample.annotation_count > 0 ? "แก้ป้ายกำกับ" : "ติดป้ายกำกับ";
    edit.onclick = () => openSample(sample.id);
    row.append(detail, edit);
    list.append(row);
  });
}

$("refreshDataset").addEventListener("click", loadDataset);

const jobLabels = {
  queued: "รอเริ่ม", running: "กำลังฝึก", completed: "ฝึกเสร็จแล้ว",
  activated: "เปิดใช้แล้ว", failed: "ฝึกไม่สำเร็จ", interrupted: "หยุดกลางคัน",
};

function renderJob(job) {
  if (!job) {
    $("jobPanel").hidden = true;
    window.latestTrainingStatus = "";
    renderDataset();
    return;
  }
  currentJobId = job.id;
  window.latestTrainingStatus = job.status;
  $("jobPanel").hidden = false;
  $("fineTuneClass").disabled = !classes.length || ["queued", "running"].includes(job.status);
  $("jobStatus").textContent = `${jobLabels[job.status] || job.status} · ${job.id.slice(0, 8)}`;
  $("jobProgressText").textContent = job.status === "running" || job.status === "completed"
    ? `Epoch ${job.epoch}/${job.epochs}` : "";
  $("jobProgress").style.width = `${job.progress || 0}%`;
  $("jobProgress").parentElement.setAttribute("aria-valuenow", String(job.progress || 0));
  $("jobProgress").classList.toggle("progress-bar-animated", ["queued", "running"].includes(job.status));
  $("jobMessage").textContent = job.message || "";
  const metricEntries = Object.entries(job.metrics || {}).slice(0, 8);
  $("jobMetrics").textContent = metricEntries.length
    ? `Validation: ${metricEntries.map(([key, value]) => `${key} ${value}`).join(" · ")}`
    : "";
  const targetClass = $("fineTuneClass").value;
  const targetImageCount = targetClass
    ? samples.filter((row) => (row.class_counts?.[targetClass] || 0) > 0).length
    : 0;
  $("startTraining").disabled = !targetClass || targetImageCount < 4
    || ["queued", "running"].includes(job.status);
  if (job.status === "completed") loadModels("job:" + job.id);
  if (["queued", "running"].includes(job.status)) schedulePoll();
  else if (pollTimer) clearTimeout(pollTimer);
}

function renderModels(preferredId = "") {
  const select = $("modelSelect");
  const previousId = preferredId || select.value;
  select.replaceChildren();
  if (!availableModels.length) {
    select.append(new Option("ไม่พบโมเดล", ""));
    $("activateSelectedModel").disabled = true;
    return;
  }
  availableModels.forEach((model) => {
    const label = model.current ? model.label + " · กำลังใช้" : model.label;
    select.append(new Option(label, model.id));
  });
  select.value = availableModels.some((model) => model.id === previousId)
    ? previousId
    : (availableModels.find((model) => model.current)?.id || availableModels[0].id);
  updateModelSelection();
}

function updateModelSelection() {
  const selected = availableModels.find((model) => model.id === $("modelSelect").value);
  $("activateSelectedModel").disabled = !selected || selected.current;
  if (selected) {
    $("modelMessage").textContent = selected.current
      ? "กำลังใช้โมเดลนี้อยู่ · " + selected.model_hash.slice(0, 12)
      : "เลือกไว้ · " + selected.model_hash.slice(0, 12) + " · ยังไม่ได้เปิดใช้";
  }
}

async function loadModels(preferredId = "") {
  try {
    availableModels = await requestJson(API + "?action=models");
    renderModels(preferredId);
    $("modelMessage").className = "small text-body-secondary mt-2 mb-0";
  } catch (error) {
    $("modelSelect").replaceChildren(new Option("โหลดรายการโมเดลไม่สำเร็จ", ""));
    $("activateSelectedModel").disabled = true;
    $("modelMessage").textContent = error.message === "ไม่พบ endpoint ที่ร้องขอ"
      ? "AI service ยังไม่โหลด API เลือกโมเดล ให้หยุด service เดิมแล้วรัน python ai/app.py ใหม่"
      : error.message;
    $("modelMessage").className = "small text-danger mt-2 mb-0";
  }
}

async function refreshJob() {
  try {
    const job = await requestJson(`${API}?action=job${currentJobId ? `&id=${encodeURIComponent(currentJobId)}` : ""}`);
    renderJob(job);
  } catch (error) {
    $("jobMessage").textContent = `โหลดสถานะงานไม่ได้: ${error.message}`;
  }
}

function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    await refreshJob();
  }, 2500);
}

$("startTraining").addEventListener("click", async () => {
  const epochs = Number($("epochs").value);
  if (!Number.isInteger(epochs) || epochs < 5 || epochs > 100)
    return $("trainingReadiness").textContent = "ตั้ง epochs ได้ตั้งแต่ 5 ถึง 100";
  const button = $("startTraining");
  button.disabled = true;
  try {
    const job = await requestJson(`${API}?action=start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ epochs, target_class: $("fineTuneClass").value }),
    });
    currentJobId = job.id;
    renderJob(job);
  } catch (error) {
    $("trainingReadiness").textContent = error.message;
    const targetClass = $("fineTuneClass").value;
    button.disabled = !targetClass
      || samples.filter((row) => (row.class_counts?.[targetClass] || 0) > 0).length < 4;
  }
});

$("fineTuneClass").addEventListener("change", renderDataset);
$("modelSelect").addEventListener("change", updateModelSelection);
$("refreshModels").addEventListener("click", () => loadModels());

$("activateSelectedModel").addEventListener("click", async () => {
  const selected = availableModels.find((model) => model.id === $("modelSelect").value);
  if (!selected || selected.current) return;
  if (!confirm("เปิดใช้ “" + selected.label + "” หรือไม่? โมเดลที่ใช้อยู่จะถูกเก็บเป็นข้อมูลสำรอง")) return;
  const button = $("activateSelectedModel");
  button.disabled = true;
  try {
    const result = await requestJson(API + "?action=activate-model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: selected.id }),
    });
    await loadModels();
    $("modelMessage").textContent = result.message + " · " + result.active_model.slice(0, 12);
    $("modelMessage").className = "small text-success mt-2 mb-0";
  } catch (error) {
    $("modelMessage").textContent = error.message;
    $("modelMessage").className = "small text-danger mt-2 mb-0";
    button.disabled = false;
  }
});

async function initialize() {
  await loadDataset();
  await loadModels();
  await refreshJob();
}
initialize();
