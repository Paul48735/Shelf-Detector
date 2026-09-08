const STORAGE_KEY = 'shelfVision.planogram.v1';
const $ = (id) => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const newShelf = (name) => ({ id: crypto.randomUUID(), name, product: '', target: 3, points: [] });
let plan = { version: 1, name: 'ชั้นวาง 2 ชั้น', image: '', ratio: 1, shelves: [newShelf('ชั้นบน'), newShelf('ชั้นล่าง')] };
let activeId = null;
let draft = [];
let dirty = false;
let loadingImage = false;

function message(text, error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
}
function changed() { dirty = true; message('มีการเปลี่ยนแปลงที่ยังไม่บันทึก'); }
function validPoints(points) {
  if (!Array.isArray(points) || points.length !== 4 || !points.every(p => Array.isArray(p) && p.length === 2 && p.every(n => Number.isFinite(n) && n >= 0 && n <= 1))) return false;
  const crosses = points.map((a, i) => {
    const b = points[(i + 1) % 4], c = points[(i + 2) % 4];
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
  });
  return crosses.every(n => n > 0.0001) || crosses.every(n => n < -0.0001);
}
function element(tag, attributes) {
  const node = document.createElementNS(svgNS, tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}
function draw() {
  $('regions').replaceChildren();
  const height = 1000 / plan.ratio;
  const coords = points => points.map(([x, y]) => `${x * 1000},${y * height}`).join(' ');
  plan.shelves.forEach((shelf, index) => {
    if (!validPoints(shelf.points)) return;
    const color = shelf.id === activeId ? '#c7f36b' : '#2fd3c5';
    $('regions').append(element('polygon', { points: coords(shelf.points), fill: color, 'fill-opacity': '.16', stroke: color, 'stroke-width': 3 }));
    const [x, y] = shelf.points[0];
    const label = element('text', { x: x * 1000 + 8, y: y * height + 25, fill: '#fff', stroke: '#071119', 'stroke-width': 3, 'paint-order': 'stroke', 'font-size': 20 });
    label.textContent = `${index + 1}. ${shelf.name} · ${shelf.product || 'ยังไม่เลือกสินค้า'} (${shelf.target})`;
    $('regions').append(label);
  });
  if (draft.length) {
    $('regions').append(element('polyline', { points: coords(draft), fill: 'none', stroke: '#c7f36b', 'stroke-width': 3 }));
    draft.forEach(([x, y]) => $('regions').append(element('circle', { cx: x * 1000, cy: y * height, r: 6, fill: '#c7f36b' })));
  }
  $('editor').classList.toggle('drawing', !!activeId);
  $('undoPoint').disabled = !draft.length;
  $('cancelDraw').disabled = !activeId;
  const shelf = plan.shelves.find(s => s.id === activeId);
  $('drawHint').textContent = shelf ? `${shelf.name}: คลิก 4 มุมตามเข็มหรือทวนเข็มรอบพื้นที่ (${draft.length}/4)` : 'กด “วาดพื้นที่” เพื่อกำหนดหรือวาดกรอบใหม่ โดยใช้มุมกล้องเดียวกับภาพที่จะตรวจ';
}
function renderShelves() {
  $('shelfList').replaceChildren();
  plan.shelves.forEach(shelf => {
    const card = document.createElement('article');
    card.className = `shelf-card${shelf.id === activeId ? ' active' : ''}`;
    [['ชื่อพื้นที่', 'name'], ['สินค้า (ชื่อคลาสโมเดล)', 'product'], ['จำนวนเป้าหมายที่มองเห็นด้านหน้า', 'target']].forEach(([title, key]) => {
      const label = document.createElement('label');
      label.textContent = title;
      const input = document.createElement('input');
      input.value = shelf[key];
      input.type = key === 'target' ? 'number' : 'text';
      if (key === 'target') { input.min = '1'; input.max = '999'; input.step = '1'; }
      else input.maxLength = 100;
      if (key === 'product') input.setAttribute('list', 'productClasses');
      input.addEventListener('input', () => { shelf[key] = key === 'target' ? Number(input.value) : input.value; changed(); draw(); });
      label.append(input); card.append(label);
    });
    const edit = document.createElement('button');
    edit.textContent = validPoints(shelf.points) ? 'วาดพื้นที่ใหม่ ✓' : 'วาดพื้นที่';
    edit.disabled = !plan.image || loadingImage;
    edit.onclick = () => { activeId = shelf.id; draft = []; renderShelves(); draw(); };
    const remove = document.createElement('button');
    remove.textContent = 'ลบพื้นที่';
    remove.onclick = () => {
      if (!confirm(`ลบพื้นที่ “${shelf.name}”?`)) return;
      plan.shelves = plan.shelves.filter(s => s.id !== shelf.id);
      if (activeId === shelf.id) { activeId = null; draft = []; }
      changed(); renderShelves(); draw();
    };
    card.append(edit, remove); $('shelfList').append(card);
  });
}
function showImage() {
  const height = 1000 / plan.ratio;
  $('editor').setAttribute('viewBox', `0 0 1000 ${height}`);
  $('referenceImage').setAttribute('height', height);
  $('referenceImage').setAttribute('href', plan.image);
  $('editor').hidden = !plan.image;
  // SVG does not implement HTMLElement.hidden consistently.
  $('editor').toggleAttribute('hidden', !plan.image);
  $('noImage').hidden = !!plan.image;
  draw(); renderShelves();
}
$('editor').addEventListener('click', event => {
  if (!activeId || loadingImage) return;
  const rect = $('editor').getBoundingClientRect();
  draft.push([Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))]);
  if (draft.length === 4) {
    if (!validPoints(draft)) { draft.pop(); message('กรอบต้องไม่ไขว้กันและมีพื้นที่ กรุณาเลือกมุมสุดท้ายใหม่', true); }
    else { plan.shelves.find(s => s.id === activeId).points = draft; draft = []; activeId = null; changed(); renderShelves(); }
  }
  draw();
});
$('undoPoint').onclick = () => { draft.pop(); draw(); };
$('cancelDraw').onclick = () => { activeId = null; draft = []; renderShelves(); draw(); };
$('addShelf').onclick = () => { plan.shelves.push(newShelf(`ชั้น ${plan.shelves.length + 1}`)); changed(); renderShelves(); };
$('planName').oninput = () => { plan.name = $('planName').value; changed(); };
$('referenceInput').onchange = async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024) return message('เลือกภาพ JPG, PNG หรือ WEBP ขนาดไม่เกิน 10 MB', true);
  if (plan.shelves.some(s => s.points.length) && !confirm('เปลี่ยนภาพจะล้างกรอบทุกชั้น ต้องการเปลี่ยนภาพหรือไม่?')) return;
  loadingImage = true; $('referenceInput').disabled = true; $('savePlan').disabled = true; renderShelves();
  const url = URL.createObjectURL(file);
  try {
    const image = new Image(); image.src = url; await image.decode();
    const scale = Math.min(1, 1400 / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale)); canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    plan.image = canvas.toDataURL('image/jpeg', .8); plan.ratio = canvas.width / canvas.height;
    plan.shelves.forEach(s => s.points = []); activeId = null; draft = []; changed();
  } catch { message('อ่านภาพไม่สำเร็จ กรุณาเลือกไฟล์ภาพใหม่', true); }
  finally { URL.revokeObjectURL(url); loadingImage = false; $('referenceInput').disabled = false; $('savePlan').disabled = false; showImage(); }
};
$('savePlan').onclick = async () => {
  if (activeId) return message('วาดให้ครบ 4 มุม หรือยกเลิกการวาดก่อนบันทึก', true);
  if (!plan.image || !plan.name.trim() || !plan.shelves.length) return message('กรุณาระบุชื่อแผน ภาพ และพื้นที่อย่างน้อย 1 ชั้น', true);
  if (plan.shelves.some(s => !s.name.trim() || !s.product.trim() || !Number.isInteger(s.target) || s.target < 1 || s.target > 999 || !validPoints(s.points))) return message('ทุกชั้นต้องมีชื่อ สินค้า จำนวนเต็ม 1–999 และกรอบครบ 4 มุม', true);
  const snapshot = JSON.stringify(plan);
  $('savePlan').disabled = true;
  try {
    const response = await fetch('../backend/api/planogram.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: snapshot });
    const payload = await response.json();
    if (!response.ok || !payload.success) throw new Error(payload.message || 'บันทึกแผนไม่สำเร็จ');
    if (JSON.stringify(plan) === snapshot) {
      plan = payload.data; dirty = false; showImage();
      message('บันทึกแผนที่หลังบ้านแล้ว เลือกแผนนี้ในหน้าตรวจจับได้');
    } else message('บันทึกข้อมูลก่อนแก้ไขแล้ว ยังมีการเปลี่ยนแปลงที่ต้องบันทึกอีกครั้ง');
  } catch (error) { message(error.message, true); }
  finally { $('savePlan').disabled = loadingImage; }
};
window.addEventListener('beforeunload', event => { if (dirty || draft.length) { event.preventDefault(); event.returnValue = ''; } });
try {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
  if (saved) {
    if (saved.version !== 1 || typeof saved.name !== 'string' || typeof saved.image !== 'string' || !saved.image.startsWith('data:image/jpeg;base64,') || !Number.isFinite(saved.ratio) || saved.ratio <= 0 || !Array.isArray(saved.shelves) || !saved.shelves.length || !saved.shelves.every(s => s && typeof s.id === 'string' && typeof s.name === 'string' && typeof s.product === 'string' && Number.isInteger(s.target) && s.target >= 1 && s.target <= 999 && validPoints(s.points))) throw new Error('Invalid plan');
    plan = saved; $('planName').value = plan.name; message('โหลดแผนที่บันทึกไว้แล้ว');
  }
} catch { message('อ่านแผนเดิมไม่ได้ สามารถสร้างแผนใหม่ได้', true); }
showImage();
document.querySelector('.workspace').inert = true;
fetch('../backend/api/planogram.php').then(async response => {
  const payload = await response.json();
  if (!response.ok || !payload.success) throw new Error(payload.message || 'โหลดแผนไม่สำเร็จ');
  if (payload.data) {
    plan = payload.data; $('planName').value = plan.name; dirty = false; showImage();
    message('โหลดแผนจากหลังบ้านแล้ว');
  } else if (plan.image) {
    dirty = true; message('พบแผนเดิมในเบราว์เซอร์ กรุณากดบันทึกเพื่อส่งไปหลังบ้าน');
  }
}).catch(error => message(`โหลดแผนจากหลังบ้านไม่ได้: ${error.message}`, true))
  .finally(() => { document.querySelector('.workspace').inert = false; });
fetch('../backend/api/classes.php').then(async response => {
  const payload = await response.json();
  if (!response.ok || !payload.success || !Array.isArray(payload.data)) throw new Error();
  payload.data.forEach(name => { const option = document.createElement('option'); option.value = name; $('productClasses').append(option); });
  $('classStatus').textContent = `เลือกสินค้าได้ ${payload.data.length} คลาส หรือพิมพ์ชื่อคลาสเอง`;
}).catch(() => { $('classStatus').textContent = 'AI service ไม่พร้อม สามารถพิมพ์ชื่อคลาสสินค้าเองได้'; });
