export async function GET() {
  try {
    const res = await fetch("http://ihht-pi.local:8080/focus", { signal: AbortSignal.timeout(2000) });
    if (!res.ok) return Response.json({ score: null }, { status: 502 });
    return new Response(await res.text(), {
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ score: null }, { status: 502 });
  }
}
