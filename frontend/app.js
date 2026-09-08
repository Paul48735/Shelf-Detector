const API_BASE = "../backend/api";
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

let selectedFile = null;
let previewUrl = null;

async function readJsonResponse(response) {
  const raw = await response.text();
  const jsonStart = raw.indexOf("{");
  if (jsonStart < 0) throw new Error("เซิร์ฟเวอร์ส่งข้อมูลกลับมาไม่ถูกต้อง");
  return JSON.parse(raw.slice(jsonStart));
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
  imageCaption.textContent = "ภาพต้นฉบับที่รอตรวจสอบ";
}

function acceptFile(file) {
  setError();
  if (!file) return;
  if (!ALLOWED_TYPES.includes(file.type)) return setError("รองรับเฉพาะไฟล์ JPG, PNG และ WEBP");
  if (file.size > MAX_FILE_SIZE) return setError("ไฟล์ภาพต้องมีขนาดไม่เกิน 10 MB");
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
    list.innerHTML = '<p class="empty-row">ไม่พบสินค้าในภาพ</p>';
    return;
  }
  entries.forEach(([name, count]) => {
    const row = document.createElement("div");
    row.className = "detection-row";
    row.innerHTML = `<span>${name}</span><strong>${count} ชิ้น</strong>`;
    list.append(row);
  });
}

function renderGaps(gaps) {
  const list = document.querySelector("#gapList");
  list.innerHTML = "";
  if (!gaps.length) {
    list.innerHTML = '<p class="empty-row">ไม่พบช่องว่างในภาพ</p>';
    return;
  }
  gaps.forEach((gap) => {
    const row = document.createElement("div");
    row.className = "detection-row";
    const product = gap.product_class || "ไม่สามารถระบุสินค้าได้";
    const certainty = gap.association_certainty === "high" ? "มั่นใจสูง" : gap.association_certainty === "medium" ? "คาดการณ์" : "หลักฐานไม่พอ";
    row.innerHTML = `<span>Gap ${gap.gap_number}<small>${certainty}</small></span><strong>${product}</strong>`;
    list.append(row);
  });
}

function showResult(payload) {
  document.querySelector("#totalProducts").textContent = payload.total_products;
  document.querySelector("#totalClasses").textContent = Object.keys(payload.product_counts).length;
  document.querySelector("#totalGaps").textContent = payload.total_gaps;
  document.querySelector("#identifiedGaps").textContent = payload.identified_gaps;
  renderProducts(payload.product_counts);
  renderGaps(payload.gaps);
  previewImage.src = `${payload.result_image_url}?v=${Date.now()}`;
  previewImage.alt = "ผลตรวจจับสินค้าและช่องว่าง";
  imageCaption.textContent = `พบสินค้า ${payload.total_products} ชิ้น และ gap ${payload.total_gaps} ตำแหน่ง`;
  resultPanel.hidden = false;
  resultPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function checkService() {
  const status = document.querySelector("#serviceStatus");
  try {
    const response = await fetch(`${API_BASE}/classes.php`);
    const payload = await readJsonResponse(response);
    if (!response.ok || !payload.success) throw new Error(payload.message);
    status.className = "service-status ready";
    status.querySelector("span:last-child").textContent = `2 โมเดลพร้อม · สินค้า ${payload.count} คลาส`;
  } catch {
    status.className = "service-status offline";
    status.querySelector("span:last-child").textContent = "AI service ไม่พร้อม";
  }
}

productConfidence.addEventListener("input", () => {
  document.querySelector("#productConfidenceValue").textContent = Number(productConfidence.value).toFixed(2);
});
gapConfidence.addEventListener("input", () => {
  document.querySelector("#gapConfidenceValue").textContent = Number(gapConfidence.value).toFixed(2);
});
imageInput.addEventListener("change", () => acceptFile(imageInput.files[0]));
document.querySelector("#removeFile").addEventListener("click", clearFile);

["dragenter", "dragover"].forEach((name) => dropZone.addEventListener(name, (event) => {
  event.preventDefault();
  dropZone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((name) => dropZone.addEventListener(name, (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
}));
dropZone.addEventListener("drop", (event) => acceptFile(event.dataTransfer.files[0]));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setError();
  if (!selectedFile) return setError("กรุณาเลือกไฟล์ภาพ");

  submitButton.disabled = true;
  submitButton.querySelector(".button-label").hidden = true;
  submitButton.querySelector(".button-loading").hidden = false;
  imageCaption.textContent = "Product Model และ Gap Model กำลังวิเคราะห์ภาพ...";

  try {
    const extension = selectedFile.name.split(".").pop().toLowerCase();
    const response = await fetch(`${API_BASE}/detect.php`, {
      method: "PUT",
      headers: {
        "Content-Type": selectedFile.type,
        "X-File-Extension": extension,
        "X-Product-Confidence": productConfidence.value,
        "X-Gap-Confidence": gapConfidence.value,
      },
      body: selectedFile,
    });
    const payload = await readJsonResponse(response);
    if (!response.ok || !payload.success) throw new Error(payload.message || "ประมวลผลไม่สำเร็จ");
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
