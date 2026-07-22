import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { uploadDocument } from "../api/endpoints";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tiff,.webp";

export default function Upload() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setError(null);
    setBusy(true);
    try {
      const doc = await uploadDocument(file);
      qc.invalidateQueries({ queryKey: ["documents"] });
      // Go to detail: OCR runs in background; user can Auto-fill or edit manually.
      navigate(`/documents/${doc.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Caricamento non riuscito");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Carica documento</h1>
      <div
        className={`dropzone ${dragging ? "dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) handleFile(f);
        }}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
          }}
        />
        {busy ? (
          <p>Caricamento in corso…</p>
        ) : (
          <>
            <div className="dz-icon">⬆️</div>
            <p>Trascina qui un file oppure fai clic per selezionarlo</p>
            <p className="muted">PDF, JPG, PNG, TIFF, WEBP — max 25&nbsp;MB</p>
          </>
        )}
      </div>
      {error && <div className="error">{error}</div>}
      <p className="muted">
        Dopo il caricamento potrai usare <strong>Compila automaticamente</strong> per estrarre data,
        tipo di visita e tag dal testo (OCR), oppure inserirli manualmente.
      </p>
    </div>
  );
}
