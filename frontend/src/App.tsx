import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LoadingState } from "./components/LoadingState";
import { homePathFor } from "./lib/roles";

const LoginPage = lazy(() => import("./pages/LoginPage"));
const AuthCallbackPage = lazy(() => import("./pages/AuthCallbackPage"));
const PendingApprovalPage = lazy(() => import("./pages/PendingApprovalPage"));
const NotAuthorizedPage = lazy(() => import("./pages/NotAuthorizedPage"));
const InnovatorDashboard = lazy(() => import("./pages/InnovatorDashboard"));
const PatentWorkflowPage = lazy(() => import("./pages/PatentWorkflowPage"));
const AgentDashboard = lazy(() => import("./pages/AgentDashboard"));
const DraftWorkspacePage = lazy(() => import("./pages/DraftWorkspacePage"));
const AdminDashboard = lazy(() => import("./pages/AdminDashboard"));
const AdminPatentsPage = lazy(() => import("./pages/AdminPatentsPage"));
const AdminPatentDetailPage = lazy(() => import("./pages/AdminPatentDetailPage"));
const SuperAdminDashboard = lazy(() => import("./pages/SuperAdminDashboard"));
const CalendarPage = lazy(() => import("./pages/CalendarPage"));
const ReportsPage = lazy(() => import("./pages/ReportsPage"));

/**
 * Landing router: waits for the session to resolve, then forwards by auth
 * state. Unknown paths land here too instead of a blank page.
 */
function IndexRoute() {
  const { status, user } = useAuth();
  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <LoadingState label="Signing in…" />
      </div>
    );
  }
  if (status === "pending") {
    return <Navigate to="/pending-approval" replace />;
  }
  if (status === "unauthenticated" || !user) {
    return <Navigate to="/login" replace />;
  }
  const home = homePathFor(user.roles);
  return <Navigate to={home === "/login" ? "/not-authorized" : home} replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={<div className="flex min-h-screen items-center justify-center bg-slate-50"><LoadingState label="Loading page…" /></div>}>
          <Routes>
          <Route path="/" element={<IndexRoute />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route path="/pending-approval" element={<PendingApprovalPage />} />
          <Route path="/not-authorized" element={<NotAuthorizedPage />} />

          <Route
            path="/innovator/calendar"
            element={
              <ProtectedRoute requireRole={["INNOVATOR"]}>
                <CalendarPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/innovator/reports"
            element={
              <ProtectedRoute requireRole={["INNOVATOR"]}>
                <ReportsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/innovator/patents/:id"
            element={
              <ProtectedRoute requireRole={["INNOVATOR"]}>
                <PatentWorkflowPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/innovator/*"
            element={
              <ProtectedRoute requireRole={["INNOVATOR"]}>
                <InnovatorDashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/agent/calendar"
            element={
              <ProtectedRoute requireRole={["PATENT_AGENT"]}>
                <CalendarPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/agent/reports"
            element={
              <ProtectedRoute requireRole={["PATENT_AGENT"]}>
                <ReportsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/agent/patents/:id/draft"
            element={
              <ProtectedRoute requireRole={["PATENT_AGENT"]}>
                <DraftWorkspacePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/agent/*"
            element={
              <ProtectedRoute requireRole={["PATENT_AGENT"]}>
                <AgentDashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/calendar"
            element={
              <ProtectedRoute requireRole={["ADMIN"]}>
                <CalendarPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/reports"
            element={
              <ProtectedRoute requireRole={["ADMIN"]}>
                <ReportsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/patents/:id"
            element={
              // Shared with Super Admin — backend visibility treats ADMIN and
              // SUPER_ADMIN identically for patents.
              <ProtectedRoute requireRole={["ADMIN", "SUPER_ADMIN"]}>
                <AdminPatentDetailPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/patents/:id/draft"
            element={
              // Admin and Super Admin are allowed into the drafting
              // workspace by can_review_draft() server-side.
              <ProtectedRoute requireRole={["ADMIN", "SUPER_ADMIN"]}>
                <DraftWorkspacePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/patents"
            element={
              <ProtectedRoute requireRole={["ADMIN", "SUPER_ADMIN"]}>
                <AdminPatentsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/*"
            element={
              <ProtectedRoute requireRole={["ADMIN"]}>
                <AdminDashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/super-admin/calendar"
            element={
              <ProtectedRoute requireRole={["SUPER_ADMIN"]}>
                <CalendarPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/super-admin/reports"
            element={
              <ProtectedRoute requireRole={["SUPER_ADMIN"]}>
                <ReportsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/super-admin/*"
            element={
              <ProtectedRoute requireRole={["SUPER_ADMIN"]}>
                <SuperAdminDashboard />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<IndexRoute />} />
        </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
  );
}
