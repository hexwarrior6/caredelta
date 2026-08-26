"use client";

import { useEffect, useState } from "react";

type HealthResponse = {
  status: string;
  service: string;
};

type HealthState =
  | { state: "loading" }
  | { state: "connected"; data: HealthResponse }
  | { state: "error"; message: string };

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function ApiHealth() {
  const [health, setHealth] = useState<HealthState>({ state: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    async function checkHealth() {
      try {
        const response = await fetch(`${apiUrl}/health`, {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`API returned HTTP ${response.status}`);
        }

        const data = (await response.json()) as HealthResponse;
        setHealth({ state: "connected", data });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        const message = error instanceof Error ? error.message : "Unknown error";
        setHealth({ state: "error", message });
      }
    }

    void checkHealth();
    return () => controller.abort();
  }, []);

  return (
    <div className="mt-10 rounded-2xl border border-slate-200 bg-slate-50 p-5">
      <div className="flex items-center gap-3">
        <span
          className={`h-3 w-3 rounded-full ${
            health.state === "connected"
              ? "bg-emerald-500"
              : health.state === "error"
                ? "bg-rose-500"
                : "animate-pulse bg-amber-400"
          }`}
          aria-hidden="true"
        />
        <p className="font-medium text-slate-900">
          {health.state === "loading" && "Checking API connection…"}
          {health.state === "connected" && "Backend connected"}
          {health.state === "error" && "Backend unavailable"}
        </p>
      </div>
      <p className="mt-2 text-sm text-slate-500">
        {health.state === "connected"
          ? `${health.data.service}: ${health.data.status}`
          : health.state === "error"
            ? health.message
            : `Requesting ${apiUrl}/health`}
      </p>
    </div>
  );
}
