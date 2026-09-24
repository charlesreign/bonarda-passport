import {
  Briefcase,
  CalendarBlank,
  Check,
  ClockCounterClockwise,
  Flag,
  Globe,
  MapPin,
  Scales,
  ShieldCheck,
  Translate,
  X,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
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
  Avatar,
  Card,
  Empty,
  ErrorNote,
  InfoNote,
  Loading,
  SkillPill,
  Status,
  SuccessNote,
  TierBadge,
  availabilityText,
  date,
  dateTime,
  labelFor,
  useSkillNames,
} from "../ui";

function DisputeButton({ targetType, targetId, label }: { targetType: string; targetId: string; label: string }) {
  const queryClient = useQueryClient();
  const fieldId = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const file = useMutation({
    mutationFn: () =>
      api("/disputes", { method: "POST", body: { target_type: targetType, target_id: targetId, reason } }),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["my-disputes"] });
    },
  });
  if (!open)
    return (
      <>
        <button className="ghost small" onClick={() => setOpen(true)} aria-label={`Dispute ${label}`}>
          <Flag size={16} aria-hidden="true" />
          Dispute
        </button>
        {file.isSuccess && <SuccessNote>Dispute filed. People Ops will review it.</SuccessNote>}
      </>
    );
  return (
    <div className="inline-form" style={{ width: "100%" }}>
      <label className="field" htmlFor={fieldId}>
        What is wrong with this {label}?
        <span className="hint">At least 10 characters. People Ops reply within 30 days.</span>
        <textarea id={fieldId} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="row">
        <button className="small" disabled={reason.trim().length < 10 || file.isPending} onClick={() => file.mutate()}>
          File dispute
        </button>
        <button className="secondary small" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      <ErrorNote error={file.error} />
    </div>
  );
}

function Profile({ me }: { me: WorkerView }) {
  const skillName = useSkillNames();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState(me.availability_status);
  const [from, setFrom] = useState(me.available_from ?? "");
  const save = useMutation({
    mutationFn: () =>
      api("/workers/me", {
        method: "PATCH",
        body: { availability_status: status, available_from: status === "available_from" ? from || null : null },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["me-worker"] }),
  });
  return (
    <Card title="Profile" icon={<Briefcase size={20} aria-hidden="true" />}>
      <div className="meta">
        <span>
          <MapPin size={16} aria-hidden="true" />
          {me.base_location ?? "No location"}
        </span>
        <span>
          <Globe size={16} aria-hidden="true" />
          Region {me.data_region}
        </span>
        <span>
          <Translate size={16} aria-hidden="true" />
          {me.languages?.join(", ").toUpperCase()}
        </span>
      </div>
      <h3>Skills</h3>
      <div className="chips">
        {me.skills.map((s) => (
          <SkillPill key={s.skill_id} name={skillName(s.skill_id)} verified={s.verification_status === "bonarda_verified"} />
        ))}
      </div>
      <h3>Availability</h3>
      <div className="row wrap" style={{ alignItems: "flex-end" }}>
        <label className="field">
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="available">Available now</option>
            <option value="available_from">Available from a date</option>
            <option value="unavailable">Unavailable</option>
          </select>
        </label>
        {status === "available_from" && (
          <label className="field">
            From
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
        )}
        <button className="secondary" onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </div>
      <p className="muted small-text top-gap">
        Project managers see: {availabilityText(me.availability_status, me.available_from)}
      </p>
      <ErrorNote error={save.error} />
    </Card>
  );
}

