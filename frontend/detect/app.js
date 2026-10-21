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
const emptyState = document.querySelector("#emptyState");
const imageStage = document.querySelector("#imageStage");
const imageCaption = document.querySelector("#imageCaption");
const resultPanel = document.querySelector("#resultPanel");
const planogramSelect = document.querySelector("#planogramSelect");
let selectedFile = null;
let previewUrl = null;
let selectedPlan = null;
let sourceRatio = null;
let busy = false;
let planLoading = false;
let alignmentReady = false;
let previewGeneration = 0;
let showingResult = false;
const byId = id => document.getElementById(id);
const alignmentPanel = byId('alignmentPanel');
function uploadPointsChanged(points, source) {
  for (const picker of [uploadPicker, detailUploadPicker]) {
    if (picker !== source) { picker.points = points.map(p => [...p]); picker.draw?.(); }
  }
  if (showingResult) {
    showingResult = false; previewImage.hidden = true;
    byId('uploadAlignmentPicker').hidden = false;
    imageCaption.textContent = 'ภาพต้นฉบับ — กำลังเลือกจุดอ้างอิง';
  }
  invalidateAlignment(); updateAlignmentHint(); resultPanel.hidden = true;
}
const uploadPicker = new CornerPicker(byId('uploadAlignmentPicker'), points => uploadPointsChanged(points, uploadPicker), message => alignmentError(message));
const detailUploadPicker = new CornerPicker(byId('detailUploadAlignmentPicker'), points => uploadPointsChanged(points, detailUploadPicker), message => alignmentError(message));
const referencePicker = new CornerPicker(byId('referenceAlignmentPicker'), () => {}, () => {
  alignmentError('ภาพด้านขวาเป็นภาพอ้างอิง ให้คลิกภาพอัปโหลดด้านซ้ายเพื่อกำหนดจุด 1–4');
});

