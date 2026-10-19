import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
async function proxy(request: NextRequest) {
  const base = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
  const headers = new Headers();
  for (const name of ["cookie", "content-type", "origin", "idempotency-key"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const chunks: Uint8Array[] = [];
    const limit=request.nextUrl.pathname==="/api/inquiries/import"?12*1024*1024:256*1024;
    let size = 0;
    if (request.body) {
      const reader = request.body.getReader();
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        size += chunk.value.byteLength;
        if (size > limit) {
          await reader.cancel();
          return Response.json({detail: "Превышен допустимый размер запроса"}, {status: 413});
        }
        chunks.push(chunk.value);
      }
    }
    const body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
    const upstream = await fetch(`${base}${request.nextUrl.pathname}${request.nextUrl.search}`, {
      method: request.method, headers, cache: "no-store", redirect: "error",
      body: request.method === "GET" ? undefined : body,
      signal: AbortSignal.timeout(120000),
    });
    const outgoing = new Headers();
    for (const name of ["content-type", "content-disposition", "set-cookie", "x-content-type-options"]) {
      const value = upstream.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    outgoing.set("Cache-Control", "no-store");
    return new Response(upstream.body, { status: upstream.status, headers: outgoing });
  } catch {
    return Response.json({ detail: "API недоступен. Проверьте сервис и повторите запрос" }, { status: 502 });
  }
}
export { proxy as GET, proxy as POST };
