import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { DashboardShell } from "../components/DashboardShell";
import { StatusBadge } from "../components/StatusBadge";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { EmptyState } from "../components/EmptyState";
import { apiFetch } from "../lib/api";
import type {
  AvailableAgentOut,
  PatentOut,
  TeamDetailOut,
  TeamOut,
} from "../lib/types";

export default function InnovatorDashboard() {
  const [teams, setTeams] = useState<TeamOut[] | null>(null);
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTeamName, setNewTeamName] = useState("");
  const [creatingTeam, setCreatingTeam] = useState(false);

  async function loadTeams() {
    try {
      const data = await apiFetch<TeamOut[]>("/api/teams");
      setTeams(data);
      if (data.length > 0 && selectedTeamId === null) {
        setSelectedTeamId(data[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load teams");
    }
  }

  useEffect(() => {
    loadTeams();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createTeam(e: React.FormEvent) {
    e.preventDefault();
    if (!newTeamName.trim()) return;
    setCreatingTeam(true);
    setError(null);
    try {
      const team = await apiFetch<TeamOut>("/api/teams", {
        method: "POST",
        body: JSON.stringify({ team_name: newTeamName.trim() }),
      });
      setNewTeamName("");
      await loadTeams();
      setSelectedTeamId(team.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create team");
    } finally {
      setCreatingTeam(false);
    }
  }

  return (
    <DashboardShell title="Innovator">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px_1fr]">
        <div className="space-y-4">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="mb-3 text-sm font-semibold text-slate-700">Your Teams</h2>
            {error && <p className="mb-2 text-xs text-red-600">{error}</p>}
            <div className="space-y-1">
              {teams === null && <LoadingState compact />}
              {teams?.length === 0 && (
                <EmptyState title="No teams yet." message="Create one below." />
              )}
              {teams?.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setSelectedTeamId(t.id)}
                  className={`w-full rounded-md px-3 py-2 text-left text-sm transition ${
                    selectedTeamId === t.id
                      ? "bg-slate-900 text-white"
                      : "text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  <div className="font-medium">{t.team_name}</div>
                  <div
                    className={`text-xs ${
                      selectedTeamId === t.id ? "text-slate-300" : "text-slate-400"
                    }`}
                  >
                    {t.member_count} member{t.member_count !== 1 ? "s" : ""} ·{" "}
                    {t.patent_count} patent{t.patent_count !== 1 ? "s" : ""}
                  </div>
                </button>
              ))}
            </div>
            <form onSubmit={createTeam} className="mt-4 flex gap-2">
              <input
                type="text"
                placeholder="New team name"
                value={newTeamName}
                onChange={(e) => setNewTeamName(e.target.value)}
                className="min-w-0 flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
              />
              <button
                type="submit"
                disabled={creatingTeam}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              >
                Create
              </button>
            </form>
          </div>
        </div>

        <div>
          {selectedTeamId ? (
            <TeamPanel teamId={selectedTeamId} onTeamsChanged={loadTeams} />
          ) : (
            <p className="text-sm text-slate-500">
              Select or create a team to get started.
            </p>
          )}
        </div>
      </div>
    </DashboardShell>
  );
}

function TeamPanel({
  teamId,
  onTeamsChanged,
}: {
  teamId: string;
  onTeamsChanged: () => void;
}) {
  const [team, setTeam] = useState<TeamDetailOut | null>(null);
  const [patents, setPatents] = useState<PatentOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [memberEmail, setMemberEmail] = useState("");
  const [newPatentTitle, setNewPatentTitle] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setError(null);
    try {
      const [teamData, allPatents] = await Promise.all([
        apiFetch<TeamDetailOut>(`/api/teams/${teamId}`),
        apiFetch<PatentOut[]>("/api/patents"),
      ]);
      setTeam(teamData);
      setPatents(allPatents.filter((p) => p.team_id === teamId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load team");
    }
  }

  useEffect(() => {
    setTeam(null);
    setPatents(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId]);

  async function addMember(e: React.FormEvent) {
    e.preventDefault();
    if (!memberEmail.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/teams/${teamId}/members`, {
        method: "POST",
        body: JSON.stringify({ email: memberEmail.trim() }),
      });
      setMemberEmail("");
      await load();
      onTeamsChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add member");
    } finally {
      setBusy(false);
    }
  }

  async function removeMember(userId: string) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/teams/${teamId}/members/${userId}`, { method: "DELETE" });
      await load();
      onTeamsChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove member");
    } finally {
      setBusy(false);
    }
  }

  async function createPatent(e: React.FormEvent) {
    e.preventDefault();
    if (!newPatentTitle.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/api/patents", {
        method: "POST",
        body: JSON.stringify({ team_id: teamId, invention_title: newPatentTitle.trim() }),
      });
      setNewPatentTitle("");
      await load();
      onTeamsChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create patent");
    } finally {
      setBusy(false);
    }
  }

  if (!team)
    return error ? (
      <ErrorState message={error} onRetry={load} />
    ) : (
      <LoadingState />
    );

  return (
    <div className="space-y-6">
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">
          Members of {team.team_name}
        </h2>
        <ul className="space-y-1.5">
          {team.members.map((m) => (
            <li
              key={m.id}
              className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-1.5 text-sm"
            >
              <span>
                {m.full_name} <span className="text-xs text-slate-400">({m.email})</span>
              </span>
              {m.user_id !== team.created_by && (
                <button
                  onClick={() => removeMember(m.user_id)}
                  disabled={busy}
                  className="text-xs text-red-600 hover:underline disabled:opacity-50"
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
        <form onSubmit={addMember} className="mt-3 flex gap-2">
          <input
            type="email"
            placeholder="colleague@example.com"
            value={memberEmail}
            onChange={(e) => setMemberEmail(e.target.value)}
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Add member
          </button>
        </form>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Patent Applications</h2>
        <div className="space-y-3">
          {patents?.length === 0 && (
            <EmptyState title="No patent applications yet." />
          )}
          {patents?.map((p) => (
            <PatentCard key={p.id} patent={p} onChanged={load} />
          ))}
        </div>
        <form onSubmit={createPatent} className="mt-4 flex gap-2">
          <input
            type="text"
            placeholder="Invention title"
            value={newPatentTitle}
            onChange={(e) => setNewPatentTitle(e.target.value)}
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            New patent application
          </button>
        </form>
      </div>
    </div>
  );
}

function PatentCard({ patent, onChanged }: { patent: PatentOut; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAgentPicker, setShowAgentPicker] = useState(false);
  const [agents, setAgents] = useState<AvailableAgentOut[] | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patent.id}/submit`, { method: "POST" });
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit");
    } finally {
      setBusy(false);
    }
  }

  async function openAgentPicker() {
    setShowAgentPicker(true);
    try {
      const data = await apiFetch<AvailableAgentOut[]>("/api/patents/available-agents");
      setAgents(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load agents");
    }
  }

  async function assignAgent(agentId: string) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patent.id}/assign`, {
        method: "POST",
        body: JSON.stringify({ patent_agent_id: agentId }),
      });
      setShowAgentPicker(false);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to assign agent");
    } finally {
      setBusy(false);
    }
  }

  async function autoAssign() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/patents/${patent.id}/auto-assign`, { method: "POST" });
      setShowAgentPicker(false);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to auto-assign");
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = patent.application_status === "Draft";
  const canAssign =
    patent.application_status === "Submitted" ||
    patent.application_status === "Awaiting Patent Agent Acceptance";

  return (
    <div className="rounded-md border border-slate-200 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-900">{patent.invention_title}</span>
        <StatusBadge status={patent.application_status} />
      </div>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}

      <div className="mt-2 flex flex-wrap gap-2">
        <Link
          to={`/innovator/patents/${patent.id}`}
          className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          {canSubmit ? "Basic Info & Questionnaire" : "View"}
        </Link>
        {canSubmit && (
          <button
            onClick={submit}
            disabled={busy}
            className="rounded-md bg-slate-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            Submit
          </button>
        )}
        {canAssign && !showAgentPicker && (
          <button
            onClick={openAgentPicker}
            disabled={busy}
            className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Assign a Patent Agent
          </button>
        )}
      </div>

      {showAgentPicker && (
        <div className="mt-3 rounded-md bg-slate-50 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-slate-600">Choose an agent</span>
            <button
              onClick={autoAssign}
              disabled={busy}
              className="text-xs font-medium text-blue-600 hover:underline disabled:opacity-50"
            >
              Auto-assign (lightest workload)
            </button>
          </div>
          {agents === null && <LoadingState compact />}
          <div className="space-y-1">
            {agents?.map((a) => (
              <button
                key={a.id}
                onClick={() => assignAgent(a.id)}
                disabled={busy}
                className="flex w-full items-center justify-between rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs hover:bg-slate-100 disabled:opacity-50"
              >
                <span>
                  {a.full_name} <span className="text-slate-400">({a.email})</span>
                </span>
                <span className="text-slate-400">{a.active_assignment_count} active</span>
              </button>
            ))}
          </div>
          <button
            onClick={() => setShowAgentPicker(false)}
            className="mt-2 text-xs text-slate-400 hover:underline"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
