import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type AuditEntry, type Dispute, type Page, type WorkerView } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorNote, Status, TierBadge, date, dateTime } from "../ui";

function OverrideForm({ workerId }: { workerId: string }) {
  const queryClient = useQueryClient();
  const [tier, setTier] = useState("tier_1");
  const [reason, setReason] = useState("");
  const worker = useQuery({
    queryKey: ["worker", workerId],
    queryFn: () => api<WorkerView>(`/workers/${workerId}`),
  });
  const save = useMutation({
    mutationFn: () =>
      api(`/workers/${workerId}/standing-overrides`, { method: "POST", body: { tier, reason } }),
    onSuccess: () => {
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["worker", workerId] });
    },
  });
  return (
    <div className="inline-form">
      <p className="small-text">
        {worker.data?.full_name}: currently {worker.data && <TierBadge tier={worker.data.standing_tier} />}
      </p>
      <div className="row wrap">
        <select value={tier} onChange={(e) => setTier(e.target.value)}>
          <option value="unrated">Unrated</option>
          <option value="tier_1">Tier 1</option>
          <option value="tier_2">Tier 2</option>
        </select>
        <input
          className="grow"
          placeholder="Reason (required, at least 10 characters)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <button className="small" disabled={reason.trim().length < 10} onClick={() => save.mutate()}>
          Override tier
        </button>
      </div>
      {save.isSuccess && <p className="ok">Tier updated.</p>}
      <ErrorNote error={save.error} />
    </div>
  );
}

function DisputeCard({ dispute }: { dispute: Dispute }) {
  const queryClient = useQueryClient();
  const [notes, setNotes] = useState("");
  const [override, setOverride] = useState(false);
  const worker = useQuery({
    queryKey: ["worker", dispute.worker_id],
    queryFn: () => api<WorkerView>(`/workers/${dispute.worker_id}`),
  });
  const resolve = useMutation({
    mutationFn: (resolution: string) =>
      api(`/disputes/${dispute.id}`, {
        method: "PATCH",
        body: { resolution, resolution_notes: notes },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["disputes"] }),
  });
  const overdue = new Date(dispute.due_at) < new Date();
  return (
    <div className="dispute">
      <div className="row between">
        <span>
          <b>{worker.data?.full_name ?? "…"}</b> disputes a{" "}
          <b>{dispute.target_type.replace("_", " ")}</b> · filed {date(dispute.created_at)}
        </span>
        {dispute.status === "open" ? (
          <span className={overdue ? "pill pill-bad" : "pill pill-warn"}>
            {overdue ? "Overdue" : "Due"} {date(dispute.due_at)}
          </span>
        ) : (
          <Status value={dispute.resolution ?? dispute.status} />
        )}
      </div>
      <p className="quote">“{dispute.reason}”</p>
      {dispute.status === "open" ? (
        <>
          <textarea
            rows={2}
            placeholder="Resolution notes; the freelancer receives these (at least 10 characters)"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div className="row wrap">
            <button className="small" disabled={notes.trim().length < 10} onClick={() => resolve.mutate("upheld")}>
              Uphold
            </button>
            <button className="small danger" disabled={notes.trim().length < 10} onClick={() => resolve.mutate("rejected")}>
              Reject
            </button>
            <button className="small ghost" onClick={() => setOverride((v) => !v)}>
              Override standing…
            </button>
          </div>
          {dispute.target_type === "feedback" && (
            <p className="muted small-text">
              Upholding excludes this feedback from the freelancer's standing and recalculates it.
            </p>
          )}
          {override && <OverrideForm workerId={dispute.worker_id} />}
          <ErrorNote error={resolve.error} />
        </>
      ) : (
        dispute.resolution_notes && <p className="muted">Notes: {dispute.resolution_notes}</p>
      )}
    </div>
  );
}

function Disputes() {
  const [status, setStatus] = useState("open");
  const { data, error } = useQuery({
    queryKey: ["disputes", status],
    queryFn: () => api<Page<Dispute>>(`/disputes?status=${status}&limit=50`),
  });
  return (
    <Card
      title="Disputes"
      actions={
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
        </select>
      }
    >
      <ErrorNote error={error} />
      {data?.items.length === 0 && <p className="muted">Nothing here.</p>}
      {data?.items.map((d) => (
        <DisputeCard key={d.id} dispute={d} />
      ))}
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
      actions={
        <input
          className="search"
          placeholder="Filter by action, e.g. dispute.resolved"
          value={action}
          onChange={(e) => setAction(e.target.value.trim())}
        />
      }
    >
      <ErrorNote error={query.error} />
      <table className="table audit">
        <thead>
          <tr>
            <th>When</th>
            <th>Action</th>
            <th>Actor</th>
            <th>Target</th>
            <th>Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="small-text">{dateTime(r.occurred_at)}</td>
              <td>
                <code>{r.action}</code>
              </td>
              <td className="small-text">{r.actor_role ?? "system"}</td>
              <td className="small-text">
                {r.target_type} {r.target_id.slice(0, 8)}
              </td>
              <td className="small-text">
                {r.before && <code>{JSON.stringify(r.before)}</code>}
                {r.before && r.after && " → "}
                {r.after && <code>{JSON.stringify(r.after)}</code>}
                {r.reason && <div className="muted">reason: {r.reason}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {query.hasNextPage && (
        <button className="ghost" onClick={() => void query.fetchNextPage()}>
          Load more
        </button>
      )}
    </Card>
  );
}

function Policies() {
  const tiering = useQuery({
    queryKey: ["policies", "tiering"],
    queryFn: () => api<{ version: number; status: string; rules: unknown; notes: string | null }[]>("/policies/tiering/versions"),
  });
  const matching = useQuery({
    queryKey: ["policies", "matching"],
    queryFn: () => api<{ version: number; status: string; rules: unknown; notes: string | null }[]>("/policies/matching/versions"),
  });
  return (
    <Card title="Policies">
      <p className="muted small-text">
        Versioned rules; a new version needs a second People Ops member to activate it.
      </p>
      {[
        ["Tiering", tiering.data],
        ["Matching", matching.data],
      ].map(([label, versions]) => (
        <details key={label as string}>
          <summary>{label as string}</summary>
          {(versions as { version: number; status: string; rules: unknown }[] | undefined)?.map((v) => (
            <div key={v.version}>
              <p>
                v{v.version} <Status value={v.status} />
              </p>
              <pre>{JSON.stringify(v.rules, null, 2)}</pre>
            </div>
          ))}
        </details>
      ))}
    </Card>
  );
}

export default function Ops() {
  const { me } = useAuth();
  const [tab, setTab] = useState(me?.role === "admin" ? "audit" : "disputes");
  const tabs = me?.role === "admin" ? ["audit"] : ["disputes", "audit", "policies"];
  return (
    <div className="stack">
      <div className="tabs">
        {tabs.map((t) => (
          <button key={t} className={t === tab ? "tab active" : "tab"} onClick={() => setTab(t)}>
            {t === "disputes" ? "Disputes" : t === "audit" ? "Audit log" : "Policies"}
          </button>
        ))}
      </div>
      {tab === "disputes" && <Disputes />}
      {tab === "audit" && <AuditLog />}
      {tab === "policies" && <Policies />}
    </div>
  );
}
