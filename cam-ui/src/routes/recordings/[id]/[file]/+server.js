import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { clipDir, clipIdOk, frameNameOk } from "$lib/clips.js";

export async function GET({ params }) {
  if (!clipIdOk(params.id) || !frameNameOk(params.file)) return new Response("not found", { status: 404 });
  try {
    const bytes = await readFile(join(clipDir(params.id), params.file));
    return new Response(bytes, {
      headers: { "Content-Type": "image/png", "Cache-Control": "no-store" },
    });
  } catch {
    return new Response("not found", { status: 404 });
  }
}
