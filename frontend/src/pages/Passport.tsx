import {
  Briefcase,
  CalendarBlank,
  Check,
  ClockCounterClockwise,
  Flag,
  Globe,
  HourglassMedium,
  MapPin,
  PenNib,
  Scales,
  ShieldCheck,
  Translate,
  X,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  type Consent,
  type DisputePage,
  type Engagement,
  type Standing,
  type WorkerSelf,
} from "../api";
import {
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
  answerLabel,
  availabilityText,
  date,
  dateTime,
  money,
  percent,
  tierLabel,
  useSkillNames,
} from "../ui";

type Target = "engagement" | "feedback" | "standing_change";

function DisputeButton({ targetType, targetId }: { targetType: Target; targetId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const fieldId = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const target = t(`targets.${targetType}`);
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
        <button
          className="ghost small"
          onClick={() => setOpen(true)}
          aria-label={t("passport.dispute.aria", { target })}
        >
          <Flag size={16} aria-hidden="true" />
          {t("passport.dispute.button")}
        </button>
        {file.isSuccess && <SuccessNote>{t("passport.dispute.filed")}</SuccessNote>}
      </>
    );
  return (
    <div className="inline-form" style={{ width: "100%" }}>
      <label className="field" htmlFor={fieldId}>
        {t("passport.dispute.question", { target })}
        <span className="hint">{t("passport.dispute.hint")}</span>
        <textarea id={fieldId} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="row">
        <button className="small" disabled={reason.trim().length < 10 || file.isPending} onClick={() => file.mutate()}>
          {t("passport.dispute.file")}
        </button>
        <button className="secondary small" onClick={() => setOpen(false)}>
          {t("common.cancel")}
        </button>
      </div>
      <ErrorNote error={file.error} />
    </div>
  );
}

function Profile({ me }: { me: WorkerSelf }) {
  const { t } = useTranslation();
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
    <Card title={t("passport.profile.title")} icon={<Briefcase size={20} aria-hidden="true" />}>
      <div className="meta">
        <span>
          <MapPin size={16} aria-hidden="true" />
          {me.base_location ?? t("passport.profile.noLocation")}
        </span>
        <span>
          <Globe size={16} aria-hidden="true" />
          {t("passport.profile.region", { region: me.data_region })}
        </span>
        <span>
          <Translate size={16} aria-hidden="true" />
          {me.languages.join(", ").toUpperCase()}
        </span>
      </div>
      <h3>{t("passport.profile.skills")}</h3>
      <div className="chips">
        {me.skills.map((s) => (
          <SkillPill key={s.skill_id} name={skillName(s.skill_id)} verified={s.verification_status === "bonarda_verified"} />
        ))}
      </div>
      <h3>{t("passport.profile.availability")}</h3>
      <div className="row wrap" style={{ alignItems: "flex-end" }}>
        <label className="field">
          {t("passport.profile.status")}
          <select value={status} onChange={(e) => setStatus(e.target.value as WorkerSelf["availability_status"])}>
            <option value="available">{t("availability.now")}</option>
            <option value="available_from">{t("passport.profile.fromDate")}</option>
            <option value="unavailable">{t("availability.unavailable")}</option>
          </select>
        </label>
        {status === "available_from" && (
          <label className="field">
            {t("passport.profile.from")}
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
        )}
        <button className="secondary" onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? t("common.saving") : t("common.save")}
        </button>
      </div>
      <p className="muted small-text top-gap">
        {t("passport.profile.pmsSee", { value: availabilityText(me.availability_status, me.available_from) })}
      </p>
      <ErrorNote error={save.error} />
    </Card>
  );
}

