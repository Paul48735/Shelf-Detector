const API_BASE = "../../backend/api";
const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];

const form = document.querySelector("#detectionForm");
const productConfidence = document.querySelector("#productConfidence");
const gapConfidence = document.querySelector("#gapConfidence");
const imageInput = document.querySelector("#imageInput");
const dropZone = document.querySelector("#dropZone");
const fileInfo = document.querySelector("#fileInfo");
const fileName = document.querySelector("#fileName");
const submitButton = document.querySelector("#submitButton");
const formError = document.querySelector("#formError");
const previewImage = document.querySelector("#previewImage");
const alignmentNotice = document.querySelector("#alignmentNotice");
const emptyState = document.querySelector("#emptyState");
const imageStage = document.querySelector("#imageStage");
const imageCaption = document.querySelector("#imageCaption");
const resultPanel = document.querySelector("#resultPanel");
const planogramSelect = document.querySelector("#planogramSelect");
const perspectiveEnabled = document.querySelector("#perspectiveEnabled");
const perspectivePanel = document.querySelector("#perspectivePanel");
const perspectiveStatus = document.querySelector("#perspectiveStatus");
const perspectiveOriginal = document.querySelector("#perspectiveOriginal");
const perspectiveCorrected = document.querySelector("#perspectiveCorrected");
const noCorrectedImage = document.querySelector("#noCorrectedImage");
const cornerOverlay = document.querySelector("#cornerOverlay");
const confirmCorners = document.querySelector("#confirmCorners");
let selectedFile = null;
let previewUrl = null;
let perspectiveCorners = [];
let perspectiveReady = false;
let manualDrawing = false;
let perspectiveRevision = 0;

function drawPerspectiveCorners() {
  cornerOverlay.replaceChildren();
  if (!perspectiveCorners.length) return;
  const points = perspectiveCorners.map(([x, y]) => `${x * 1000},${y * 1000}`).join(" ");
  const shape = document.createElementNS("http://www.w3.org/2000/svg",
    perspectiveCorners.length === 4 ? "polygon" : "polyline");
  shape.setAttribute("points", points);
  shape.setAttribute("fill", perspectiveCorners.length === 4 ? "#0d6efd22" : "none");
  shape.setAttribute("stroke", "#0d6efd");
  shape.setAttribute("stroke-width", "5");
  cornerOverlay.append(shape);
  perspectiveCorners.forEach(([x, y], index) => {
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.setAttribute("cx", x * 1000);
    dot.setAttribute("cy", y * 1000);
    dot.setAttribute("r", "12");
    dot.setAttribute("fill", "#0d6efd");
    cornerOverlay.append(dot);
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", x * 1000 + 15);
    label.setAttribute("y", y * 1000 - 12);
    label.setAttribute("font-size", "32");
    label.setAttribute("font-weight", "700");
    label.textContent = String(index + 1);
    cornerOverlay.append(label);
  });
}

async function analyzePerspective(corners = null) {
  if (!selectedFile || !planogramSelect.value || !perspectiveEnabled.checked) return;
  const revision = ++perspectiveRevision;
  perspectiveReady = false;
  updateSubmitState();
  perspectiveStatus.textContent = corners ? "กำลังปรับภาพจาก 4 มุมที่เลือก..." : "กำลังหามุมชั้นวางอัตโนมัติ...";
  const body = new FormData();
  body.append("image", selectedFile, selectedFile.name);
  body.append("planogram_id", planogramSelect.value);
  if (corners) body.append("corners", JSON.stringify(corners));
  try {
    const response = await fetch(`${API_BASE}/perspective.php`, { method: "POST", body });
    const payload = await readJsonResponse(response);
    if (revision !== perspectiveRevision) return;
    if (!response.ok || !payload.success) throw new Error(payload.message || "ปรับภาพไม่สำเร็จ");
    const analysis = payload.data;
    perspectiveCorners = analysis.corners || [];
    drawPerspectiveCorners();
    perspectiveReady = analysis.status === "ready";
    manualDrawing = false;
    perspectiveCorrected.hidden = !analysis.corrected_image;
    noCorrectedImage.hidden = !!analysis.corrected_image;
    if (analysis.corrected_image) perspectiveCorrected.src = analysis.corrected_image;
    confirmCorners.hidden = perspectiveReady || perspectiveCorners.length !== 4;
    const score = analysis.method === "user_selected" ? "ผู้ใช้กำหนดจุด" :
      `คะแนนกรอบ ${Math.round(analysis.confidence * 100)}% (เกณฑ์จากรูปทรง ไม่ใช่ความถูกต้องที่รับประกัน)`;
    perspectiveStatus.textContent = perspectiveReady
      ? `พบ 4 มุม (${score}) ตรวจภาพที่ปรับแล้วก่อนกดตรวจสอบ`
      : `${analysis.reason || "กรุณาตรวจมุมที่เสนอ"} (${score})`;
  } catch (error) {
    if (revision !== perspectiveRevision) return;
    perspectiveStatus.textContent = error.message;
    perspectiveCorrected.hidden = true;
    noCorrectedImage.hidden = false;
  }
  updateSubmitState();
}

