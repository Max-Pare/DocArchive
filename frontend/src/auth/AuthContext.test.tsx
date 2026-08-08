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
   * Regression guard for a data leak across user switch: dropping the token is not
   * enough, because every per-user response (document list, OCR text, admin user
   * list) stays in the React Query cache. On a shared family device the next user
   * would render the previous user's medical documents from cache - and
   * refetchOnWindowFocus is disabled in main.tsx, which widens that window.
   */
  it("logout() clears the React Query cache so per-user data cannot leak", async () => {
    localStorage.setItem(TOKEN_KEY, "valid-token");
    getMeMock.mockResolvedValue(ALICE);

    const { ui, queryClient } = renderAuth();
    await waitFor(() => expect(userText()).toBe("alice@example.com"));

    // stand in for whatever Library.tsx cached while user A was logged in
    queryClient.setQueryData(["documents", {}], [{ id: 42, title: "Esami del sangue" }]);
    expect(queryClient.getQueryCache().getAll()).toHaveLength(1);

    await ui.click(screen.getByRole("button", { name: "log out" }));
    await waitFor(() => expect(userText()).toBe("anonymous"));

    expect(queryClient.getQueryData(["documents", {}])).toBeUndefined();
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
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