function StandingCard() {
  const { t } = useTranslation();
  const { data, error, isLoading } = useQuery({
    queryKey: ["my-standing"],
    queryFn: () => api<Standing>("/workers/me/standing"),
  });
  return (
    <Card
      title={t("passport.standing.title")}
      icon={<ShieldCheck size={20} aria-hidden="true" />}
      subtitle={data && t("passport.standing.subtitle", { version: data.policy_version, months: data.window_months })}
    >
      {isLoading && <Loading />}
      <ErrorNote error={error} />
      {data && (
        <>
          <div className="standing-hero">
            <TierBadge tier={data.tier} large />
            <dl className="stats">
              <div className="stat">
                <dt>{t("standing.completed")}</dt>
                <dd>{data.factors.completed}</dd>
              </div>
              <div className="stat">
                <dt>{t("standing.reviewers")}</dt>
                <dd>{data.factors.distinct_reviewers}</dd>
              </div>
              <div className="stat">
                <dt>{t("standing.positive")}</dt>
                <dd>{percent(data.factors.positive_ratio)}</dd>
              </div>
            </dl>
          </div>
          {data.evaluated_tier !== data.tier && (
            <div className="top-gap">
              <InfoNote>{t("passport.standing.overridden", { tier: tierLabel(data.evaluated_tier) })}</InfoNote>
            </div>
          )}
          <h3>{t("passport.standing.howEarned")}</h3>
          <div>
            <table className="table compact">
              <thead>
                <tr>
                  <th scope="col">{t("standing.tier")}</th>
                  <th scope="col">{t("standing.completed")}</th>
                  <th scope="col">{t("standing.reviewers")}</th>
                  <th scope="col">{t("standing.positive")}</th>
                </tr>
              </thead>
              <tbody>
                {data.tiers.map((rule) => (
                  <tr key={rule.tier}>
                    <td>
                      <TierBadge tier={rule.tier} short />
                    </td>
                    <td className="num">≥ {rule.min_completed}</td>
                    <td className="num">≥ {rule.min_distinct_reviewers}</td>
                    <td className="num">≥ {percent(rule.min_positive_ratio)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>{t("passport.standing.history")}</h3>
          {data.history.length === 0 ? (
            <p className="muted">{t("passport.standing.noChanges")}</p>
          ) : (
            <ul className="timeline">
              {data.history.map((c) => (
                <li key={c.id}>
                  <div>
                    <div className="row wrap">
                      <TierBadge tier={c.previous_tier} />
                      <span aria-label={t("common.to")}>→</span>
                      <TierBadge tier={c.new_tier} />
                    </div>
                    <p className="muted small-text">
                      {dateTime(c.occurred_at)} ·{" "}
                      {c.automated
                        ? t("passport.standing.byRules", { version: c.policy_version })
                        : t("passport.standing.byPeopleOps", { reason: c.override_reason })}
                    </p>
                  </div>
                  <DisputeButton targetType="standing_change" targetId={c.id} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}

const IN_FLIGHT = ["pending_signature", "awaiting_signature"];

/** The freelancer's side of the e-signature step. In production the provider
 * emails the contract; in the demo this card plays that role. */
function ContractToSign({ engagement }: { engagement: Engagement }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const sign = useMutation({
    mutationFn: () => api(`/demo/engagements/${engagement.id}/sign`, { method: "POST" }),
    onSuccess: () => {
      for (const key of [["engagements", engagement.worker_id], ["me-worker"]])
        void queryClient.invalidateQueries({ queryKey: key });
    },
  });
  if (engagement.status === "pending_signature")
    return (
      <p className="muted small-text row top-gap" role="status">
        <HourglassMedium size={16} aria-hidden="true" />
        {t("passport.contract.preparing")}
      </p>
    );
  return (
    <div className="panel-soft top-gap" style={{ borderLeft: "3px solid var(--color-highlight)" }}>
      <p className="row" style={{ fontWeight: 650 }}>
        <PenNib size={18} aria-hidden="true" />
        {t("passport.contract.ready")}
      </p>
      <dl className="meta top-gap" style={{ margin: 0 }}>
        <span>
          <strong>{t("engagement.scope")}:</strong>&nbsp;{engagement.contract_terms.scope}
        </span>
        <span>
          <strong>{t("engagement.start")}:</strong>&nbsp;{date(engagement.start_date)}
        </span>
        <span className="num">
          <strong>{t("engagement.rate")}:</strong>&nbsp;
          {t("engagement.perDay", { amount: money(engagement.rate, engagement.currency) })}
        </span>
        <span>
          <strong>{t("engagement.mode")}:</strong>&nbsp;{t(`workMode.${engagement.work_mode}`)}
        </span>
      </dl>
      <div className="row wrap top-gap">
        <button className="small" onClick={() => sign.mutate()} disabled={sign.isPending}>
          <PenNib size={16} aria-hidden="true" />
          {sign.isPending ? t("passport.contract.signing") : t("passport.contract.sign")}
        </button>
        <span className="muted small-text">{t("passport.contract.demoNote")}</span>
      </div>
      <ErrorNote error={sign.error} />
    </div>
  );
}

function Engagements({ workerId }: { workerId: string }) {
  const { t } = useTranslation();
  const { data, error, isLoading } = useQuery({
    queryKey: ["engagements", workerId],
    queryFn: () => api<Engagement[]>(`/workers/${workerId}/engagements`),
    // Pick up the contract as soon as the worker process has sent it.
    refetchInterval: (query) => (query.state.data?.some((e) => IN_FLIGHT.includes(e.status)) ? 2000 : false),
  });
  return (
    <Card title={t("passport.engagements.title")} icon={<ClockCounterClockwise size={20} aria-hidden="true" />}>
      {isLoading && <Loading />}
      <ErrorNote error={error} />
      {data?.length === 0 && (
        <Empty icon={<Briefcase size={40} aria-hidden="true" />}>{t("passport.engagements.none")}</Empty>
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
                <span className="num">{t("engagement.perDay", { amount: money(e.rate, e.currency) })}</span>
                <span>{t(`workMode.${e.work_mode}`)}</span>
                {e.path === "reactivation" && <span>{t("engagement.reactivation")}</span>}
              </div>
            </div>
            <div className="row">
              <Status value={e.status} />
              <DisputeButton targetType="engagement" targetId={e.id} />
            </div>
          </div>
          {IN_FLIGHT.includes(e.status) && <ContractToSign engagement={e} />}
          {e.feedback && (
            <div className="feedback panel-soft">
              <ul className="answers">
                {Object.entries(e.feedback.structured_answers).map(([k, v]) => (
                  <li key={k}>
                    {v ? (
                      <Check size={16} weight="bold" className="yes" aria-label={t("common.yes")} />
                    ) : (
                      <X size={16} weight="bold" className="no" aria-label={t("common.no")} />
                    )}
                    {answerLabel(k)}
                  </li>
                ))}
              </ul>
              {e.feedback.free_text && <p className="quote">{e.feedback.free_text}</p>}
              <DisputeButton targetType="feedback" targetId={e.feedback.id} />
            </div>
          )}
        </article>
      ))}
    </Card>
  );
}

function Consents() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["consents"], queryFn: () => api<Consent[]>("/workers/me/consents") });
  const toggle = useMutation({
    mutationFn: (c: Consent) =>
      api(`/workers/me/consents/${c.purpose}`, { method: "PUT", body: { granted: !c.granted } }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["consents"] }),
  });
  return (
    <Card title={t("passport.privacy.title")} subtitle={t("passport.privacy.subtitle")}>
      {data?.map((c) => (
        <label key={c.purpose} className="check">
          <input type="checkbox" checked={c.granted} onChange={() => toggle.mutate(c)} />
          {t(`passport.privacy.${c.purpose}`)}
        </label>
      ))}
      <ErrorNote error={toggle.error} />
    </Card>
  );
}

function MyDisputes() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["my-disputes"], queryFn: () => api<DisputePage>("/disputes") });
  return (
    <Card title={t("passport.disputes.title")} icon={<Scales size={20} aria-hidden="true" />}>
      {data?.items.length === 0 && <p className="muted">{t("passport.disputes.none")}</p>}
      {data?.items.map((d) => (
        <article key={d.id} className="list-item">
          <div className="row between wrap">
            <strong>{t(`targets.${d.target_type}`)}</strong>
            <Status value={d.resolution ?? d.status} />
          </div>
          <p className="muted small-text">
            {t("passport.disputes.dates", { filed: date(d.created_at), due: date(d.due_at) })}
          </p>
          <p className="quote">{d.reason}</p>
          {d.resolution_notes && (
            <p className="small-text">
              <strong>{t("roles.people_ops")}:</strong> {d.resolution_notes}
            </p>
          )}
        </article>
      ))}
    </Card>
  );
}

export default function Passport() {
  const { t } = useTranslation();
  const { data: me, error } = useQuery({ queryKey: ["me-worker"], queryFn: () => api<WorkerSelf>("/workers/me") });
  if (error) return <ErrorNote error={error} />;
  if (!me) return <Loading lines={4} />;
  return (
    <>
      <div className="page-head">
        <div className="person">
          <Avatar name={me.full_name} large />
          <div>
            <p className="eyebrow">{t("nav.passport")}</p>
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
