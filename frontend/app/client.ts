export async function api<T>(path: string, body?: unknown, key?: string): Promise<T> {
  const response = await fetch(`/api${path}`, {method: body === undefined ? "GET" : "POST", headers: {"Content-Type": "application/json", ...(key ? {"Idempotency-Key": key} : {})}, body: body === undefined ? undefined : JSON.stringify(body)});
  return readResponse<T>(response);
}
export async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `Проверьте поля формы (${response.status})`);
  }
  return response.json();
}
