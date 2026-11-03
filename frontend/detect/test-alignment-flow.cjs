// Test the page's request/state flow with DOM stubs, not a browser UI test.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
class Element {
  constructor() {
    this.events = {};
    this.hidden = false;
    this.disabled = false;
    this.children = [];
    this.style = {};
    this.value = "";
    this.classList = { add() {}, remove() {} };
  }
  addEventListener(name, fn) {
    this.events[name] = fn;
  }
  append(...items) {
    this.children.push(...items);
  }
  replaceChildren(...items) {
    this.children = items;
  }
  querySelector() {
    return new Element();
  }
  setAttribute(key, value) {
    this[key] = value;
  }
  scrollIntoView() {}
}
const elements = new Map();
const element = (id) => {
  if (!elements.has(id)) elements.set(id, new Element());
  return elements.get(id);
};
const corners = [
  [0.1, 0.1],
  [0.9, 0.1],
  [0.9, 0.9],
  [0.1, 0.9],
];
const plan = {
  id: "a".repeat(32),
  ratio: 1 / 2,
  image: "reference.jpg",
  alignment_points: corners,
  shelves: [],
};
const mapped = [
  {
    points: [
      [0.2, 0.1],
      [0.8, 0.2],
      [0.9, 0.9],
      [0.1, 0.8],
    ],
  },
];
const requests = [];
let autoFailure = false;
const context = vm.createContext({
  console,
  document: {
    querySelector: (selector) => element(selector.replace("#", "")),
    getElementById: element,
    createElement: () => new Element(),
    createElementNS: () => new Element(),
  },
  Image: class {
    constructor() {
      this.naturalWidth = 400;
      this.naturalHeight = 300;
    }
    async decode() {}
  },
  URL: { createObjectURL: () => "blob:source", revokeObjectURL() {} },
  Option: class {},
  FormData: class {
    constructor() {
      this.fields = {};
    }
    append(key, value) {
      this.fields[key] = value;
    }
  },
  fetch: async (url, options) => {
    requests.push({ url, options });
    let payload = { success: true };
    if (url.includes("classes.php")) payload.count = 30;
    else if (url.includes("list=1")) payload.data = [];
    else if (url.includes("planogram.php?id=")) payload.data = plan;
    else if (url.includes("preview=1")) {
      if (options.body.fields.alignment_mode === "aruco" && autoFailure)
        return {
          ok: false,
          text: async () =>
            JSON.stringify({ success: false, message: "Required ArUco markers are missing" }),
        };
      Object.assign(payload, {
        planogram_regions: mapped,
        width: 400,
        height: 300,
        alignment: {
          applied: true,
          mode: "planogram-to-image",
          ...(options.body.fields.alignment_mode === "aruco"
            ? {
                method: "aruco",
                preview_token: "server-token",
                markers: [
                  {
                    id: 0,
                    points: [
                      [0.1, 0.1],
                      [0.2, 0.1],
                      [0.2, 0.2],
                      [0.1, 0.2],
                    ],
                  },
                ],
                quality: { inliers: 16, matches: 16, median_error_px: 0.7 },
              }
            : {}),
        },
      });
    } else
      Object.assign(payload, {
        products: [],
        gaps: [],
        product_counts: {},
        total_products: 0,
        total_gaps: 0,
        identified_gaps: 0,
        result_image_url: "result.jpg",
        image_width: 400,
        image_height: 300,
        planogram_regions: mapped,
        alignment: {
          applied: options.body.fields.alignment_mode === "aruco",
          mode: "planogram-to-image",
        },
      });
    return { ok: true, text: async () => JSON.stringify(payload) };
  },
});
vm.runInContext(fs.readFileSync(__dirname + "/app.js", "utf8"), context);
element("alignmentMode").value = "off";
const run = (code) => vm.runInContext(code, context);
const tick = () => new Promise((resolve) => setImmediate(resolve));
(async () => {
  await tick();
  run("acceptFile({name:'shelf.jpg',type:'image/jpeg',size:100})");
  await tick();
  assert.equal(element("submitButton").disabled, false);
  await element("detectionForm").events.submit({ preventDefault() {} });
  assert.equal(requests.at(-1).options.body.fields.alignment_mode, "off");
  assert.equal(requests.at(-1).options.body.fields.alignment_points, undefined);
  element("planogramSelect").value = plan.id;
  assert.equal(typeof element("planogramSelect").events.change, "function");
  await element("planogramSelect").events.change();
  assert.equal(run("selectedPlan.id"), plan.id);
  assert.equal(element("imageCaption").textContent, "ภาพที่รอตรวจสอบ");
  assert.equal(element("previewImage").alt, "ภาพสำหรับตรวจสอบ");
  element("alignmentMode").value = "aruco";
  element("alignmentMode").onchange();
  await tick();
  assert.equal(requests.at(-1).options.body.fields.alignment_mode, "aruco");
  assert.equal(element("submitButton").disabled, false);
  assert.equal(element("alignedRegions").children.length, 3);
  await element("detectionForm").events.submit({ preventDefault() {} });
  assert.equal(requests.at(-1).options.body.fields.alignment_token, "server-token");
  assert.equal(requests.at(-1).options.body.fields.image.name, "shelf.jpg");
  assert.equal(requests.at(-1).options.body.fields.alignment_experimental, undefined);
  autoFailure = true;
  run("acceptFile({name:'missing.jpg',type:'image/jpeg',size:100})");
  await tick();
  assert.equal(element("submitButton").disabled, true);
  assert.equal(run("alignmentToken"), null);
  const count = requests.length;
  await element("detectionForm").events.submit({ preventDefault() {} });
  assert.equal(requests.length, count);
  element("alignmentMode").value = "off";
  element("alignmentMode").onchange();
  assert.equal(element("submitButton").disabled, false);
  assert.equal(element("imageCaption").textContent, "ภาพที่รอตรวจสอบ");
  assert.equal(element("previewImage").alt, "ภาพสำหรับตรวจสอบ");
  await element("detectionForm").events.submit({ preventDefault() {} });
  assert.equal(requests.at(-1).options.body.fields.alignment_token, undefined);
  const html = fs.readFileSync(__dirname + "/index.html", "utf8");
  assert.doesNotMatch(
    html,
    /value="auto"|value="manual"|CornerPicker|corner-picker|alignmentExperimental/,
  );
  console.log(
    "Detect: bypass, ArUco preview/token/overlay, missing-marker block and removed controls passed.",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
