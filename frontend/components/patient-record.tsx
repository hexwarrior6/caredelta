"use client";

import { useEffect, useMemo, useState } from "react";
import type {
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

  useEffect(() => {
    const controller = new AbortController();

    async function loadRecord() {
      try {
        setRecord(null);
        setError(null);
        const response = await fetch(`${apiUrl}/api/patients/${patientId}/record`, {
          signal: controller.signal,
          headers: {
            "X-Actor-Id": demoActors[role],
            "X-Actor-Role": role,
            "X-Clinic-Id": clinicId,
          },
        });
        if (!response.ok) throw new Error(`API returned HTTP ${response.status}`);
        setRecord((await response.json()) as PatientRecordData);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(caught instanceof Error ? caught.message : "Unable to load record");
      }
    }

    void loadRecord();
    return () => controller.abort();
  }, [role]);

  const commentsByEntry = useMemo(() => {
    return new Map(
      record?.comments.map((comment) => [comment.entry_id, comment]) ?? [],
    );
  }, [record]);

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
              <span className="text-sm text-slate-500">{record.timeline_entries.length} entries</span>
            </div>

            <div className="relative mt-6 space-y-5 before:absolute before:bottom-6 before:left-[19px] before:top-6 before:w-px before:bg-slate-200">
              {record.timeline_entries.map((entry) => {
                const comment = commentsByEntry.get(entry.id);
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
                      {comment && (
                        <div className="mt-4 rounded-xl border border-indigo-100 bg-indigo-50/70 p-4">
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-semibold text-indigo-800">{comment.author_name} commented</span>
                            <span className="text-indigo-500">Open thread</span>
                          </div>
                          <p className="mt-2 text-sm leading-6 text-indigo-950/75">{comment.body}</p>
                        </div>
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
