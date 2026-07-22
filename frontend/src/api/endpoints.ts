import { apiFetch, setToken } from "./client";
import type {
  Document,
  DocumentFilters,
  OcrSuggestion,
  Tag,
  User,
  VisitType,
} from "./types";

// ---- Auth ----
export async function login(email: string, password: string): Promise<void> {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);
  const res = await apiFetch<{ access_token: string }>("/auth/login", {
    method: "POST",
    form,
    auth: false,
  });
  setToken(res.access_token);
}

export const getMe = () => apiFetch<User>("/auth/me");
export const listUsers = () => apiFetch<User[]>("/auth/users");
export const createUser = (email: string, password: string, is_admin: boolean) =>
  apiFetch<User>("/auth/users", { method: "POST", body: { email, password, is_admin } });

// ---- Catalog ----
export const listVisitTypes = () => apiFetch<VisitType[]>("/visit_types");
export const listTags = () => apiFetch<Tag[]>("/tags");
export const createTag = (name: string) =>
  apiFetch<Tag>("/tags", { method: "POST", body: { name } });

// ---- Documents ----
export function listDocuments(filters: DocumentFilters = {}): Promise<Document[]> {
  const p = new URLSearchParams();
  if (filters.q) p.set("q", filters.q);
  if (filters.visit_type_id) p.set("visit_type_id", String(filters.visit_type_id));
  if (filters.date_from) p.set("date_from", filters.date_from);
  if (filters.date_to) p.set("date_to", filters.date_to);
  filters.tag_ids?.forEach((id) => p.append("tag_ids", String(id)));
  const qs = p.toString();
  return apiFetch<Document[]>(`/documents${qs ? `?${qs}` : ""}`);
}

export const getDocument = (id: number) => apiFetch<Document>(`/documents/${id}`);

export function uploadDocument(file: File): Promise<Document> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<Document>("/documents", { method: "POST", form });
}

export interface DocumentPatch {
  doc_date?: string | null;
  visit_type_id?: number | null;
  title?: string | null;
  notes?: string | null;
  tag_ids?: number[];
}
export const updateDocument = (id: number, patch: DocumentPatch) =>
  apiFetch<Document>(`/documents/${id}`, { method: "PATCH", body: patch });

export const deleteDocument = (id: number) =>
  apiFetch<void>(`/documents/${id}`, { method: "DELETE" });

export const runOcr = (id: number) =>
  apiFetch<OcrSuggestion>(`/documents/${id}/ocr`, { method: "POST" });

export const fetchFileBlob = (id: number) =>
  apiFetch<Blob>(`/documents/${id}/file`);
