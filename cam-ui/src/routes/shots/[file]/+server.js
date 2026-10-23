import { readFile } from "node:fs/promises";
import { basename, join } from "node:path";

const shots = join(process.cwd(), "shots");

function shotNameOk(name) {
  return typeof name === "string" && name === basename(name) && /^[\w.-]+\.jpe?g$/i.test(name);
}

export async function GET({ params }) {
  const name = params.file;
  if (!shotNameOk(name)) return new Response("not found", { status: 404 });
  try {
    const bytes = await readFile(join(shots, name));
    return new Response(bytes, {
      headers: { "Content-Type": "image/jpeg", "Cache-Control": "no-store" },
    });
  } catch {
    return new Response("not found", { status: 404 });
  }
}
