const NATIVE_WIDTH = 2592;
const NATIVE_HEIGHT = 1944;

export const streamPresets = [
  { id: "640", label: "640×480 · 8 fps" },
  { id: "1296", label: "1296×972 · 5 fps" },
  { id: "2592", label: "2592×1944 · 2 fps" },
];

export const methods = {
  combo: {
    label: "Combined",
    fields: [
      { key: "strip", label: "Strip height", min: 80, max: 900, step: 20, value: 320 },
      { key: "bore0", label: "Bore left", min: 0.05, max: 0.55, step: 0.01, value: 0.3 },
      { key: "bore1", label: "Bore right", min: 0.45, max: 0.95, step: 0.01, value: 0.7 },
      { key: "boreAngle", label: "Bore angle", min: -5, max: 5, step: 0.1, value: 0 },
      { key: "glint", label: "Glint radius", min: 0.4, max: 16, step: 0.1, value: 3.5 },
      { key: "disk", label: "Disk radius", min: 2, max: 80, step: 0.5, value: 28 },
      { key: "blur", label: "Vertical blur", min: 2, max: 160, step: 1, value: 40 },
      { key: "shiftX", label: "Shift x", min: -120, max: 80, step: 1, value: -37 },
      { key: "shiftY", label: "Shift y", min: -80, max: 120, step: 1, value: 26 },
    ],
  },
  glint: {
    label: "Glint",
    fields: [
      { key: "strip", label: "Strip height", min: 80, max: 900, step: 20, value: 320 },
      { key: "bore0", label: "Bore left", min: 0.05, max: 0.55, step: 0.01, value: 0.3 },
      { key: "bore1", label: "Bore right", min: 0.45, max: 0.95, step: 0.01, value: 0.7 },
      { key: "boreAngle", label: "Bore angle", min: -5, max: 5, step: 0.1, value: 0 },
      { key: "glint", label: "Glint radius", min: 0.4, max: 16, step: 0.1, value: 3.5 },
      { key: "disk", label: "Disk radius", min: 2, max: 80, step: 0.5, value: 28 },
      { key: "shiftX", label: "Shift x", min: -120, max: 80, step: 1, value: -37 },
      { key: "shiftY", label: "Shift y", min: -80, max: 120, step: 1, value: 26 },
    ],
  },
  peak: {
    label: "Bright peak",
    fields: [
      { key: "strip", label: "Strip height", min: 80, max: 900, step: 20, value: 480 },
      { key: "bore0", label: "Bore left", min: 0.05, max: 0.55, step: 0.01, value: 0.3 },
      { key: "bore1", label: "Bore right", min: 0.45, max: 0.95, step: 0.01, value: 0.7 },
      { key: "boreAngle", label: "Bore angle", min: -5, max: 5, step: 0.1, value: 0 },
      { key: "blur", label: "Vertical blur", min: 2, max: 160, step: 1, value: 40 },
      { key: "shiftX", label: "Shift x", min: -120, max: 80, step: 1, value: -37 },
      { key: "shiftY", label: "Shift y", min: -80, max: 120, step: 1, value: 26 },
    ],
  },
  column: {
    label: "Dark column",
    fields: [
      { key: "strip", label: "Strip height", min: 80, max: 900, step: 20, value: 480 },
      { key: "bore0", label: "Bore left", min: 0.05, max: 0.55, step: 0.01, value: 0.35 },
      { key: "bore1", label: "Bore right", min: 0.45, max: 0.95, step: 0.01, value: 0.75 },
      { key: "boreAngle", label: "Bore angle", min: -5, max: 5, step: 0.1, value: 0 },
      { key: "narrow", label: "Narrow sigma", min: 1, max: 80, step: 1, value: 18 },
      { key: "wide", label: "Wide sigma", min: 4, max: 240, step: 1, value: 70 },
    ],
  },
};

export function defaultParams() {
  const params = {};
  for (const [name, method] of Object.entries(methods)) {
    params[name] = Object.fromEntries(method.fields.map((field) => [field.key, field.value]));
  }
  return params;
}

function solve(matrix, target) {
  const size = target.length;
  const rows = matrix.map((row, index) => [...row, target[index]]);
  for (let col = 0; col < size; col += 1) {
    let pivot = col;
    for (let row = col + 1; row < size; row += 1) {
      if (Math.abs(rows[row][col]) > Math.abs(rows[pivot][col])) pivot = row;
    }
    [rows[col], rows[pivot]] = [rows[pivot], rows[col]];
    const scale = rows[col][col] || 1e-12;
    for (let row = col + 1; row < size; row += 1) {
      const factor = rows[row][col] / scale;
      for (let k = col; k <= size; k += 1) rows[row][k] -= factor * rows[col][k];
    }
  }
  const value = new Array(size);
  for (let row = size - 1; row >= 0; row -= 1) {
    let sum = rows[row][size];
    for (let col = row + 1; col < size; col += 1) sum -= rows[row][col] * value[col];
    value[row] = sum / (rows[row][row] || 1e-12);
  }
  return value;
}

