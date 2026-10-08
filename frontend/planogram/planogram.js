const STORAGE_KEY = "shelfVision.planogram.v1";
const $ = (id) => document.getElementById(id);
const svgNS = "http://www.w3.org/2000/svg";
const badgeMeasure = document.createElement("canvas").getContext("2d");
const newShelf = (name) => ({
  id: crypto.randomUUID(),
  name,
  product: "",
  target: 3,
  points: [],
});
let plan = {
  version: 1,
  name: "ชั้นวาง 2 ชั้น",
  image: "",
  ratio: 1,
  shelves: [newShelf("ชั้นบน"), newShelf("ชั้นล่าง")],
};
let activeId = null;
let editingId = null;
let draft = [];
let draggedCorner = null;
let dirty = false;
let loadingImage = false;
let productClasses = [];

async function refreshSavedPlans(selectedId = plan.id) {
  const response = await fetch("../../backend/api/planogram.php?list=1");
  const payload = await response.json();
  if (!response.ok || !payload.success) throw new Error(payload.message || "โหลดรายการแผนไม่ได้");
  $("savedPlan").replaceChildren(new Option("แผนใหม่", ""));
  payload.data.forEach((item) => {
    const savedAt = item.created_at ? item.created_at.replace("T", " ").slice(0, 19) : "";
    const idSuffix = item.id ? item.id.slice(0, 8) : "";
    $("savedPlan").append(new Option(`${item.name} · ${savedAt} · ${idSuffix}`, item.id));
  });
  $("savedPlan").value = selectedId || "";
}

function setPlan(next) {
  plan = {
    id: next.id,
    version: next.version,
    name: next.name,
    image: next.image,
    ratio: next.ratio,
    overlap_threshold: next.overlap_threshold,
    shelves: next.shelves,
  };
  $("planName").value = plan.name;
  activeId = null;
  editingId = null;
  draggedCorner = null;
  draft = [];
  dirty = false;
  showImage();
}

