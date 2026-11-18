import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { LoadingState } from "./LoadingState";

interface ProtectedRouteProps {
  children: ReactNode;
  requireRole?: string[]; // user must hold at least one
  requirePermission?: string;
}

export function ProtectedRoute({ children, requireRole, requirePermission }: ProtectedRouteProps) {
  const { status, hasRole, hasPermission } = useAuth();

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <LoadingState label="Checking your session…" />
      </div>
    );
  }

  if (status === "unauthenticated") {
    return <Navigate to="/login" replace />;
  }

  if (status === "pending") {
    return <Navigate to="/pending-approval" replace />;
  }

  if (requireRole && !requireRole.some((r) => hasRole(r))) {
    return <Navigate to="/not-authorized" replace />;
  }

  if (requirePermission && !hasPermission(requirePermission)) {
    return <Navigate to="/not-authorized" replace />;
  }

  return <>{children}</>;
}
