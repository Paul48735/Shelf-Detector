const $ = id => document.getElementById(id);
const API = '../backend/api';
let offset = 0, listVersion = 0, detailVersion = 0;
const pageSize = 10;
function node(tag, text, className = '') { const n = document.createElement(tag); n.textContent = text; n.className = className; return n; }
function date(value) { return value ? value.replace('T', ' ').slice(0, 19) : '—'; }
function imageUrl(path) {
  if (typeof path !== 'string' || !/^storage\/(results|uploads)\/[a-zA-Z0-9_.-]+$/.test(path)) return null;
  return new URL(`../${path}`, location.href).href;
}
async function get(url) { const response = await fetch(url, { cache: 'no-store' }); const data = await response.json(); if (!response.ok || !data.success) throw new Error(data.message || 'โหลดข้อมูลไม่สำเร็จ'); return data.data; }
function clearDetail() {
  ['totalProducts', 'wrongShelf', 'totalGaps', 'identifiedGaps', 'issueCount'].forEach(id => $(id).textContent = '—');
  $('runImage').hidden = true; $('runImage').removeAttribute('src'); $('fullImage').hidden = true;
  $('imageEmpty').hidden = false; $('imageEmpty').textContent = 'ยังไม่มีภาพผลตรวจ';
  $('planBadge').textContent = 'ยังไม่ได้เลือกรอบ'; $('runMeta').textContent = 'เลือกรายการจากประวัติเพื่อดูรายละเอียด';
  $('issues').replaceChildren(node('p', 'รอผลตรวจที่เลือก', 'round-note'));
}
async function selectRun(id) {
  const version = ++detailVersion; clearDetail();
  $('loadMessage').textContent = `กำลังโหลดรอบ #${id}…`;
  document.querySelectorAll('#history tr').forEach(row => row.classList.toggle('selected', row.dataset.id === String(id)));
  try {
    const run = await get(`${API}/detections.php?id=${encodeURIComponent(id)}`);
    if (version !== detailVersion) return;
    const checked = run.planogram_id && !run.products.some(p => p.placement_status === 'unchecked');
    $('totalProducts').textContent = run.total_products; $('wrongShelf').textContent = checked ? run.wrong_shelf_count : '—';
    $('totalGaps').textContent = run.total_gaps; $('identifiedGaps').textContent = run.identified_gaps;
    $('planBadge').textContent = run.planogram_id ? run.planogram_name || 'แผนที่บันทึกไว้' : 'ไม่ได้ใช้ Planogram';
    $('runMeta').textContent = `รอบ #${run.id} · ${date(run.detected_at)}`;
    const url = imageUrl(run.result_image_path);
    if (url) {
      $('runImage').onload = () => { if (version === detailVersion) { $('runImage').hidden = false; $('imageEmpty').hidden = true; } };
      $('runImage').onerror = () => { if (version === detailVersion) { $('imageEmpty').textContent = 'ไม่พบไฟล์ภาพผลตรวจ'; $('imageEmpty').hidden = false; $('fullImage').hidden = true; } };
      $('runImage').src = url; $('fullImage').href = url; $('fullImage').hidden = false;
    }
    $('issues').replaceChildren(); let count = 0;
    function issue(title, detail, tone) { const item = node('article', '', `issue ${tone}`); item.append(node('strong', title), node('p', detail)); $('issues').append(item); count++; }
    run.products.forEach(p => {
      if (p.placement_status === 'wrong-shelf') issue(`ผิด shelf · ${p.class_name}`, `ควรเป็น ${p.expected_class} · ${p.region_name || p.region_id}`, 'danger');
      else if (run.planogram_id && ['unmatched', 'unchecked'].includes(p.placement_status)) issue(`ตรวจสอบตำแหน่ง · ${p.class_name}`, p.placement_status === 'unchecked' ? 'ผลเดิมยังไม่ได้ตรวจเทียบตำแหน่ง' : 'จับคู่พื้นที่ในแผนไม่ได้', 'neutral');
    });
    run.gaps.forEach(g => issue(g.product_class ? `ช่องว่าง · ${g.product_class}` : 'ช่องว่าง · ไม่ทราบ class', g.product_class ? `พื้นที่ ${g.region_name || g.region_id}` : 'ยังจับคู่กับพื้นที่ในแผนไม่ได้', 'warning'));
    $('issueCount').textContent = `${count} รายการ`;
    if (!count) $('issues').append(node('p', run.planogram_id ? 'ไม่พบรายการที่ต้องแก้ไขในรอบนี้' : 'รอบนี้ไม่ได้ตรวจตำแหน่งสินค้า', 'round-note'));
    if (!run.planogram_id) $('issues').prepend(node('p', 'ไม่ได้ใช้ Planogram จึงยังยืนยันการวางถูก shelf ไม่ได้', 'round-note'));
    $('loadMessage').textContent = `แสดงผลรอบ #${id}`;
  } catch (error) { if (version === detailVersion) $('loadMessage').textContent = `โหลดรายละเอียดไม่ได้: ${error.message}`; }
}
async function loadHistory() {
  const version = ++listVersion; ++detailVersion; clearDetail();
  $('retry').hidden = true; $('loadMessage').textContent = 'กำลังโหลดประวัติ…';
  $('history').replaceChildren(); $('next').disabled = true; $('previous').disabled = true;
  try {
    const params = new URLSearchParams({ limit: pageSize, offset });
    if ($('planFilter').value) params.set('planogram_id', $('planFilter').value);
    const rows = await get(`${API}/detections.php?${params}`);
    if (version !== listVersion) return;
    $('previous').disabled = offset === 0; $('next').disabled = rows.length < pageSize;
    $('pageLabel').textContent = `หน้า ${offset / pageSize + 1}`;
    rows.forEach(run => {
      const row = node('tr', ''); row.dataset.id = run.id;
      const preview = node('td', ''); const url = imageUrl(run.result_image_path);
      if (url) { const img = document.createElement('img'); img.src = url; img.alt = ''; img.loading = 'lazy'; img.onerror = () => img.hidden = true; preview.append(img); }
      preview.append(node('span', `#${run.id}`)); row.append(preview);
      [date(run.detected_at), run.planogram_name || 'ไม่ได้ใช้แผน', run.total_products, run.planogram_id ? run.wrong_shelf_count : '—', run.total_gaps].forEach(value => row.append(node('td', value)));
      const cell = node('td', ''); const button = node('button', 'ดูผล', 'quiet-button'); button.setAttribute('aria-label', `ดูผลรอบ ${run.id}`); button.onclick = () => selectRun(run.id); cell.append(button); row.append(cell); $('history').append(row);
    });
    if (rows.length) await selectRun(rows[0].id);
    else { $('loadMessage').textContent = 'ไม่พบผลตรวจในรายการนี้'; $('imageEmpty').textContent = 'เริ่มต้นด้วยปุ่ม “ตรวจภาพใหม่” หรือเลือกแผนอื่น'; }
  } catch (error) { if (version === listVersion) { $('loadMessage').textContent = `โหลดข้อมูลไม่ได้: ${error.message}`; $('retry').hidden = false; } }
}
$('planFilter').onchange = () => { offset = 0; loadHistory(); };
$('refresh').onclick = $('retry').onclick = () => loadHistory();
$('next').onclick = () => { offset += pageSize; loadHistory(); };
$('previous').onclick = () => { offset = Math.max(0, offset - pageSize); loadHistory(); };
get(`${API}/planogram.php?list=1`).then(plans => plans.forEach(plan => {
  const option = node('option', `${plan.name} · ${date(plan.created_at)} · ${plan.id.slice(-6)}`); option.value = plan.id; $('planFilter').append(option);
})).catch(() => { $('planFilter').disabled = true; $('planFilter').options[0].textContent = 'โหลดตัวกรองแผนไม่ได้'; });
loadHistory();
