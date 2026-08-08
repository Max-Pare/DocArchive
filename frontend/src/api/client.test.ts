import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, clearToken, getToken, setToken } from "./client";

const TOKEN_KEY = "docarchive_token";

/**
 * VITE_API_BASE is not defined when Vitest loads the module, so client.ts falls
 * back to the relative "/api" prefix. Every URL assertion below depends on that.
 */
const BASE = "/api";

type FetchMock = ReturnType<typeof vi.fn<(input: string, init?: RequestInit) => Promise<Response>>>;

let fetchMock: FetchMock;

/** Reads the RequestInit of the nth fetch call (defaults to the first). */
function initOf(call = 0): RequestInit {
  const args = fetchMock.mock.calls[call];
  if (!args) throw new Error(`fetch was not called ${call + 1} time(s)`);
  return args[1] ?? {};
}

/** Reads the plain header record client.ts builds for the nth fetch call. */
function headersOf(call = 0): Record<string, string> {
  return (initOf(call).headers ?? {}) as Record<string, string>;
}

/** Awaits a rejection and returns it, failing loudly if the promise resolves. */
async function rejection(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (err) {
    return err;
  }
  throw new Error("expected apiFetch to reject, but it resolved");
}

beforeEach(() => {
  localStorage.clear();
  fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("token storage", () => {
  it("round-trips the token through localStorage under the documented key", () => {
    expect(getToken()).toBeNull();

    setToken("abc.def.ghi");
    expect(localStorage.getItem(TOKEN_KEY)).toBe("abc.def.ghi");
    expect(getToken()).toBe("abc.def.ghi");

    clearToken();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(getToken()).toBeNull();
  });
});

describe("apiFetch request shaping", () => {
  it("prefixes the API base and forwards the method", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      })
    );

    await apiFetch<{ id: number }>("/documents/1", { method: "DELETE" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]![0]).toBe(`${BASE}/documents/1`);
    expect(initOf().method).toBe("DELETE");
  });

  it("sends the Authorization bearer header when a token is stored", async () => {
    setToken("stored-token");
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ email: "a@b.c" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      })
    );

    await apiFetch("/auth/me");

    expect(headersOf()["Authorization"]).toBe("Bearer stored-token");
  });

  it("does NOT send Authorization when auth is false, even with a token stored", async () => {
    setToken("stored-token");
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ access_token: "new" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      })
    );

    const form = new URLSearchParams({ username: "a@b.c", password: "pw" });
    await apiFetch("/auth/login", { method: "POST", form, auth: false });

    expect(headersOf()).not.toHaveProperty("Authorization");
    // a form body must stay un-typed so the browser sets the multipart/urlencoded header
    expect(headersOf()).not.toHaveProperty("Content-Type");
    expect(initOf().body).toBe(form);
  });

  it("omits Authorization when auth is on but no token is stored", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    await apiFetch("/documents/1", { method: "DELETE" });

    expect(headersOf()).not.toHaveProperty("Authorization");
  });

  it("JSON-encodes an object body and sets Content-Type", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: 7 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      })
    );

    await apiFetch("/documents/7", { method: "PATCH", body: { title: "Referto" } });

    expect(headersOf()["Content-Type"]).toBe("application/json");
    expect(initOf().body).toBe(JSON.stringify({ title: "Referto" }));
  });
});

describe("apiFetch responses", () => {
  it("parses a JSON success body", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: 1, email: "a@b.c" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      })
    );

    const out = await apiFetch<{ id: number; email: string }>("/auth/me");

    expect(out).toEqual({ id: 1, email: "a@b.c" });
  });

  it("resolves to undefined on 204 No Content", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    const out = await apiFetch<void>("/documents/1", { method: "DELETE" });

    expect(out).toBeUndefined();
  });

  it("returns a blob for a non-JSON success body (file download)", async () => {
    fetchMock.mockResolvedValue(
      new Response("%PDF-1.7 fake", {
        status: 200,
        headers: { "content-type": "application/pdf" },
      })
    );

    const blob = await apiFetch<Blob>("/documents/1/file");

    // not `instanceof Blob`: the jsdom global and the fetch implementation's Blob
    // are different classes, so identity checks are meaningless here.
    expect(typeof blob.size).toBe("number");
    expect(await blob.text()).toBe("%PDF-1.7 fake");
  });
});

