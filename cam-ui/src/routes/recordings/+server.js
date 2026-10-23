import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { clipDir, clipIdOk, frameNameOk, recordingsRoot } from "$lib/clips.js";

const camera = "http://ihht-pi.local:8080";

async function labelCount(id) {
  try {
    const data = JSON.parse(await readFile(join(clipDir(id), "labels.json"), "utf8"));
    return Object.keys(data.frames ?? {}).length;
  } catch {
    return 0;
  }
}

export async function GET() {
  let names = [];
  try {
    names = await readdir(recordingsRoot);
  } catch {
    return Response.json({ clips: [] });
  }
  const clips = [];
  for (const id of names.sort((a, b) => b.localeCompare(a))) {
    if (!clipIdOk(id)) continue;
    try {
      const clip = JSON.parse(await readFile(join(clipDir(id), "clip.json"), "utf8"));
      if (!Array.isArray(clip.frames)) continue;
      clips.push({ ...clip, labeled: await labelCount(id) });
    } catch {
      continue;
    }
  }
  return Response.json({ clips }, { headers: { "Cache-Control": "no-store" } });
}

export async function POST({ request }) {
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "bad json" }, { status: 400 });
  }
  const id = body.id;
  if (!clipIdOk(id)) return Response.json({ error: "bad id" }, { status: 400 });
  let clipRes;
  try {
    clipRes = await fetch(`${camera}/recordings/${encodeURIComponent(id)}/clip.json`, {
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    return Response.json({ error: "camera unreachable" }, { status: 502 });
  }
  if (!clipRes.ok) return Response.json({ error: "clip not on camera" }, { status: 502 });
  let clip;
  try {
    clip = await clipRes.json();
  } catch {
    return Response.json({ error: "bad clip" }, { status: 502 });
  }
  if (!Array.isArray(clip.frames)) return Response.json({ error: "bad clip" }, { status: 502 });
  const dir = clipDir(id);
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "clip.json"), JSON.stringify(clip, null, 2) + "\n");
  for (const frame of clip.frames) {
    if (!frameNameOk(frame.file)) {
      return Response.json({ error: "bad frame name" }, { status: 502 });
    }
    let res;
    try {
      res = await fetch(`${camera}/recordings/${encodeURIComponent(id)}/${frame.file}`, {
        signal: AbortSignal.timeout(60000),
      });
    } catch {
      return Response.json({ error: `missing ${frame.file}` }, { status: 502 });
    }
    if (!res.ok) return Response.json({ error: `missing ${frame.file}` }, { status: 502 });
    await writeFile(join(dir, frame.file), Buffer.from(await res.arrayBuffer()));
  }
  return Response.json({ id, frames: clip.frames.length });
}
