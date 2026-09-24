import { Check, ClockCountdown, FileText, Gavel, ListMagnifyingGlass, SlidersHorizontal, X } from "@phosphor-icons/react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type KeyboardEvent } from "react";
import { api, type AuditEntry, type Dispute, type Page, type WorkerView } from "../api";
import { useAuth } from "../auth";
import {
  Avatar,
  Card,
  Empty,
  ErrorNote,
  Loading,
  Status,
  SuccessNote,
  TierBadge,
  date,
  dateTime,
  labelFor,
} from "../ui";

function OverrideForm({ workerId }: { workerId: string }) {
  const queryClient = useQueryClient();
  const reasonId = useId();
  const [tier, setTier] = useState("tier_1");
  const [reason, setReason] = useState("");
  const worker = useQuery({ queryKey: ["worker", workerId], queryFn: () => api<WorkerView>(`/workers/${workerId}`) });
  const save = useMutation({
    mutationFn: () => api(`/workers/${workerId}/standing-overrides`, { method: "POST", body: { tier, reason } }),
    onSuccess: () => {
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["worker", workerId] });
    },
  });
  return (
    <div className="inline-form">
      <p className="small-text row wrap">
        Current tier: {worker.data && <TierBadge tier={worker.data.standing_tier} />}
      </p>
      <div className="form-grid" style={{ margin: 0 }}>
        <label className="field">
          New tier
          <select value={tier} onChange={(e) => setTier(e.target.value)}>
            <option value="unrated">Unrated</option>
            <option value="tier_1">Tier 1</option>
            <option value="tier_2">Tier 2</option>
          </select>
        </label>
        <label className="field span-2" htmlFor={reasonId}>
          Reason <span className="hint">Required, at least 10 characters. Recorded in the audit log.</span>
          <input id={reasonId} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      </div>
      <div>
        <button className="small" disabled={reason.trim().length < 10 || save.isPending} onClick={() => save.mutate()}>
          Override tier
        </button>
      </div>
      {save.isSuccess && <SuccessNote>Tier updated. The freelancer has been notified.</SuccessNote>}
      <ErrorNote error={save.error} />
    </div>
  );
}

function DisputeCard({ dispute }: { dispute: Dispute }) {
  const queryClient = useQueryClient();
  const notesId = useId();
  const [notes, setNotes] = useState("");
  const [override, setOverride] = useState(false);
  const worker = useQuery({
    queryKey: ["worker", dispute.worker_id],
    queryFn: () => api<WorkerView>(`/workers/${dispute.worker_id}`),
  });
  const resolve = useMutation({
    mutationFn: (resolution: string) =>
      api(`/disputes/${dispute.id}`, { method: "PATCH", body: { resolution, resolution_notes: notes } }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["disputes"] }),
  });
  const overdue = new Date(dispute.due_at) < new Date();
  const name = worker.data?.full_name ?? "…";
  const target = labelFor(dispute.target_type.replace("_", "-")).toLowerCase();
  return (
    <article className="list-item">
      <div className="row between wrap">
        <div className="person">
          <Avatar name={name} />
          <div>
            <strong>{name}</strong>
            <p className="muted small-text">
              Disputes a {target} · filed {date(dispute.created_at)}
            </p>
          </div>
        </div>
        {dispute.status === "open" ? (
          <span className={overdue ? "pill pill-bad" : "pill pill-warn"}>
            <ClockCountdown size={14} aria-hidden="true" />
            {overdue ? "Overdue since" : "Due"} {date(dispute.due_at)}
          </span>
        ) : (
          <Status value={dispute.resolution ?? dispute.status} />
        )}
      </div>
      <p className="quote">{dispute.reason}</p>
      {dispute.status === "open" ? (
        <div className="stack" style={{ gap: 12 }}>
          <label className="field" htmlFor={notesId}>
            Resolution notes
            <span className="hint">Sent to the freelancer. At least 10 characters.</span>
            <textarea id={notesId} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          {dispute.target_type !== "standing_change" && (
            <p className="muted small-text">
              Upholding stops this {target === "engagement" ? "engagement's feedback" : "feedback"} counting toward
              their standing and recalculates it.
            </p>
          )}
          <div className="row wrap">
            <button className="small" disabled={notes.trim().length < 10 || resolve.isPending} onClick={() => resolve.mutate("upheld")}>
              <Check size={16} aria-hidden="true" />
              Uphold
            </button>
            <button
              className="secondary small"
              disabled={notes.trim().length < 10 || resolve.isPending}
              onClick={() => resolve.mutate("rejected")}
            >
              <X size={16} aria-hidden="true" />
              Reject
            </button>
            <button className="ghost small" aria-expanded={override} onClick={() => setOverride((v) => !v)}>
              <SlidersHorizontal size={16} aria-hidden="true" />
              Override standing
            </button>
          </div>
          {override && <OverrideForm workerId={dispute.worker_id} />}
          <ErrorNote error={resolve.error} />
        </div>
      ) : (
        dispute.resolution_notes && (
          <p className="small-text">
            <strong>Notes:</strong> {dispute.resolution_notes}
          </p>
        )
      )}
    </article>
  );
}

