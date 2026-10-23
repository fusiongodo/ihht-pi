export async function GET() {
  try {
    const res = await fetch("http://ihht-pi.local:8080/frame", { signal: AbortSignal.timeout(4000) });
    if (!res.ok) return new Response(null, { status: 502 });
    return new Response(await res.arrayBuffer(), {
      headers: { "Content-Type": "image/jpeg", "Cache-Control": "no-store" },
    });
  } catch {
    return new Response(null, { status: 502 });
  }
}
