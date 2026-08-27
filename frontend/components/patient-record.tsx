"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  AIIngestResult,
  AIInteractionType,
  AIRedactionPreview,
  Comment,
  Highlight,
  PatientRecord as PatientRecordData,
  PatientChatResponse,
  RiskLevel,
  TimelineEntry,
  UserRole,
  DemoSession,
  Version,
} from "@/lib/types";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
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

const interactionLabels: Record<AIInteractionType, string> = {
  ai_doctor_consult_summary: "Doctor consultation",
  ai_nurse_consult_summary: "Nurse consultation",
  ai_patient_session_summary: "Patient session",
};

const fallbackLabels: Record<NonNullable<AIIngestResult["fallback_reason"]>, string> = {
  llm_unavailable: "LLM unavailable",
  invalid_json: "LLM returned invalid JSON",
  timeout: "LLM request timed out",
  provenance_unresolved: "LLM provenance could not be resolved",
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

function provenanceLabel(confidence: Highlight["provenance_pointer"]["offset_confidence"]) {
  return `${confidence} provenance`;
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

export function PatientRecord({ session, patientId, onLogout }: { session: DemoSession; patientId: string; onLogout: () => void }) {
  const role: UserRole = session.identity.role;
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
  const [editEntryId, setEditEntryId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [historyEntryId, setHistoryEntryId] = useState<string | null>(null);
  const [showAIIngest, setShowAIIngest] = useState(false);
  const [interactionType, setInteractionType] = useState<AIInteractionType>("ai_doctor_consult_summary");
  const [sourceId, setSourceId] = useState(() => crypto.randomUUID());
  const [transcript, setTranscript] = useState("");
  const [redactionPreview, setRedactionPreview] = useState<AIRedactionPreview | null>(null);
  const [ingestResult, setIngestResult] = useState<AIIngestResult | null>(null);
  const [highlightPage, setHighlightPage] = useState(1);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [chatMessage, setChatMessage] = useState("");
  const [chatRedactions, setChatRedactions] = useState<string[]>([]);

  const authHeaders = useCallback(
    () => ({
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.access_token}`,
    }),
    [session.access_token],
  );

  const loadRecord = useCallback(async (signal?: AbortSignal, requestedPage = 1) => {
    const query = new URLSearchParams({
      highlight_page: String(requestedPage),
      highlight_page_size: "3",
    });
    const response = await fetch(`${apiUrl}/api/patients/${patientId}/record?${query}`, {
      signal,
      headers: authHeaders(),
    });
    if (!response.ok) throw new Error(`API returned HTTP ${response.status}`);
    const nextRecord = (await response.json()) as PatientRecordData;
    setRecord(nextRecord);
    setHighlightPage(nextRecord.highlight_pagination.page);
  }, [authHeaders, patientId]);

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

  const versionsByEntry = useMemo(() => {
    const grouped = new Map<string, Version[]>();
    for (const version of record?.versions ?? []) {
      grouped.set(
        version.entry_id,
        [...(grouped.get(version.entry_id) ?? []), version].sort(
          (left, right) => right.version_number - left.version_number,
        ),
      );
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
      await loadRecord(undefined, highlightPage);
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : "Unable to save change");
      throw caught;
    } finally {
      setBusy(false);
    }
  }

  async function postJson<T>(path: string, body: object): Promise<T> {
    const response = await fetch(`${apiUrl}${path}`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
      throw new Error(payload?.detail ?? `API returned HTTP ${response.status}`);
    }
    return (await response.json()) as T;
  }

  async function previewRedaction() {
    setBusy(true);
    setMutationError(null);
    setIngestResult(null);
    try {
      const preview = await postJson<AIRedactionPreview>(
        `/api/patients/${patientId}/ai-ingest/preview`,
        { transcript },
      );
      setRedactionPreview(preview);
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : "Unable to preview redaction");
    } finally {
      setBusy(false);
    }
  }

  function toggleAIIngest() {
    if (!showAIIngest) {
      setTranscript("");
      setRedactionPreview(null);
      setIngestResult(null);
      setSourceId(crypto.randomUUID());
    }
    setShowAIIngest((current) => !current);
  }

  async function runAIIngest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!redactionPreview) return;
    setBusy(true);
    setMutationError(null);
    try {
      const result = await postJson<AIIngestResult>(
        `/api/patients/${patientId}/ai-ingest`,
        {
          interaction_type: interactionType,
          source_id: sourceId,
          transcript,
        },
      );
      setIngestResult(result);
      setSourceId(crypto.randomUUID());
      setHighlightPage(1);
      await loadRecord(undefined, 1);
      if (result.highlights[0]) setFocusedHighlight(result.highlights[0]);
      window.setTimeout(() => {
        document.getElementById(result.entry.id)?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 100);
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : "Unable to run AI ingest");
    } finally {
      setBusy(false);
    }
  }

  const activeChat = activeChatId === "new"
    ? null
    : record?.patient_chat_sessions.find((item) => item.id === activeChatId)
      ?? record?.patient_chat_sessions[0]
      ?? null;

  async function sendPatientChat(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!chatMessage.trim()) return;
    setBusy(true);
    setMutationError(null);
    try {
      const result = await postJson<PatientChatResponse>(
        `/api/patients/${patientId}/ai-chat`,
        { message: chatMessage, session_id: activeChat?.id ?? null },
      );
      setActiveChatId(result.session.id);
      setChatRedactions(result.redacted_phi_types);
      setChatMessage("");
      await loadRecord(undefined, highlightPage);
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : "Unable to send message");
    } finally {
      setBusy(false);
    }
  }

  async function ingestPatientChat() {
    if (!activeChat) return;
    setBusy(true);
    setMutationError(null);
    try {
      const result = await postJson<AIIngestResult & { session: { id: string } }>(
        `/api/patients/${patientId}/ai-chat/${activeChat.id}/ingest`,
        {},
      );
      setHighlightPage(1);
      await loadRecord(undefined, 1);
      if (result.highlights[0]) setFocusedHighlight(result.highlights[0]);
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : "Unable to add conversation to record");
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

  function canEditEntry(entry: TimelineEntry) {
    if (role === "admin") {
      return ["staff_note", "clinician_note", "clinician_section"].includes(entry.entry_type);
    }
    if (role === "staff") {
      return entry.entry_type === "staff_note" && entry.author_id === session.identity.id;
    }
    return role === "clinician" && ["clinician_note", "clinician_section"].includes(entry.entry_type);
  }

  async function submitEdit(event: React.FormEvent<HTMLFormElement>, entry: TimelineEntry) {
    event.preventDefault();
    try {
      await mutate(`/api/patients/${patientId}/entries/${entry.id}`, "PATCH", {
        content: editContent,
        expected_version: entry.version,
      });
      setEditEntryId(null);
      setHistoryEntryId(entry.id);
    } catch {}
  }

  async function revertEntry(entry: TimelineEntry, targetVersion: number) {
    try {
      await mutate(`/api/patients/${patientId}/entries/${entry.id}/revert`, "POST", {
        target_version: targetVersion,
        expected_version: entry.version,
      });
      setHistoryEntryId(entry.id);
    } catch {}
  }

  function revealSource(highlight: Highlight) {
    setFocusedHighlight(highlight);
    void recordHighlightInteraction(highlight, "highlight");
    requestAnimationFrame(() => {
      document
        .getElementById(highlight.provenance_pointer.entry_id)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  async function recordHighlightInteraction(
    highlight: Highlight,
    eventType: "pin" | "highlight" | "less_relevant",
  ) {
    try {
      await postJson(
        `/api/patients/${patientId}/highlights/${highlight.id}/interactions`,
        { event_type: eventType },
      );
      await loadRecord(undefined, highlightPage);
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : "Unable to record interaction");
    }
  }

  function revealConflictSource(entryId: string) {
    setFocusedHighlight(null);
    requestAnimationFrame(() => {
      document.getElementById(entryId)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  async function changeHighlightPage(page: number) {
    setBusy(true);
    setMutationError(null);
    try {
      setHighlightPage(page);
      await loadRecord(undefined, page);
      setFocusedHighlight(null);
      document.getElementById("glance-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (caught) {
      setMutationError(caught instanceof Error ? caught.message : "Unable to load highlight page");
    } finally {
      setBusy(false);
    }
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
            <div className="hidden text-right sm:block">
              <p className="text-xs font-semibold text-slate-700">{session.identity.display_name}</p>
              <p className="text-[11px] capitalize text-slate-400">{role} demo session</p>
            </div>
            <button type="button" onClick={onLogout} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50">
              Log out
            </button>
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

        <section id="glance-card" className="mt-8 scroll-mt-6 overflow-hidden rounded-3xl bg-teal-950 text-white shadow-2xl shadow-teal-950/15">
          <div className="flex flex-col justify-between gap-4 border-b border-white/10 px-6 py-6 sm:px-8 md:flex-row md:items-center">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-teal-300">10-second glance · {role} view</p>
              <h2 className="mt-2 text-2xl font-semibold">What changed and needs action</h2>
              <p className="mt-2 text-xs text-teal-200/70">Trust-filtered and backend-ranked · 3 signals per page</p>
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
              <article
                key={highlight.id}
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
                  <span className="text-teal-100/70">
                    {trustLabel(highlight.trust_status)} · {highlight.extraction_confidence} extraction · {provenanceLabel(highlight.provenance_pointer.offset_confidence)}
                  </span>
                  <span className="font-semibold text-teal-300">Effective importance</span>
                </div>
                <div className="mt-4 space-y-1.5 border-t border-white/10 pt-4 text-xs leading-5 text-teal-100/65">
                  <p><span className="font-semibold text-teal-200">Risk:</span> {highlight.risk_floor_reason ?? highlight.risk_reason}</p>
                  <p><span className="font-semibold text-teal-200">Confidence:</span> {highlight.confidence_reason}</p>
                  <p><span className="font-semibold text-teal-200">Importance:</span> {highlight.importance_reason}</p>
                  {highlight.learning_adjustment > 0 && (
                    <p className="text-emerald-300"><span className="font-semibold">Learning +{highlight.learning_adjustment}:</span> {highlight.learning_reason}</p>
                  )}
                  {highlight.learning_adjustment < 0 && (
                    <p className="text-amber-300"><span className="font-semibold">Learning {highlight.learning_adjustment}:</span> {highlight.learning_reason}</p>
                  )}
                  {highlight.learning_reason?.includes("safety_protected_from_negative_learning") && (
                    <p className="text-rose-300"><span className="font-semibold">Safety guard:</span> negative learning was ignored for this signal.</p>
                  )}
                  {highlight.decay_reason && (
                    <p><span className="font-semibold text-teal-200">Data decay {highlight.decay_adjustment}:</span> {highlight.decay_reason}</p>
                  )}
                </div>
                <div className={`mt-5 grid gap-2 ${(role === "clinician" || role === "admin") ? "grid-cols-[minmax(0,1fr)_5.5rem_5.5rem]" : "grid-cols-1"}`}>
                  <button
                    type="button"
                    onClick={() => revealSource(highlight)}
                    className="min-w-0 rounded-lg border border-white/20 px-2.5 py-1.5 text-xs font-semibold text-teal-200 hover:bg-white/10 hover:text-white"
                  >
                    Source ↓
                  </button>
                  {(role === "clinician" || role === "admin") && (
                    <>
                      <button
                        type="button"
                        onClick={() => void recordHighlightInteraction(highlight, "pin")}
                        className="rounded-lg border border-emerald-300/50 bg-emerald-300/10 px-2 py-1.5 text-xs font-semibold text-emerald-200 hover:border-emerald-200 hover:bg-emerald-300/20"
                      >
                        Pin <span className="font-mono">+4</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => void recordHighlightInteraction(highlight, "less_relevant")}
                        className="rounded-lg border border-amber-300/50 bg-amber-300/10 px-2 py-1.5 text-xs font-semibold text-amber-200 hover:border-amber-200 hover:bg-amber-300/20"
                      >
                        Reduce <span className="font-mono">−2</span>
                      </button>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
          {record.highlight_pagination.total_pages > 1 && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 px-6 py-4 sm:px-8">
              <p className="text-xs text-teal-100/70">
                Page {record.highlight_pagination.page} of {record.highlight_pagination.total_pages} · {record.highlight_pagination.total_items} ranked signals
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={busy || record.highlight_pagination.page === 1}
                  onClick={() => void changeHighlightPage(record.highlight_pagination.page - 1)}
                  className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-semibold text-white hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Previous
                </button>
                <span className="grid h-8 min-w-20 place-items-center rounded-lg bg-white px-3 text-xs font-semibold text-teal-950" aria-current="page">
                  {record.highlight_pagination.page} / {record.highlight_pagination.total_pages}
                </span>
                <button
                  type="button"
                  disabled={busy || record.highlight_pagination.page === record.highlight_pagination.total_pages}
                  onClick={() => void changeHighlightPage(record.highlight_pagination.page + 1)}
                  className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-semibold text-white hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </section>

        {role === "patient" && (
          <section className="mt-8 overflow-hidden rounded-3xl border border-sky-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-sky-100 bg-sky-50 px-5 py-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-700">Patient AI assistant</p>
                <h2 className="mt-1 text-xl font-semibold text-slate-950">Ask about your care</h2>
                <p className="mt-1 text-sm text-slate-600">Questions are redacted before DeepSeek. You decide when a conversation becomes part of the clinical timeline.</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setActiveChatId("new");
                  setChatRedactions([]);
                }}
                className="rounded-xl border border-sky-300 bg-white px-3 py-2 text-xs font-semibold text-sky-800 hover:bg-sky-100"
              >
                New conversation
              </button>
            </div>
            <div className="grid lg:grid-cols-[220px_minmax(0,1fr)]">
              <aside className="border-b border-slate-200 bg-slate-50 p-3 lg:border-b-0 lg:border-r">
                <p className="px-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Conversation history</p>
                <div className="mt-2 flex gap-2 overflow-x-auto lg:block lg:space-y-2">
                  {record.patient_chat_sessions.map((session) => (
                    <button
                      key={session.id}
                      type="button"
                      onClick={() => setActiveChatId(session.id)}
                      className={`min-w-44 rounded-xl p-3 text-left text-xs lg:w-full ${activeChat?.id === session.id ? "bg-sky-100 text-sky-950" : "bg-white text-slate-600 hover:bg-slate-100"}`}
                    >
                      <span className="block truncate font-semibold">{session.title}</span>
                      <span className="mt-1 block text-[10px] text-slate-400">{session.messages.length / 2} exchange(s){session.ingested_entry_id ? " · in record" : ""}</span>
                    </button>
                  ))}
                  {record.patient_chat_sessions.length === 0 && <p className="px-2 py-4 text-xs text-slate-400">No conversations yet.</p>}
                </div>
              </aside>
              <div className="p-5">
                <div className="max-h-96 min-h-56 space-y-3 overflow-y-auto rounded-2xl bg-slate-50 p-4">
                  {activeChat?.messages.map((message) => (
                    <div key={message.id} className={`flex ${message.role === "patient" ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-6 ${message.role === "patient" ? "bg-sky-700 text-white" : "border border-slate-200 bg-white text-slate-700"}`}>
                        {message.content}
                      </div>
                    </div>
                  ))}
                  {!activeChat && <div className="grid min-h-48 place-items-center text-center text-sm text-slate-400">Start a conversation with the patient assistant.</div>}
                </div>
                {chatRedactions.length > 0 && (
                  <p className="mt-2 text-xs text-emerald-700">Protected before sending: {chatRedactions.join(", ")}</p>
                )}
                <form onSubmit={sendPatientChat} className="mt-3 flex gap-2">
                  <textarea
                    required
                    value={chatMessage}
                    onChange={(event) => setChatMessage(event.target.value)}
                    rows={2}
                    placeholder="Ask a question or describe a change in your symptoms…"
                    className="min-w-0 flex-1 resize-none rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-sky-500"
                  />
                  <button disabled={busy || !chatMessage.trim()} className="rounded-xl bg-sky-700 px-5 text-sm font-semibold text-white hover:bg-sky-600 disabled:opacity-50">
                    {busy ? "Sending…" : "Send"}
                  </button>
                </form>
                {activeChat && (
                  <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                    <p className="text-xs leading-5 text-amber-900">Adding this conversation creates an AI-extracted, source-backed timeline entry for care-team review.</p>
                    <button
                      type="button"
                      disabled={busy || Boolean(activeChat.ingested_entry_id)}
                      onClick={() => void ingestPatientChat()}
                      className="shrink-0 rounded-lg bg-amber-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
                    >
                      {activeChat.ingested_entry_id ? "Added to record" : "Add to record"}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
          <section>
            <div className="flex items-end justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-700">Longitudinal record</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-950">Timeline</h2>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-slate-500">{record.timeline_entries.length} entries</span>
                {(role === "clinician" || role === "admin") && (
                  <button
                    type="button"
                    onClick={toggleAIIngest}
                    className="rounded-xl border border-violet-200 bg-violet-50 px-4 py-2 text-sm font-semibold text-violet-800 hover:bg-violet-100"
                  >
                    {showAIIngest ? "Close AI ingest" : "Ingest AI note"}
                  </button>
                )}
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

            {showAIIngest && (role === "clinician" || role === "admin") && (
              <form onSubmit={runAIIngest} className="mt-5 overflow-hidden rounded-2xl border border-violet-200 bg-white shadow-sm">
                <div className="border-b border-violet-100 bg-violet-50/70 px-5 py-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-violet-700">Secure AI ingest</p>
                  <h3 className="mt-1 text-lg font-semibold text-slate-950">Redact first, then extract source-backed signals</h3>
                  <p className="mt-1 text-sm text-slate-600">The backend re-runs redaction during ingest. Raw text is never passed directly to the LLM.</p>
                </div>
                <div className="grid gap-5 p-5 lg:grid-cols-2">
                  <div>
                    <label className="text-xs font-semibold uppercase tracking-wide text-slate-600" htmlFor="interaction-type">Interaction type</label>
                    <select
                      id="interaction-type"
                      value={interactionType}
                      onChange={(event) => setInteractionType(event.target.value as AIInteractionType)}
                      className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-violet-500"
                    >
                      {Object.entries(interactionLabels).map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                    <p className="mt-3 rounded-lg border border-violet-100 bg-violet-50 px-3 py-2 text-xs leading-5 text-violet-800">
                      The timeline title and source ID are generated automatically during ingest.
                    </p>
                    <label className="mt-4 block text-xs font-semibold uppercase tracking-wide text-slate-600" htmlFor="ai-transcript">Synthetic transcript or note</label>
                    <textarea
                      id="ai-transcript"
                      required
                      value={transcript}
                      onChange={(event) => {
                        setTranscript(event.target.value);
                        setRedactionPreview(null);
                        setIngestResult(null);
                      }}
                      rows={10}
                      placeholder="Paste a synthetic consultation transcript. Include a demo name, phone, ID, or email to verify redaction."
                      className="mt-2 w-full rounded-xl border border-slate-200 px-3 py-3 text-sm leading-6 outline-none focus:border-violet-500"
                    />
                    <button
                      type="button"
                      disabled={busy || transcript.trim().length === 0}
                      onClick={() => void previewRedaction()}
                      className="mt-3 rounded-xl border border-violet-300 px-4 py-2 text-sm font-semibold text-violet-800 hover:bg-violet-50 disabled:opacity-50"
                    >
                      {busy ? "Checking…" : "Preview redaction"}
                    </button>
                  </div>

                  <div className="flex h-full flex-col rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">Text sent to LLM</p>
                      {redactionPreview && (
                        <div className="flex flex-wrap gap-1.5">
                          {redactionPreview.redacted_phi_types.map((type) => (
                            <span key={type} className="rounded-full bg-emerald-100 px-2 py-1 text-[10px] font-semibold uppercase text-emerald-700">{type} redacted</span>
                          ))}
                        </div>
                      )}
                    </div>
                    {redactionPreview ? (
                      <div className="mt-3 flex min-h-0 flex-1 flex-col">
                        <pre className="min-h-72 flex-1 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-4 text-xs leading-6 text-slate-100">{redactionPreview.redacted_text}</pre>
                        {redactionPreview.warning && (
                          <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800">Redaction warning: {redactionPreview.warning}</p>
                        )}
                        <button
                          disabled={busy}
                          className="mt-4 w-full rounded-xl bg-violet-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-600 disabled:opacity-50"
                        >
                          {busy ? "Extracting…" : "Extract signals & generate title"}
                        </button>
                      </div>
                    ) : (
                      <div className="mt-3 grid min-h-72 flex-1 place-items-center rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center text-sm leading-6 text-slate-500">
                        Preview redaction before enabling AI ingest.
                      </div>
                    )}
                  </div>
                </div>

                {ingestResult && (
                  <div className={`border-t px-5 py-4 ${ingestResult.extraction_method === "deepseek" ? "border-emerald-100 bg-emerald-50" : "border-amber-100 bg-amber-50"}`}>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{ingestResult.entry.title}</p>
                        <p className="mt-1 text-xs font-medium text-slate-500">
                          Ingest complete · {ingestResult.promoted_count} promoted · {ingestResult.review_queue_count} queued for review
                        </p>
                        <p className="mt-1 text-sm text-slate-600">{ingestResult.summary}</p>
                      </div>
                      <span className={`rounded-full px-3 py-1 text-xs font-semibold ${ingestResult.extraction_method === "deepseek" ? "bg-emerald-200 text-emerald-900" : "bg-amber-200 text-amber-900"}`}>
                        {ingestResult.extraction_method === "deepseek" ? "DeepSeek LLM" : `Deterministic fallback · ${ingestResult.fallback_reason ? fallbackLabels[ingestResult.fallback_reason] : "unknown reason"}`}
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-slate-500">The new system entry and source-backed highlights are now visible below and in the glance card.</p>
                  </div>
                )}
              </form>
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
                const versions = versionsByEntry.get(entry.id) ?? [];
                const previousVersion = versions.find(
                  (version) => version.version_number < entry.version,
                );
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
                        {isFocused && focusedHighlight && (
                          <span className="font-semibold text-amber-700">
                            Exact source · {focusedHighlight.provenance_pointer.offset_confidence} confidence
                          </span>
                        )}
                        {canEditEntry(entry) && (
                          <button
                            type="button"
                            onClick={() => {
                              setEditEntryId(entry.id);
                              setEditContent(entry.content);
                            }}
                            className="ml-auto font-semibold text-teal-700 hover:text-teal-900"
                          >
                            Edit note
                          </button>
                        )}
                        {versions.length > 0 && (
                          <button
                            type="button"
                            onClick={() => setHistoryEntryId(
                              historyEntryId === entry.id ? null : entry.id,
                            )}
                            className="font-semibold text-violet-700 hover:text-violet-900"
                          >
                            {historyEntryId === entry.id ? "Hide history" : `History (${versions.length})`}
                          </button>
                        )}
                      </div>

                      {editEntryId === entry.id && canEditEntry(entry) && (
                        <form onSubmit={(event) => void submitEdit(event, entry)} className="mt-4 rounded-xl border border-teal-200 bg-teal-50/50 p-4">
                          <label className="text-xs font-semibold uppercase tracking-wide text-teal-800" htmlFor={`edit-${entry.id}`}>
                            Edit version {entry.version + 1}
                          </label>
                          <textarea
                            id={`edit-${entry.id}`}
                            required
                            value={editContent}
                            onChange={(event) => setEditContent(event.target.value)}
                            rows={4}
                            className="mt-2 w-full rounded-lg border border-teal-200 bg-white px-3 py-2 text-sm outline-none focus:border-teal-500"
                          />
                          <div className="mt-3 flex justify-end gap-2">
                            <button type="button" onClick={() => setEditEntryId(null)} className="px-3 py-2 text-xs font-semibold text-slate-500">Cancel</button>
                            <button disabled={busy} className="rounded-lg bg-teal-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">
                              {busy ? "Saving…" : "Save new version"}
                            </button>
                          </div>
                        </form>
                      )}

                      {historyEntryId === entry.id && versions.length > 0 && (
                        <section className="mt-4 rounded-xl border border-violet-200 bg-violet-50/60 p-4" aria-label={`Revision history for ${entry.title}`}>
                          <div className="flex items-center justify-between">
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-violet-700">Revision history</p>
                              <p className="mt-1 text-xs text-slate-500">Revert always creates a new version.</p>
                            </div>
                            <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-violet-700">Current v{entry.version}</span>
                          </div>

                          {previousVersion && (
                            <div className="mt-4 grid gap-3 md:grid-cols-2">
                              <div className="rounded-lg border border-slate-200 bg-white p-3">
                                <p className="text-xs font-semibold text-slate-500">Previous · v{previousVersion.version_number}</p>
                                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{previousVersion.content_snapshot}</p>
                              </div>
                              <div className="rounded-lg border border-teal-200 bg-white p-3">
                                <p className="text-xs font-semibold text-teal-700">Current · v{entry.version}</p>
                                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{entry.content}</p>
                              </div>
                            </div>
                          )}

                          <div className="mt-4 space-y-2">
                            {versions.map((version) => (
                              <div key={version.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-violet-100 bg-white px-3 py-2.5">
                                <div>
                                  <p className="text-sm font-semibold text-slate-800">v{version.version_number} · {version.change_summary}</p>
                                  <p className="mt-0.5 text-xs text-slate-400">{formatDate(version.created_at, true)} · {roleLabels[version.changed_by_role]}</p>
                                </div>
                                {version.version_number < entry.version && canEditEntry(entry) && (
                                  <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => void revertEntry(entry, version.version_number)}
                                    className="rounded-lg border border-violet-200 px-3 py-1.5 text-xs font-semibold text-violet-700 hover:bg-violet-100 disabled:opacity-50"
                                  >
                                    Revert to v{version.version_number}
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                        </section>
                      )}
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
            {role !== "patient" && (
              <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider text-amber-700">Review queue</p>
                    <h2 className="mt-1 font-semibold text-amber-950">Abstained signals</h2>
                  </div>
                  <span className="grid h-7 min-w-7 place-items-center rounded-full bg-amber-200 px-2 text-xs font-bold text-amber-900">{record.review_queue.length}</span>
                </div>
                {record.review_queue.length === 0 ? (
                  <p className="mt-4 text-sm leading-6 text-amber-800/75">No low-confidence or conflicting signals need review.</p>
                ) : (
                  <div className="mt-4 space-y-3">
                    {record.review_queue.map((highlight) => (
                      <button
                        key={highlight.id}
                        type="button"
                        onClick={() => revealSource(highlight)}
                        className="w-full rounded-xl border border-amber-200 bg-white p-4 text-left transition hover:border-amber-400"
                      >
                        <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase">
                          <span className="rounded-full bg-rose-100 px-2 py-1 text-rose-700">Review needed</span>
                          <span className="text-amber-700">{categoryLabels[highlight.category]}</span>
                          <span className="text-slate-400">{highlight.extraction_confidence} confidence</span>
                        </div>
                        <p className="mt-3 text-sm font-semibold leading-5 text-slate-900">{highlight.text}</p>
                        <p className="mt-2 text-xs leading-5 text-slate-600">{highlight.abstention_reason ?? highlight.confidence_reason}</p>
                        <p className="mt-2 text-xs font-semibold text-amber-700">Inspect source →</p>
                      </button>
                    ))}
                  </div>
                )}
              </section>
            )}

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

            {record.conflicts.length > 0 && (
              <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5">
                <p className="text-xs font-semibold uppercase tracking-wider text-rose-600">Conflict review</p>
                <div className="mt-3 space-y-4">
                  {record.conflicts.map((conflict) => (
                    <div key={conflict.id} className="rounded-xl border border-rose-200 bg-white p-4">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] font-semibold uppercase text-rose-600">{conflict.conflict_type} · review needed</span>
                        <span className="text-[11px] font-semibold uppercase text-rose-400">{conflict.severity}</span>
                      </div>
                      <p className="mt-2 text-sm font-semibold leading-6 text-rose-950">{conflict.summary}</p>
                      <div className="mt-3 grid grid-cols-2 gap-2">
                        {conflict.source_entry_ids.slice(0, 2).map((entryId, index) => (
                          <button
                            key={entryId}
                            type="button"
                            onClick={() => revealConflictSource(entryId)}
                            className="rounded-lg border border-rose-200 px-2 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-50"
                          >
                            Source {index + 1} ↑
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-xs text-rose-700">Both source entries are preserved · no silent overwrite</p>
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
