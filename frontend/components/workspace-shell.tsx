"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PatientRecord } from "@/components/patient-record";
import type { DemoSession } from "@/lib/types";

const patientNames: Record<string, string> = {
  "patient-syn-001": "Elaine Tan",
  "patient-syn-002": "Amir Rahman",
  "patient-syn-003": "Sofia Chen",
};

export function WorkspaceShell({ patientId }: { patientId: string }) {
  const router = useRouter();
  const [session, setSession] = useState<DemoSession | null>(null);

  useEffect(() => {
    const raw = localStorage.getItem("caredelta-demo-session");
    if (!raw) {
      router.replace("/");
      return;
    }

    try {
      const parsed = JSON.parse(raw) as DemoSession;
      if (!parsed.identity.available_patient_ids.includes(patientId)) {
        router.replace(`/workspace/${parsed.identity.default_patient_id}`);
        return;
      }
      queueMicrotask(() => setSession(parsed));
    } catch {
      localStorage.removeItem("caredelta-demo-session");
      router.replace("/");
    }
  }, [patientId, router]);

  function logout() {
    localStorage.removeItem("caredelta-demo-session");
    router.replace("/");
  }

  if (!session) {
    return (
      <main className="grid min-h-screen place-items-center text-slate-500">
        Checking demo session…
      </main>
    );
  }

  return (
    <>
      {session.identity.role !== "patient" && (
        <div className="border-b border-teal-900 bg-teal-950 px-5 py-2 text-white">
          <div className="mx-auto flex max-w-7xl items-center justify-end gap-3">
            <label className="text-xs text-teal-200" htmlFor="patient-switcher">
              Patient workspace
            </label>
            <select
              id="patient-switcher"
              value={patientId}
              onChange={(event) => router.push(`/workspace/${event.target.value}`)}
              className="rounded-lg border border-white/20 bg-teal-900 px-3 py-1.5 text-xs font-semibold outline-none"
            >
              {session.identity.available_patient_ids.map((id) => (
                <option key={id} value={id}>
                  {patientNames[id]}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
      <PatientRecord session={session} patientId={patientId} onLogout={logout} />
    </>
  );
}
