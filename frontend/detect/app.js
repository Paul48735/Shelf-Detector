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
  submitButton.disabled = !selectedFile;
}

function setPreview(file) {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  previewImage.src = previewUrl;
  previewImage.hidden = false;
  emptyState.hidden = true;
  imageStage.classList.remove("empty");
  imageCaption.textContent = "ภาพที่รอตรวจสอบ";
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
  previewImage.src = `${payload.result_image_url}?v=${Date.now()}`;
  previewImage.alt = "ผลตรวจจับสินค้าและช่องว่าง";
  imageCaption.textContent = `พบสินค้า ${payload.total_products} ชิ้น · ผิด shelf ${payload.wrong_shelf_count || 0} ชิ้น · gap ที่ระบุได้ ${payload.identified_gaps} ตำแหน่ง`;
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
        "เลือกแผนที่สร้างจากภาพมุมเดียวกับภาพที่จะตรวจ";
    } else
      document.querySelector("#planogramStatus").textContent =
        "ยังไม่มีแผน กรุณาบันทึกในหน้ากำหนด Planogram";
  })
  .catch(() => {
    document.querySelector("#planogramStatus").textContent =
      "โหลดแผนไม่ได้ ตรวจสอบ AI service แล้วโหลดหน้าใหม่";
  });
