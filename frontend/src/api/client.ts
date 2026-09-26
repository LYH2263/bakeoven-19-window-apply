export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return fallback;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    let detail: unknown = text;
    try {
      const body: unknown = JSON.parse(text);
      if (body && typeof body === "object") {
        detail = "detail" in body ? (body as { detail: unknown }).detail : body;
      }
    } catch {
      /* 非 JSON 响应，保留原文 */
    }
    throw new ApiError(res.status, detail, detailMessage(detail, text || res.statusText));
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}
