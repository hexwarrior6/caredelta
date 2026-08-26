import { ApiHealth } from "@/components/api-health";

export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <section className="w-full max-w-2xl rounded-3xl border border-emerald-950/10 bg-white p-8 shadow-xl shadow-emerald-950/5 sm:p-12">
        <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-emerald-700">
          Clinical Change Radar
        </p>
        <h1 className="text-4xl font-semibold tracking-tight text-emerald-950 sm:text-5xl">
          CareDelta
        </h1>
        <p className="mt-5 max-w-xl text-lg leading-8 text-slate-600">
          Source-backed clinical change tracking for safer, more trustworthy
          handoffs.
        </p>
        <ApiHealth />
      </section>
    </main>
  );
}
