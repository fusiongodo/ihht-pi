import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const shots = join(process.cwd(), "shots");
const annotations = join(process.cwd(), "annotations.json");

function stamp() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  );
}

async function rememberScale(name, scale) {
  let data = { width: 2592, height: 1944, balls: {}, scales: {} };
  try {
    data = JSON.parse(await readFile(annotations, "utf8"));
  } catch {
    data = { width: 2592, height: 1944, balls: {}, scales: {} };
  }
  data.width = 2592;
  data.height = 1944;
  data.balls = data.balls ?? {};
  data.scales = { ...(data.scales ?? {}), [name]: scale };
  await writeFile(annotations, JSON.stringify(data, null, 2) + "\n");
}

export async function POST({ request }) {
  let scale = null;
  const text = await request.text();
  if (text) {
    let body;
    try {
      body = JSON.parse(text);
    } catch {
      return Response.json({ error: "scale must be a number" }, { status: 400 });
    }
    if (body.scale !== undefined && body.scale !== null) {
      if (typeof body.scale !== "number" || !Number.isFinite(body.scale)) {
        return Response.json({ error: "scale must be a number" }, { status: 400 });
      }
      scale = body.scale;
    }
  }

  let res;
  try {
    res = await fetch("http://ihht-pi.local:8080/snap", { signal: AbortSignal.timeout(60000) });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return Response.json({ error: message }, { status: 502 });
  }
  if (!res.ok) {
    return Response.json({ error: `camera returned ${res.status}` }, { status: 502 });
  }
  const jpeg = Buffer.from(await res.arrayBuffer());
  await mkdir(shots, { recursive: true });
  const file = scale === null ? `${stamp()}.jpg` : `${stamp()}_${scale}.jpg`;
  await writeFile(join(shots, file), jpeg);
  if (scale !== null) await rememberScale(file, scale);
  return Response.json({ file });
}