function homography(from, to) {
  const matrix = [];
  const target = [];
  for (let i = 0; i < 4; i += 1) {
    const [x, y] = from[i];
    const [u, v] = to[i];
    matrix.push([x, y, 1, 0, 0, 0, -u * x, -u * y]);
    target.push(u);
    matrix.push([0, 0, 0, x, y, 1, -v * x, -v * y]);
    target.push(v);
  }
  const h = solve(matrix, target);
  return [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], 1];
}

function apply(h, x, y) {
  const w = h[6] * x + h[7] * y + h[8];
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
}

function stripWidth(corners, height) {
  const span = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const top = span(corners[0], corners[1]);
  const bottom = span(corners[3], corners[2]);
  const left = span(corners[0], corners[3]);
  const right = span(corners[1], corners[2]);
  const ratio = (top + bottom) / 2 / Math.max((left + right) / 2, 1);
  return Math.max(24, Math.round(height * ratio));
}

function sample(gray, width, height, x, y) {
  if (x < 0 || y < 0 || x >= width - 1 || y >= height - 1) return 0;
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const dx = x - x0;
  const dy = y - y0;
  const i = y0 * width + x0;
  return (
    gray[i] * (1 - dx) * (1 - dy) +
    gray[i + 1] * dx * (1 - dy) +
    gray[i + width] * (1 - dx) * dy +
    gray[i + width + 1] * dx * dy
  );
}

function warp(gray, frameWidth, frameHeight, corners, height) {
  const scaleX = frameWidth / NATIVE_WIDTH;
  const scaleY = frameHeight / NATIVE_HEIGHT;
  const frameCorners = corners.map(([x, y]) => [x * scaleX, y * scaleY]);
  const width = stripWidth(corners, height);
  const from = [
    [0, 0],
    [width - 1, 0],
    [width - 1, height - 1],
    [0, height - 1],
  ];
  const toFrame = homography(from, frameCorners);
  const strip = new Float32Array(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const [fx, fy] = apply(toFrame, x, y);
      strip[y * width + x] = sample(gray, frameWidth, frameHeight, fx, fy);
    }
  }
  return { strip, width, height, toFrame };
}

function subpixel(score, index) {
  if (index <= 0 || index >= score.length - 1) return index;
  const left = score[index - 1];
  const mid = score[index];
  const right = score[index + 1];
  const denom = left - 2 * mid + right;
  if (Math.abs(denom) < 1e-6) return index;
  return index + (0.5 * (left - right)) / denom;
}

function odd(value) {
  const rounded = Math.max(3, Math.round(value));
  return rounded % 2 ? rounded : rounded + 1;
}

export function kernelSize(glint, disk, stripHeight) {
  const scale = stripHeight / NATIVE_HEIGHT;
  const core = Math.max(0.6, glint * scale);
  const ring = Math.max(core + 1.2, disk * scale);
  return { core, ring };
}

function boreShift(height, angle, y) {
  return (y - (height - 1) / 2) * Math.tan(((angle || 0) * Math.PI) / 180);
}

function boreSpan(width, height, bore0, bore1, angle, y, lo, hi) {
  const shift = boreShift(height, angle, y);
  let x0 = Math.floor(width * bore0 + shift);
  let x1 = Math.floor(width * bore1 + shift);
  x0 = Math.max(lo, Math.min(hi - 1, x0));
  x1 = Math.max(x0 + 1, Math.min(hi, x1));
  return [x0, x1];
}

function boreSegment(width, height, fraction, angle) {
  const yMid = (height - 1) / 2;
  const slope = Math.tan(((angle || 0) * Math.PI) / 180);
  const xAt = (y) => width * fraction + (y - yMid) * slope;
  let y0 = 0;
  let y1 = height - 1;
  if (Math.abs(slope) > 1e-8) {
    const yAt = (x) => yMid + (x - width * fraction) / slope;
    const low = Math.min(yAt(0), yAt(width - 1));
    const high = Math.max(yAt(0), yAt(width - 1));
    y0 = Math.max(0, low);
    y1 = Math.min(height - 1, high);
  } else if (width * fraction < 0 || width * fraction > width - 1) {
    return null;
  }
  if (y1 - y0 < 1) return null;
  return [
    [xAt(y0), y0],
    [xAt(y1), y1],
  ];
}

