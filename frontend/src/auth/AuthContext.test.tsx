import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { User } from "../api/types";
import { AuthProvider, useAuth } from "./AuthContext";

vi.mock("../api/endpoints", () => ({
  getMe: vi.fn(),
  login: vi.fn(),
}));

// imported after vi.mock so these are the mocked implementations
import { getMe, login as apiLogin } from "../api/endpoints";

const getMeMock = vi.mocked(getMe);
const loginMock = vi.mocked(apiLogin);

const TOKEN_KEY = "docarchive_token";

const ALICE: User = {
  id: 1,
  email: "alice@example.com",
  is_admin: false,
  created_at: "2026-01-01T00:00:00Z",
};

function Consumer() {
  const { user, loading, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="loading">{loading ? "loading" : "ready"}</span>
      <span data-testid="user">{user ? user.email : "anonymous"}</span>
      <button type="button" onClick={() => void login("alice@example.com", "pw")}>
        log in
      </button>
      <button type="button" onClick={logout}>
        log out
      </button>
    </div>
  );
}

function renderAuth(queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const ui = userEvent.setup();
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Consumer />
      </AuthProvider>
    </QueryClientProvider>
  );
  return { ui, queryClient };
}

const loadingText = () => screen.getByTestId("loading").textContent;
const userText = () => screen.getByTestId("user").textContent;

beforeEach(() => {
  localStorage.clear();
  getMeMock.mockReset();
  loginMock.mockReset();
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("AuthProvider bootstrap", () => {
  it("makes no network call and settles loading=false when no token is stored", async () => {
    renderAuth();

    await waitFor(() => expect(loadingText()).toBe("ready"));
    expect(getMeMock).not.toHaveBeenCalled();
    expect(userText()).toBe("anonymous");
  });

  it("hydrates the user from getMe() when a token is stored", async () => {
    localStorage.setItem(TOKEN_KEY, "valid-token");
    getMeMock.mockResolvedValue(ALICE);

    renderAuth();

    expect(await screen.findByText("alice@example.com")).toBeInTheDocument();
    await waitFor(() => expect(loadingText()).toBe("ready"));
    expect(getMeMock).toHaveBeenCalledTimes(1);
    // a valid session must keep its credential
    expect(localStorage.getItem(TOKEN_KEY)).toBe("valid-token");
  });

  it("clears the stale token and stays anonymous when getMe() rejects", async () => {
    localStorage.setItem(TOKEN_KEY, "expired-token");
    getMeMock.mockRejectedValue(new ApiError(401, "Could not validate credentials"));

    renderAuth();

    // loading still settles: the .finally() runs on the rejection path too
    await waitFor(() => expect(loadingText()).toBe("ready"));
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(userText()).toBe("anonymous");
  });
});

describe("login / logout", () => {
  it("login() posts the credentials and then populates the user from getMe()", async () => {
    loginMock.mockResolvedValue(undefined);
    getMeMock.mockResolvedValue(ALICE);

    const { ui } = renderAuth();
    await waitFor(() => expect(loadingText()).toBe("ready"));
    // no token at mount, so getMe has not run yet
    expect(getMeMock).not.toHaveBeenCalled();

    await ui.click(screen.getByRole("button", { name: "log in" }));

    await waitFor(() => expect(userText()).toBe("alice@example.com"));
    expect(loginMock).toHaveBeenCalledWith("alice@example.com", "pw");
    expect(getMeMock).toHaveBeenCalledTimes(1);
  });

  it("logout() drops the user and removes the token from localStorage", async () => {
    localStorage.setItem(TOKEN_KEY, "valid-token");
    getMeMock.mockResolvedValue(ALICE);

    const { ui } = renderAuth();
    await waitFor(() => expect(userText()).toBe("alice@example.com"));

    await ui.click(screen.getByRole("button", { name: "log out" }));

    await waitFor(() => expect(userText()).toBe("anonymous"));
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  /**
   * DEFECT (data leak across user switch, pinned): logout() only does
   * clearToken() + setUser(null). It never touches the React Query cache, and
   * AuthProvider has no access to the QueryClient created in main.tsx. So every
   * cached per-user response - the document list, a document's OCR text, the
   * admin user list - survives logout. On a shared family device, user B who
   * logs in right after user A sees A's cached medical documents rendered from
   * cache until each query refetches (and `refetchOnWindowFocus` is disabled in
   * main.tsx, which widens the window further).
   *
   * Fix: call queryClient.clear() (or removeQueries) inside logout, e.g. via
   * useQueryClient() in AuthProvider. This test pins the current leaky
   * behaviour so the fix flips it.
   */
  it("logout() does NOT clear the React Query cache, so per-user data leaks", async () => {
    localStorage.setItem(TOKEN_KEY, "valid-token");
    getMeMock.mockResolvedValue(ALICE);

    const { ui, queryClient } = renderAuth();
    await waitFor(() => expect(userText()).toBe("alice@example.com"));

    // stand in for whatever Library.tsx cached while user A was logged in
    queryClient.setQueryData(["documents", {}], [{ id: 42, title: "Esami del sangue" }]);
    expect(queryClient.getQueryCache().getAll()).toHaveLength(1);

    await ui.click(screen.getByRole("button", { name: "log out" }));
    await waitFor(() => expect(userText()).toBe("anonymous"));

    // still there after logout - this is the bug
    expect(queryClient.getQueryData(["documents", {}])).toEqual([
      { id: 42, title: "Esami del sangue" },
    ]);
    expect(queryClient.getQueryCache().getAll()).toHaveLength(1);
  });
});

describe("useAuth", () => {
  it("throws when used outside an AuthProvider", () => {
    // React logs the thrown render error; silence it to keep the output readable
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      expect(() => render(<Consumer />)).toThrowError(/useAuth must be used within AuthProvider/);
    } finally {
      consoleError.mockRestore();
    }
  });
});
