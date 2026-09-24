import { ArrowsClockwise, CalendarBlank, Check, HourglassMedium, MapPin, UserPlus, X } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  ApiError,
  api,
  type Engagement,
  type Prefill,
  type Project,
  type Standing,
  type WorkerView,
} from "../api";
import {
  ANSWER_LABEL,
  Avatar,
  ErrorNote,
  InfoNote,
  Loading,
  SkillPill,
  Status,
  SuccessNote,
  TierBadge,
  availabilityText,
  date,
  useSkillNames,
} from "../ui";

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
  const set = (key: string) => (e: { target: { value: string } }) => setOverrides((o) => ({ ...o, [key]: e.target.value }));

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
        ...(reactivating ? { prefilled_from_engagement_id: prefill.data!.prefilled_from_engagement_id } : {}),
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
      for (const key of [["worker", worker.id], ["engagements", worker.id], ["candidates", project.id], ["first-shot", project.id]])
        void queryClient.invalidateQueries({ queryKey: key });
    },
  });

  if (prefill.isLoading) return <Loading lines={2} />;
  if (!reactivating && !firstTime) return <ErrorNote error={prefill.error} />;
  return (
    <section className="drawer-section" aria-labelledby="engage-heading">
      <h2 id="engage-heading" className="row">
        {reactivating ? <ArrowsClockwise size={20} aria-hidden="true" /> : <UserPlus size={20} aria-hidden="true" />}
        {reactivating ? "Reactivate" : "Engage for the first time"}
      </h2>
      {reactivating && (
        <p className="muted small-text top-gap">
          Terms prefilled from their last engagement
          {prefill.data?.last_days_to_start != null && ` · last time to start: ${prefill.data.last_days_to_start.toFixed(1)} days`}.
        </p>
      )}
      <div className="form-grid">
        <label className="field">
          Start date
          <input type="date" value={terms.start_date} onChange={set("start_date")} />
        </label>
        <label className="field">
          Day rate
          <input inputMode="decimal" value={terms.rate} onChange={set("rate")} />
        </label>
        <label className="field">
          Currency
          <input value={terms.currency} onChange={set("currency")} maxLength={3} />
        </label>
        <label className="field">
          Work mode
          <select value={terms.work_mode} onChange={set("work_mode")}>
            <option value="remote">Remote</option>
            <option value="hybrid">Hybrid</option>
            <option value="onsite">On site</option>
          </select>
        </label>
        <label className="field span-2">
          Scope
          <input value={terms.scope} onChange={set("scope")} />
        </label>
      </div>
      {submit.isSuccess ? (
        <SuccessNote>Engagement recorded. The contract is on its way to {worker.full_name}.</SuccessNote>
      ) : (
        <button onClick={() => submit.mutate()} disabled={submit.isPending}>
          {submit.isPending ? "Sending…" : "Confirm and send contract"}
        </button>
      )}
      <ErrorNote error={submit.error} />
    </section>
  );
}

function FeedbackForm({ engagement, onDone }: { engagement: Engagement; onDone: () => void }) {
  const noteId = useId();
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
    <fieldset className="inline-form" style={{ border: 0 }}>
      <legend className="small-text" style={{ fontWeight: 600 }}>
        Feedback (all three questions are required)
      </legend>
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
      <label className="field" htmlFor={noteId}>
        Note <span className="hint">Optional. The freelancer can read it.</span>
        <textarea id={noteId} rows={2} value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <button className="small" onClick={() => submit.mutate()} disabled={submit.isPending}>
        Submit feedback
      </button>
      <ErrorNote error={submit.error} />
    </fieldset>
  );
}

