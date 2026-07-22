import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { listDocuments, listTags, listVisitTypes } from "../api/endpoints";
import type { DocumentFilters } from "../api/types";

const STATUS_LABEL: Record<string, string> = {
  uploaded: "In coda OCR",
  ocr_running: "OCR in corso",
  ocr_done: "OCR completato",
  ocr_failed: "OCR fallito",
};

export default function Library() {
  const [filters, setFilters] = useState<DocumentFilters>({});
  const [qDraft, setQDraft] = useState("");

  const visitTypes = useQuery({ queryKey: ["visit_types"], queryFn: listVisitTypes });
  const tags = useQuery({ queryKey: ["tags"], queryFn: listTags });
  const docs = useQuery({
    queryKey: ["documents", filters],
    queryFn: () => listDocuments(filters),
  });

  function apply(patch: Partial<DocumentFilters>) {
    setFilters((f) => ({ ...f, ...patch }));
  }

  return (
    <div>
      <div className="page-head">
        <h1>Archivio</h1>
        <Link to="/upload" className="btn">
          + Carica documento
        </Link>
      </div>

      <div className="card filterbar">
        <form
          className="search-row"
          onSubmit={(e) => {
            e.preventDefault();
            apply({ q: qDraft || undefined });
          }}
        >
          <input
            placeholder="Cerca nel testo dei documenti…"
            value={qDraft}
            onChange={(e) => setQDraft(e.target.value)}
          />
          <button type="submit">Cerca</button>
        </form>

        <div className="filters">
          <label>
            Tipo
            <select
              value={filters.visit_type_id ?? ""}
              onChange={(e) =>
                apply({ visit_type_id: e.target.value ? Number(e.target.value) : undefined })
              }
            >
              <option value="">Tutti</option>
              {visitTypes.data?.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Da
            <input
              type="date"
              value={filters.date_from ?? ""}
              onChange={(e) => apply({ date_from: e.target.value || undefined })}
            />
          </label>
          <label>
            A
            <input
              type="date"
              value={filters.date_to ?? ""}
              onChange={(e) => apply({ date_to: e.target.value || undefined })}
            />
          </label>
          <button
            className="link-btn"
            onClick={() => {
              setFilters({});
              setQDraft("");
            }}
          >
            Azzera filtri
          </button>
        </div>

        {tags.data && tags.data.length > 0 && (
          <div className="chips">
            {tags.data.map((t) => {
              const on = filters.tag_ids?.includes(t.id) ?? false;
              return (
                <button
                  key={t.id}
                  className={`chip ${on ? "chip-on" : ""}`}
                  onClick={() =>
                    apply({
                      tag_ids: on
                        ? filters.tag_ids?.filter((x) => x !== t.id)
                        : [...(filters.tag_ids ?? []), t.id],
                    })
                  }
                >
                  {t.name}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {docs.isLoading && <p className="muted">Caricamento…</p>}
      {docs.isError && <p className="error">Errore nel caricamento dei documenti.</p>}
      {docs.data && docs.data.length === 0 && (
        <p className="muted">Nessun documento trovato.</p>
      )}

      <div className="doc-grid">
        {docs.data?.map((d) => (
          <Link key={d.id} to={`/documents/${d.id}`} className="card doc-card">
            <div className="doc-icon">{d.mime_type === "application/pdf" ? "📄" : "🖼️"}</div>
            <div className="doc-body">
              <div className="doc-title">{d.title || d.original_filename}</div>
              <div className="doc-meta">
                {d.visit_type && <span className="badge">{d.visit_type.label}</span>}
                {d.doc_date && <span>{d.doc_date}</span>}
              </div>
              <div className="chips small">
                {d.tags.map((t) => (
                  <span key={t.id} className="chip chip-static">
                    {t.name}
                  </span>
                ))}
              </div>
              <div className={`status status-${d.status}`}>{STATUS_LABEL[d.status] ?? d.status}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