function StandingCard() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["my-standing"],
    queryFn: () => api<Standing>("/workers/me/standing"),
  });
  return (
    <Card
      title="My standing"
      icon={<ShieldCheck size={20} aria-hidden="true" />}
      subtitle={data && `Policy v${data.policy_version} · feedback from the last ${data.window_months} months`}
    >
      {isLoading && <Loading />}
      <ErrorNote error={error} />
      {data && (
        <>
          <div className="standing-hero">
            <TierBadge tier={data.tier} large />
            <dl className="stats">
              <div className="stat">
                <dt>Completed</dt>
                <dd>{data.factors.completed}</dd>
              </div>
              <div className="stat">
                <dt>Reviewers</dt>
                <dd>{data.factors.distinct_reviewers}</dd>
              </div>
              <div className="stat">
                <dt>Positive</dt>
                <dd>{Math.round(data.factors.positive_ratio * 100)}%</dd>
              </div>
            </dl>
          </div>
          {data.evaluated_tier !== data.tier && (
            <div className="top-gap">
              <InfoNote>
                The rules currently give {data.evaluated_tier.replace("_", " ")}; People Ops set your
                tier by hand.
              </InfoNote>
            </div>
          )}
          <h3>How tiers are earned</h3>
          <div>
            <table className="table compact">
              <thead>
                <tr>
                  <th scope="col">Tier</th>
                  <th scope="col">Completed</th>
                  <th scope="col">Reviewers</th>
                  <th scope="col">Positive</th>
                </tr>
              </thead>
              <tbody>
                {data.tiers.map((t) => (
                  <tr key={t.tier}>
                    <td>
                      <TierBadge tier={t.tier} short />
                    </td>
                    <td className="num">≥ {t.min_completed}</td>
                    <td className="num">≥ {t.min_distinct_reviewers}</td>
                    <td className="num">≥ {Math.round(t.min_positive_ratio * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>History</h3>
          {data.history.length === 0 ? (
            <p className="muted">No changes yet.</p>
          ) : (
            <ul className="timeline">
              {data.history.map((c) => (
                <li key={c.id}>
                  <div>
                    <div className="row wrap">
                      <TierBadge tier={c.previous_tier} />
                      <span aria-label="to">→</span>
                      <TierBadge tier={c.new_tier} />
                    </div>
                    <p className="muted small-text">
                      {dateTime(c.occurred_at)} ·{" "}
                      {c.automated ? `rules, policy v${c.policy_version}` : `People Ops: “${c.override_reason}”`}
                    </p>
                  </div>
                  <DisputeButton targetType="standing_change" targetId={c.id} label="standing change" />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}

function Engagements({ workerId }: { workerId: string }) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["engagements", workerId],
    queryFn: () => api<Engagement[]>(`/workers/${workerId}/engagements`),
  });
  return (
    <Card title="Engagements" icon={<ClockCounterClockwise size={20} aria-hidden="true" />}>
      {isLoading && <Loading />}
      <ErrorNote error={error} />
      {data?.length === 0 && (
        <Empty icon={<Briefcase size={40} aria-hidden="true" />}>No engagements yet.</Empty>
      )}
      {data?.map((e) => (
        <article key={e.id} className="list-item">
          <div className="row between wrap">
            <div>
              <strong>{e.contract_terms.scope}</strong>
              <div className="meta">
                <span>
                  <CalendarBlank size={16} aria-hidden="true" />
                  {date(e.start_date)} – {date(e.end_date)}
                </span>
                <span className="num">
                  {e.rate} {e.currency}/day
                </span>
                <span>{e.work_mode}</span>
                {e.path === "reactivation" && <span>Reactivation</span>}
              </div>
            </div>
            <div className="row">
              <Status value={e.status} />
              <DisputeButton targetType="engagement" targetId={e.id} label="engagement" />
            </div>
          </div>
          {e.feedback && (
            <div className="feedback panel-soft">
              <ul className="answers">
                {Object.entries(e.feedback.structured_answers).map(([k, v]) => (
                  <li key={k}>
                    {v ? (
                      <Check size={16} weight="bold" className="yes" aria-label="Yes" />
                    ) : (
                      <X size={16} weight="bold" className="no" aria-label="No" />
                    )}
                    {ANSWER_LABEL[k] ?? k}
                  </li>
                ))}
              </ul>
              {e.feedback.free_text && <p className="quote">{e.feedback.free_text}</p>}
              <DisputeButton targetType="feedback" targetId={e.feedback.id} label="feedback" />
            </div>
          )}
        </article>
      ))}
    </Card>
  );
}

function Consents() {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["consents"], queryFn: () => api<Consent[]>("/workers/me/consents") });
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
    <Card title="Privacy" subtitle="You can change these at any time.">
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
  const { data } = useQuery({ queryKey: ["my-disputes"], queryFn: () => api<Page<Dispute>>("/disputes") });
  return (
    <Card title="My disputes" icon={<Scales size={20} aria-hidden="true" />}>
      {data?.items.length === 0 && <p className="muted">None filed. Use “Dispute” on any record you think is wrong.</p>}
      {data?.items.map((d) => (
        <article key={d.id} className="list-item">
          <div className="row between wrap">
            <strong>{labelFor(d.target_type.replace("_", "-"))}</strong>
            <Status value={d.resolution ?? d.status} />
          </div>
          <p className="muted small-text">
            Filed {date(d.created_at)} · reply due {date(d.due_at)}
          </p>
          <p className="quote">{d.reason}</p>
          {d.resolution_notes && (
            <p className="small-text">
              <strong>People Ops:</strong> {d.resolution_notes}
            </p>
          )}
        </article>
      ))}
    </Card>
  );
}

export default function Passport() {
  const { data: me, error } = useQuery({ queryKey: ["me-worker"], queryFn: () => api<WorkerView>("/workers/me") });
  if (error) return <ErrorNote error={error} />;
  if (!me) return <Loading lines={4} />;
  return (
    <>
      <div className="page-head">
        <div className="person">
          <Avatar name={me.full_name} large />
          <div>
            <p className="eyebrow">My passport</p>
            <h1>{me.full_name}</h1>
            <p>{availabilityText(me.availability_status, me.available_from)}</p>
          </div>
        </div>
        <TierBadge tier={me.standing_tier} large />
      </div>
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
    </>
  );
}