function message(text, error = false) {
  const status = $("message");
  status.textContent = text;
  status.className = error
    ? "alert alert-danger mt-3 mb-0"
    : "alert alert-info mt-3 mb-0";
  status.hidden = !text;
}
function changed() {
  dirty = true;
  message("มีการเปลี่ยนแปลงที่ยังไม่บันทึก");
}
function validPoints(points) {
  if (
    !Array.isArray(points) ||
    points.length !== 4 ||
    !points.every(
      (p) =>
        Array.isArray(p) &&
        p.length === 2 &&
        p.every((n) => Number.isFinite(n) && n >= 0 && n <= 1),
    )
  )
    return false;
  const crosses = points.map((a, i) => {
    const b = points[(i + 1) % 4],
      c = points[(i + 2) % 4];
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
  });
  return crosses.every((n) => n > 0.0001) || crosses.every((n) => n < -0.0001);
}
function element(tag, attributes) {
  const node = document.createElementNS(svgNS, tag);
  Object.entries(attributes).forEach(([key, value]) =>
    node.setAttribute(key, value),
  );
  return node;
}
function draw() {
  $("regions").replaceChildren();
  const height = 1000 / plan.ratio;
  const coords = (points) =>
    points.map(([x, y]) => `${x * 1000},${y * height}`).join(" ");
  plan.shelves.forEach((shelf, index) => {
    if (!validPoints(shelf.points)) return;
    const color = shelf.id === activeId ? "#c7f36b" : "#2fd3c5";
    $("regions").append(
      element("polygon", {
        points: coords(shelf.points),
        fill: color,
        "fill-opacity": ".16",
        stroke: color,
        "stroke-width": 3,
      }),
    );
    if (shelf.id === editingId) {
      shelf.points.forEach(([x, y], cornerIndex) => {
        const handle = element("circle", {
          cx: x * 1000,
          cy: y * height,
          r: 11,
          fill: "#fff",
          stroke: color,
          "stroke-width": 4,
          class: "corner-handle",
          "data-corner-shelf": shelf.id,
          "data-corner-index": cornerIndex,
          tabindex: 0,
          role: "button",
          "aria-label": `จุดมุม ${cornerIndex + 1} ของ ${shelf.name} ใช้ลากหรือกดปุ่มลูกศรเพื่อปรับ`,
        });
        $("regions").append(handle);
        const number = element("text", {
          x: x * 1000,
          y: y * height + 5,
          fill: "#17343c",
          "font-size": 13,
          "font-weight": 700,
          "text-anchor": "middle",
          "pointer-events": "none",
        });
        number.textContent = String(cornerIndex + 1);
        $("regions").append(number);
      });
    }
    const xs = shelf.points.map(([x]) => x * 1000);
    const ys = shelf.points.map(([, y]) => y * height);
    const regionWidth = Math.max(...xs) - Math.min(...xs);
    const maxBadgeWidth = Math.max(22, regionWidth - 12);
    const maxTextWidth = Math.max(10, maxBadgeWidth - 12);
    const prefix = `${index + 1}. `;
    const fullName = shelf.product || shelf.name || "พื้นที่";
    badgeMeasure.font = "700 14px sans-serif";
    let nameParts = Array.from(fullName);
    let badgeLabel = `${prefix}${fullName}`;
    if (badgeMeasure.measureText(badgeLabel).width > maxTextWidth) {
      while (nameParts.length && badgeMeasure.measureText(`${prefix}${nameParts.join("")}…`).width > maxTextWidth) {
        nameParts.pop();
      }
      badgeLabel = nameParts.length ? `${prefix}${nameParts.join("")}…` : String(index + 1);
    }
    const textWidth = badgeMeasure.measureText(badgeLabel).width;
    const badgeWidth = Math.min(maxBadgeWidth, Math.max(24, textWidth + 12));
    const badgeHeight = 26;
    const badgeX = Math.max(2, Math.min(998 - badgeWidth, Math.min(...xs) + 6));
    const badgeY = Math.max(2, Math.min(height - badgeHeight - 2, Math.min(...ys) + 6));
    const fullLabel = `${index + 1}. ${shelf.name} · ${shelf.product || "ยังไม่เลือกสินค้า"} (${shelf.target})`;
    const badge = element("g", {
      "pointer-events": "none",
      "aria-label": fullLabel,
    });
    const title = element("title", {});
    title.textContent = fullLabel;
    const background = element("rect", {
      x: badgeX,
      y: badgeY,
      width: badgeWidth,
      height: badgeHeight,
      rx: 6,
      fill: color,
      stroke: "#071119",
      "stroke-width": 2,
    });
    const number = element("text", {
      x: badgeX + badgeWidth / 2,
      y: badgeY + 18,
      fill: shelf.id === activeId ? "#17343c" : "#fff",
      "font-size": 14,
      "font-weight": 700,
      "text-anchor": "middle",
    });
    number.textContent = badgeLabel;
    badge.append(title, background, number);
    $("regions").append(badge);
  });
  if (draft.length) {
    $("regions").append(
      element("polyline", {
        points: coords(draft),
        fill: "none",
        stroke: "#c7f36b",
        "stroke-width": 3,
      }),
    );
    draft.forEach(([x, y]) =>
      $("regions").append(
        element("circle", {
          cx: x * 1000,
          cy: y * height,
          r: 6,
          fill: "#c7f36b",
        }),
      ),
    );
  }
  $("editor").classList.toggle("drawing", !!activeId);
  $("editor").classList.toggle("adjusting", !!editingId);
  $("undoPoint").disabled = !draft.length;
  $("cancelDraw").disabled = !activeId;
  const shelf = plan.shelves.find((s) => s.id === activeId);
  const editingShelf = plan.shelves.find((s) => s.id === editingId);
  $("drawHint").textContent = shelf
    ? `${shelf.name}: คลิก 4 มุมตามเข็มหรือทวนเข็มรอบพื้นที่ (${draft.length}/4)`
    : editingShelf
      ? `${editingShelf.name}: ลากจุด 1–4 ให้ตรงขอบชั้น · ใช้ปุ่มลูกศรขยับละเอียด · กรอบจะไม่ยอมให้เส้นตัดกัน`
      : "กด “วาดพื้นที่” เพื่อกำหนดกรอบ หรือ “แก้ไขกรอบ” เพื่อขยับจุดของพื้นที่เดิม";
}
function renderShelves() {
  $("shelfList").replaceChildren();
  plan.shelves.forEach((shelf, index) => {
    const card = document.createElement("article");
    card.className = `card border-start border-4 mb-3 ${shelf.id === activeId ? "border-success" : "border-primary"}`;
    const body = document.createElement("div");
    body.className = "card-body";
    card.append(body);
    const heading = document.createElement("h3");
    heading.className = "h6 mb-3";
    heading.textContent = `พื้นที่ ${index + 1}`;
    body.append(heading);
    [
      ["ชื่อพื้นที่", "name"],
      ["สินค้า (ชื่อคลาสโมเดล)", "product"],
      ["จำนวนเป้าหมายที่มองเห็นด้านหน้า", "target"],
    ].forEach(([title, key]) => {
      const label = document.createElement("label");
      label.textContent = title;
      label.className = "form-label d-block fw-semibold mb-3";
      const input = document.createElement(key === "product" ? "select" : "input");
      input.className = key === "product" ? "form-select mt-1" : "form-control mt-1";
      if (key === "product") {
        input.append(new Option("เลือกคลาสสินค้า", ""));
        productClasses.forEach((name) => input.append(new Option(name, name)));
        if (shelf.product && !productClasses.includes(shelf.product))
          input.append(new Option(`${shelf.product} (คลาสเดิม)`, shelf.product));
      } else {
        input.type = key === "target" ? "number" : "text";
        if (key === "target") {
          input.min = "1";
          input.max = "999";
          input.step = "1";
        } else input.maxLength = 100;
      }
      input.value = shelf[key];
      input.addEventListener(key === "product" ? "change" : "input", () => {
        shelf[key] = key === "target" ? Number(input.value) : input.value;
        changed();
        draw();
      });
      label.append(input);
      body.append(label);
    });
    const edit = document.createElement("button");
    edit.textContent = validPoints(shelf.points)
      ? "วาดพื้นที่ใหม่ ✓"
      : "วาดพื้นที่";
    edit.className = "btn btn-outline-primary btn-sm me-2 mb-2";
    edit.disabled = !plan.image || loadingImage;
    edit.onclick = () => {
      activeId = shelf.id;
      editingId = null;
      draggedCorner = null;
      draft = [];
      renderShelves();
      draw();
    };
    let adjust = null;
    if (validPoints(shelf.points)) {
      adjust = document.createElement("button");
      adjust.textContent = editingId === shelf.id ? "เสร็จการแก้ไข ✓" : "แก้ไขกรอบ";
      adjust.className = "btn btn-outline-success btn-sm me-2 mb-2";
      adjust.disabled = !plan.image || loadingImage || (!!activeId && activeId !== shelf.id);
      adjust.setAttribute("aria-pressed", String(editingId === shelf.id));
      adjust.onclick = () => {
        activeId = null;
        draft = [];
        draggedCorner = null;
        editingId = editingId === shelf.id ? null : shelf.id;
        renderShelves();
        draw();
      };
    }
    const remove = document.createElement("button");
    remove.textContent = "ลบพื้นที่";
    remove.className = "btn btn-outline-danger btn-sm mb-2";
    remove.onclick = () => {
      if (!confirm(`ลบพื้นที่ “${shelf.name}”?`)) return;
      plan.shelves = plan.shelves.filter((s) => s.id !== shelf.id);
      if (activeId === shelf.id) {
        activeId = null;
        draft = [];
      }
      if (editingId === shelf.id) editingId = null;
      changed();
      renderShelves();
      draw();
    };
    body.append(edit);
    if (adjust) body.append(adjust);
    body.append(remove);
    $("shelfList").append(card);
  });
}
function showImage() {
  const height = 1000 / plan.ratio;
  $("editor").setAttribute("viewBox", `0 0 1000 ${height}`);
  $("referenceImage").setAttribute("height", height);
  $("referenceImage").setAttribute("href", plan.image);
  $("editor").hidden = !plan.image;
  // SVG does not implement HTMLElement.hidden consistently.
  $("editor").toggleAttribute("hidden", !plan.image);
  $("noImage").hidden = !!plan.image;
  draw();
  renderShelves();
}
$("editor").addEventListener("click", (event) => {
  if (!activeId || editingId || loadingImage) return;
  const rect = $("editor").getBoundingClientRect();
  draft.push([
    Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
    Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
  ]);
  if (draft.length === 4) {
    if (!validPoints(draft)) {
      draft.pop();
      message("กรอบต้องไม่ไขว้กันและมีพื้นที่ กรุณาเลือกมุมสุดท้ายใหม่", true);
    } else {
      plan.shelves.find((s) => s.id === activeId).points = draft;
      draft = [];
      activeId = null;
      changed();
      renderShelves();
    }
  }
  draw();
});