function refreshPerspective() {
  ++perspectiveRevision;
  perspectiveReady = false;
  perspectiveCorners = [];
  manualDrawing = false;
  drawPerspectiveCorners();
  confirmCorners.hidden = true;
  perspectiveCorrected.hidden = true;
  noCorrectedImage.hidden = false;
  perspectivePanel.hidden = !perspectiveEnabled.checked || !selectedFile;
  if (!perspectivePanel.hidden) {
    perspectiveOriginal.src = previewUrl;
    if (planogramSelect.value) analyzePerspective();
    else perspectiveStatus.textContent = "เลือก Planogram ก่อนปรับ perspective";
  }
  updateSubmitState();
}

perspectiveEnabled.addEventListener("change", refreshPerspective);
planogramSelect.addEventListener("change", refreshPerspective);
document.querySelector("#redrawCorners").addEventListener("click", () => {
  manualDrawing = true;
  perspectiveReady = false;
  perspectiveCorners = [];
  ++perspectiveRevision;
  drawPerspectiveCorners();
  confirmCorners.hidden = true;
  perspectiveCorrected.hidden = true;
  noCorrectedImage.hidden = false;
  perspectiveStatus.textContent = "คลิกมุมชั้นวางบนภาพ: บนซ้าย → บนขวา → ล่างขวา → ล่างซ้าย (0/4)";
  updateSubmitState();
});
document.querySelector("#undoCorner").addEventListener("click", () => {
  manualDrawing = true;
  perspectiveReady = false;
  ++perspectiveRevision;
  perspectiveCorners.pop();
  drawPerspectiveCorners();
  perspectiveStatus.textContent = `เลือกมุมแล้ว ${perspectiveCorners.length}/4`;
  updateSubmitState();
});
cornerOverlay.addEventListener("click", (event) => {
  if (!manualDrawing || perspectiveCorners.length >= 4) return;
  const rect = cornerOverlay.getBoundingClientRect();
  perspectiveCorners.push([(event.clientX - rect.left) / rect.width,
    (event.clientY - rect.top) / rect.height]);
  drawPerspectiveCorners();
  perspectiveStatus.textContent = `เลือกมุมแล้ว ${perspectiveCorners.length}/4`;
  if (perspectiveCorners.length === 4) analyzePerspective(perspectiveCorners);
});
confirmCorners.addEventListener("click", () => analyzePerspective(perspectiveCorners));

async function readJsonResponse(response) {
  const raw = await response.text();
  try {
    return JSON.parse(raw.replace(/^\uFEFF/, "").trim());
  } catch {
    const detail = raw.trimStart().startsWith("<")
      ? "PHP API ส่งหน้า HTML กลับมาแทน JSON ตรวจ URL และ Apache/PHP error log"
      : "เซิร์ฟเวอร์ส่งข้อมูลที่ไม่ใช่ JSON กลับมา";
    throw new Error(`${detail} (HTTP ${response.status})`);
  }
}

function setError(message = "") {
  formError.textContent = message;
  formError.hidden = !message;
}

function updateSubmitState() {
  submitButton.disabled = !selectedFile ||
    (perspectiveEnabled.checked && (!planogramSelect.value || !perspectiveReady));
}

function setPreview(file) {
  alignmentNotice.hidden = true;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  previewImage.src = previewUrl;
  previewImage.hidden = false;
  emptyState.hidden = true;
  imageStage.classList.remove("empty");
  imageCaption.textContent = "ภาพที่รอตรวจสอบ";
  refreshPerspective();
}

function acceptFile(file) {
  setError();
  if (!file) return;
  if (!ALLOWED_TYPES.includes(file.type))
    return setError("รองรับเฉพาะไฟล์ JPG, PNG และ WEBP");
  if (file.size > MAX_FILE_SIZE)
    return setError("ไฟล์ภาพต้องมีขนาดไม่เกิน 10 MB");
  selectedFile = file;
  fileName.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
  fileInfo.hidden = false;
  setPreview(file);
  resultPanel.hidden = true;
  updateSubmitState();
}

