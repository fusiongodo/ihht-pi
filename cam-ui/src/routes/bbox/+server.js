import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const file = join(process.cwd(), "bbox.json");
const WIDTH = 2592;
const HEIGHT = 1944;

function cornersOk(corners) {
  return (
    Array.isArray(corners) &&
    corners.length === 4 &&
    corners.every(
      (point) =>
        Array.isArray(point) &&
        point.length === 2 &&
        point.every((value) => Number.isFinite(value)) &&
        point[0] >= 0 &&
        point[0] <= WIDTH &&
        point[1] >= 0 &&
        point[1] <= HEIGHT,
    )
  );
}

async function pushCorners(corners) {
  if (!cornersOk(corners)) return;
  try {
    await fetch("http://ihht-pi.local:8080/bbox", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ corners }),
      signal: AbortSignal.timeout(2000),
    });
  } catch {}
}

export async function GET() {
  try {
    const text = await readFile(file, "utf8");
    const saved = JSON.parse(text);
    await pushCorners(saved.corners);
    return new Response(text, {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ width: WIDTH, height: HEIGHT, corners: [] });
  }
}

export async function POST({ request }) {
  const body = await request.json();
  if (!cornersOk(body.corners)) {
    return Response.json({ error: "need four corners inside the frame" }, { status: 400 });
  }
  const saved = {
    width: WIDTH,
    height: HEIGHT,
    corners: body.corners.map(([x, y]) => [Math.round(x), Math.round(y)]),
  };
  await writeFile(file, JSON.stringify(saved, null, 2) + "\n");
  await pushCorners(saved.corners);
  return Response.json(saved);
}