export function searchOverlay(corners, bore0, bore1, angle = 0) {
  const height = 64;
  const width = stripWidth(corners, height);
  const toFrame = homography(
    [
      [0, 0],
      [width - 1, 0],
      [width - 1, height - 1],
      [0, height - 1],
    ],
    corners,
  );
  const edge = (fraction) => {
    const segment = boreSegment(width, height, fraction, angle);
    if (!segment) return "";
    const [a, b] = segment.map(([x, y]) => apply(toFrame, x, y));
    return `M${a[0].toFixed(1)} ${a[1].toFixed(1)}L${b[0].toFixed(1)} ${b[1].toFixed(1)}`;
  };
  return { lines: `${edge(bore0)}${edge(bore1)}` };
}

function matchedResponse(strip, width, height, glintPx, diskPx) {
  const { core, ring } = kernelSize(glintPx, diskPx, height);
  const size = odd(ring * 2.6);
  const kernel = new Float32Array(size * size);
  const center = (size / 2) | 0;
  let positive = 0;
  let negative = 0;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const r2 = (y - center) ** 2 + (x - center) ** 2;
      if (r2 <= core * core) {
        kernel[y * size + x] = 1;
        positive += 1;
      } else if (r2 <= ring * ring) {
        kernel[y * size + x] = -1;
        negative += 1;
      }
    }
  }
  const balance = positive / (negative || 1);
  for (let i = 0; i < kernel.length; i += 1) if (kernel[i] < 0) kernel[i] *= balance;
  const response = new Float32Array(width * height);
  const margin = center;
  for (let y = margin; y < height - margin; y += 1) {
    for (let x = margin; x < width - margin; x += 1) {
      let sum = 0;
      for (let ky = 0; ky < size; ky += 1) {
        const sy = y + ky - center;
        for (let kx = 0; kx < size; kx += 1) {
          const weight = kernel[ky * size + kx];
          if (weight) sum += weight * strip[sy * width + (x + kx - center)];
        }
      }
      response[y * width + x] = sum;
    }
  }
  return { response, margin };
}

function glintPoint(view, params) {
  const { strip, width, height, toFrame } = view;
  const { response, margin } = matchedResponse(strip, width, height, params.glint, params.disk);
  let best = -Infinity;
  let bx = margin;
  let by = margin;
  let rowX0 = margin;
  let rowX1 = margin + 1;
  for (let y = margin; y < height - margin; y += 1) {
    const [x0, x1] = boreSpan(width, height, params.bore0, params.bore1, params.boreAngle, y, margin, width - margin);
    for (let x = x0; x < x1; x += 1) {
      const value = response[y * width + x];
      if (value > best) {
        best = value;
        bx = x;
        by = y;
        rowX0 = x0;
        rowX1 = x1;
      }
    }
  }
  const column = [];
  for (let y = margin; y < height - margin; y += 1) column.push(response[y * width + bx]);
  const row = [];
  for (let x = rowX0; x < rowX1; x += 1) row.push(response[by * width + x]);
  const y = margin + subpixel(column, by - margin);
  const x = rowX0 + subpixel(row, bx - rowX0);
  return { x, y, toFrame };
}

function blurVertical(strip, width, height, radius) {
  const blurred = new Float32Array(strip.length);
  const span = radius * 2 + 1;
  for (let x = 0; x < width; x += 1) {
    for (let y = 0; y < height; y += 1) {
      let sum = 0;
      for (let k = -radius; k <= radius; k += 1) {
        const sy = Math.min(height - 1, Math.max(0, y + k));
        sum += strip[sy * width + x];
      }
      blurred[y * width + x] = sum / span;
    }
  }
  return blurred;
}

function peakPoint(view, params) {
  const { strip, width, height, toFrame } = view;
  const radius = Math.max(1, Math.round((params.blur * height) / NATIVE_HEIGHT));
  const blurred = blurVertical(strip, width, height, radius);
  let best = -Infinity;
  let bx = 0;
  let by = 0;
  for (let y = radius; y < height - radius; y += 1) {
    const [x0, x1] = boreSpan(width, height, params.bore0, params.bore1, params.boreAngle, y, 0, width);
    for (let x = x0; x < x1; x += 1) {
      const value = strip[y * width + x] - blurred[y * width + x];
      if (value > best) {
        best = value;
        bx = x;
        by = y;
      }
    }
  }
  return { x: bx, y: by, toFrame };
}

function smooth(values, sigma) {
  const radius = Math.max(1, Math.round(sigma * 3));
  const kernel = [];
  let weight = 0;
  for (let i = -radius; i <= radius; i += 1) {
    const value = Math.exp(-0.5 * (i / sigma) ** 2);
    kernel.push(value);
    weight += value;
  }
  return values.map((_, index) => {
    let sum = 0;
    for (let k = -radius; k <= radius; k += 1) {
      const at = Math.min(values.length - 1, Math.max(0, index + k));
      sum += values[at] * kernel[k + radius];
    }
    return sum / weight;
  });
}

