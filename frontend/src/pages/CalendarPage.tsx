import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import type { EventClickArg, EventInput } from "@fullcalendar/core";
import { DashboardShell } from "../components/DashboardShell";
import { LoadingState } from "../components/LoadingState";
import { EmptyState } from "../components/EmptyState";
import { useAuth } from "../context/AuthContext";
import { apiFetch, getFriendlyError } from "../lib/api";
import { ROLE_HOME, type CalendarEventOut } from "../lib/types";

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

const EVENT_COLOR: Record<string, string> = {
  "Filing Deadline": "#dc2626", // red-600
  Examination: "#4f46e5", // indigo-600
  Hearing: "#d97706", // amber-600
  Reminder: "#475569", // slate-600
};

/** Read-only, cross-patent agenda rendered with FullCalendar's month grid.
 * Creating/deleting an event happens from the Calendar tab on the specific
 * application (Agent/Admin only) — see components/CollaborationPanel.tsx. */
export default function CalendarPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [events, setEvents] = useState<CalendarEventOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setEvents(await apiFetch<CalendarEventOut[]>("/api/calendar/events"));
      } catch (err) {
        setError(
          getFriendlyError("CalendarPage.loadEvents", err, "Failed to load calendar events")
        );
      }
    })();
  }, []);

  const homeRole = user?.roles[0];
  function linkFor(patentId: string): string {
    if (homeRole === "PATENT_AGENT") return `/agent/patents/${patentId}/draft`;
    if (homeRole === "INNOVATOR") return `/innovator/patents/${patentId}`;
    return homeRole ? ROLE_HOME[homeRole] : "/";
  }

  const calendarEvents: EventInput[] = useMemo(
    () =>
      (events ?? [])
        .filter((e) => e.event_date)
        .map((e) => ({
          id: String(e.id),
          title: `${e.event_type} — ${e.invention_title}`,
          date: e.event_date as string,
          color: EVENT_COLOR[e.event_type ?? ""] ?? "#475569",
          extendedProps: { patentId: e.patent_application_id },
        })),
    [events]
  );

  function onEventClick(arg: EventClickArg) {
    const patentId = arg.event.extendedProps.patentId as string;
    navigate(linkFor(patentId));
  }

  const sorted = useMemo(
    () =>
      [...(events ?? [])].sort(
        (a, b) => new Date(a.event_date ?? 0).getTime() - new Date(b.event_date ?? 0).getTime()
      ),
    [events]
  );

  return (
    <DashboardShell title="Calendar">
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      {events === null && !error && <LoadingState />}

      {events !== null && events.length === 0 && (
        <EmptyState
          title="No calendar events yet."
          message="Events are added by a Patent Agent or Admin on each application's Calendar tab."
        />
      )}

      {events !== null && events.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <FullCalendar
              plugins={[dayGridPlugin]}
              initialView="dayGridMonth"
              height="auto"
              events={calendarEvents}
              eventClick={onEventClick}
            />
          </div>

          <div>
            <h2 className="mb-3 text-sm font-semibold text-slate-700">All events</h2>
            <div className="space-y-2">
              {sorted.map((ev) => (
                <button
                  key={ev.id}
                  onClick={() => navigate(linkFor(ev.patent_application_id))}
                  className="block w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-left hover:bg-slate-50"
                >
                  <span
                    className="mr-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium text-white"
                    style={{ backgroundColor: EVENT_COLOR[ev.event_type ?? ""] ?? "#475569" }}
                  >
                    {ev.event_type}
                  </span>
                  <span className="text-sm text-slate-800">{ev.invention_title}</span>
                  <span className="mt-1 block text-xs text-slate-400">
                    {formatDateTime(ev.event_date)}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </DashboardShell>
  );
}

