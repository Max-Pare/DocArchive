import { Link, Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import Login from "./pages/Login";
import Library from "./pages/Library";
import Upload from "./pages/Upload";
import DocumentDetail from "./pages/DocumentDetail";
import Admin from "./pages/Admin";

function NavBar() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return (
    <nav className="navbar">
      <Link to="/" className="brand">
        📁 DocArchive
      </Link>
      <div className="nav-links">
        <Link to="/">Archivio</Link>
        <Link to="/upload">Carica</Link>
        {user.is_admin && <Link to="/admin">Utenti</Link>}
        <span className="muted">{user.email}</span>
        <button className="link-btn" onClick={logout}>
          Esci
        </button>
      </div>
    </nav>
  );
}

export default function App() {
  return (
    <div className="app">
      <NavBar />
      <main className="container">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Library />
              </ProtectedRoute>
            }
          />
          <Route
            path="/upload"
            element={
              <ProtectedRoute>
                <Upload />
              </ProtectedRoute>
            }
          />
          <Route
            path="/documents/:id"
            element={
              <ProtectedRoute>
                <DocumentDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <ProtectedRoute adminOnly>
                <Admin />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
