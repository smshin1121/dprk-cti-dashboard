import { create } from "zustand";
import { config } from "./config";

type ShellState = {
  environment: "dev" | "prod";
};

const useShellStore = create<ShellState>(() => ({
  environment: "dev",
}));

const apiBaseUrl = config.apiUrl;
const llmProxyBaseUrl = config.llmProxyUrl;

export default function App() {
  const environment = useShellStore((state) => state.environment);

  return (
    <main className="min-h-screen bg-slate-100 text-ink">
      <section className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center gap-6 px-6 py-16">
        <p className="text-sm font-semibold uppercase tracking-[0.25em] text-signal">
          Implementation Prep
        </p>
        <h1 className="max-w-3xl text-5xl font-black tracking-tight">
          DPRK Cyber Threat Intelligence Platform
        </h1>
        <p className="max-w-2xl text-lg text-slate-700">
          Frontend scaffold only. KPI cards, maps, ATT&amp;CK heatmap, alerts, and
          similarity panels land in the next phase.
        </p>
        <div className="grid gap-4 md:grid-cols-3">
          <Card label="Environment" value={environment} />
          <Card label="API" value={apiBaseUrl} />
          <Card label="LLM Proxy" value={llmProxyBaseUrl} />
        </div>
      </section>
    </main>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <article className="rounded-2xl border border-grid bg-white p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
        {label}
      </p>
      <p className="mt-3 break-all text-sm font-medium text-slate-800">{value}</p>
    </article>
  );
}