function normalizedPointerPoint(event) {
  const rect = $("editor").getBoundingClientRect();
  return [
    Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
    Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
  ];
}

function finishCornerDrag(event) {
  if (!draggedCorner || draggedCorner.pointerId !== event.pointerId) return;
  const changedShape = draggedCorner.changed;
  draggedCorner = null;
  if (changedShape) {
    changed();
    renderShelves();
  }
  draw();
}

$("editor").addEventListener("pointerdown", (event) => {
  const handle = event.target.closest?.("[data-corner-shelf]");
  if (!handle || loadingImage || handle.dataset.cornerShelf !== editingId) return;
  event.preventDefault();
  draggedCorner = {
    shelfId: handle.dataset.cornerShelf,
    cornerIndex: Number(handle.dataset.cornerIndex),
    pointerId: event.pointerId,
    changed: false,
  };
  $("editor").setPointerCapture(event.pointerId);
});

$("editor").addEventListener("pointermove", (event) => {
  if (!draggedCorner || draggedCorner.pointerId !== event.pointerId) return;
  const shelf = plan.shelves.find((item) => item.id === draggedCorner.shelfId);
  if (!shelf) return;
  const previous = shelf.points[draggedCorner.cornerIndex];
  shelf.points[draggedCorner.cornerIndex] = normalizedPointerPoint(event);
  if (validPoints(shelf.points)) {
    draggedCorner.changed = true;
    draw();
  } else shelf.points[draggedCorner.cornerIndex] = previous;
});

