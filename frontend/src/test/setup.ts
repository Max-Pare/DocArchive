// Registers the jest-dom matchers (toBeInTheDocument, toHaveTextContent, ...) on
// Vitest's `expect`, and augments its TS types so `tsc --noEmit` accepts them.
import "@testing-library/jest-dom/vitest";

/**
 * Web Storage shim for Node >= 26.
 *
 * Node 26 exposes its own `localStorage` / `sessionStorage` globals, which stay
 * inert (they warn once and evaluate to `undefined`) unless the process was
 * started with --localstorage-file. Vitest's jsdom environment copies the jsdom
 * window's properties onto `globalThis` but skips any name that already exists
 * there - and it aliases `window` to `globalThis` - so both `localStorage` and
 * `window.localStorage` end up being Node's inert global. App code that calls
 * bare `localStorage.getItem(...)` (src/api/client.ts stores the auth token
 * that way) then dies with "Cannot read properties of undefined".
 *
 * Fix: install a spec-shaped in-memory Storage on the global when the runtime's
 * own one is unusable. Values and keys are coerced to strings, as the Web
 * Storage spec requires, so tests cannot pass on non-string round-trips that a
 * browser would have stringified.
 */
class MemoryStorage implements Storage {
  private entries = new Map<string, string>();

  get length(): number {
    return this.entries.size;
  }

  key(index: number): string | null {
    return [...this.entries.keys()][index] ?? null;
  }

  getItem(key: string): string | null {
    return this.entries.get(String(key)) ?? null;
  }

  setItem(key: string, value: string): void {
    this.entries.set(String(key), String(value));
  }

  removeItem(key: string): void {
    this.entries.delete(String(key));
  }

  clear(): void {
    this.entries.clear();
  }
}

for (const key of ["localStorage", "sessionStorage"] as const) {
  // read the descriptor instead of the property: touching Node's accessor is
  // what emits the "--localstorage-file was not provided" ExperimentalWarning.
  const existing = Object.getOwnPropertyDescriptor(globalThis, key)?.value as Storage | undefined;
  if (typeof existing?.getItem !== "function") {
    Object.defineProperty(globalThis, key, {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    });
  }
}
