import { ArrowsClockwise, CalendarBlank, Check, HourglassMedium, MapPin, UserPlus, X } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  ApiError,
  api,
  type DisputeStatusRead,
  type Engagement,
  type Prefill,
  type Project,
  type Standing,
  type WorkerView,
} from "../api";
import { useAuth } from "../auth";
import { currentLanguage } from "../i18n";
import {
  Avatar,
  ErrorNote,
  InfoNote,
  Loading,
  SkillPill,
  Status,
  SuccessNote,
  TierBadge,
  answerLabel,
  availabilityText,
  DeclineSummary,
  date,
  money,
  percent,
  useSkillNames,
} from "../ui";

const IN_FLIGHT = ["pending_signature", "awaiting_signature"];

function EngageForm({ worker, project }: { worker: WorkerView; project: Project }) {
  const { t } = useTranslation();
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
    scope: prefill.data?.contract_terms.scope ?? t("engage.defaultScope", { project: project.name }),
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
  const lastDays = prefill.data?.last_days_to_start;
  return (
    <section className="drawer-section" aria-labelledby="engage-heading">
      <h2 id="engage-heading" className="row">
        {reactivating ? <ArrowsClockwise size={20} aria-hidden="true" /> : <UserPlus size={20} aria-hidden="true" />}
        {reactivating ? t("engage.reactivate") : t("engage.firstTime")}
      </h2>
      {reactivating && (
        <p className="muted small-text top-gap">
          {t("engage.prefilled")}
          {lastDays != null &&
            ` · ${t("engage.lastTimeToStart", {
              days: new Intl.NumberFormat(currentLanguage(), { maximumFractionDigits: 1 }).format(lastDays),
            })}`}
        </p>
      )}
      <div className="form-grid">
        <label className="field">
          {t("engage.startDate")}
          <input type="date" value={terms.start_date} onChange={set("start_date")} />
        </label>
        <label className="field">
          {t("engage.dayRate")}
          <input inputMode="decimal" value={terms.rate} onChange={set("rate")} />
        </label>
        <label className="field">
          {t("engage.currency")}
          <input value={terms.currency} onChange={set("currency")} maxLength={3} />
        </label>
        <label className="field">
          {t("engagement.mode")}
          <select value={terms.work_mode} onChange={set("work_mode")}>
            <option value="remote">{t("workMode.remote")}</option>
            <option value="hybrid">{t("workMode.hybrid")}</option>
            <option value="onsite">{t("workMode.onsite")}</option>
          </select>
        </label>
        <label className="field span-2">
          {t("engagement.scope")}
          <input value={terms.scope} onChange={set("scope")} />
        </label>
      </div>
      {submit.isSuccess ? (
        <SuccessNote>{t("engage.sent", { name: worker.full_name })}</SuccessNote>
      ) : (
        <button onClick={() => submit.mutate()} disabled={submit.isPending}>
          {submit.isPending ? t("engage.sending") : t("engage.confirm")}
        </button>
      )}
      <ErrorNote error={submit.error} />
    </section>
  );
}

function FeedbackForm({ engagement, onDone }: { engagement: Engagement; onDone: () => void }) {
  const { t } = useTranslation();
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
        {t("feedback.legend")}
      </legend>
      {Object.keys(answers).map((key) => (
        <label key={key} className="check">
          <input
            type="checkbox"
            checked={answers[key]}
            onChange={(e) => setAnswers((a) => ({ ...a, [key]: e.target.checked }))}
          />
          {answerLabel(key)}
        </label>
      ))}
      <label className="field" htmlFor={noteId}>
        {t("feedback.note")} <span className="hint">{t("feedback.noteHint")}</span>
        <textarea id={noteId} rows={2} value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <button className="small" onClick={() => submit.mutate()} disabled={submit.isPending}>
        {t("feedback.submit")}
      </button>
      <ErrorNote error={submit.error} />
    </fieldset>
  );
}

