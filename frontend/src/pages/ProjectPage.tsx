import {
  ArrowLeft,
  Buildings,
  CalendarBlank,
  Globe,
  MagnifyingGlass,
  Sparkle,
  UserCircleCheck,
  UsersThree,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Candidate, type CandidatePage, type FirstShotPanel, type Project } from "../api";
import {
  Avatar,
  Card,
  Empty,
  ErrorNote,
  Loading,
  Pill,
  SkillPill,
  Status,
  TierBadge,
  availabilityText,
  date,
  useSkillNames,
} from "../ui";
import WorkerPanel from "./WorkerPanel";

const PASS_REASONS = [
  "skills_mismatch",
  "availability_mismatch",
  "rate_mismatch",
  "location_mismatch",
  "already_staffed",
  "other",
] as const;

const SEGMENTS = [
  ["verified_skills", "seg-verified"],
  ["self_reported_skills", "seg-self"],
  ["availability", "seg-avail"],
  ["tier", "seg-tier"],
] as const;

function Score({ candidate }: { candidate: Candidate }) {
  const { t } = useTranslation();
  const b = candidate.score_breakdown;
  const summary = SEGMENTS.map(([key]) => `${t(`score.${key}`)} ${b[key].points.toFixed(2)}`).join(", ");
  return (
    <div className="score">
      <strong>{candidate.score.toFixed(2)}</strong>
      <div
        className="scorebar"
        role="img"
        aria-label={t("score.aria", { score: candidate.score.toFixed(2), summary })}
        title={summary}
      >
        {SEGMENTS.map(([key, cls]) => (
          <span key={key} className={cls} style={{ width: `${b[key].points * 100}%` }} />
        ))}
      </div>
    </div>
  );
}

