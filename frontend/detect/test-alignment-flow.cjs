// Test the page's request/state flow with DOM stubs, not a browser UI test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.events = {}; this.hidden = false; this.disabled = false; this.children = []; this.style = {}; this.value = ''; this.classList = {add() {}, remove() {}}; }
  addEventListener(name, fn) { this.events[name] = fn; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  querySelector() { return new Element(); }
  setAttribute() {}
  scrollIntoView() {}
}
class Picker {
  constructor(host, onChange) { this.points = []; this.onChange = onChange; }
  setImage(url, ratio, points = [], readonly = false) { this.points = points.map(p => [...p]); this.readonly = readonly; }
  clear() { this.points = []; this.onChange(this.points); }
  undo() { this.points.pop(); this.onChange(this.points); }
}
const elements = new Map();
const element = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const corners = [[.1, .1], [.9, .1], [.9, .9], [.1, .9]];
const plan = {id: 'a'.repeat(32), ratio: 4 / 3, image: 'reference.jpg', alignment_points: corners, shelves: []};
const requests = [];
const context = vm.createContext({
  console, CornerPicker: Picker, validAlignmentPoints: points => Array.isArray(points) && points.length === 4,
  document: {querySelector: selector => element(selector.replace('#', '')), getElementById: element,
    createElement: () => new Element(), createElementNS: () => new Element()},
  Image: class { constructor() { this.naturalWidth = 400; this.naturalHeight = 300; } async decode() {} },
  URL: {createObjectURL: () => 'blob:source', revokeObjectURL() {}},
  Option: class {}, FormData: class { constructor() { this.fields = {}; } append(key, value) { this.fields[key] = value; } },
  fetch: async (url, options) => {
    requests.push({url, options});
    let payload = {success: true};
    if (url.includes('classes.php')) payload.count = 30;
    else if (url.includes('list=1')) payload.data = [];
    else if (url.includes('planogram.php?id=')) payload.data = plan;
    else if (url.includes('preview=1')) Object.assign(payload, {image: 'data:image/jpeg;base64,preview', alignment: {applied: true}});
    else Object.assign(payload, {products: [], gaps: [], product_counts: {}, total_products: 0, total_gaps: 0,
      identified_gaps: 0, result_image_url: 'result.jpg', alignment: {applied: options.body.fields.alignment_points !== '[]'}});
    return {ok: true, text: async () => JSON.stringify(payload)};
  },
});
vm.runInContext(fs.readFileSync(__dirname + '/app.js', 'utf8'), context);
const run = code => vm.runInContext(code, context);
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  await tick();
  run("acceptFile({name: 'shelf.jpg', type: 'image/jpeg', size: 100})");
  await tick();
  assert.equal(element('submitButton').disabled, false);
  assert.equal(element('uploadAlignmentPicker').hidden, false);
  assert.equal(element('previewImage').hidden, true);
  assert.equal(run('uploadPicker.readonly'), false); // Selection must work before reference setup too.
  assert.equal(run('detailUploadPicker.readonly'), false);
  run('detailUploadPicker.points = [[.2,.3]]; detailUploadPicker.onChange(detailUploadPicker.points)');
  assert.equal(run('uploadPicker.points.length'), 1);
  assert.equal(run('uploadPicker.points[0][0]'), .2);
  assert.match(element('detailPointStatus').textContent, /1\/4/);
  element('clearUploadAlignment').onclick();
  assert.equal(run('detailUploadPicker.points.length'), 0);
  await element('detectionForm').events.submit({preventDefault() {}});
  assert.equal(requests.at(-1).options.body.fields.alignment_points, '[]');
  assert.equal(element('detectionForm').inert, false);
  assert.equal(element('uploadAlignmentPicker').hidden, true);
  assert.equal(element('previewImage').hidden, false);
  element('editUploadPoints').onclick();
  assert.equal(element('uploadAlignmentPicker').hidden, false);
  assert.equal(element('previewImage').hidden, true);

  plan.alignment_points = [];
  element('planogramSelect').value = plan.id;
  await run('loadSelectedPlan()');
  assert.equal(run('uploadPicker.readonly'), false);
  assert.equal(element('setupPlanAlignment').hidden, false);
  assert.equal(element('setupPlanAlignment').href, '../planogram/?id=' + plan.id + '#alignment');
  assert.equal(element('previewAlignment').disabled, true);
  plan.alignment_points = corners;

  element('planogramSelect').value = plan.id;
  await run('loadSelectedPlan()');
  run('uploadPicker.points = [[.1,.1],[.9,.1],[.9,.9]]; uploadPicker.onChange(uploadPicker.points)');
  assert.equal(run('detailUploadPicker.points.length'), 3);
  let before = requests.length;
  await element('detectionForm').events.submit({preventDefault() {}});
  assert.equal(requests.length, before); // Incomplete points must not reach Detect.
  assert.match(element('formError').textContent, /4/);

  run('uploadPicker.points = [[.1,.1],[.9,.1],[.9,.9],[.1,.9]]; uploadPicker.onChange(uploadPicker.points)');
  await element('previewAlignment').onclick();
  assert.equal(element('alignedPreviewSection').hidden, false);
  assert.equal(element('detectAligned').disabled, false);
  assert.equal(requests.at(-1).url.includes('preview=1'), true);
  await element('detectionForm').events.submit({preventDefault() {}});
  assert.deepEqual(JSON.parse(requests.at(-1).options.body.fields.alignment_points), corners);

  element('clearUploadAlignment').onclick();
  assert.equal(element('alignedPreviewSection').hidden, true);
  await element('detectionForm').events.submit({preventDefault() {}});
  assert.equal(requests.at(-1).options.body.fields.alignment_points, '[]'); // Reference points never enable alignment on their own.
  run('acceptFile({name: "next.jpg", type: "image/jpeg", size: 100})');
  await tick();
  assert.equal(run('uploadPicker.points.length'), 0);
  assert.equal(run('alignmentReady'), false);
  console.log('Detect flow: lower/main image selection and point sync, missing-reference guide, result/source switch, original bypass, preview, aligned Detect and reset passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