describe("apiFetch error handling", () => {
  it("clears the stored token on 401 so the session-expiry path logs the user out", async () => {
    setToken("expired-token");
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Could not validate credentials" }), {
        status: 401,
        statusText: "Unauthorized",
        headers: { "content-type": "application/json" },
      })
    );

    const err = await rejection(apiFetch("/auth/me"));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    expect((err as ApiError).message).toBe("Could not validate credentials");
    // the security-relevant assertion: the dead credential must not survive
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(getToken()).toBeNull();
  });

  it("leaves the token in place on a non-401 failure", async () => {
    setToken("good-token");
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Not your document" }), {
        status: 403,
        statusText: "Forbidden",
        headers: { "content-type": "application/json" },
      })
    );

    const err = await rejection(apiFetch("/documents/99"));

    expect((err as ApiError).status).toBe(403);
    expect((err as ApiError).message).toBe("Not your document");
    expect(getToken()).toBe("good-token");
  });

  it("surfaces the JSON `detail` string as the thrown message", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "File too large" }), {
        status: 413,
        statusText: "Payload Too Large",
        headers: { "content-type": "application/json" },
      })
    );

    const err = await rejection(apiFetch("/documents", { method: "POST" }));

    expect((err as ApiError).message).toBe("File too large");
  });

  it("falls back to statusText when the error body is not JSON (no parse crash)", async () => {
    // e.g. an nginx/Caddy 502 HTML page, which is exactly what a dead backend returns
    fetchMock.mockResolvedValue(
      new Response("<html><body>502 Bad Gateway</body></html>", {
        status: 502,
        statusText: "Bad Gateway",
        headers: { "content-type": "text/html" },
      })
    );

    const err = await rejection(apiFetch("/documents"));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(502);
    expect((err as ApiError).message).toBe("Bad Gateway");
  });

  it("falls back when a JSON error body carries no `detail`", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: "nope" }), {
        status: 500,
        statusText: "Internal Server Error",
        headers: { "content-type": "application/json" },
      })
    );

    const err = await rejection(apiFetch("/documents"));

    expect((err as ApiError).message).toBe("Internal Server Error");
  });

  /**
   * DEFECT (UX, pinned): FastAPI returns 422 with `detail` as an ARRAY of
   * per-field validation objects, e.g.
   *   {"detail":[{"loc":["body","doc_date"],"msg":"invalid date format",...}]}
   * client.ts does `detail = data.detail ?? detail` and then
   * `typeof detail === "string" ? detail : "Request failed"`, so the array is
   * discarded and every validation failure collapses to the opaque string
   * "Request failed". The user is told nothing about WHICH field is wrong and
   * the per-field `msg` never reaches the UI. The `typeof` guard does at least
   * prevent an "[object Object]" message. Fix would be to join the `msg` fields
   * (or expose `detail` on ApiError so forms can map it to inputs); until then
   * this test pins the current, lossy behaviour.
   */
  it("collapses a FastAPI 422 array detail to the generic fallback message", async () => {
    const detail = [
      { type: "date_from_datetime_parsing", loc: ["body", "doc_date"], msg: "invalid date format" },
      { type: "int_parsing", loc: ["body", "visit_type_id"], msg: "not a valid integer" },
    ];
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail }), {
        status: 422,
        statusText: "Unprocessable Entity",
        headers: { "content-type": "application/json" },
      })
    );

    const err = await rejection(apiFetch("/documents/1", { method: "PATCH", body: {} }));

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(422);
    expect((err as ApiError).message).toBe("Request failed");
    // the actual, actionable messages are nowhere to be found
    expect((err as ApiError).message).not.toContain("invalid date format");
    expect((err as ApiError).message).not.toContain("[object Object]");
    // and nothing structured is attached to the error either
    expect(err).not.toHaveProperty("detail");
  });
});