function FirstShot({ projectId, onOpen }: { projectId: string; onOpen: (id: string) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [passing, setPassing] = useState<string | null>(null);
  const [reason, setReason] = useState<string>(PASS_REASONS[0]);
  const { data, error, isLoading } = useQuery({
    queryKey: ["first-shot", projectId],
    queryFn: () => api<FirstShotPanel>(`/projects/${projectId}/first-shot`),
  });
  const review = useMutation({
    mutationFn: (v: { workerId: string; outcome: string; reason_code?: string }) =>
      api(`/projects/${projectId}/first-shot/${v.workerId}/review`, {
        method: "POST",
        body: { outcome: v.outcome, reason_code: v.reason_code ?? null },
      }),
    onSuccess: () => {
      setPassing(null);
      void queryClient.invalidateQueries({ queryKey: ["first-shot", projectId] });
    },
  });
  return (
    <Card
      highlight
      title={t("firstShot.title")}
      icon={<Sparkle size={20} weight="fill" aria-hidden="true" />}
      subtitle={data && t("firstShot.policy", { version: data.policy_version })}
    >
      <p className="fs-intro">
        <UserCircleCheck size={20} aria-hidden="true" />
        {t("firstShot.intro")}
      </p>
      {isLoading && <Loading />}
      <ErrorNote error={error} />
      {data?.items.length === 0 && (
        <Empty icon={<UsersThree size={36} aria-hidden="true" />}>{t("firstShot.none")}</Empty>
      )}
      {data?.items.map((item) => {
        const w = item.worker;
        const decided = item.outcome === "engaged";
        return (
          <article key={w.worker_id} className="list-item">
            <div className="row between">
              <div className="person">
                <Avatar name={w.display_name} />
                <div>
                  <button className="link" onClick={() => onOpen(w.worker_id)}>
                    {w.display_name}
                  </button>
                  <div className="meta">
                    <span>{w.base_location}</span>
                    <span>{t("candidates.pastEngagements", { count: w.engagements_total })}</span>
                  </div>
                </div>
              </div>
              <Status value={item.outcome} />
            </div>
            <div className="row wrap top-gap">
              <TierBadge tier={w.standing_tier} />
              <span className="small-text muted">{availabilityText(w.availability_status, w.available_from)}</span>
            </div>
            {decided ? null : passing === w.worker_id ? (
              <div className="inline-form">
                <label className="field">
                  {t("firstShot.passReason")}
                  <select value={reason} onChange={(e) => setReason(e.target.value)}>
                    {PASS_REASONS.map((r) => (
                      <option key={r} value={r}>
                        {t(`passReasons.${r}`)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="row">
                  <button
                    className="danger small"
                    onClick={() => review.mutate({ workerId: w.worker_id, outcome: "passed", reason_code: reason })}
                  >
                    {t("firstShot.confirmPass")}
                  </button>
                  <button className="secondary small" onClick={() => setPassing(null)}>
                    {t("common.cancel")}
                  </button>
                </div>
              </div>
            ) : (
              <div className="fs-actions">
                <button className="small" onClick={() => review.mutate({ workerId: w.worker_id, outcome: "shortlisted" })}>
                  {t("firstShot.shortlist")}
                </button>
                <button
                  className="secondary small"
                  onClick={() => review.mutate({ workerId: w.worker_id, outcome: "contacted" })}
                >
                  {t("firstShot.contacted")}
                </button>
                <button className="ghost small" onClick={() => setPassing(w.worker_id)}>
                  {t("firstShot.pass")}
                </button>
              </div>
            )}
          </article>
        );
      })}
      <ErrorNote error={review.error} />
    </Card>
  );
}

export default function ProjectPage() {
  const { t } = useTranslation();
  const { projectId = "" } = useParams();
  const skillName = useSkillNames();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [openWorker, setOpenWorker] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);
  const [q, setQ] = useState("");
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api<Project>(`/projects/${projectId}`) });
  const candidates = useQuery({
    queryKey: ["candidates", projectId, q],
    queryFn: () =>
      api<CandidatePage>(`/projects/${projectId}/candidates?limit=25${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  });
  const close = useMutation({
    mutationFn: () => api(`/projects/${projectId}/close`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate("/console");
    },
  });
  const p = project.data;
  return (
    <>
      <Link
        to="/console"
        className="small-text"
        style={{ display: "inline-flex", gap: 6, alignItems: "center", marginBottom: 12 }}
      >
        <ArrowLeft size={16} aria-hidden="true" /> {t("project.allProjects")}
      </Link>
      <ErrorNote error={project.error} />
      {p && (
        <div className="page-head">
          <div>
            <p className="eyebrow">{t("nav.staffing")}</p>
            <h1>{p.name}</h1>
            <div className="meta top-gap">
              <span>
                <Buildings size={16} aria-hidden="true" />
                {p.client_name ?? t("project.internal")}
              </span>
              <span>
                <Globe size={16} aria-hidden="true" />
                {p.data_region}
              </span>
              <span>
                <CalendarBlank size={16} aria-hidden="true" />
                {t("project.starts", { date: date(p.starts_on) })}
              </span>
            </div>
          </div>
          <div className="stack" style={{ gap: 8, alignItems: "flex-end" }}>
            {confirmClose ? (
              <div className="row wrap">
                <span className="small-text">{t("project.closeConfirm")}</span>
                <button className="danger small" onClick={() => close.mutate()} disabled={close.isPending}>
                  {t("project.close")}
                </button>
                <button className="secondary small" onClick={() => setConfirmClose(false)}>
                  {t("common.cancel")}
                </button>
              </div>
            ) : (
              <button className="secondary small" onClick={() => setConfirmClose(true)}>
                {t("project.close")}
              </button>
            )}
            <ErrorNote error={close.error} />
            <p className="small-text muted" style={{ marginBottom: 4 }}>
              {t("project.requiredSkills")}
            </p>
            <div className="chips">
              {p.required_skill_ids.map((id) => (
                <Pill key={id} tone="info">
                  {skillName(id)}
                </Pill>
              ))}
            </div>
          </div>
        </div>
      )}
      <div className="grid-staffing">
        <Card
          title={t("candidates.title")}
          icon={<UsersThree size={20} aria-hidden="true" />}
          subtitle={t("candidates.lead")}
          actions={
            <div className="search-field">
              <MagnifyingGlass size={18} aria-hidden="true" />
              <input
                type="search"
                aria-label={t("candidates.searchAria")}
                placeholder={t("candidates.search")}
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
          }
        >
          {candidates.isLoading && <Loading lines={5} />}
          <ErrorNote error={candidates.error} />
          {candidates.data && candidates.data.items.length > 0 && (
            <>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col" className="col-name">
                        {t("candidates.freelancer")}
                      </th>
                      <th scope="col">{t("standing.tier")}</th>
                      <th scope="col" className="col-skills">
                        {t("candidates.skills")}
                      </th>
                      <th scope="col">{t("candidates.availability")}</th>
                      <th scope="col">{t("candidates.score")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.data.items.map((c) => (
                      <tr key={c.worker.worker_id} className="clickable" onClick={() => setOpenWorker(c.worker.worker_id)}>
                        <td>
                          <div className="person">
                            <Avatar name={c.worker.display_name} />
                            <div>
                              <button
                                className="link"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenWorker(c.worker.worker_id);
                                }}
                              >
                                {c.worker.display_name}
                              </button>
                              <div className="sub">
                                {c.worker.base_location} ·{" "}
                                {t("candidates.engagements", { count: c.worker.engagements_total })}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <TierBadge tier={c.worker.standing_tier} />
                        </td>
                        <td className="col-skills">
                          {c.worker.verified_skill_ids.map((id) => (
                            <SkillPill key={id} name={skillName(id)} verified />
                          ))}
                          {c.worker.self_reported_skill_ids.map((id) => (
                            <SkillPill key={id} name={skillName(id)} verified={false} />
                          ))}
                        </td>
                        <td className="small-text">
                          {availabilityText(c.worker.availability_status, c.worker.available_from)}
                        </td>
                        <td>
                          <Score candidate={c} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="legend" aria-hidden="true">
                {SEGMENTS.map(([key, cls]) => (
                  <span key={key}>
                    <i className={cls} />
                    {t(`score.${key}`)}
                  </span>
                ))}
              </div>
            </>
          )}
          {candidates.data?.items.length === 0 && (
            <Empty icon={<MagnifyingGlass size={36} aria-hidden="true" />}>{t("candidates.none")}</Empty>
          )}
        </Card>
        <FirstShot projectId={projectId} onOpen={setOpenWorker} />
      </div>
      {openWorker && p && <WorkerPanel workerId={openWorker} project={p} onClose={() => setOpenWorker(null)} />}
    </>
  );
}