function columnPoint(view, params) {
  const { strip, width, height, toFrame } = view;
  const column = [];
  for (let y = 0; y < height; y += 1) {
    const [x0, x1] = boreSpan(width, height, params.bore0, params.bore1, params.boreAngle, y, 0, width);
    let sum = 0;
    for (let x = x0; x < x1; x += 1) sum += strip[y * width + x];
    column.push(sum / (x1 - x0));
  }
  const scale = height / NATIVE_HEIGHT;
  const narrow = smooth(column, Math.max(0.8, params.narrow * scale));
  const wide = smooth(column, Math.max(2, params.wide * scale));
  let best = Infinity;
  let by = 0;
  const margin = Math.round(params.wide * scale);
  for (let y = margin; y < height - margin; y += 1) {
    const value = narrow[y] - wide[y];
    if (value < best) {
      best = value;
      by = y;
    }
  }
  const score = column.map((_, index) => wide[index] - narrow[index]);
  const y = subpixel(score, by);
  const [x0, x1] = boreSpan(width, height, params.bore0, params.bore1, params.boreAngle, y, 0, width);
  return { x: (x0 + x1) / 2, y, toFrame };
}

function comboPoint(view, params) {
  const { strip, width, height, toFrame } = view;
  const { response, margin } = matchedResponse(strip, width, height, params.glint, params.disk);
  const radius = Math.max(1, Math.round(((params.blur || 40) * height) / NATIVE_HEIGHT));
  const blurred = blurVertical(strip, width, height, radius);
  const column = [];
  for (let y = 0; y < height; y += 1) {
    const [x0, x1] = boreSpan(width, height, params.bore0, params.bore1, params.boreAngle, y, 0, width);
    let sum = 0;
    for (let x = x0; x < x1; x += 1) sum += strip[y * width + x];
    column.push(sum / (x1 - x0));
  }
  const scale = height / NATIVE_HEIGHT;
  const narrow = smooth(column, Math.max(0.8, 18 * scale));
  const wide = smooth(column, Math.max(2, 70 * scale));
  const y0 = Math.max(margin, radius);
  const y1 = height - y0;
  let maxGlint = 0;
  let maxCompact = 0;
  let maxDark = 0;
  for (let y = y0; y < y1; y += 1) {
    const dark = wide[y] - narrow[y];
    if (dark > maxDark) maxDark = dark;
    const [x0, x1] = boreSpan(width, height, params.bore0, params.bore1, params.boreAngle, y, margin, width - margin);
    for (let x = x0; x < x1; x += 1) {
      const glint = response[y * width + x];
      const compact = strip[y * width + x] - blurred[y * width + x];
      if (glint > maxGlint) maxGlint = glint;
      if (compact > maxCompact) maxCompact = compact;
    }
  }
  let best = -Infinity;
  let bx = margin;
  let by = y0;
  let rowX0 = margin;
  let rowX1 = margin + 1;
  for (let y = y0; y < y1; y += 1) {
    const dark = maxDark > 0 ? Math.max(0, wide[y] - narrow[y]) / maxDark : 1;
    const [x0, x1] = boreSpan(width, height, params.bore0, params.bore1, params.boreAngle, y, margin, width - margin);
    for (let x = x0; x < x1; x += 1) {
      const glint = Math.max(0, response[y * width + x]) / (maxGlint || 1);
      const compact = Math.max(0, strip[y * width + x] - blurred[y * width + x]) / (maxCompact || 1);
      const score = glint * (0.35 + 0.65 * compact) * (0.65 + 0.35 * dark);
      if (score > best) {
        best = score;
        bx = x;
        by = y;
        rowX0 = x0;
        rowX1 = x1;
      }
    }
  }
  const profile = [];
  for (let y = y0; y < y1; y += 1) profile.push(response[y * width + bx]);
  const across = [];
  for (let x = rowX0; x < rowX1; x += 1) across.push(response[by * width + x]);
  return {
    x: rowX0 + subpixel(across, bx - rowX0),
    y: y0 + subpixel(profile, by - y0),
    toFrame,
  };
}

const scorers = { combo: comboPoint, glint: glintPoint, peak: peakPoint, column: columnPoint };

export function locate(gray, frameWidth, frameHeight, corners, method, params) {
  if (!corners || corners.length !== 4) return null;
  const height = Math.round(params.strip);
  const view = warp(gray, frameWidth, frameHeight, corners, height);
  const found = scorers[method](view, params);
  const [x, y] = apply(found.toFrame, found.x, found.y);
  const scaleX = NATIVE_WIDTH / frameWidth;
  const scaleY = NATIVE_HEIGHT / frameHeight;
  const peakX = x * scaleX;
  const peakY = y * scaleY;
  return {
    x: peakX + (params.shiftX || 0),
    y: peakY + (params.shiftY || 0),
    peakX,
    peakY,
  };
}