function alignmentError(message = '') {
  byId('alignmentError').textContent = message;
  byId('alignmentError').hidden = !message;
}
function invalidateAlignment() {
  previewGeneration++; alignmentReady = false;
  byId('alignedPreviewSection').hidden = true; alignmentError();
}
function updateAlignmentHint() {
  const ready = validAlignmentPoints(selectedPlan?.alignment_points);
  const count = uploadPicker.points.length;
  byId('alignmentHint').textContent = !selectedPlan
    ? 'เลือก Planogram เพื่อใช้การจัดแนว หรือกดตรวจสอบภาพต้นฉบับได้เลย'
    : !ready ? 'แผนนี้ยังไม่มีจุดอ้างอิงโครงตู้ เปิดหน้า Planogram กำหนด 4 จุดแล้วบันทึกแผนใหม่ก่อนใช้การจัดแนว ขณะนี้ยังตรวจภาพต้นฉบับได้'
      : count === 4 ? (alignmentReady ? 'แสดงตัวอย่างแล้ว ตรวจภาพด้านล่างก่อนกดตรวจสอบภาพ' : 'ครบ 4 จุดแล้ว กดแสดงภาพหลังจัดแนว จากนั้นกดตรวจสอบภาพ')
        : `เลือกแล้ว ${count}/4 จุด · ${count ? 'เลือกให้ครบ หรือล้างจุดเพื่อใช้ภาพต้นฉบับ' : 'ยังไม่เลือกจุด: Detect จะใช้ภาพต้นฉบับ'}`;
  // Reference points are required to warp, not to let the user select source points.
  uploadPicker.readonly = false;
  detailUploadPicker.readonly = false;
  byId('detailPointStatus').textContent = `เลือกแล้ว ${count}/4 จุด · คลิกภาพด้านบนของข้อความนี้เพื่อเพิ่มจุด หรือลากจุดเดิมเพื่อแก้ไข`;
  byId('uploadPointStatus').textContent = showingResult
    ? 'กำลังแสดงผล Detect กดเลือก / แก้จุดเพื่อกลับไปภาพต้นฉบับ'
    : `คลิกบนภาพนี้ได้เลย (${count}/4 จุด): 1 บนซ้าย → 2 บนขวา → 3 ล่างขวา → 4 ล่างซ้าย`;
  byId('setupPlanAlignment').hidden = ready;
  byId('setupPlanAlignment').href = `../planogram/${selectedPlan ? '?id=' + encodeURIComponent(selectedPlan.id) : ''}#alignment`;
  byId('undoUploadAlignment').disabled = !count || busy;
  byId('clearUploadAlignment').disabled = !count || busy;
  byId('previewAlignment').disabled = !ready || count !== 4 || busy || planLoading;
  byId('detectAligned').disabled = !alignmentReady || busy;
}
function refreshAlignmentPanel() {
  alignmentPanel.hidden = !selectedFile || !sourceRatio;
  showingResult = false;
  const hasImage = !!selectedFile && !!sourceRatio;
  byId('uploadPointControls').hidden = !hasImage;
  byId('uploadAlignmentPicker').hidden = !hasImage;
  if (hasImage) previewImage.hidden = true;
  uploadPicker.setImage(previewUrl, sourceRatio || 1, [], false);
  detailUploadPicker.setImage(previewUrl, sourceRatio || 1, [], false);
  referencePicker.setImage(selectedPlan?.image || '', selectedPlan?.ratio || 1, selectedPlan?.alignment_points || [], true);
  invalidateAlignment(); updateAlignmentHint();
}
function setBusy(value) {
  busy = value; form.inert = value; alignmentPanel.inert = value;
  byId('uploadPointControls').inert = value;
  byId('uploadAlignmentPicker').inert = value;
  updateSubmitState(); updateAlignmentHint();
}
function overlayPlan() {
  const svg = byId('alignedRegions'); svg.replaceChildren();
  const height = 1000 / selectedPlan.ratio;
  svg.setAttribute('viewBox', `0 0 1000 ${height}`);
  for (const region of selectedPlan.shelves) {
    const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    polygon.setAttribute('points', region.points.map(([x, y]) => `${x * 1000},${y * height}`).join(' '));
    polygon.setAttribute('fill', '#20c99722'); polygon.setAttribute('stroke', '#20c997'); polygon.setAttribute('stroke-width', '3');
    svg.append(polygon);
  }
}
async function loadSelectedPlan() {
  const id = planogramSelect.value;
  selectedPlan = null; planLoading = !!id; resultPanel.hidden = true;
  refreshAlignmentPanel(); updateSubmitState(); setError();
  if (!id) return;
  try {
    const response = await fetch(`${API_BASE}/planogram.php?id=${encodeURIComponent(id)}`);
    const payload = await readJsonResponse(response);
    if (!response.ok || !payload.success || !payload.data) throw new Error(payload.message || 'โหลดแผนไม่ได้');
    if (planogramSelect.value !== id) return;
    selectedPlan = payload.data;
  } catch (error) { if (planogramSelect.value === id) setError(error.message); }
  finally {
    if (planogramSelect.value === id) { planLoading = false; refreshAlignmentPanel(); updateSubmitState(); }
  }
}
planogramSelect.addEventListener('change', loadSelectedPlan);
byId('undoUploadAlignment').onclick = () => uploadPicker.undo();
byId('clearUploadAlignment').onclick = () => uploadPicker.clear();
function editUploadPoints() {
  if (!selectedFile || !sourceRatio || busy) return;
  showingResult = false;
  previewImage.hidden = true;
  byId('uploadAlignmentPicker').hidden = false;
  imageCaption.textContent = 'ภาพต้นฉบับ — คลิกจุดโครงตู้ 4 จุด หรือไม่เลือกจุดเพื่อตรวจภาพตามปกติ';
  updateAlignmentHint();
  imageStage.scrollIntoView({behavior: 'smooth', block: 'center'});
}
byId('editUploadPoints').onclick = editUploadPoints;
byId('backToUploadPoints').onclick = editUploadPoints;
byId('detectAligned').onclick = () => form.requestSubmit();
byId('previewAlignment').onclick = async () => {
  if (busy || !selectedFile || uploadPicker.points.length !== 4 || !selectedPlan) return;
  const generation = ++previewGeneration;
  setBusy(true); alignmentError();
  byId('previewAlignment').textContent = 'กำลังจัดแนวภาพ...';
  try {
    const body = new FormData();
    body.append('image', selectedFile, selectedFile.name);
    body.append('alignment_points', JSON.stringify(uploadPicker.points));
    const response = await fetch(`${API_BASE}/detect.php?preview=1`, {
      method: 'POST', headers: {'X-Planogram-Id': selectedPlan.id}, body,
    });
    const payload = await readJsonResponse(response);
    if (!response.ok || !payload.success) throw new Error(payload.message || 'จัดแนวภาพไม่สำเร็จ');
    if (generation !== previewGeneration) return;
    byId('alignedPreview').src = payload.image;
    overlayPlan(); byId('alignedPreviewSection').hidden = false;
    alignmentReady = true;
    byId('alignedPreviewSection').scrollIntoView({behavior: 'smooth', block: 'nearest'});
  } catch (error) { if (generation === previewGeneration) { alignmentReady = false; alignmentError(error.message); } }
  finally { byId('previewAlignment').textContent = 'แสดงภาพหลังจัดแนว'; setBusy(false); }
};

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
  submitButton.disabled = !selectedFile || busy || planLoading || !sourceRatio;
}

