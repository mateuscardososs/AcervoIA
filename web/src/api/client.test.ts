import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, request } from "./client";

describe("API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("attaches the session bearer token to private requests", async () => {
    sessionStorage.setItem("acervoia.accessToken", "token-123");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "user-1" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await request("/auth/me");

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer token-123");
  });

  it("sends login credentials as an OAuth2 form without placing them in the URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ access_token: "jwt", token_type: "bearer" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.login("person@example.test", "private-password");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/auth/token");
    expect(url).not.toContain("private-password");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(URLSearchParams);
    expect(String(init.body)).toContain("username=person%40example.test");
  });

  it("does not set multipart content type so the browser can add its boundary", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "document-1" }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["manual"], "manual.txt", { type: "text/plain" });

    await api.uploadDocument("collection-1", file);

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  });

  it("clears the session token and reports a safe error on 401", async () => {
    sessionStorage.setItem("acervoia.accessToken", "expired-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "unauthorized" }), { status: 401 }),
      ),
    );

    await expect(request("/auth/me")).rejects.toBeInstanceOf(ApiError);
    expect(sessionStorage.getItem("acervoia.accessToken")).toBeNull();
  });
});
