import { readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { clipDir, clipIdOk, frameNameOk } from "$lib/clips.js";

const WIDTH = 2592;
const HEIGHT = 1944;

let writeTail = Promise.resolve();

function locked(task) {
  const run = writeTail.then(task, task);
  writeTail = run.then(
    () => {},
    () => {},
  );
  return run;
}

function cleanLabel(label) {
  if (!label || typeof label !== "object" || Array.isArray(label)) return null;
  if (label.absent === true) return { absent: true };
  if (!Number.isFinite(label.x) || !Number.isFinite(label.y)) return null;
  if (label.x < 0 || label.x > WIDTH || label.y < 0 || label.y > HEIGHT) return null;
  if (label.source !== "click" && label.source !== "accepted") return null;
  return { x: label.x, y: label.y, source: label.source };
}

async function readClip(id) {
  const clip = JSON.parse(await readFile(join(clipDir(id), "clip.json"), "utf8"));
  return clip;
}

async function readLabels(id) {
  try {
    const data = JSON.parse(await readFile(join(clipDir(id), "labels.json"), "utf8"));
    const frames = {};
    for (const [name, label] of Object.entries(data.frames ?? {})) {
      if (!frameNameOk(name)) continue;
      const clean = cleanLabel(label);
      if (clean) frames[name] = clean;
    }
    return { frames };
  } catch (err) {
    if (err && err.code === "ENOENT") return { frames: {} };
    throw err;
  }
}

async function writeLabels(id, labels) {
  const path = join(clipDir(id), "labels.json");
  const tmp = `${path}.tmp`;
  await writeFile(tmp, JSON.stringify(labels, null, 2) + "\n");
  await rename(tmp, path);
}

export async function GET({ params }) {
  if (!clipIdOk(params.id)) return Response.json({ error: "bad id" }, { status: 400 });
  try {
    const [clip, labels] = await Promise.all([readClip(params.id), readLabels(params.id)]);
    return Response.json({ clip, labels }, { headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    if (err && err.code === "ENOENT") return Response.json({ error: "unknown clip" }, { status: 404 });
    return Response.json({ error: "bad clip" }, { status: 500 });
  }
}

export async function POST({ params, request }) {
  if (!clipIdOk(params.id)) return Response.json({ error: "bad id" }, { status: 400 });
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "bad json" }, { status: 400 });
  }
  if (!frameNameOk(body.file)) return Response.json({ error: "bad frame" }, { status: 400 });
  const label = body.label === null ? null : cleanLabel(body.label);
  if (body.label !== null && !label) return Response.json({ error: "bad label" }, { status: 400 });
  try {
    const saved = await locked(async () => {
      const clip = await readClip(params.id);
      const known = new Set((clip.frames ?? []).map((frame) => frame.file));
      if (!known.has(body.file)) {
        const error = new Error("unknown frame");
        error.status = 404;
        throw error;
      }
      const labels = await readLabels(params.id);
      if (label) labels.frames[body.file] = label;
      else delete labels.frames[body.file];
      await writeLabels(params.id, labels);
      return labels.frames[body.file] ?? null;
    });
    return Response.json({ file: body.file, label: saved });
  } catch (err) {
    const status = err && err.status ? err.status : err && err.code === "ENOENT" ? 404 : 500;
    return Response.json({ error: err instanceof Error ? err.message : "save failed" }, { status });
  }
}
