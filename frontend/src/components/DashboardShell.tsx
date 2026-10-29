import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { NotificationBell } from "./NotificationBell";
import { homePathFor } from "../lib/roles";

export function DashboardShell({
  title,
  children,
  breadcrumbs,
}: {
  title: string;
  children: ReactNode;
  breadcrumbs?: { label: string; to?: string }[];
}) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const homePath = homePathFor(user?.roles);
  const calendarPath = homePath === "/login" ? "/calendar" : `${homePath}/calendar`;
  const reportsPath = homePath === "/login" ? "/reports" : `${homePath}/reports`;

  const navItems = [
    { label: "Dashboard", to: homePath },
    { label: "Reports", to: reportsPath },
    { label: "Calendar", to: calendarPath },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="mx-auto max-w-6xl">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-lg font-semibold text-slate-900">{title}</h1>
              <p className="text-xs text-slate-500">
                {user?.full_name} · {user?.email} · {user?.roles.join(", ")}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <nav className="flex items-center gap-1" aria-label="Main navigation">
                {navItems.map((item) => {
                  const active = location.pathname === item.to;
                  return (
                    <Link
                      key={item.label}
                      to={item.to}
                      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                        active
                          ? "bg-slate-900 text-white"
                          : "text-slate-700 hover:bg-slate-100"
                      }`}
                      aria-current={active ? "page" : undefined}
                    >
                      {item.label}
                    </Link>
                  );
                })}
              </nav>
              <NotificationBell />
              <button
                onClick={logout}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-400 focus:ring-offset-1"
              >
                Sign out
              </button>
            </div>
          </div>
          {breadcrumbs && breadcrumbs.length > 0 && (
            <nav aria-label="Breadcrumb" className="mt-2">
              <ol className="flex items-center gap-1.5 text-xs text-slate-500">
                {breadcrumbs.map((crumb, i) => (
                  <li key={i} className="flex items-center gap-1.5">
                    {i > 0 && <span aria-hidden="true">/</span>}
                    {crumb.to ? (
                      <Link to={crumb.to} className="hover:text-slate-900 hover:underline">
                        {crumb.label}
                      </Link>
                    ) : (
                      <span className="font-medium text-slate-700">{crumb.label}</span>
                    )}
                  </li>
                ))}
              </ol>
            </nav>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  );
}
