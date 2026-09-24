import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  api,
  type Consent,
  type Dispute,
  type Engagement,
  type Page,
  type Standing,
  type WorkerView,
} from "../api";
import {
  ANSWER_LABEL,
  Card,
  ErrorNote,
  Pill,
  Status,
  TierBadge,
  availabilityText,
  date,
  dateTime,
} from "../ui";

function DisputeButton({ targetType, targetId }: { targetType: string; targetId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const file = useMutation({
    mutationFn: () =>
      api("/disputes", {
        method: "POST",
        body: { target_type: targetType, target_id: targetId, reason },
      }),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["my-disputes"] });
    },
  });
  if (!open)
    return (
      <button className="ghost small" onClick={() => setOpen(true)}>
        Dispute
      </button>
    );
  return (
    <div className="inline-form">
      <textarea
        rows={2}
        placeholder="What is wrong with this record? (at least 10 characters)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div className="row">
        <button className="small" disabled={reason.trim().length < 10 || file.isPending} onClick={() => file.mutate()}>
          File dispute
        </button>
        <button className="ghost small" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      <ErrorNote error={file.error} />
    </div>
  );
}

function Profile({ me }: { me: WorkerView }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState(me.availability_status);
  const [from, setFrom] = useState(me.available_from ?? "");
  const save = useMutation({
    mutationFn: () =>
      api("/workers/me", {
        method: "PATCH",
        body: {
          availability_status: status,
          available_from: status === "available_from" ? from || null : null,
        },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["me-worker"] }),
  });
  return (
    <Card title={me.full_name} actions={<TierBadge tier={me.standing_tier} />}>
      <p className="muted">
        {me.base_location ?? "No location"} · {me.data_region} · {me.languages?.join(", ")} ·{" "}
        {me.email}
      </p>
      <div className="chips">
        {me.skills.map((s) => (
          <Pill key={s.skill_id} tone={s.verification_status === "bonarda_verified" ? "good" : "neutral"}>
            {s.slug}
            {s.verification_status === "bonarda_verified" ? " ✓ verified" : ""}
          </Pill>
        ))}
      </div>
      <div className="row wrap top-gap">
        <label>
          Availability
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="available">Available now</option>
            <option value="available_from">Available from…</option>
            <option value="unavailable">Unavailable</option>
          </select>
        </label>
        {status === "available_from" && (
          <label>
            From
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
        )}
        <button className="small" onClick={() => save.mutate()} disabled={save.isPending}>
          Save
        </button>
        <span className="muted">
          Now: {availabilityText(me.availability_status, me.available_from)}
        </span>
      </div>
      <ErrorNote error={save.error} />
    </Card>
  );
}

