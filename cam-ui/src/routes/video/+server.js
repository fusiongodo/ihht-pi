export async function GET() {
  try {
    const res = await fetch("http://ihht-pi.local:8080/video", { signal: AbortSignal.timeout(2000) });
    if (!res.ok) return Response.json({ error: res.statusText }, { status: 502 });
    return new Response(await res.text(), {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "camera unreachable" }, { status: 502 });
  }
}

export async function POST({ request }) {
  try {
    const res = await fetch("http://ihht-pi.local:8080/video", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
      signal: AbortSignal.timeout(8000),
    });
    const text = await res.text();
    return new Response(text, {
      status: res.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "camera unreachable" }, { status: 502 });
  }
}
