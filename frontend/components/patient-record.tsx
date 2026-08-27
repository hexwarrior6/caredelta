"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  Comment,
  Highlight,
  PatientRecord as PatientRecordData,
  RiskLevel,
  TimelineEntry,
  UserRole,
} from "@/lib/types";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const patientId = "patient-syn-001";
const clinicId = "clinic-syn-orchard";

const demoActors: Record<UserRole, string> = {
  patient: "patient-syn-001",
  staff: "staff-syn-chen",
  clinician: "clinician-syn-lim",
  admin: "admin-syn-orchard",
};

const categoryLabels: Record<string, string> = {
  new: "New",
  worsening: "Worsening",
  recurring: "Recurring",
  unresolved: "Unresolved",
  contradicted: "Contradicted",
  confirmed: "Confirmed",
};

const roleLabels: Record<string, string> = {
  patient: "Patient",
  staff: "Staff",
  clinician: "Clinician",
  admin: "Admin",
  system: "AI Scribe",
};

const riskStyles: Record<RiskLevel, string> = {
  high: "border-rose-200 bg-rose-50 text-rose-700",
  medium: "border-amber-200 bg-amber-50 text-amber-700",
  low: "border-sky-200 bg-sky-50 text-sky-700",
};

function formatDate(value: string, includeTime = false) {
  return new Intl.DateTimeFormat("en-SG", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(includeTime && { hour: "2-digit", minute: "2-digit" }),
  }).format(new Date(value));
}

function trustLabel(status: Highlight["trust_status"]) {
  if (status === "clinician_confirmed") return "Clinician confirmed";
  if (status === "needs_review") return "Needs review";
  return "AI suggested";
}

function TimelineContent({
  entry,
  focusedPointer,
}: {
  entry: TimelineEntry;
  focusedPointer: Highlight["provenance_pointer"] | null;
}) {
  if (!focusedPointer || focusedPointer.entry_id !== entry.id) {
    return <>{entry.content}</>;
  }

  const before = entry.content.slice(0, focusedPointer.start_offset);
  const source = entry.content.slice(
    focusedPointer.start_offset,
    focusedPointer.end_offset,
  );
  const after = entry.content.slice(focusedPointer.end_offset);

  return (
    <>
      {before}
      <mark className="rounded bg-amber-200 px-1 text-slate-950 ring-4 ring-amber-100">
        {source}
      </mark>
      {after}
    </>
  );
}