function clearFile() {
  alignmentNotice.hidden = true;
  selectedFile = null;
  imageInput.value = "";
  fileInfo.hidden = true;
  previewImage.hidden = true;
  emptyState.hidden = false;
  imageStage.classList.add("empty");
  imageCaption.textContent = "อัปโหลดภาพเพื่อเริ่มตรวจสอบ";
  resultPanel.hidden = true;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  refreshPerspective();
  updateSubmitState();
}

function renderProducts(counts) {
  const list = document.querySelector("#productList");
  const entries = Object.entries(counts);
  list.innerHTML = "";
  if (!entries.length) {
    list.innerHTML =
      '<div class="list-group-item text-body-secondary">ไม่พบสินค้าในภาพ</div>';
    return;
  }
  entries.forEach(([name, count]) => {
    const row = document.createElement("div");
    row.className =
      "list-group-item d-flex justify-content-between align-items-start gap-3";
    const label = document.createElement("span");
    label.textContent = name;
    const quantity = document.createElement("strong");
    quantity.className = "text-primary text-end";
    quantity.textContent = `${count} ชิ้น`;
    row.append(label, quantity);
    list.append(row);
  });
}

function renderGaps(gaps) {
  const list = document.querySelector("#gapList");
  const visibleGaps = gaps.filter((gap) => gap.product_class);
  list.innerHTML = "";
  if (!visibleGaps.length) {
    list.innerHTML =
      '<div class="list-group-item text-body-secondary">ไม่มีช่องว่างที่ระบุสินค้าได้</div>';
    return;
  }
  visibleGaps.forEach((gap) => {
    const row = document.createElement("div");
    row.className =
      "list-group-item d-flex justify-content-between align-items-start gap-3";
    const product = gap.product_class;
    const labels = {
      planogram: `ตามแผน: ${gap.shelf_name}`,
      "no-planogram": "ไม่ได้เลือกแผน",
      "ambiguous-region": "ทับซ้อนหลายพื้นที่",
      "outside-planogram": "ระบุพื้นที่ไม่ได้",
    };
    const title = document.createElement("span");
    title.textContent = `Out Stock ${gap.gap_number}`;
    const detail = document.createElement("small");
    detail.textContent = labels[gap.association_method] || "ระบุพื้นที่ไม่ได้";
    detail.className = "d-block text-body-secondary";
    const name = document.createElement("strong");
    name.textContent = product;
    name.className = "text-primary text-end";
    title.append(detail);
    row.append(title, name);
    list.append(row);
  });
}

