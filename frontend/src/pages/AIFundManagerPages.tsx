import { useEffect, useState } from "react";
import { getJson } from "../api/client";

type JsonRecord = Record<string, unknown>;

function useJson(path: string) {
  const [state, setState] = useState<{ status: string; data?: JsonRecord }>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    void getJson<JsonRecord>(path).then((res) => {
      if (!cancelled) setState({ status: res.status, data: res.data });
    });
    return () => { cancelled = true; };
  }, [path]);
  return state;
}

function TruthBadge({ label, value }: { label: string; value: string }) {
  return <span className={`state-badge ${value.toLowerCase()}`}>{label}: {value}</span>;
}

export function DashboardPage() {
  const health = useJson("/health");
  const ready = useJson("/ready");
  return (
    <section className="panel">
      <header className="panel-header"><h2>AI Fund Manager Dashboard</h2></header>
      <TruthBadge label="Live" value="DISABLED" />
      <TruthBadge label="Real LLM" value="NOT_CONFIGURED" />
      <TruthBadge label="Shadow" value="FRAMEWORK_READY" />
      <p>Backend health: {health.status}; Ready: {ready.status}</p>
    </section>
  );
}

export function ShadowCampaignPage() {
  const campaign = useJson("/shadow/campaign");
  const data = campaign.data ?? {};
  return (
    <section className="panel">
      <header className="panel-header"><h2>Shadow Campaign</h2></header>
      <TruthBadge label="Forward Complete" value="NO" />
      <TruthBadge label="Empirically Validated" value="NO" />
      <p>Campaign state: {String(data.status ?? "NOT_STARTED")}</p>
      <p>Elapsed real days: {String(data.elapsed_real_calendar_days ?? 0)}</p>
    </section>
  );
}

export function ReadinessPage() {
  const readiness = useJson("/readiness");
  return (
    <section className="panel">
      <header className="panel-header"><h2>Readiness</h2></header>
      <TruthBadge label="Capital Readiness" value="INSUFFICIENT_DATA" />
      <p>Backend readiness: {JSON.stringify(readiness.data ?? {})}</p>
    </section>
  );
}