function setPreview(file) {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  previewImage.src = previewUrl;
  previewImage.hidden = false;
  emptyState.hidden = true;
  imageStage.classList.remove("empty");
  imageCaption.textContent = "ภาพที่รอตรวจสอบ";
  sourceRatio = null;
  refreshAlignmentPanel();
  const url = previewUrl;
  const source = new Image(); source.src = url;
  source.decode().then(() => {
    if (previewUrl !== url) return;
    sourceRatio = source.naturalWidth / source.naturalHeight;
    refreshAlignmentPanel(); updateSubmitState();
  }).catch(() => { if (previewUrl === url) setError('อ่านไฟล์ภาพไม่สำเร็จ'); });
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
  sourceRatio = null;
  refreshAlignmentPanel();
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
  showingResult = true;
  byId('uploadAlignmentPicker').hidden = true;
  previewImage.hidden = false;
  updateAlignmentHint();
  previewImage.src = `${payload.result_image_url}?v=${Date.now()}`;
  previewImage.alt = "ผลตรวจจับสินค้าและช่องว่าง";
  imageCaption.textContent = `${payload.alignment?.applied ? 'จัดแนวเข้ากับ Planogram แล้ว' : 'ตรวจภาพต้นฉบับ'} · พบสินค้า ${payload.total_products} ชิ้น · ผิด shelf ${payload.wrong_shelf_count || 0} ชิ้น · gap ที่ระบุได้ ${payload.identified_gaps} ตำแหน่ง`;
  if (payload.aligned_image_url) {
    byId('alignedPreview').src = payload.aligned_image_url;
    byId('alignedPreviewSection').hidden = false;
  }
  resultPanel.hidden = false;
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
  if (planogramSelect.value && !selectedPlan) return setError('โหลด Planogram ไม่สำเร็จ กรุณาเลือกแผนใหม่');
  if (uploadPicker.points.length && !validAlignmentPoints(selectedPlan?.alignment_points))
    return setError('เลือกจุดบนภาพแล้ว แต่ Planogram ยังไม่มีจุดอ้างอิง ให้กดลิงก์กำหนดจุดอ้างอิงของแผน หรือกดล้างจุดเพื่อตรวจภาพต้นฉบับ');
  if (uploadPicker.points.length && !alignmentReady) return setError('เลือกจุดให้ครบ 4 จุดแล้วกดแสดงภาพหลังจัดแนวก่อนตรวจสอบ หรือล้างจุดเพื่อใช้ภาพต้นฉบับ');
  setBusy(true);
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
    body.append('alignment_points', JSON.stringify(uploadPicker.points));
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
    setBusy(false);
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
        "เลือกแผนของชั้นวางเดียวกัน ภาพเอียงสามารถกำหนดจุดอ้างอิงเพื่อปรับมุมได้ ส่วนภาพตรงไม่ต้องกำหนดจุด";
    } else
      document.querySelector("#planogramStatus").textContent =
        "ยังไม่มีแผน กรุณาบันทึกในหน้ากำหนด Planogram";
  })
  .catch(() => {
    document.querySelector("#planogramStatus").textContent =
      "โหลดแผนไม่ได้ ตรวจสอบ AI service แล้วโหลดหน้าใหม่";
  });
