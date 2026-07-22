import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";

import { useAuth } from "./AuthContext";

export function ProtectedRoute({ children, adminOnly = false }: { children: ReactNode; adminOnly?: boolean }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center muted">Caricamento…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (adminOnly && !user.is_admin) return <Navigate to="/" replace />;
  return <>{children}</>;
}