$("editor").addEventListener("pointerup", finishCornerDrag);
$("editor").addEventListener("pointercancel", finishCornerDrag);
$("editor").addEventListener("lostpointercapture", finishCornerDrag);

$("editor").addEventListener("keydown", (event) => {
  const handle = event.target.closest?.("[data-corner-shelf]");
  if (!handle || handle.dataset.cornerShelf !== editingId) return;
  const directions = {
    ArrowLeft: [-1, 0],
    ArrowRight: [1, 0],
    ArrowUp: [0, -1],
    ArrowDown: [0, 1],
  };
  const direction = directions[event.key];
  if (!direction) return;
  event.preventDefault();
  const shelf = plan.shelves.find((item) => item.id === editingId);
  const cornerIndex = Number(handle.dataset.cornerIndex);
  const previous = shelf.points[cornerIndex];
  const step = event.shiftKey ? 0.01 : 0.002;
  shelf.points[cornerIndex] = [
    Math.max(0, Math.min(1, previous[0] + direction[0] * step)),
    Math.max(0, Math.min(1, previous[1] + direction[1] * step)),
  ];
  if (!validPoints(shelf.points)) {
    shelf.points[cornerIndex] = previous;
    return;
  }
  changed();
  draw();
  const nextHandle = $("regions").querySelector(
    `[data-corner-shelf="${editingId}"][data-corner-index="${cornerIndex}"]`,
  );
  nextHandle?.focus();
});
$("undoPoint").onclick = () => {
  draft.pop();
  draw();
};
$("cancelDraw").onclick = () => {
  activeId = null;
  editingId = null;
  draggedCorner = null;
  draft = [];
  renderShelves();
  draw();
};
$("addShelf").onclick = () => {
  activeId = null;
  editingId = null;
  draft = [];
  plan.shelves.unshift(newShelf(`ชั้น ${plan.shelves.length + 1}`));
  changed();
  renderShelves();
  draw();
};
$("planName").oninput = () => {
  plan.name = $("planName").value;
  changed();
};
$("savedPlan").onchange = async () => {
  const id = $("savedPlan").value;
  if (!id) return;
  if ((dirty || draft.length) && !confirm("มีการแก้ไขที่ยังไม่บันทึก ต้องการเปิดแผนอื่นหรือไม่?")) {
    $("savedPlan").value = plan.id || "";
    return;
  }
  try {
    const response = await fetch(`../../backend/api/planogram.php?id=${encodeURIComponent(id)}`);
    const payload = await response.json();
    if (!response.ok || !payload.success || !payload.data)
      throw new Error(payload.message || "เปิดแผนไม่สำเร็จ");
    setPlan(payload.data);
    message(`เปิดแผน ${plan.name} แล้ว`);
  } catch (error) { message(error.message, true); }
};
$("newPlan").onclick = () => {
  if ((dirty || draft.length) && !confirm("มีการแก้ไขที่ยังไม่บันทึก ต้องการสร้างแผนใหม่หรือไม่?")) return;
  setPlan({version: 1, name: "แผนใหม่",
    image: "", ratio: 1, shelves: [newShelf("ชั้นบน"), newShelf("ชั้นล่าง")]});
  $("savedPlan").value = "";
  changed();
};
$("referenceInput").onchange = async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  if (
    !["image/jpeg", "image/png", "image/webp"].includes(file.type) ||
    file.size > 10 * 1024 * 1024
  )
    return message("เลือกภาพ JPG, PNG หรือ WEBP ขนาดไม่เกิน 10 MB", true);
  if (
    plan.shelves.some((s) => s.points.length) &&
    !confirm("เปลี่ยนภาพจะล้างกรอบทุกชั้น ต้องการเปลี่ยนภาพหรือไม่?")
  )
    return;
  loadingImage = true;
  $("referenceInput").disabled = true;
  $("savePlan").disabled = true;
  renderShelves();
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const scale = Math.min(
      1,
      1400 / Math.max(image.naturalWidth, image.naturalHeight),
    );
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
    plan.image = canvas.toDataURL("image/jpeg", 0.8);
    plan.ratio = canvas.width / canvas.height;
    plan.shelves.forEach((s) => (s.points = []));
    activeId = null;
    editingId = null;
    draggedCorner = null;
    draft = [];
    changed();
  } catch {
    message("อ่านภาพไม่สำเร็จ กรุณาเลือกไฟล์ภาพใหม่", true);
  } finally {
    URL.revokeObjectURL(url);
    loadingImage = false;
    $("referenceInput").disabled = false;
    $("savePlan").disabled = false;
    showImage();
  }
};
$("savePlan").onclick = async () => {
  if (activeId)
    return message("วาดให้ครบ 4 มุม หรือยกเลิกการวาดก่อนบันทึก", true);
  if (!plan.image || !plan.name.trim() || !plan.shelves.length)
    return message("กรุณาระบุชื่อแผน ภาพ และพื้นที่อย่างน้อย 1 ชั้น", true);
  if (
    plan.shelves.some(
      (s) =>
        !s.name.trim() ||
        !s.product.trim() ||
        !Number.isInteger(s.target) ||
        s.target < 1 ||
        s.target > 999 ||
        !validPoints(s.points),
    )
  )
    return message(
      "ทุกชั้นต้องมีชื่อ สินค้า จำนวนเต็ม 1–999 และกรอบครบ 4 มุม",
      true,
    );
  if (plan.shelves.some((s) => !productClasses.includes(s.product)))
    return message("กรุณาเลือกคลาสสินค้าจากรายการที่โหลดได้", true);
  const snapshot = JSON.stringify(plan);
  $("savePlan").disabled = true;
  try {
    const response = await fetch("../../backend/api/planogram.php", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: snapshot,
    });
    const payload = await response.json();
    if (!response.ok || !payload.success)
      throw new Error(payload.message || "บันทึกแผนไม่สำเร็จ");
    if (JSON.stringify(plan) === snapshot) {
      setPlan(payload.data);
      message(`บันทึกแผน ${plan.name} แล้ว`);
      refreshSavedPlans(plan.id).catch(() =>
        message("บันทึกแผนแล้ว แต่โหลดรายการแผนล่าสุดไม่ได้", true),
      );
    } else
      message(
        "บันทึกข้อมูลก่อนแก้ไขแล้ว ยังมีการเปลี่ยนแปลงที่ต้องบันทึกอีกครั้ง",
      );
  } catch (error) {
    message(error.message, true);
  } finally {
    $("savePlan").disabled = loadingImage;
  }
};
window.addEventListener("beforeunload", (event) => {
  if (dirty || draft.length) {
    event.preventDefault();
    event.returnValue = "";
  }
});
try {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
  if (saved) {
    if (
      saved.version !== 1 ||
      typeof saved.name !== "string" ||
      typeof saved.image !== "string" ||
      !saved.image.startsWith("data:image/jpeg;base64,") ||
      !Number.isFinite(saved.ratio) ||
      saved.ratio <= 0 ||
      !Array.isArray(saved.shelves) ||
      !saved.shelves.length ||
      !saved.shelves.every(
        (s) =>
          s &&
          typeof s.id === "string" &&
          typeof s.name === "string" &&
          typeof s.product === "string" &&
          Number.isInteger(s.target) &&
          s.target >= 1 &&
          s.target <= 999 &&
          validPoints(s.points),
      )
    )
      throw new Error("Invalid plan");
    setPlan(saved);
    message("โหลดแผนที่บันทึกไว้แล้ว");
  }
} catch {
  message("อ่านแผนเดิมไม่ได้ สามารถสร้างแผนใหม่ได้", true);
}
showImage();
document.querySelector(".workspace").inert = true;
fetch("../../backend/api/planogram.php")
  .then(async (response) => {
    const payload = await response.json();
    if (!response.ok || !payload.success)
      throw new Error(payload.message || "โหลดแผนไม่สำเร็จ");
    if (payload.data) {
      setPlan(payload.data);
      message("โหลดแผนจากหลังบ้านแล้ว");
    } else if (plan.image) {
      dirty = true;
      message("พบแผนเดิมในเบราว์เซอร์ กรุณากดบันทึกเพื่อส่งไปหลังบ้าน");
    }
  })
  .then(() => refreshSavedPlans())
  .catch((error) => message(`โหลดแผนจากหลังบ้านไม่ได้: ${error.message}`, true))
  .finally(() => {
    document.querySelector(".workspace").inert = false;
  });
async function loadProductClasses() {
  let source = "โมเดล";
  try {
    const response = await fetch("../../backend/api/classes.php");
    const payload = await response.json();
    if (!response.ok || !payload.success || !Array.isArray(payload.data) || !payload.data.length)
      throw new Error("โหลดคลาสจากโมเดลไม่ได้");
    productClasses = payload.data;
  } catch {
    try {
      const response = await fetch("../../backend/api/products.php");
      const payload = await response.json();
      if (!response.ok || !payload.success || !Array.isArray(payload.data) || !payload.data.length)
        throw new Error("โหลดคลาสจากฐานข้อมูลไม่ได้");
      productClasses = payload.data.slice().reverse().map((product) => product.yolo_class_name);
      source = "ฐานข้อมูลสินค้า";
    } catch {
      $("classStatus").textContent = "โหลดรายชื่อคลาสไม่ได้ กรุณาตรวจสอบ AI service และฐานข้อมูล";
      return;
    }
  }
  productClasses = [...new Set(productClasses.filter((name) => typeof name === "string" && name))];
  renderShelves();
  $("classStatus").textContent = `เลือกได้ ${productClasses.length} คลาสจาก${source}`;
}
loadProductClasses();
