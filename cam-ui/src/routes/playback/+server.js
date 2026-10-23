import { readFile } from "node:fs/promises";
import { join } from "node:path";

export async function GET() {
  try {
    const data = await readFile(join(process.cwd(), "..", "eval", "playback.json"), "utf8");
    return new Response(data, {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "no playback" }, { status: 404 });
  }
}
