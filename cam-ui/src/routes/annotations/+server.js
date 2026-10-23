import { readdir, readFile, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";

const WIDTH = 2592;
const HEIGHT = 1944;
const shotsDir = join(process.cwd(), "shots");
const file = join(process.cwd(), "annotations.json");

function nameOk(name) {
  return typeof name === "string" && name === basename(name) && /^[\w.-]+\.jpe?g$/i.test(name);
}

function pointOk(point) {
  return (
    Array.isArray(point) &&
    point.length === 2 &&
    point.every((value) => Number.isFinite(value)) &&
    point[0] >= 0 &&
    point[0] <= WIDTH &&
    point[1] >= 0 &&
    point[1] <= HEIGHT
  );
}

function scaleOk(scale) {
  return typeof scale === "number" && Number.isFinite(scale);
}

async function loadStored() {
  try {
    const data = JSON.parse(await readFile(file, "utf8"));
    const balls = {};
    const scales = {};
    for (const [name, point] of Object.entries(data.balls ?? {})) {
      if (nameOk(name) && pointOk(point)) balls[name] = point.map((value) => Math.round(value));
    }
    for (const [name, scale] of Object.entries(data.scales ?? {})) {
      if (nameOk(name) && scaleOk(scale)) scales[name] = scale;
    }
    return { balls, scales };
  } catch {
    return { balls: {}, scales: {} };
  }
}

async function listShots() {
  try {
    const names = await readdir(shotsDir);
    return names
      .filter((name) => nameOk(name))
      .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  } catch {
    return [];
  }
}

export async function GET() {
  const [files, stored] = await Promise.all([listShots(), loadStored()]);
  const balls = {};
  const scales = {};
  for (const name of files) {
    if (stored.balls[name]) balls[name] = stored.balls[name];
    if (stored.scales[name] !== undefined) scales[name] = stored.scales[name];
  }
  return Response.json(
    { width: WIDTH, height: HEIGHT, files, balls, scales },
    { headers: { "Cache-Control": "no-store" } },
  );
}

export async function POST({ request }) {
  const body = await request.json();
  const hasPoint = body.point !== undefined;
  const hasScale = body.scale !== undefined;
  if (!nameOk(body.file) || (!hasPoint && !hasScale)) {
    return Response.json({ error: "need a shot filename and a point or scale" }, { status: 400 });
  }
  if (hasPoint && !pointOk(body.point)) {
    return Response.json({ error: "point is outside the frame" }, { status: 400 });
  }
  if (hasScale && body.scale !== null && !scaleOk(body.scale)) {
    return Response.json({ error: "scale must be a number" }, { status: 400 });
  }
  const files = await listShots();
  if (!files.includes(body.file)) return Response.json({ error: "unknown shot" }, { status: 404 });
  const { balls, scales } = await loadStored();
  if (hasPoint) balls[body.file] = body.point.map((value) => Math.round(value));
  if (hasScale) {
    if (body.scale === null) delete scales[body.file];
    else scales[body.file] = body.scale;
  }
  await writeFile(file, JSON.stringify({ width: WIDTH, height: HEIGHT, balls, scales }, null, 2) + "\n");
  return Response.json({
    file: body.file,
    point: balls[body.file] ?? null,
    scale: scales[body.file] ?? null,
  });
}
