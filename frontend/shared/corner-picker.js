/* Four named correspondences. Coordinates always refer to the full image, not letterboxing. */
(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const names = ['บนซ้าย', 'บนขวา', 'ล่างขวา', 'ล่างซ้าย'];
  const node = (name, attrs = {}) => {
    const item = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([key, value]) => item.setAttribute(key, value));
    return item;
  };
  function valid(points) {
    if (!Array.isArray(points) || points.length !== 4 || !points.every(p =>
      Array.isArray(p) && p.length === 2 && p.every(v => Number.isFinite(v) && v >= 0 && v <= 1))) return false;
    const cross = points.map((a, i) => {
      const b = points[(i + 1) % 4], c = points[(i + 2) % 4];
      return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
    });
    const area = points.reduce((sum, a, i) => {
      const b = points[(i + 1) % 4]; return sum + a[0] * b[1] - b[0] * a[1];
    }, 0) / 2;
    return cross.every(v => v > 0) && area >= 0.002 && points.every((p, i) =>
      Math.hypot(p[0] - points[(i + 1) % 4][0], p[1] - points[(i + 1) % 4][1]) >= 0.01);
  }
  class CornerPicker {
    constructor(host, onChange, onError = () => {}) {
      this.host = host; this.onChange = onChange; this.onError = onError;
      this.points = []; this.height = 1000; this.readonly = false;
      this.svg = node('svg', {class: 'perspective-picker', role: 'group', preserveAspectRatio: 'none',
        'aria-label': 'จุดอ้างอิงโครงตู้ บนซ้าย บนขวา ล่างขวา ล่างซ้าย'});
      this.image = node('image', {width: 1000, preserveAspectRatio: 'none', 'pointer-events': 'none'});
      // Explicitly receive input across the complete image, independently of SVG <image> hit testing.
      this.hitArea = node('rect', {x: 0, y: 0, width: 1000, fill: 'transparent', 'pointer-events': 'all'});
      this.overlay = node('g', {'pointer-events': 'none'});
      this.svg.append(this.image, this.hitArea, this.overlay); host.append(this.svg);
      this.svg.addEventListener('click', event => {
        if (this.readonly) { this.onError('ภาพนี้เป็นภาพอ้างอิง ให้เลือกจุดบนภาพอัปโหลด'); return; }
        if (this.points.length >= 4 || this.suppressClick) return;
        const point = this.point(event);
        if (!point) return;
        const points = [...this.points, point];
        if (points.length === 4 && !valid(points)) {
          this.onError('เลือกจุดตามลำดับ บนซ้าย → บนขวา → ล่างขวา → ล่างซ้าย และอย่าให้กรอบไขว้กัน'); return;
        }
        this.points = points; this.changed();
      });
      this.svg.addEventListener('pointerdown', event => {
        const handle = event.target.closest('[data-corner]');
        if (this.readonly || !handle) return;
        event.preventDefault(); this.drag = Number(handle.dataset.corner);
        this.suppressClick = true; this.svg.setPointerCapture(event.pointerId);
      });
      this.svg.addEventListener('pointermove', event => {
        if (this.drag === undefined) return;
        const point = this.point(event);
        if (!point) return;
        const next = this.points.map(p => [...p]); next[this.drag] = point;
        if (next.length < 4 || valid(next)) { this.points = next; this.changed(); }
      });
      const end = () => { this.drag = undefined; setTimeout(() => { this.suppressClick = false; }, 0); };
      this.svg.addEventListener('pointerup', end); this.svg.addEventListener('pointercancel', end);
      this.svg.addEventListener('lostpointercapture', end);
      this.svg.addEventListener('keydown', event => {
        const handle = event.target.closest('[data-corner]');
        const direction = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[event.key];
        if (this.readonly || !handle || !direction) return;
        event.preventDefault(); const i = Number(handle.dataset.corner), step = event.shiftKey ? 0.01 : 0.002;
        const next = this.points.map(p => [...p]);
        next[i] = next[i].map((v, axis) => Math.max(0, Math.min(1, v + direction[axis] * step)));
        if (next.length < 4 || valid(next)) { this.points = next; this.changed(); this.overlay.querySelector(`[data-corner="${i}"]`)?.focus(); }
      });
    }
    point(event) {
      const rect = this.svg.getBoundingClientRect();
      if (!rect.width || !rect.height) {
        this.onError('ภาพยังไม่พร้อมรับจุด กรุณารอให้ภาพแสดงครบแล้วคลิกอีกครั้ง');
        return null;
      }
      return [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
        Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
    }
    setImage(url, ratio = 1, points = [], readonly = false) {
      this.drag = undefined; this.suppressClick = false;
      this.readonly = readonly; this.height = 1000 / ratio;
      this.points = points.map(p => [...p]); this.svg.toggleAttribute('hidden', !url);
      this.svg.setAttribute('data-readonly', String(readonly));
      this.svg.style.display = url ? 'block' : 'none';
      this.svg.style.aspectRatio = String(ratio);
      this.svg.setAttribute('width', 1000); this.svg.setAttribute('height', this.height);
      this.svg.setAttribute('viewBox', `0 0 1000 ${this.height}`);
      this.hitArea.setAttribute('height', this.height);
      this.image.setAttribute('height', this.height); this.image.setAttribute('href', url || ''); this.draw();
    }
    changed() { this.draw(); this.onChange(this.points.map(p => [...p])); }
    clear() { this.drag = undefined; this.suppressClick = false; this.points = []; this.changed(); }
    undo() { this.points.pop(); this.changed(); }
    draw() {
      this.overlay.replaceChildren();
      if (this.points.length) this.overlay.append(node(this.points.length === 4 ? 'polygon' : 'polyline', {
        points: this.points.map(([x, y]) => `${x * 1000},${y * this.height}`).join(' '),
        fill: this.points.length === 4 ? '#0d6efd22' : 'none', stroke: '#ffd43b', 'stroke-width': 4,
        'pointer-events': 'none'
      }));
      this.points.forEach(([x, y], i) => {
        this.overlay.append(node('circle', {cx: x * 1000, cy: y * this.height, r: 13, fill: '#0d6efd', stroke: '#fff', 'stroke-width': 3,
          'data-corner': i, 'pointer-events': 'all', tabindex: this.readonly ? -1 : 0, role: 'button', 'aria-label': `${i + 1} ${names[i]} ลากหรือใช้ลูกศรเพื่อแก้จุด`}));
        const text = node('text', {x: x * 1000, y: y * this.height + 5, fill: '#fff', 'font-size': 15,
          'text-anchor': 'middle', 'font-weight': 700, 'pointer-events': 'none'});
        text.textContent = i + 1; this.overlay.append(text);
      });
    }
  }
  window.CornerPicker = CornerPicker; window.validAlignmentPoints = valid;
})();
