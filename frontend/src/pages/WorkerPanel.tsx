import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  ApiError,
  api,
  type Engagement,
  type Prefill,
  type Project,
  type Standing,
  type WorkerView,
} from "../api";
import { ANSWER_LABEL, ErrorNote, Pill, Status, TierBadge, availabilityText, date } from "../ui";

const IN_FLIGHT = ["pending_signature", "awaiting_signature"];

function EngageForm({ worker, project }: { worker: WorkerView; project: Project }) {
  const queryClient = useQueryClient();
  const idempotencyKey = useMemo(() => crypto.randomUUID(), []);
  const prefill = useQuery({
    queryKey: ["prefill", worker.id, project.id],
    queryFn: () => api<Prefill>(`/workers/${worker.id}/reactivation-prefill?project_id=${project.id}`),
    retry: false,
  });
  const reactivating = prefill.isSuccess;
  const firstTime = prefill.error instanceof ApiError && prefill.error.code === "no_prior_engagement";
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const terms = {
    // Today, so a signed contract activates at once in the demo; editable.
    start_date: new Date().toISOString().slice(0, 10),
    rate: prefill.data?.rate ?? (project.data_region === "EU" ? "380.00" : "450.00"),
    currency: prefill.data?.currency ?? (project.data_region === "EU" ? "EUR" : "GHS"),
    work_mode: prefill.data?.work_mode ?? "remote",
    scope: prefill.data?.contract_terms.scope ?? `${project.name}: analysis work`,
    ...overrides,
  };
  const set = (key: string) => (e: { target: { value: string } }) =>
    setOverrides((o) => ({ ...o, [key]: e.target.value }));

  const submit = useMutation({
    mutationFn: () => {
      const body = {
        project_id: project.id,
        start_date: terms.start_date,
        rate: terms.rate,
        currency: terms.currency,
        work_mode: terms.work_mode,
        location: null,
        contract_terms: { scope: terms.scope, access_notes: null },
        ...(reactivating
          ? { prefilled_from_engagement_id: prefill.data!.prefilled_from_engagement_id }
          : {}),
      };
      return reactivating
        ? api<Engagement>(`/workers/${worker.id}/reactivations`, {
            method: "POST",
            body,
            headers: { "Idempotency-Key": idempotencyKey },
          })
        : api<Engagement>(`/workers/${worker.id}/engagements`, { method: "POST", body });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["worker", worker.id] });
      void queryClient.invalidateQueries({ queryKey: ["engagements", worker.id] });
      void queryClient.invalidateQueries({ queryKey: ["candidates", project.id] });
      void queryClient.invalidateQueries({ queryKey: ["first-shot", project.id] });
    },
  });

  if (prefill.isLoading) return <p className="muted">Loading terms…</p>;
  if (!reactivating && !firstTime) return <ErrorNote error={prefill.error} />;
  return (
    <div className="engage">
      <h3>{reactivating ? "Reactivate" : "Engage for the first time"}</h3>
      {reactivating && (
        <p className="muted small-text">
          Terms prefilled from their last engagement
          {prefill.data?.last_days_to_start != null &&
            ` · last time-to-start ${prefill.data.last_days_to_start.toFixed(1)} days`}
          .
        </p>
      )}
      <div className="form-grid">
        <label>
          Start
          <input type="date" value={terms.start_date} onChange={set("start_date")} />
        </label>
        <label>
          Day rate
          <input value={terms.rate} onChange={set("rate")} />
        </label>
        <label>
          Currency
          <input value={terms.currency} onChange={set("currency")} maxLength={3} />
        </label>
        <label>
          Mode
          <select value={terms.work_mode} onChange={set("work_mode")}>
            <option value="remote">remote</option>
            <option value="hybrid">hybrid</option>
            <option value="onsite">onsite</option>
          </select>
        </label>
        <label className="span-2">
          Scope
          <input value={terms.scope} onChange={set("scope")} />
        </label>
      </div>
      <button onClick={() => submit.mutate()} disabled={submit.isPending || submit.isSuccess}>
        {submit.isSuccess ? "Sent for signature ✓" : "Confirm and send contract"}
      </button>
      <ErrorNote error={submit.error} />
    </div>
  );
}

function FeedbackForm({ engagement, onDone }: { engagement: Engagement; onDone: () => void }) {
  const [answers, setAnswers] = useState<Record<string, boolean>>({
    delivered_on_agreed_dates: true,
    handled_scope_changes_without_escalation: true,
    would_reengage: true,
  });
  const [text, setText] = useState("");
  const submit = useMutation({
    mutationFn: () =>
      api(`/engagements/${engagement.id}/feedback`, {
        method: "POST",
        body: { structured_answers: answers, free_text: text || null, skill_ids_demonstrated: [] },
      }),
    onSuccess: onDone,
  });
  return (
    <div className="inline-form">
      {Object.keys(answers).map((key) => (
        <label key={key} className="check">
          <input
            type="checkbox"
            checked={answers[key]}
            onChange={(e) => setAnswers((a) => ({ ...a, [key]: e.target.checked }))}
          />
          {ANSWER_LABEL[key]}
        </label>
      ))}
      <textarea rows={2} placeholder="Optional note (the freelancer can read it)" value={text} onChange={(e) => setText(e.target.value)} />
      <button className="small" onClick={() => submit.mutate()} disabled={submit.isPending}>
        Submit feedback
      </button>
      <ErrorNote error={submit.error} />
    </div>
  );
}

