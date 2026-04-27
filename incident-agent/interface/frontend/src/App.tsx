import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Tab = "overview" | "incidents" | "live" | "chat";

type Metrics = {
  label: string;
  deployments_total: number;
  deployment_frequency_per_day: number;
  deployment_duration_minutes: number;
  deployment_failures_30d: number;
  percent_downtime_6mo: number;
  series: { deployments_per_week: number[]; incident_minutes_per_week: number[] };
};

type HistoryRow = Record<string, unknown>;

function weekSeries(values: number[], prefix: string) {
  return values.map((v, i) => ({ name: `${prefix} ${i + 1}`, value: v }));
}

function JsonBlock({ title, data }: { title: string; data: unknown }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-acme-slate/60 p-3">
      <div className="mb-2 text-sm font-semibold text-acme-amber">{title}</div>
      <pre className="max-h-64 overflow-auto text-xs text-slate-200">{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [detail, setDetail] = useState<HistoryRow | null>(null);
  const [chatLog, setChatLog] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatScenario, setChatScenario] = useState("latency-spike");
  const [flushToken, setFlushToken] = useState("");
  const [flushMsg, setFlushMsg] = useState("");

  const loadMetrics = useCallback(async () => {
    const r = await fetch("/api/dashboard/metrics");
    if (r.ok) setMetrics((await r.json()) as Metrics);
  }, []);

  const loadHistory = useCallback(async () => {
    const r = await fetch("/api/incidents/history?limit=50");
    if (r.ok) {
      const j = (await r.json()) as { items: HistoryRow[] };
      setHistory(j.items);
    }
  }, []);

  useEffect(() => {
    void loadMetrics();
  }, [loadMetrics]);

  useEffect(() => {
    if (tab === "incidents") void loadHistory();
  }, [tab, loadHistory]);

  const deployChart = useMemo(() => {
    if (!metrics) return [];
    return weekSeries(metrics.series.deployments_per_week, "Week");
  }, [metrics]);

  const incidentChart = useMemo(() => {
    if (!metrics) return [];
    return weekSeries(metrics.series.incident_minutes_per_week, "Week");
  }, [metrics]);

  async function sendChat() {
    const text = chatInput.trim();
    if (!text) return;
    setChatInput("");
    setChatLog((c) => [...c, { role: "user", text }]);
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, scenario: chatScenario }),
    });
    const j = (await r.json()) as { reply?: string; detail?: string };
    setChatLog((c) => [...c, { role: "assistant", text: j.reply || j.detail || "No response" }]);
  }

  async function runFlush() {
    setFlushMsg("");
    const r = await fetch("/api/admin/incidents/flush", {
      method: "POST",
      headers: { "X-Demo-Admin-Token": flushToken },
    });
    const j = await r.json().catch(() => ({}));
    setFlushMsg(r.ok ? `Flushed (${j.deleted_rows ?? 0} rows).` : (j.detail as string) || "Flush failed");
    void loadHistory();
  }

  async function openDetail(id: string) {
    const r = await fetch(`/api/incidents/history/${id}`);
    if (r.ok) setDetail((await r.json()) as HistoryRow);
  }

  const navBtn = (id: Tab, label: string) => (
    <button
      type="button"
      key={id}
      onClick={() => setTab(id)}
      className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
        tab === id
          ? "bg-acme-amber text-acme-navy"
          : "bg-acme-slate text-slate-200 hover:bg-slate-700"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="min-h-screen bg-gradient-to-b from-acme-navy to-[#060b14]">
      <header className="border-b border-slate-800 bg-acme-slate/40 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-6 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-acme-mist">Demo command center</div>
            <h1 className="text-3xl font-semibold text-white">
              Acme Corp <span className="text-acme-amber">SRE</span>
            </h1>
            <p className="mt-1 max-w-xl text-sm text-acme-mist">
              Observability-first incident response: static triage packs, timeline, simulator, and history for stakeholder
              walkthroughs.
            </p>
          </div>
          <nav className="flex flex-wrap gap-2">
            {navBtn("overview", "Overview")}
            {navBtn("incidents", "Incidents")}
            {navBtn("live", "Live + simulator")}
            {navBtn("chat", "Chat")}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {tab === "overview" && (
          <section className="space-y-8">
            {metrics ? (
              <>
                <div className="grid gap-4 md:grid-cols-3">
                  <MetricCard label="Total deployments" value={String(metrics.deployments_total)} sub="p (demo)" />
                  <MetricCard
                    label="Deployment frequency"
                    value={`${metrics.deployment_frequency_per_day} / day`}
                    sub="x/day (demo)"
                  />
                  <MetricCard
                    label="Typical duration"
                    value={`${metrics.deployment_duration_minutes} min`}
                    sub="y minutes (demo)"
                  />
                  <MetricCard label="Failures (30d)" value={String(metrics.deployment_failures_30d)} sub="z (demo)" />
                  <MetricCard
                    label="Downtime (6 mo)"
                    value={`${metrics.percent_downtime_6mo}%`}
                    sub="q% over r months (demo)"
                  />
                  <MetricCard label="Program" value={metrics.label} sub="Fixed demo numbers" />
                </div>
                <div className="grid gap-6 md:grid-cols-2">
                  <ChartCard title="Deployments per week (demo)">
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart data={deployChart}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} />
                        <YAxis stroke="#94a3b8" fontSize={11} />
                        <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                        <Bar dataKey="value" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </ChartCard>
                  <ChartCard title="Incident minutes per week (demo)">
                    <ResponsiveContainer width="100%" height={240}>
                      <LineChart data={incidentChart}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} />
                        <YAxis stroke="#94a3b8" fontSize={11} />
                        <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                        <Line type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} dot />
                      </LineChart>
                    </ResponsiveContainer>
                  </ChartCard>
                </div>
              </>
            ) : (
              <p className="text-acme-mist">Loading metrics…</p>
            )}
          </section>
        )}

        {tab === "incidents" && (
          <section className="space-y-4">
            <div className="overflow-hidden rounded-xl border border-slate-700 bg-acme-slate/40">
              <table className="w-full text-left text-sm">
                <thead className="bg-acme-slate/80 text-xs uppercase text-acme-mist">
                  <tr>
                    <th className="px-4 py-3">Time</th>
                    <th className="px-4 py-3">Service</th>
                    <th className="px-4 py-3">Scenario</th>
                    <th className="px-4 py-3">Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((row) => (
                    <tr
                      key={String(row.id)}
                      className="cursor-pointer border-t border-slate-800 hover:bg-slate-800/60"
                      onClick={() => void openDetail(String(row.id))}
                    >
                      <td className="px-4 py-3 text-xs text-slate-300">{String(row.created_at)}</td>
                      <td className="px-4 py-3">{String(row.service)}</td>
                      <td className="px-4 py-3">{row.scenario != null ? String(row.scenario) : "—"}</td>
                      <td className="px-4 py-3">{row.outcome != null ? String(row.outcome) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="rounded-xl border border-slate-700 bg-acme-slate/30 p-4">
              <div className="text-sm font-semibold text-acme-amber">Demo reset</div>
              <p className="mt-1 text-xs text-acme-mist">
                POST /api/admin/incidents/flush requires DEMO_ADMIN_FLUSH_TOKEN on the server.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <input
                  className="min-w-[200px] flex-1 rounded-lg border border-slate-600 bg-acme-navy px-3 py-2 text-sm"
                  placeholder="Admin flush token"
                  value={flushToken}
                  onChange={(e) => setFlushToken(e.target.value)}
                />
                <button
                  type="button"
                  className="rounded-lg bg-red-700 px-4 py-2 text-sm font-medium text-white hover:bg-red-600"
                  onClick={() => void runFlush()}
                >
                  Flush history
                </button>
              </div>
              {flushMsg ? <p className="mt-2 text-xs text-slate-300">{flushMsg}</p> : null}
            </div>
          </section>
        )}

        {tab === "live" && (
          <section className="space-y-3">
            <p className="text-sm text-acme-mist">
              Legacy operator UI (timeline + Datadog simulator controls) embedded below — same APIs as before.
            </p>
            <iframe title="Legacy live UI" src="/legacy" className="h-[720px] w-full rounded-xl border border-slate-700 bg-white" />
          </section>
        )}

        {tab === "chat" && (
          <section className="grid gap-4 md:grid-cols-[2fr,1fr]">
            <div className="flex h-[480px] flex-col rounded-xl border border-slate-700 bg-acme-slate/40">
              <div className="flex-1 space-y-3 overflow-y-auto p-4">
                {chatLog.length === 0 ? (
                  <p className="text-sm text-acme-mist">
                    Ask about checkout incidents, or type <code className="text-acme-amber">burst now</code> /{" "}
                    <code className="text-acme-amber">pause simulator</code> /{" "}
                    <code className="text-acme-amber">set scenario to error-burst</code>.
                  </p>
                ) : (
                  chatLog.map((m, i) => (
                    <div
                      key={i}
                      className={`max-w-[90%] rounded-lg px-3 py-2 text-sm ${
                        m.role === "user" ? "ml-auto bg-sky-900/60 text-sky-50" : "mr-auto bg-slate-800 text-slate-100"
                      }`}
                    >
                      {m.text}
                    </div>
                  ))
                )}
              </div>
              <div className="border-t border-slate-700 p-3">
                <textarea
                  className="mb-2 w-full rounded-lg border border-slate-600 bg-acme-navy px-3 py-2 text-sm"
                  rows={3}
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  placeholder="Message the demo assistant…"
                />
                <button
                  type="button"
                  className="rounded-lg bg-acme-amber px-4 py-2 text-sm font-semibold text-acme-navy"
                  onClick={() => void sendChat()}
                >
                  Send
                </button>
              </div>
            </div>
            <div className="rounded-xl border border-slate-700 bg-acme-slate/30 p-4 text-sm">
              <label className="block text-xs font-semibold uppercase text-acme-mist">Scenario hint</label>
              <select
                className="mt-2 w-full rounded-lg border border-slate-600 bg-acme-navy px-3 py-2"
                value={chatScenario}
                onChange={(e) => setChatScenario(e.target.value)}
              >
                <option value="latency-spike">latency-spike</option>
                <option value="error-burst">error-burst</option>
                <option value="cpu-brownout">cpu-brownout</option>
              </select>
              <p className="mt-4 text-xs text-acme-mist">
                Chat uses canned scenario text when USE_DEMO_STATIC_TRIAGE is enabled on the server; no LLM tokens are
                spent.
              </p>
            </div>
          </section>
        )}
      </main>

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => setDetail(null)}>
          <div
            className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl border border-slate-600 bg-acme-navy p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Incident log</h2>
              <button type="button" className="text-sm text-acme-amber" onClick={() => setDetail(null)}>
                Close
              </button>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <JsonBlock title="triage" data={detail.triage} />
              <JsonBlock title="remediation" data={detail.remediation} />
              <JsonBlock title="presented_to_user" data={detail.presented_to_user} />
              <JsonBlock title="meta" data={{ id: detail.id, created_at: detail.created_at, outcome: detail.outcome }} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-acme-slate/40 p-4">
      <div className="text-xs uppercase tracking-wide text-acme-mist">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
      <div className="mt-1 text-xs text-slate-400">{sub}</div>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-acme-slate/40 p-4">
      <div className="mb-2 text-sm font-semibold text-acme-amber">{title}</div>
      {children}
    </div>
  );
}