function showResult(payload) {
  alignmentNotice.hidden = payload.alignment?.status !== "failed";
  if (!alignmentNotice.hidden) {
    alignmentNotice.textContent = `${payload.alignment.reason} · ตรวจได้เฉพาะสินค้าที่มองเห็น ยังไม่ตรวจถูก/ผิด shelf หรือระบุช่องว่างตาม Planogram`;
  }
  document.querySelector("#totalProducts").textContent = payload.total_products;
  document.querySelector("#totalClasses").textContent = Object.keys(
    payload.product_counts,
  ).length;
  document.querySelector("#totalGaps").textContent = payload.total_gaps;
  document.querySelector("#identifiedGaps").textContent =
    payload.identified_gaps;
  renderProducts(payload.product_counts);
  payload.products
    .filter((p) => p.placement_status === "wrong-shelf")
    .forEach((product) => {
      const row = document.createElement("div");
      row.className = "list-group-item text-danger";
      row.textContent = `ผิด shelf: ${product.class_name} → ควรเป็น ${product.expected_class} (${product.shelf_name})`;
      document.querySelector("#productList").append(row);
    });
  renderGaps(payload.gaps);
  previewImage.src = `${payload.result_image_url}?v=${Date.now()}`;
  previewImage.alt = "ผลตรวจจับสินค้าและช่องว่าง";
  imageCaption.textContent = `พบสินค้า ${payload.total_products} ชิ้น · ผิด shelf ${payload.wrong_shelf_count || 0} ชิ้น · gap ที่ระบุได้ ${payload.identified_gaps} ตำแหน่ง`;
  resultPanel.hidden = false;
  if (payload.alignment?.status === "aligned") {
    const method = payload.alignment.method === "perspective_four_corners" ? "ปรับ perspective แล้ว" : "จัดแนวภาพด้วย ECC แล้ว";
    imageCaption.textContent = `${method} · ${imageCaption.textContent}`;
  } else if (payload.alignment?.status === "failed") {
    imageCaption.textContent = `ยังจัดแนวภาพกับ Planogram ไม่ได้ · ${imageCaption.textContent}`;
  }
  resultPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function checkService() {
  const status = document.querySelector("#serviceStatus");
  try {
    const response = await fetch(`${API_BASE}/classes.php`);
    const payload = await readJsonResponse(response);
    if (!response.ok || !payload.success) throw new Error(payload.message);
    status.className =
      "service-status badge rounded-pill text-bg-success d-inline-flex align-items-center gap-2";
    status.querySelector("span:last-child").textContent =
      `2 โมเดลพร้อม · สินค้า ${payload.count} คลาส`;
  } catch {
    status.className =
      "service-status badge rounded-pill text-bg-danger d-inline-flex align-items-center gap-2";
    status.querySelector("span:last-child").textContent = "AI service ไม่พร้อม";
  }
}

productConfidence.addEventListener("input", () => {
  document.querySelector("#productConfidenceValue").textContent = Number(
    productConfidence.value,
  ).toFixed(2);
});
gapConfidence.addEventListener("input", () => {
  document.querySelector("#gapConfidenceValue").textContent = Number(
    gapConfidence.value,
  ).toFixed(2);
});
imageInput.addEventListener("change", () => acceptFile(imageInput.files[0]));
document.querySelector("#removeFile").addEventListener("click", clearFile);

["dragenter", "dragover"].forEach((name) =>
  dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  }),
);
["dragleave", "drop"].forEach((name) =>
  dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  }),
);
dropZone.addEventListener("drop", (event) =>
  acceptFile(event.dataTransfer.files[0]),
);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setError();
  if (!selectedFile) return setError("กรุณาเลือกไฟล์ภาพ");
  if (perspectiveEnabled.checked && !perspectiveReady)
    return setError("กรุณาตรวจและยืนยัน 4 มุมของชั้นวางก่อนตรวจสอบ");

  submitButton.disabled = true;
  submitButton.querySelector(".button-label").hidden = true;
  submitButton.querySelector(".button-loading").hidden = false;
  const planogramId = planogramSelect.value;
  submitButton.querySelector(".button-loading").textContent = "AI กำลังตรวจภาพ...";

  try {
    imageCaption.textContent = "AI กำลังตรวจสินค้าและช่องว่าง...";
    const body = new FormData();
    body.append("image", selectedFile, selectedFile.name);
    body.append("product_confidence", productConfidence.value);
    body.append("gap_confidence", gapConfidence.value);
    body.append("planogram_id", planogramId);
    if (perspectiveEnabled.checked)
      body.append("perspective_corners", JSON.stringify(perspectiveCorners));
    const response = await fetch(`${API_BASE}/detect.php`, {
      method: "POST",
      headers: {
        "X-Product-Confidence": productConfidence.value,
        "X-Gap-Confidence": gapConfidence.value,
        "X-Planogram-Id": planogramId,
      },
      body,
    });
    const payload = await readJsonResponse(response);
    if (!response.ok || !payload.success)
      throw new Error(payload.message || "ประมวลผลไม่สำเร็จ");
    showResult(payload);
  } catch (error) {
    setError(error.message);
    imageCaption.textContent = "เกิดข้อผิดพลาดในการประมวลผล";
  } finally {
    submitButton.querySelector(".button-label").hidden = false;
    submitButton.querySelector(".button-loading").hidden = true;
    updateSubmitState();
  }
});

checkService();

fetch(`${API_BASE}/planogram.php?list=1`)
  .then(async (response) => {
    const payload = await readJsonResponse(response);
    if (!response.ok || !payload.success) throw new Error(payload.message);
    const plans = payload.data || [];
    if (plans.length) {
      plans.forEach((item) => {
        const savedAt = item.created_at ? item.created_at.replace("T", " ").slice(0, 19) : "";
        planogramSelect.append(new Option(`${item.name} · ${savedAt} · ${item.id.slice(0, 8)}`, item.id));
      });
      document.querySelector("#planogramStatus").textContent =
        "เลือกแผนของชั้นวางเดียวกัน ระบบจะลองจัดแนวภาพอัตโนมัติด้วย ECC";
    } else
      document.querySelector("#planogramStatus").textContent =
        "ยังไม่มีแผน กรุณาบันทึกในหน้ากำหนด Planogram";
  })
  .catch(() => {
    document.querySelector("#planogramStatus").textContent =
      "โหลดแผนไม่ได้ ตรวจสอบ AI service แล้วโหลดหน้าใหม่";
  });