function EngagementRow({ engagement, project }: { engagement: Engagement; project: Project }) {
  const { t } = useTranslation();
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
  const positive = engagement.feedback
    ? Object.values(engagement.feedback.structured_answers).filter(Boolean).length
    : 0;
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
            <span className="num">{money(engagement.rate, engagement.currency)}</span>
            <span>{t(`engagement.path.${engagement.path}`)}</span>
          </div>
        </div>
        <Status value={engagement.status} />
      </div>
      {mine && (
        <div className="fs-actions">
          {engagement.status === "pending_signature" && (
            <span className="muted small-text row" role="status">
              <HourglassMedium size={16} aria-hidden="true" />
              {t("engagement.sending")}
            </span>
          )}
          {engagement.status === "awaiting_signature" && (
            <span className="muted small-text row" role="status">
              <HourglassMedium size={16} aria-hidden="true" />
              {t("engagement.awaiting")}
            </span>
          )}
          {engagement.status === "active" && (
            <button className="small" onClick={() => complete.mutate()} disabled={complete.isPending}>
              <Check size={16} aria-hidden="true" />
              {t("engagement.complete")}
            </button>
          )}
          {engagement.status === "completed" && !engagement.feedback && !feedbackOpen && (
            <button className="small" onClick={() => setFeedbackOpen(true)}>
              {t("feedback.give")}
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
          {t("feedback.summary", { positive })}
          {engagement.feedback.free_text ? ` · “${engagement.feedback.free_text}”` : ""}
        </p>
      )}
      {engagement.decline && <DeclineSummary decline={engagement.decline} />}
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
  const { t } = useTranslation();
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
  const disputes = useQuery({
    queryKey: ["worker-disputes", workerId],
    queryFn: () => api<DisputeStatusRead[]>(`/workers/${workerId}/disputes`),
    enabled: detail,
  });
  const w = worker.data;
  const { me } = useAuth();
  const declines = engagements.data?.filter((e) => e.decline) ?? [];
  const seesDeclineCount = me?.role === "people_ops" || me?.role === "admin";
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
            <h2 id={titleId}>{t("drawer.freelancer")}</h2>
          )}
          <button ref={closeRef} className="secondary icon-btn" onClick={onClose} aria-label={t("common.close")}>
            <X size={20} aria-hidden="true" />
          </button>
        </div>
        {worker.isLoading && <Loading />}
        <ErrorNote error={worker.error} />
        {w && (
          <>
            <div className="row wrap">
              <TierBadge tier={w.standing_tier} />
              <span className="pill">{detail ? t("drawer.detailView") : t("drawer.summaryView")}</span>
            </div>
            <div className="chips top-gap">
              {w.skills.map((s) => (
                <SkillPill key={s.skill_id} name={skillName(s.skill_id)} verified={s.verification_status === "bonarda_verified"} />
              ))}
            </div>
            {!detail && (
              <div className="top-gap">
                <InfoNote>{t("drawer.summaryNote")}</InfoNote>
              </div>
            )}
            {standing.data && (
              <dl className="stats top-gap">
                <div className="stat">
                  <dt>{t("standing.completed")}</dt>
                  <dd>{standing.data.factors.completed}</dd>
                </div>
                <div className="stat">
                  <dt>{t("standing.reviewers")}</dt>
                  <dd>{standing.data.factors.distinct_reviewers}</dd>
                </div>
                <div className="stat">
                  <dt>{t("standing.positive")}</dt>
                  <dd>{percent(standing.data.factors.positive_ratio)}</dd>
                </div>
              </dl>
            )}
            {disputes.data && disputes.data.length > 0 && (
              <p className="small-text top-gap row wrap">
                {t("drawer.disputes")}
                {disputes.data.map((d) => (
                  <Status key={d.id} value={d.resolution ?? d.status} />
                ))}
              </p>
            )}
            {!openEngagement && <EngageForm worker={w} project={project} />}
            {detail && (
              <section className="drawer-section" aria-labelledby="eng-heading">
                <h2 id="eng-heading">{t("passport.engagements.title")}</h2>
                {seesDeclineCount && declines.length > 0 && (
                  <p className="muted small-text">{t("engagement.declinedOffers", { count: declines.length })}</p>
                )}
                {engagements.data?.length === 0 && <p className="muted top-gap">{t("drawer.noEngagements")}</p>}
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
