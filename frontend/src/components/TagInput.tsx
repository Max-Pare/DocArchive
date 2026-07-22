import { useState } from "react";

import type { Tag } from "../api/types";

interface Props {
  allTags: Tag[];
  selected: number[];
  onChange: (ids: number[]) => void;
  onCreate: (name: string) => Promise<Tag>;
}

// Multi-select tag chips + free-text creation.
export function TagInput({ allTags, selected, onChange, onCreate }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  function toggle(id: number) {
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  }

  async function addNew() {
    const name = text.trim();
    if (!name) return;
    setBusy(true);
    try {
      const existing = allTags.find((t) => t.name.toLowerCase() === name.toLowerCase());
      const tag = existing ?? (await onCreate(name));
      if (!selected.includes(tag.id)) onChange([...selected, tag.id]);
      setText("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tag-input">
      <div className="chips">
        {allTags.map((t) => (
          <button
            type="button"
            key={t.id}
            className={`chip ${selected.includes(t.id) ? "chip-on" : ""}`}
            onClick={() => toggle(t.id)}
          >
            {t.name}
          </button>
        ))}
      </div>
      <div className="tag-add">
        <input
          placeholder="Nuovo tag…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addNew();
            }
          }}
        />
        <button type="button" onClick={addNew} disabled={busy || !text.trim()}>
          + Aggiungi
        </button>
      </div>
    </div>
  );
}