function EngagementRow({ engagement, project }: { engagement: Engagement; project: Project }) {
  const queryClient = useQueryClient();
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["engagements", engagement.worker_id] });
    void queryClient.invalidateQueries({ queryKey: ["worker", engagement.worker_id] });
  };
  const complete = useMutation({
    mutationFn: () => api(`/engagements/${engagement.id}/complete`, { method: "POST", body: {} }),
    onSuccess: refresh,
  });
  const mine = engagement.project_id === project.id;
  return (
    <article className="list-item">
      <div className="row between wrap">
        <div>
          <strong>{engagement.contract_terms.scope}</strong>
          <div className="meta">
            <span>
              <CalendarBlank size={16} aria-hidden="true" />
              {date(engagement.start_date)} – {date(engagement.end_date)}
            </span>
            <span className="num">
              {engagement.rate} {engagement.currency}
            </span>
            <span>{engagement.path.replace("_", " ")}</span>
          </div>
        </div>
        <Status value={engagement.status} />
      </div>
      {mine && (
        <div className="fs-actions">
          {engagement.status === "pending_signature" && (
            <span className="muted small-text row" role="status">
              <HourglassMedium size={16} aria-hidden="true" />
              Sending the contract…
            </span>
          )}
          {engagement.status === "awaiting_signature" && (
            <span className="muted small-text row" role="status">
              <HourglassMedium size={16} aria-hidden="true" />
              Awaiting the freelancer's signature. This updates by itself once they sign.
            </span>
          )}
          {engagement.status === "active" && (
            <button className="small" onClick={() => complete.mutate()} disabled={complete.isPending}>
              <Check size={16} aria-hidden="true" />
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
        <p className="muted small-text top-gap">
          Feedback: {Object.values(engagement.feedback.structured_answers).filter(Boolean).length} of 3 positive
          {engagement.feedback.free_text ? ` · “${engagement.feedback.free_text}”` : ""}
        </p>
      )}
      <ErrorNote error={complete.error} />
    </article>
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
  const titleId = useId();
  const skillName = useSkillNames();
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => opener?.focus();
  }, []);

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      onClose();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])',
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }

  const worker = useQuery({ queryKey: ["worker", workerId], queryFn: () => api<WorkerView>(`/workers/${workerId}`) });
  const detail = worker.data?.view === "detail";
  const engagements = useQuery({
    queryKey: ["engagements", workerId],
    queryFn: () => api<Engagement[]>(`/workers/${workerId}/engagements`),
    enabled: detail,
    refetchInterval: (query) => (query.state.data?.some((e) => IN_FLIGHT.includes(e.status)) ? 2000 : false),
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
      <aside
        ref={dialogRef}
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="drawer-head">
          {w ? (
            <div className="person">
              <Avatar name={w.full_name} large />
              <div>
                <h2 id={titleId}>{w.full_name}</h2>
                <div className="meta">
                  <span>
                    <MapPin size={16} aria-hidden="true" />
                    {w.base_location} · {w.data_region}
                  </span>
                  <span>{availabilityText(w.availability_status, w.available_from)}</span>
                </div>
              </div>
            </div>
          ) : (
            <h2 id={titleId}>Freelancer</h2>
          )}
          <button ref={closeRef} className="secondary icon-btn" onClick={onClose} aria-label="Close">
            <X size={20} aria-hidden="true" />
          </button>
        </div>
        {worker.isLoading && <Loading />}
        <ErrorNote error={worker.error} />
        {w && (
          <>
            <div className="row wrap">
              <TierBadge tier={w.standing_tier} />
              <span className="pill">{detail ? "Detail view" : "Summary view"}</span>
            </div>
            <div className="chips top-gap">
              {w.skills.map((s) => (
                <SkillPill key={s.skill_id} name={skillName(s.skill_id)} verified={s.verification_status === "bonarda_verified"} />
              ))}
            </div>
            {!detail && (
              <div className="top-gap">
                <InfoNote>
                  History and feedback appear once you shortlist or engage this person on one of your projects.
                </InfoNote>
              </div>
            )}
            {standing.data && (
              <dl className="stats top-gap">
                <div className="stat">
                  <dt>Completed</dt>
                  <dd>{standing.data.factors.completed}</dd>
                </div>
                <div className="stat">
                  <dt>Reviewers</dt>
                  <dd>{standing.data.factors.distinct_reviewers}</dd>
                </div>
                <div className="stat">
                  <dt>Positive</dt>
                  <dd>{Math.round(standing.data.factors.positive_ratio * 100)}%</dd>
                </div>
              </dl>
            )}
            {!openEngagement && <EngageForm worker={w} project={project} />}
            {detail && (
              <section className="drawer-section" aria-labelledby="eng-heading">
                <h2 id="eng-heading">Engagements</h2>
                {engagements.data?.length === 0 && <p className="muted top-gap">None yet.</p>}
                <div className="top-gap">
                  {engagements.data?.map((e) => (
                    <EngagementRow key={e.id} engagement={e} project={project} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