function StandingCard() {
  const { data, error } = useQuery({
    queryKey: ["my-standing"],
    queryFn: () => api<Standing>("/workers/me/standing"),
  });
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;
  return (
    <Card
      title="My standing"
      actions={<span className="muted">Policy v{data.policy_version} · last {data.window_months} months</span>}
    >
      <div className="standing">
        <div>
          <TierBadge tier={data.tier} />
          {data.evaluated_tier !== data.tier && (
            <p className="muted small-text">
              The rules currently give <b>{data.evaluated_tier}</b>; your tier was set by People Ops.
            </p>
          )}
        </div>
        <dl className="factors">
          <div>
            <dt>Completed engagements</dt>
            <dd>{data.factors.completed}</dd>
          </div>
          <div>
            <dt>Distinct reviewers</dt>
            <dd>{data.factors.distinct_reviewers}</dd>
          </div>
          <div>
            <dt>Positive answers</dt>
            <dd>{Math.round(data.factors.positive_ratio * 100)}%</dd>
          </div>
        </dl>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>Tier</th>
            <th>Completed</th>
            <th>Reviewers</th>
            <th>Positive</th>
          </tr>
        </thead>
        <tbody>
          {data.tiers.map((t) => (
            <tr key={t.tier}>
              <td>
                <TierBadge tier={t.tier} />
              </td>
              <td>≥ {t.min_completed}</td>
              <td>≥ {t.min_distinct_reviewers}</td>
              <td>≥ {Math.round(t.min_positive_ratio * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>History</h3>
      {data.history.length === 0 && <p className="muted">No changes yet.</p>}
      <ul className="timeline">
        {data.history.map((c) => (
          <li key={c.id}>
            <span>
              {dateTime(c.occurred_at)}: <TierBadge tier={c.previous_tier} /> →{" "}
              <TierBadge tier={c.new_tier} />{" "}
              {c.automated ? (
                <span className="muted">rules, policy v{c.policy_version}</span>
              ) : (
                <span className="muted">People Ops: “{c.override_reason}”</span>
              )}
            </span>
            <DisputeButton targetType="standing_change" targetId={c.id} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Engagements({ workerId }: { workerId: string }) {
  const { data, error } = useQuery({
    queryKey: ["engagements", workerId],
    queryFn: () => api<Engagement[]>(`/workers/${workerId}/engagements`),
  });
  return (
    <Card title="My engagements">
      <ErrorNote error={error} />
      {data?.length === 0 && <p className="muted">No engagements yet.</p>}
      {data?.map((e) => (
        <div key={e.id} className="engagement">
          <div className="row between">
            <div>
              <b>{e.contract_terms.scope}</b>
              <p className="muted">
                {date(e.start_date)} – {date(e.end_date)} · {e.rate} {e.currency}/day ·{" "}
                {e.work_mode}
                {e.path === "reactivation" ? " · reactivation" : ""}
              </p>
            </div>
            <div className="row">
              <Status value={e.status} />
              <DisputeButton targetType="engagement" targetId={e.id} />
            </div>
          </div>
          {e.feedback && (
            <div className="feedback">
              <ul>
                {Object.entries(e.feedback.structured_answers).map(([k, v]) => (
                  <li key={k}>
                    {v ? "✓" : "✗"} {ANSWER_LABEL[k] ?? k}
                  </li>
                ))}
              </ul>
              {e.feedback.free_text && <p className="quote">“{e.feedback.free_text}”</p>}
              <DisputeButton targetType="feedback" targetId={e.feedback.id} />
            </div>
          )}
        </div>
      ))}
    </Card>
  );
}

function Consents() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["consents"],
    queryFn: () => api<Consent[]>("/workers/me/consents"),
  });
  const toggle = useMutation({
    mutationFn: (c: Consent) =>
      api(`/workers/me/consents/${c.purpose}`, { method: "PUT", body: { granted: !c.granted } }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["consents"] }),
  });
  const LABEL: Record<string, string> = {
    cross_region_matching: "Show me to projects in other regions",
    external_prefill: "Prefill my profile from external credentials",
  };
  return (
    <Card title="Consents">
      {data?.map((c) => (
        <label key={c.purpose} className="check">
          <input type="checkbox" checked={c.granted} onChange={() => toggle.mutate(c)} />
          {LABEL[c.purpose] ?? c.purpose}
        </label>
      ))}
      <ErrorNote error={toggle.error} />
    </Card>
  );
}

function MyDisputes() {
  const { data } = useQuery({
    queryKey: ["my-disputes"],
    queryFn: () => api<Page<Dispute>>("/disputes"),
  });
  return (
    <Card title="My disputes">
      {data?.items.length === 0 && <p className="muted">None filed.</p>}
      {data?.items.map((d) => (
        <div key={d.id} className="dispute">
          <div className="row between">
            <span>
              {d.target_type.replace("_", " ")} · filed {date(d.created_at)} · due {date(d.due_at)}
            </span>
            <Status value={d.resolution ?? d.status} />
          </div>
          <p className="quote">“{d.reason}”</p>
          {d.resolution_notes && <p className="muted">People Ops: {d.resolution_notes}</p>}
        </div>
      ))}
    </Card>
  );
}

export default function Passport() {
  const { data: me, error } = useQuery({
    queryKey: ["me-worker"],
    queryFn: () => api<WorkerView>("/workers/me"),
  });
  if (error) return <ErrorNote error={error} />;
  if (!me) return <p className="muted pad">Loading…</p>;
  return (
    <div className="grid-2">
      <div className="stack">
        <Profile me={me} />
        <Engagements workerId={me.id} />
      </div>
      <div className="stack">
        <StandingCard />
        <MyDisputes />
        <Consents />
      </div>
    </div>
  );
}