function Disputes() {
  const [status, setStatus] = useState("open");
  const { data, error, isLoading } = useQuery({
    queryKey: ["disputes", status],
    queryFn: () => api<Page<Dispute>>(`/disputes?status=${status}&limit=50`),
  });
  return (
    <Card
      title="Disputes"
      icon={<Gavel size={20} aria-hidden="true" />}
      subtitle="Oldest due first. Each dispute is answered within 30 days."
      actions={
        <label className="field">
          <span className="sr-only">Show</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">Open</option>
            <option value="resolved">Resolved</option>
          </select>
        </label>
      }
    >
      {isLoading && <Loading />}
      <ErrorNote error={error} />
      {data?.items.length === 0 && <Empty icon={<Gavel size={36} aria-hidden="true" />}>Nothing here.</Empty>}
      {data?.items.map((d) => <DisputeCard key={d.id} dispute={d} />)}
    </Card>
  );
}

function AuditLog() {
  const [action, setAction] = useState("");
  const query = useInfiniteQuery({
    queryKey: ["audit", action],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Page<AuditEntry>>(
        `/governance/audit-log?limit=25${action ? `&action=${encodeURIComponent(action)}` : ""}${
          pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""
        }`,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = query.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Card
      title="Audit log"
      icon={<ListMagnifyingGlass size={20} aria-hidden="true" />}
      subtitle="Every change, who made it and why, newest first."
      actions={
        <div className="search-field">
          <ListMagnifyingGlass size={18} aria-hidden="true" />
          <input
            type="search"
            aria-label="Filter by action"
            placeholder="e.g. dispute.resolved"
            value={action}
            onChange={(e) => setAction(e.target.value.trim())}
          />
        </div>
      }
    >
      {query.isLoading && <Loading lines={5} />}
      <ErrorNote error={query.error} />
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="table audit">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Action</th>
                <th scope="col">By</th>
                <th scope="col">Target</th>
                <th scope="col">Change</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="small-text num" style={{ whiteSpace: "nowrap" }}>
                    {dateTime(r.occurred_at)}
                  </td>
                  <td>
                    <code>{r.action}</code>
                  </td>
                  <td className="small-text">{(r.actor_role ?? "system").replace("_", " ")}</td>
                  <td className="small-text">
                    {r.target_type} <code>{r.target_id.slice(0, 8)}</code>
                  </td>
                  <td className="small-text">
                    {r.before && <code>{JSON.stringify(r.before)}</code>}
                    {r.before && r.after && " → "}
                    {r.after && <code>{JSON.stringify(r.after)}</code>}
                    {r.reason && <div className="muted">Reason: {r.reason}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {query.hasNextPage && (
        <button className="secondary top-gap" onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>
          {query.isFetchingNextPage ? "Loading…" : "Load more"}
        </button>
      )}
    </Card>
  );
}

type PolicyVersion = { version: number; status: string; rules: unknown; notes: string | null };

function Policies() {
  const kinds = ["tiering", "matching"] as const;
  const results = {
    tiering: useQuery({ queryKey: ["policies", "tiering"], queryFn: () => api<PolicyVersion[]>("/policies/tiering/versions") }),
    matching: useQuery({ queryKey: ["policies", "matching"], queryFn: () => api<PolicyVersion[]>("/policies/matching/versions") }),
  };
  return (
    <Card
      title="Policies"
      icon={<FileText size={20} aria-hidden="true" />}
      subtitle="Versioned rules. A new version needs a second People Ops member to activate it."
    >
      {kinds.map((kind) => (
        <section key={kind} className="list-item">
          <h3 style={{ marginTop: 0 }}>{kind}</h3>
          <ErrorNote error={results[kind].error} />
          {results[kind].data?.map((v) => (
            <details key={v.version} open={v.status === "active"}>
              <summary className="row" style={{ cursor: "pointer", minHeight: 44 }}>
                <strong>v{v.version}</strong> <Status value={v.status} />
                {v.notes && <span className="muted small-text">{v.notes}</span>}
              </summary>
              <pre>{JSON.stringify(v.rules, null, 2)}</pre>
            </details>
          ))}
        </section>
      ))}
    </Card>
  );
}

const TAB_LABEL: Record<string, string> = { disputes: "Disputes", audit: "Audit log", policies: "Policies" };

export default function Ops() {
  const { me } = useAuth();
  const tabs = me?.role === "admin" ? ["audit"] : ["disputes", "audit", "policies"];
  const [tab, setTab] = useState(tabs[0]);

  function onTabKey(event: KeyboardEvent) {
    const index = tabs.indexOf(tab);
    if (event.key === "ArrowRight") setTab(tabs[(index + 1) % tabs.length]);
    if (event.key === "ArrowLeft") setTab(tabs[(index - 1 + tabs.length) % tabs.length]);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Governance</p>
          <h1>People Ops</h1>
          <p>Disputes, standing overrides, the audit trail and the rules behind tiers and matching.</p>
        </div>
        <div className="tabs" role="tablist" aria-label="Governance sections" onKeyDown={onTabKey}>
          {tabs.map((t) => (
            <button
              key={t}
              role="tab"
              id={`tab-${t}`}
              aria-selected={t === tab}
              aria-controls={`panel-${t}`}
              tabIndex={t === tab ? 0 : -1}
              className="tab"
              onClick={() => setTab(t)}
            >
              {TAB_LABEL[t]}
            </button>
          ))}
        </div>
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "disputes" && <Disputes />}
        {tab === "audit" && <AuditLog />}
        {tab === "policies" && <Policies />}
      </div>
    </>
  );
}
