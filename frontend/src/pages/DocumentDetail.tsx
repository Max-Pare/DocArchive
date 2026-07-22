import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createTag,
  deleteDocument,
  getDocument,
  listTags,
  listVisitTypes,
  runOcr,
  updateDocument,
} from "../api/endpoints";
import type { OcrSuggestion } from "../api/types";
import { FilePreview } from "../components/FilePreview";
import { TagInput } from "../components/TagInput";

export default function DocumentDetail() {
  const { id } = useParams();
  const docId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const doc = useQuery({ queryKey: ["document", docId], queryFn: () => getDocument(docId) });
  const visitTypes = useQuery({ queryKey: ["visit_types"], queryFn: listVisitTypes });
  const tags = useQuery({ queryKey: ["tags"], queryFn: listTags });

  // editable form state
  const [title, setTitle] = useState("");
  const [docDate, setDocDate] = useState("");
  const [visitTypeId, setVisitTypeId] = useState<number | "">("");
  const [notes, setNotes] = useState("");
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [ocrMsg, setOcrMsg] = useState<string | null>(null);
  const [ocrExcerpt, setOcrExcerpt] = useState<string | null>(null);

  // hydrate form when the document loads
  useEffect(() => {
    const d = doc.data;
    if (!d) return;
    setTitle(d.title ?? "");
    setDocDate(d.doc_date ?? "");
    setVisitTypeId(d.visit_type?.id ?? "");
    setNotes(d.notes ?? "");
    setTagIds(d.tags.map((t) => t.id));
  }, [doc.data]);

  const save = useMutation({
    mutationFn: () =>
      updateDocument(docId, {
        title: title || null,
        doc_date: docDate || null,
        visit_type_id: visitTypeId === "" ? null : visitTypeId,
        notes: notes || null,
        tag_ids: tagIds,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["document", docId] });
      qc.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  const ocr = useMutation({
    mutationFn: () => runOcr(docId),
    onSuccess: (s: OcrSuggestion) => {
      // apply suggestions to the form (user can still edit before saving)
      if (s.doc_date) setDocDate(s.doc_date);
      if (s.visit_type_id) setVisitTypeId(s.visit_type_id);
      setOcrExcerpt(s.ocr_text_excerpt);
      setOcrMsg(
        s.status === "ocr_done"
          ? "Suggerimenti applicati dal testo OCR. Verifica e salva."
          : `OCR non riuscito (stato: ${s.status}). Compila manualmente.`
      );
      // create/select suggested tags
      applySuggestedTags(s.suggested_tags);
    },
  });

  async function applySuggestedTags(names: string[]) {
    const current = tags.data ?? [];
    const ids: number[] = [];
    for (const name of names) {
      const existing = current.find((t) => t.name.toLowerCase() === name.toLowerCase());
      const tag = existing ?? (await createTag(name));
      ids.push(tag.id);
    }
    if (ids.length) {
      setTagIds((prev) => Array.from(new Set([...prev, ...ids])));
      qc.invalidateQueries({ queryKey: ["tags"] });
    }
  }

  const del = useMutation({
    mutationFn: () => deleteDocument(docId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      navigate("/");
    },
  });

  if (doc.isLoading) return <p className="muted">Caricamento…</p>;
  if (doc.isError || !doc.data) return <p className="error">Documento non trovato.</p>;

  return (
    <div className="detail">
      <div className="detail-preview">
        <FilePreview docId={docId} mime={doc.data.mime_type} />
        <div className="muted small">{doc.data.original_filename}</div>
      </div>

      <div className="detail-form card">
        <div className="form-head">
          <h2>Dettagli documento</h2>
          <button
            className="btn"
            onClick={() => ocr.mutate()}
            disabled={ocr.isPending}
            title="Estrai data, tipo e tag dal testo OCR"
          >
            {ocr.isPending ? "OCR in corso…" : "✨ Compila automaticamente"}
          </button>
        </div>
        {ocrMsg && <div className="notice">{ocrMsg}</div>}

        <label>
          Titolo
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="es. Emocromo completo" />
        </label>
        <label>
          Data documento
          <input type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} />
        </label>
        <label>
          Tipo di visita
          <select
            value={visitTypeId}
            onChange={(e) => setVisitTypeId(e.target.value ? Number(e.target.value) : "")}
          >
            <option value="">— seleziona —</option>
            {visitTypes.data?.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Tag
          <TagInput
            allTags={tags.data ?? []}
            selected={tagIds}
            onChange={setTagIds}
            onCreate={async (name) => {
              const t = await createTag(name);
              qc.invalidateQueries({ queryKey: ["tags"] });
              return t;
            }}
          />
        </label>
        <label>
          Note
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
        </label>

        <div className="form-actions">
          <button className="btn" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? "Salvataggio…" : "Salva"}
          </button>
          <button
            className="btn danger"
            onClick={() => {
              if (confirm("Eliminare definitivamente questo documento?")) del.mutate();
            }}
            disabled={del.isPending}
          >
            Elimina
          </button>
        </div>
        {save.isSuccess && <div className="notice ok">Salvato.</div>}

        {ocrExcerpt && (
          <details className="ocr-excerpt">
            <summary>Testo estratto (OCR)</summary>
            <pre>{ocrExcerpt}</pre>
          </details>
        )}
      </div>
    </div>
  );
}
