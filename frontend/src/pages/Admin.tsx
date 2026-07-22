import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createUser, listUsers } from "../api/endpoints";

export default function Admin() {
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: listUsers });

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => createUser(email, password, isAdmin),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      setEmail("");
      setPassword("");
      setIsAdmin(false);
      setError(null);
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Errore"),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <div>
      <h1>Gestione utenti</h1>

      <form className="card" onSubmit={onSubmit}>
        <h2>Nuovo utente</h2>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Password (min 8 caratteri)
          <input
            type="password"
            value={password}
            minLength={8}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />
          Amministratore
        </label>
        {error && <div className="error">{error}</div>}
        <button type="submit" className="btn" disabled={create.isPending}>
          {create.isPending ? "Creazione…" : "Crea utente"}
        </button>
      </form>

      <div className="card">
        <h2>Utenti</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Ruolo</th>
              <th>Creato</th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id}>
                <td>{u.email}</td>
                <td>{u.is_admin ? "Admin" : "Utente"}</td>
                <td>{new Date(u.created_at).toLocaleDateString("it-IT")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