export function PatientRecord() {
  const [role, setRole] = useState<UserRole>("clinician");
  const [record, setRecord] = useState<PatientRecordData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focusedHighlight, setFocusedHighlight] = useState<Highlight | null>(null);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [showNoteComposer, setShowNoteComposer] = useState(false);
  const [commentEntryId, setCommentEntryId] = useState<string | null>(null);
  const [commentBody, setCommentBody] = useState("");
  const [assignClinician, setAssignClinician] = useState(true);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const authHeaders = useCallback(
    () => ({
      "Content-Type": "application/json",
      "X-Actor-Id": demoActors[role],
      "X-Actor-Role": role,
      "X-Clinic-Id": clinicId,
    }),
    [role],
  );

  const loadRecord = useCallback(async (signal?: AbortSignal) => {
    const response = await fetch(`${apiUrl}/api/patients/${patientId}/record`, {
      signal,
      headers: authHeaders(),
    });
    if (!response.ok) throw new Error(`API returned HTTP ${response.status}`);
    setRecord((await response.json()) as PatientRecordData);
  }, [authHeaders]);

  useEffect(() => {
    const controller = new AbortController();

    async function refreshRecord() {
      try {
        setRecord(null);
        setError(null);
        await loadRecord(controller.signal);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(caught instanceof Error ? caught.message : "Unable to load record");
      }
    }

    void refreshRecord();
    return () => controller.abort();
  }, [loadRecord]);

  const commentsByEntry = useMemo(() => {
    const grouped = new Map<string, Comment[]>();
    for (const comment of record?.comments ?? []) {
      grouped.set(comment.entry_id, [...(grouped.get(comment.entry_id) ?? []), comment]);
    }
    return grouped;
  }, [record]);

  async function mutate(path: string, method: "POST" | "PATCH", body: object) {
    setBusy(true);
    setMutationError(null);
    try {
      const response = await fetch(`${apiUrl}${path}`, {
        method,
        headers: authHeaders(),
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? `API returned HTTP ${response.status}`);
      }
      await loadRecord();
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : "Unable to save change");
      throw caught;
    } finally {
      setBusy(false);
    }
  }

  async function submitNote(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const section = role === "clinician" ? "clinician_section" : "staff_note";
    try {
      await mutate(`/api/patients/${patientId}/entries`, "POST", {
        section,
        title: noteTitle,
        content: noteContent,
      });
      setNoteTitle("");
      setNoteContent("");
      setShowNoteComposer(false);
    } catch {}
  }

  async function submitComment(event: React.FormEvent<HTMLFormElement>, entryId: string) {
    event.preventDefault();
    const shouldAssign = role === "staff" && assignClinician;
    const body = shouldAssign && !commentBody.includes("@clinician")
      ? `@clinician ${commentBody}`
      : commentBody;
    try {
      await mutate(`/api/patients/${patientId}/entries/${entryId}/comments`, "POST", {
        body,
        mentions: shouldAssign ? ["clinician-syn-lim"] : [],
        assigned_role: shouldAssign ? "clinician" : null,
      });
      setCommentBody("");
      setCommentEntryId(null);
    } catch {}
  }

  async function toggleComment(comment: Comment) {
    try {
      await mutate(`/api/patients/${patientId}/comments/${comment.id}`, "PATCH", {
        resolved: !comment.resolved,
      });
    } catch {}
  }

  function revealSource(highlight: Highlight) {
    setFocusedHighlight(highlight);
    requestAnimationFrame(() => {
      document
        .getElementById(highlight.provenance_pointer.entry_id)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  if (error) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <section className="max-w-lg rounded-3xl border border-rose-200 bg-white p-8 shadow-xl">
          <p className="text-sm font-semibold uppercase tracking-widest text-rose-600">
            Backend unavailable
          </p>
          <h1 className="mt-3 text-3xl font-semibold text-slate-950">
            Patient record could not load
          </h1>
          <p className="mt-4 text-slate-600">{error}</p>
          <p className="mt-2 text-sm text-slate-500">Request: {apiUrl}</p>
        </section>
      </main>
    );
  }

  if (!record) {
    return (
      <main className="grid min-h-screen place-items-center">
        <div className="flex items-center gap-3 text-slate-600">
          <span className="h-3 w-3 animate-pulse rounded-full bg-teal-500" />
          Loading source-backed record…
        </div>
      </main>
    );
  }

  const { patient } = record;

  return (
    <main className="min-h-screen pb-20">
      <header className="border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-teal-950 text-lg font-bold text-white">
              CΔ
            </div>
            <div>
              <p className="font-semibold tracking-tight text-slate-950">CareDelta</p>
              <p className="text-xs text-slate-500">Clinical Change Radar</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-xs text-slate-400 sm:inline">Demo preview only</span>
            <div className="flex rounded-xl border border-slate-200 bg-slate-50 p-1" aria-label="Preview role">
              {(["patient", "staff", "clinician", "admin"] as UserRole[]).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setRole(item)}
                  aria-pressed={role === item}
                  className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold capitalize transition sm:px-3 ${
                    role === item
                      ? "bg-teal-950 text-white shadow-sm"
                      : "text-slate-500 hover:text-slate-900"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-5 pt-8 lg:px-8">
        <section className="flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
                {patient.display_name}
              </h1>
              <span className="rounded-full bg-violet-100 px-2.5 py-1 text-xs font-semibold uppercase tracking-wide text-violet-700">
                Synthetic
              </span>
            </div>
            <p className="mt-2 text-slate-500">
              {patient.age} years · {patient.pronouns} · Last activity {formatDate(patient.last_visit_at)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {patient.active_conditions.map((condition) => (
              <span key={condition} className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700">
                {condition}
              </span>
            ))}
            {patient.allergies.map((allergy) => (
              <span key={allergy} className="rounded-full border border-rose-200 bg-rose-50 px-3 py-1.5 text-sm text-rose-700">
                Allergy: {allergy}
              </span>
            ))}
          </div>
        </section>

        <section className="mt-8 overflow-hidden rounded-3xl bg-teal-950 text-white shadow-2xl shadow-teal-950/15">
          <div className="flex flex-col justify-between gap-4 border-b border-white/10 px-6 py-6 sm:px-8 md:flex-row md:items-center">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-teal-300">10-second glance · {role} view</p>
              <h2 className="mt-2 text-2xl font-semibold">What changed and needs action</h2>
            </div>
            <p className="max-w-xl text-sm leading-6 text-teal-100/75">{patient.summary}</p>
          </div>

          <div className="grid divide-y divide-white/10 lg:grid-cols-3 lg:divide-x lg:divide-y-0">
            {record.highlights.length === 0 && (
              <div className="p-8 lg:col-span-3">
                <p className="font-semibold">No approved clinical signals in this view</p>
                <p className="mt-2 text-sm text-teal-100/70">
                  Restricted and unreviewed care-team content is filtered by the backend.
                </p>
              </div>
            )}
            {record.highlights.map((highlight) => (
              <button
                key={highlight.id}
                type="button"
                onClick={() => revealSource(highlight)}
                className="group p-6 text-left transition hover:bg-white/[0.06] sm:p-8"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold uppercase ${riskStyles[highlight.risk_level]}`}>
                    {highlight.risk_level} risk
                  </span>
                  <span className="font-mono text-sm text-teal-200">{highlight.importance_score}</span>
                </div>
                <p className="mt-5 text-xs font-semibold uppercase tracking-widest text-teal-300">
                  {categoryLabels[highlight.category]}
                </p>
                <h3 className="mt-2 text-lg font-semibold leading-snug">{highlight.text}</h3>
                <p className="mt-3 text-sm leading-6 text-teal-100/70">{highlight.risk_reason}</p>
                <div className="mt-5 flex items-center justify-between text-xs">
                  <span className="text-teal-100/70">{trustLabel(highlight.trust_status)}</span>
                  <span className="font-semibold text-teal-300 group-hover:text-white">View source ↓</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
          <section>
            <div className="flex items-end justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-700">Longitudinal record</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-950">Timeline</h2>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-slate-500">{record.timeline_entries.length} entries</span>
                {role !== "patient" && (
                  <button
                    type="button"
                    onClick={() => setShowNoteComposer((current) => !current)}
                    className="rounded-xl bg-teal-950 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800"
                  >
                    {showNoteComposer ? "Cancel" : role === "clinician" ? "Add clinician note" : "Add staff note"}
                  </button>
                )}
              </div>
            </div>

            {mutationError && (
              <p role="alert" className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
                {mutationError}
              </p>
            )}

            {showNoteComposer && role !== "patient" && (
              <form onSubmit={submitNote} className="mt-5 rounded-2xl border border-teal-200 bg-white p-5 shadow-sm">
                <p className="text-sm font-semibold text-teal-900">
                  New {role === "clinician" ? "clinician" : "staff"} note
                </p>
                <input
                  required
                  maxLength={160}
                  value={noteTitle}
                  onChange={(event) => setNoteTitle(event.target.value)}
                  placeholder="Note title"
                  aria-label="Note title"
                  className="mt-3 w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:border-teal-500"
                />
                <textarea
                  required
                  value={noteContent}
                  onChange={(event) => setNoteContent(event.target.value)}
                  placeholder="Add an observation to the shared care timeline…"
                  aria-label="Note content"
                  rows={3}
                  className="mt-3 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-teal-500"
                />
                <div className="mt-3 flex justify-end">
                  <button disabled={busy} className="rounded-xl bg-teal-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                    {busy ? "Saving…" : "Publish note"}
                  </button>
                </div>
              </form>
            )}

            <div className="relative mt-6 space-y-5 before:absolute before:bottom-6 before:left-[19px] before:top-6 before:w-px before:bg-slate-200">
              {record.timeline_entries.map((entry) => {
                const comments = commentsByEntry.get(entry.id) ?? [];
                const isFocused = focusedHighlight?.provenance_pointer.entry_id === entry.id;
                return (
                  <article key={entry.id} id={entry.id} className="relative scroll-mt-8 pl-12">
                    <span className={`absolute left-3 top-7 h-3.5 w-3.5 rounded-full border-4 border-[#f5f8f7] ${entry.author_role === "system" ? "bg-violet-500" : entry.author_role === "patient" ? "bg-sky-500" : "bg-teal-600"}`} />
                    <div className={`rounded-2xl border bg-white p-5 shadow-sm transition sm:p-6 ${isFocused ? "border-amber-300 ring-4 ring-amber-100" : "border-slate-200"}`}>
                      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600">{roleLabels[entry.author_role]}</span>
                            <span className="text-sm font-medium text-slate-700">{entry.author_name}</span>
                            <span className="text-xs text-slate-400">v{entry.version}</span>
                          </div>
                          <h3 className="mt-3 text-lg font-semibold text-slate-950">{entry.title}</h3>
                        </div>
                        <time className="shrink-0 text-sm text-slate-500">{formatDate(entry.timestamp, true)}</time>
                      </div>
                      <p className="mt-4 leading-7 text-slate-600">
                        <TimelineContent entry={entry} focusedPointer={focusedHighlight?.provenance_pointer ?? null} />
                      </p>
                      <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4 text-xs text-slate-500">
                        <span>{entry.source_label}</span>
                        {isFocused && <span className="font-semibold text-amber-700">Exact source · high confidence</span>}
                      </div>
                      {comments.map((comment) => (
                        <div key={comment.id} className={`mt-4 rounded-xl border p-4 ${comment.resolved ? "border-slate-200 bg-slate-50" : "border-indigo-100 bg-indigo-50/70"}`}>
                          <div className="flex items-center justify-between gap-3 text-xs">
                            <span className="font-semibold text-indigo-800">{comment.author_name} commented</span>
                            <span className={comment.resolved ? "text-slate-500" : "text-indigo-600"}>
                              {comment.resolved ? "Resolved" : "Open thread"}
                            </span>
                          </div>
                          <p className="mt-2 text-sm leading-6 text-indigo-950/75">{comment.body}</p>
                          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                            <div className="flex gap-2 text-xs text-indigo-600">
                              {comment.mentions.length > 0 && <span>@clinician mentioned</span>}
                              {comment.assigned_role && <span>Assigned to {comment.assigned_role}</span>}
                            </div>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void toggleComment(comment)}
                              className="text-xs font-semibold text-teal-700 hover:text-teal-900 disabled:opacity-50"
                            >
                              {comment.resolved ? "Unresolve" : "Resolve"}
                            </button>
                          </div>
                        </div>
                      ))}

                      {role !== "patient" && commentEntryId !== entry.id && (
                        <button
                          type="button"
                          onClick={() => {
                            setCommentEntryId(entry.id);
                            setCommentBody("");
                          }}
                          className="mt-4 text-sm font-semibold text-teal-700 hover:text-teal-900"
                        >
                          Add comment
                        </button>
                      )}

                      {role !== "patient" && commentEntryId === entry.id && (
                        <form onSubmit={(event) => void submitComment(event, entry.id)} className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
                          <textarea
                            required
                            value={commentBody}
                            onChange={(event) => setCommentBody(event.target.value)}
                            placeholder={role === "staff" ? "Ask @clinician to review…" : "Add an internal care-team comment…"}
                            aria-label="Comment body"
                            rows={2}
                            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-teal-500"
                          />
                          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                            {role === "staff" ? (
                              <label className="flex items-center gap-2 text-xs text-slate-600">
                                <input
                                  type="checkbox"
                                  checked={assignClinician}
                                  onChange={(event) => setAssignClinician(event.target.checked)}
                                />
                                Mention and assign clinician
                              </label>
                            ) : <span />}
                            <div className="flex gap-2">
                              <button type="button" onClick={() => setCommentEntryId(null)} className="px-3 py-2 text-xs font-semibold text-slate-500">Cancel</button>
                              <button disabled={busy} className="rounded-lg bg-teal-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">
                                {busy ? "Saving…" : "Comment"}
                              </button>
                            </div>
                          </div>
                        </form>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <aside className="space-y-5 lg:sticky lg:top-6 lg:self-start">
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-slate-950">Open actions</h2>
                <span className="grid h-7 w-7 place-items-center rounded-full bg-teal-100 text-xs font-bold text-teal-800">{record.tasks.length}</span>
              </div>
              <div className="mt-4 space-y-3">
                {record.tasks.map((task) => (
                  <div key={task.id} className="rounded-xl border border-slate-200 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase ${riskStyles[task.priority]}`}>{task.priority}</span>
                      <span className="text-xs capitalize text-slate-400">{task.assigned_role}</span>
                    </div>
                    <p className="mt-3 text-sm font-semibold leading-5 text-slate-800">{task.title}</p>
                    <p className="mt-2 text-xs text-slate-500">Due {formatDate(task.due_at, true)}</p>
                  </div>
                ))}
              </div>
            </section>

            {record.conflicts[0] && (
              <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5">
                <p className="text-xs font-semibold uppercase tracking-wider text-rose-600">Conflict review</p>
                <p className="mt-3 text-sm font-semibold leading-6 text-rose-950">{record.conflicts[0].summary}</p>
                <p className="mt-3 text-xs text-rose-700">Two source entries preserved · no silent overwrite</p>
              </section>
            )}

            <p className="px-2 text-xs leading-5 text-slate-400">
              AI signals are candidates. Clinicians decide what becomes trusted clinical memory.
            </p>
          </aside>
        </div>
      </div>
    </main>
  );
}