function EngagementRow({ engagement, project }: { engagement: Engagement; project: Project }) {
  const queryClient = useQueryClient();
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["engagements", engagement.worker_id] });
    void queryClient.invalidateQueries({ queryKey: ["worker", engagement.worker_id] });
  };
  const sign = useMutation({
    mutationFn: () => api(`/demo/engagements/${engagement.id}/sign`, { method: "POST" }),
    onSuccess: refresh,
  });
  const complete = useMutation({
    mutationFn: () => api(`/engagements/${engagement.id}/complete`, { method: "POST", body: {} }),
    onSuccess: refresh,
  });
  const mine = engagement.project_id === project.id;
  return (
    <div className="engagement">
      <div className="row between">
        <div>
          <b>{engagement.contract_terms.scope}</b>
          <p className="muted small-text">
            {date(engagement.start_date)} – {date(engagement.end_date)} · {engagement.rate}{" "}
            {engagement.currency} · {engagement.path.replace("_", " ")}
          </p>
        </div>
        <Status value={engagement.status} />
      </div>
      {mine && (
        <div className="row wrap">
          {engagement.status === "awaiting_signature" && (
            <button className="small" onClick={() => sign.mutate()}>
              Simulate freelancer signature
            </button>
          )}
          {engagement.status === "pending_signature" && (
            <span className="muted small-text">Sending the contract…</span>
          )}
          {engagement.status === "active" && (
            <button className="small" onClick={() => complete.mutate()}>
              Mark completed
            </button>
          )}
          {engagement.status === "completed" && !engagement.feedback && !feedbackOpen && (
            <button className="small" onClick={() => setFeedbackOpen(true)}>
              Give feedback
            </button>
          )}
        </div>
      )}
      {feedbackOpen && (
        <FeedbackForm
          engagement={engagement}
          onDone={() => {
            setFeedbackOpen(false);
            refresh();
          }}
        />
      )}
      {engagement.feedback && (
        <p className="muted small-text">
          Feedback:{" "}
          {Object.values(engagement.feedback.structured_answers).filter(Boolean).length}/3 positive
          {engagement.feedback.free_text ? ` · “${engagement.feedback.free_text}”` : ""}
        </p>
      )}
      <ErrorNote error={sign.error ?? complete.error} />
    </div>
  );
}

export default function WorkerPanel({
  workerId,
  project,
  onClose,
}: {
  workerId: string;
  project: Project;
  onClose: () => void;
}) {
  const worker = useQuery({
    queryKey: ["worker", workerId],
    queryFn: () => api<WorkerView>(`/workers/${workerId}`),
  });
  const detail = worker.data?.view === "detail";
  const engagements = useQuery({
    queryKey: ["engagements", workerId],
    queryFn: () => api<Engagement[]>(`/workers/${workerId}/engagements`),
    enabled: detail,
    refetchInterval: (query) =>
      query.state.data?.some((e) => IN_FLIGHT.includes(e.status)) ? 2000 : false,
  });
  const standing = useQuery({
    queryKey: ["standing", workerId],
    queryFn: () => api<Standing>(`/workers/${workerId}/standing`),
    enabled: detail,
  });
  const w = worker.data;
  const openEngagement = engagements.data?.some(
    (e) => e.project_id === project.id && !["completed", "cancelled"].includes(e.status),
  );
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <button className="ghost close" onClick={onClose}>
          ✕
        </button>
        <ErrorNote error={worker.error} />
        {w && (
          <>
            <h2>{w.full_name}</h2>
            <p className="muted">
              {w.base_location} · {w.data_region} ·{" "}
              {availabilityText(w.availability_status, w.available_from)}
            </p>
            <div className="row">
              <TierBadge tier={w.standing_tier} />
              <Pill>{w.view === "detail" ? "Detail view" : "Summary view"}</Pill>
            </div>
            <div className="chips top-gap">
              {w.skills.map((s) => (
                <Pill key={s.skill_id} tone={s.verification_status === "bonarda_verified" ? "good" : "neutral"}>
                  {s.slug}
                  {s.verification_status === "bonarda_verified" ? " ✓" : ""}
                </Pill>
              ))}
            </div>
            {!detail && (
              <p className="muted small-text top-gap">
                History and feedback appear once you shortlist or engage this person on one of your
                projects.
              </p>
            )}
            {standing.data && (
              <p className="small-text top-gap">
                Standing: {standing.data.factors.completed} completed ·{" "}
                {standing.data.factors.distinct_reviewers} reviewers ·{" "}
                {Math.round(standing.data.factors.positive_ratio * 100)}% positive (policy v
                {standing.data.policy_version})
              </p>
            )}
            {!openEngagement && <EngageForm worker={w} project={project} />}
            {detail && (
              <>
                <h3>Engagements</h3>
                {engagements.data?.length === 0 && <p className="muted">None yet.</p>}
                {engagements.data?.map((e) => (
                  <EngagementRow key={e.id} engagement={e} project={project} />
                ))}
              </>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
