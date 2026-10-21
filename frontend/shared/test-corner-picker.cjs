// Interaction/coordinate tests without a browser or external dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.attributes = {}; this.children = []; this.events = {}; this.style = {}; }
  setAttribute(key, value) { this.attributes[key] = value; }
  toggleAttribute(key, force) { if (force) this.attributes[key] = ''; else delete this.attributes[key]; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  addEventListener(name, callback) { this.events[name] = callback; }
  getBoundingClientRect() { return this.rect || {left: 0, top: 0, width: 1000, height: 500}; }
  setPointerCapture() {}
  querySelector() { return {focus() {}}; }
}
const context = {window: {}, document: {createElementNS: () => new Element()}, setTimeout};
vm.runInNewContext(fs.readFileSync(__dirname + '/corner-picker.js', 'utf8'), context);
const {CornerPicker, validAlignmentPoints} = context.window;
const points = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]];
assert.equal(validAlignmentPoints(points), true);
assert.equal(validAlignmentPoints([...points].reverse()), false);
assert.equal(validAlignmentPoints([points[0], points[2], points[1], points[3]]), false);
assert.equal(validAlignmentPoints(points.slice(0, 3)), false);
let changes = 0, errors = 0;
const picker = new CornerPicker(new Element(), () => changes++, () => errors++);
picker.setImage('image.jpg', 2, []);
for (const [x, y] of points) picker.svg.events.click({clientX: x * 1000, clientY: y * 500});
assert.equal(changes, 4);
assert.deepEqual(JSON.parse(JSON.stringify(picker.points)), points); // y uses actual image height, not 1000.
picker.svg.events.click({clientX: 500, clientY: 250});
assert.equal(changes, 4); // Fifth point cannot silently change the pairs.
picker.undo(); assert.equal(picker.points.length, 3);
picker.svg.events.click({clientX: 900, clientY: 50});
assert.equal(errors, 1); assert.equal(picker.points.length, 3);
picker.clear(); assert.equal(picker.points.length, 0);
picker.setImage('reference.jpg', 2, points, true);
picker.svg.events.click({clientX: 500, clientY: 250});
assert.deepEqual(JSON.parse(JSON.stringify(picker.points)), points);
picker.setImage('image.jpg', 2, points);
picker.svg.events.pointerdown({target: {closest: () => ({dataset: {corner: '0'}})}, preventDefault() {}, pointerId: 1});
picker.svg.events.pointermove({clientX: 150, clientY: 75});
assert.deepEqual(JSON.parse(JSON.stringify(picker.points[0])), [0.15, 0.15]);
picker.svg.events.pointerup();
picker.svg.events.keydown({target: {closest: () => ({dataset: {corner: '0'}})}, key: 'ArrowRight', preventDefault() {}});
assert.equal(picker.points[0][0], 0.152);
assert.equal(picker.hitArea.attributes['pointer-events'], 'all');
assert.equal(picker.image.attributes['pointer-events'], 'none');
assert.equal(picker.hitArea.attributes.height, 500);
picker.clear();
picker.svg.rect = {left: 37, top: 91, width: 600, height: 300};
picker.svg.events.click({clientX: 157, clientY: 181});
assert.deepEqual(JSON.parse(JSON.stringify(picker.points)), [[.2, .3]]);
picker.svg.rect = {left: 0, top: 0, width: 0, height: 0};
const previousErrors = errors;
picker.svg.events.click({clientX: 100, clientY: 100});
assert.equal(picker.points.length, 1);
assert.equal(errors, previousErrors + 1);
console.log('Corner picker: full-image input layer, scaled/offset click coordinates, invalid shapes, unavailable layout feedback, drag and keyboard passed.');
