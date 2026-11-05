import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { apiFetch } from "../lib/api";
import { NOTIFICATION_TEXT, type NotificationOut } from "../lib/types";
import { patentPathFor } from "../lib/roles";

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function NotificationBell() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationOut[] | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  async function loadUnreadCount() {
    try {
      const { unread_count } = await apiFetch<{ unread_count: number }>(
        "/api/notifications/unread-count"
      );
      setUnreadCount(unread_count);
    } catch {
      // silent — bell just won't show a count this cycle
    }
  }

  async function loadNotifications() {
    try {
      setNotifications(await apiFetch<NotificationOut[]>("/api/notifications"));
    } catch {
      setNotifications([]);
    }
  }

  useEffect(() => {
    loadUnreadCount();
    const interval = setInterval(() => {
      // Background tabs gain nothing from polling; the count refreshes on focus.
      if (!document.hidden) loadUnreadCount();
    }, 30_000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onEscape(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onEscape);
    };
  }, []);

  async function toggleOpen() {
    const next = !open;
    setOpen(next);
    if (next) await loadNotifications();
  }

  async function handleClickNotification(n: NotificationOut) {
    if (!n.is_read) {
      try {
        await apiFetch(`/api/notifications/${n.id}/read`, { method: "PATCH" });
        setUnreadCount((c) => Math.max(0, c - 1));
        setNotifications((prev) =>
          prev ? prev.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)) : prev
        );
      } catch {
        // non-fatal — still navigate
      }
    }
    setOpen(false);
    if (n.patent_application_id) {
      // A roleless account has no workspace routes; dropping its deep link
      // on /login would bounce it to /not-authorized with the target lost
      // anyway. Send it straight to /not-authorized instead of a silent detour.
      const target = patentPathFor(user?.roles, n.patent_application_id);
      navigate(target === "/login" ? "/not-authorized" : target);
    }
  }

  async function markAllRead() {
    try {
      await apiFetch("/api/notifications/read-all", { method: "POST" });
      setUnreadCount(0);
      setNotifications((prev) => (prev ? prev.map((x) => ({ ...x, is_read: true })) : prev));
    } catch {
      // silent
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={toggleOpen}
        aria-label="Notifications"
        aria-haspopup="true"
        aria-expanded={open}
        className="relative rounded-md border border-slate-300 p-1.5 text-slate-600 hover:bg-slate-50"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" className="h-4 w-4">
          <path
            d="M15 17h5l-1.4-1.4A2 2 0 0 1 18 14.2V11a6 6 0 1 0-12 0v3.2a2 2 0 0 1-.6 1.4L4 17h5m6 0v1a3 3 0 1 1-6 0v-1m6 0H9"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-10 mt-2 w-80 rounded-md border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
            <span className="text-sm font-semibold text-slate-700">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="text-xs font-medium text-slate-500 hover:text-slate-800"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {notifications === null && (
              <p className="px-3 py-4 text-sm text-slate-500">Loading…</p>
            )}
            {notifications?.length === 0 && (
              <p className="px-3 py-4 text-sm text-slate-400">You're all caught up.</p>
            )}
            {notifications?.map((n) => {
              const template = n.notification_type ? NOTIFICATION_TEXT[n.notification_type] : null;
              const text = template
                ? template(n.invention_title ?? "an application")
                : `Update on "${n.invention_title ?? "an application"}"`;
              return (
                <button
                  key={n.id}
                  onClick={() => handleClickNotification(n)}
                  className={`block w-full border-b border-slate-50 px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                    n.is_read ? "text-slate-500" : "font-medium text-slate-800"
                  }`}
                >
                  <div className="flex items-start gap-2">
                    {!n.is_read && (
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
                    )}
                    <span className="flex-1">
                      {text}
                      <span className="mt-0.5 block text-xs text-slate-400">
                        {timeAgo(n.created_at)}
                      </span>
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
