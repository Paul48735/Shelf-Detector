// Verify the main reference image switches between product-region and corner-picking modes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.events = {}; this.children = []; this.value = ''; this.classList = {toggle() {}}; }
  setAttribute() {}
  toggleAttribute() {}
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  addEventListener(event, fn) { this.events[event] = fn; }
  getContext() { return {measureText: text => ({width: text.length * 8})}; }
}
const elements = new Map();
const element = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const plan = {id: 'a'.repeat(32), version: 1, name: 'Test', image: 'reference.jpg', ratio: 4 / 3,
  alignment_points: [], shelves: [{id: 'upper', name: 'Upper', product: 'a', target: 1, points: [[0,0],[1,0],[1,1],[0,1]]}]};
const requests = [];
const context = vm.createContext({
  window: {location: {hash: '#alignment', search: '?id=' + plan.id}, addEventListener() {}},
  document: {getElementById: element, querySelector: element, createElement: () => new Element(), createElementNS: () => new Element()},
  crypto: {randomUUID: () => 'region'}, localStorage: {getItem: () => null}, URLSearchParams,
  CornerPicker: class {
    constructor(host, change) { this.onChange = change; this.points = []; }
    setImage(url, ratio, points) { this.points = points; }
    clear() { this.points = []; this.onChange([]); }
    undo() { this.points = this.points.slice(0, -1); this.onChange(this.points); }
  },
  validAlignmentPoints: points => points.length === 4, Option: class {},
  fetch: async url => {
    requests.push(url);
    return {ok: true, json: async () => ({success: true,
      data: url.includes('list=1') ? [plan] : url.includes('classes.php') ? ['a'] : plan})};
  },
});
vm.runInContext(fs.readFileSync(__dirname + '/planogram.js', 'utf8'), context);
(async () => {
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests[0], '../../backend/api/planogram.php?id=' + plan.id);
  assert.equal(element('.workspace').inert, false);
  assert.equal(element('planAlignmentPicker').hidden, false);
  assert.equal(element('editor').hidden, true);
  assert.equal(element('alignmentControls').hidden, false);
  element('pickProductMode').onclick();
  assert.equal(element('planAlignmentPicker').hidden, true);
  assert.equal(element('editor').hidden, false);
  element('pickAlignmentMode').onclick();
  assert.equal(element('planAlignmentPicker').hidden, false);
  assert.equal(element('editor').hidden, true);
  vm.runInContext('alignmentPicker.onChange([[.1,.1],[.9,.1],[.9,.9],[.1,.9]])', context);
  assert.equal(vm.runInContext('plan.alignment_points.length', context), 4);
  assert.equal(vm.runInContext('dirty', context), true);
  console.log('Planogram modes: selected-plan deep link, main-image corner editing, product mode and corner persistence state passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
