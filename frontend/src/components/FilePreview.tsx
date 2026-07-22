import { useEffect, useState } from "react";

import { fetchFileBlob } from "../api/endpoints";

// Fetches the (auth-protected) file as a blob and renders it inline.
export function FilePreview({ docId, mime }: { docId: number; mime: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    fetchFileBlob(docId)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => setError("Impossibile caricare l'anteprima"));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [docId]);

  if (error) return <div className="error">{error}</div>;
  if (!url) return <div className="muted">Caricamento anteprima…</div>;

  if (mime === "application/pdf") {
    return <embed src={url} type="application/pdf" className="file-preview" />;
  }
  if (mime.startsWith("image/")) {
    return <img src={url} alt="documento" className="file-preview" />;
  }
  return (
    <a href={url} download>
      Scarica file
    </a>
  );
}
