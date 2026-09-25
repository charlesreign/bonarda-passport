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
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Candidate, type FirstShotItem, type Project } from "../api";
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
];

const SEGMENTS: [key: string, cls: string, label: string][] = [
  ["verified_skills", "seg-verified", "Verified skills"],
  ["self_reported_skills", "seg-self", "Self-reported skills"],
  ["availability", "seg-avail", "Availability"],
  ["tier", "seg-tier", "Tier (max 15%)"],
];

function Score({ candidate }: { candidate: Candidate }) {
  const b = candidate.score_breakdown as unknown as Record<string, { points: number }>;
  const summary = SEGMENTS.map(([key, , label]) => `${label} ${b[key].points.toFixed(2)}`).join(", ");
  return (
    <div className="score">
      <strong>{candidate.score.toFixed(2)}</strong>
      <div className="scorebar" role="img" aria-label={`Score ${candidate.score.toFixed(2)}: ${summary}`} title={summary}>
        {SEGMENTS.map(([key, cls]) => (
          <span key={key} className={cls} style={{ width: `${b[key].points * 100}%` }} />
        ))}
      </div>
    </div>
  );
}

function FirstShot({ projectId, onOpen }: { projectId: string; onOpen: (id: string) => void }) {
  const queryClient = useQueryClient();
  const [passing, setPassing] = useState<string | null>(null);
  const [reason, setReason] = useState(PASS_REASONS[0]);
  const { data, error, isLoading } = useQuery({
    queryKey: ["first-shot", projectId],
    queryFn: () => api<{ items: FirstShotItem[]; policy_version: number }>(`/projects/${projectId}/first-shot`),
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
      title="First shot"
      icon={<Sparkle size={20} weight="fill" aria-hidden="true" />}
      subtitle={data && `Matching policy v${data.policy_version}`}
    >
      <p className="fs-intro">
        <UserCircleCheck size={20} aria-hidden="true" />
        Qualified for this project, with little recent work. They are shown to every PM on every
        project, and tier never filters them out.
      </p>
      {isLoading && <Loading />}
      <ErrorNote error={error} />
      {data?.items.length === 0 && (
        <Empty icon={<UsersThree size={36} aria-hidden="true" />}>No one new qualifies right now.</Empty>
      )}
      {data?.items.map((item) => {
        const w = item.worker;
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
                    <span>{w.engagements_total} past engagements</span>
                  </div>
                </div>
              </div>
              <Status value={item.outcome} />
            </div>
            <div className="row wrap top-gap">
              <TierBadge tier={w.standing_tier} />
              <span className="small-text muted">{availabilityText(w.availability_status, w.available_from)}</span>
            </div>
            {passing === w.worker_id ? (
              <div className="inline-form">
                <label className="field">
                  Reason for passing
                  <select value={reason} onChange={(e) => setReason(e.target.value)}>
                    {PASS_REASONS.map((r) => (
                      <option key={r} value={r}>
                        {r.replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="row">
                  <button
                    className="danger small"
                    onClick={() => review.mutate({ workerId: w.worker_id, outcome: "passed", reason_code: reason })}
                  >
                    Confirm pass
                  </button>
                  <button className="secondary small" onClick={() => setPassing(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="fs-actions">
                <button className="small" onClick={() => review.mutate({ workerId: w.worker_id, outcome: "shortlisted" })}>
                  Shortlist
                </button>
                <button
                  className="secondary small"
                  onClick={() => review.mutate({ workerId: w.worker_id, outcome: "contacted" })}
                >
                  Contacted
                </button>
                <button className="ghost small" onClick={() => setPassing(w.worker_id)}>
                  Pass…
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
  const { projectId = "" } = useParams();
  const skillName = useSkillNames();
  const [openWorker, setOpenWorker] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api<Project>(`/projects/${projectId}`) });
  const candidates = useQuery({
    queryKey: ["candidates", projectId, q],
    queryFn: () =>
      api<{ items: Candidate[] }>(`/projects/${projectId}/candidates?limit=25${q ? `&q=${encodeURIComponent(q)}` : ""}`),
  });
  const p = project.data;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [confirmClose, setConfirmClose] = useState(false);
  const close = useMutation({
    mutationFn: () => api(`/projects/${projectId}/close`, { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate("/console");
    },
  });
  return (
    <>
      <Link to="/console" className="small-text" style={{ display: "inline-flex", gap: 6, alignItems: "center", marginBottom: 12 }}>
        <ArrowLeft size={16} aria-hidden="true" /> All projects
      </Link>
      <ErrorNote error={project.error} />
      {p && (
        <div className="page-head">
          <div>
            <p className="eyebrow">Staffing</p>
            <h1>{p.name}</h1>
            <div className="meta top-gap">
              <span>
                <Buildings size={16} aria-hidden="true" />
                {p.client_name ?? "Internal"}
              </span>
              <span>
                <Globe size={16} aria-hidden="true" />
                {p.data_region}
              </span>
              <span>
                <CalendarBlank size={16} aria-hidden="true" />
                Starts {date(p.starts_on)}
              </span>
            </div>
          </div>
          <div className="stack" style={{ gap: 8, alignItems: "flex-end" }}>
            {confirmClose ? (
              <div className="row wrap">
                <span className="small-text">Close this project and end its staffing?</span>
                <button className="danger small" onClick={() => close.mutate()} disabled={close.isPending}>
                  Close project
                </button>
                <button className="secondary small" onClick={() => setConfirmClose(false)}>
                  Cancel
                </button>
              </div>
            ) : (
              <button className="secondary small" onClick={() => setConfirmClose(true)}>
                Close project
              </button>
            )}
            <ErrorNote error={close.error} />
            <p className="small-text muted" style={{ marginBottom: 4 }}>
              Required skills
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
          title="Candidates"
          icon={<UsersThree size={20} aria-hidden="true" />}
          subtitle="Ranked by skills, availability and tier. Past selection never adds points."
          actions={
            <div className="search-field">
              <MagnifyingGlass size={18} aria-hidden="true" />
              <input
                type="search"
                aria-label="Search candidates by name"
                placeholder="Search by name"
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
                      <th scope="col" className="col-name">Freelancer</th>
                      <th scope="col">Tier</th>
                      <th scope="col" className="col-skills">Skills</th>
                      <th scope="col">Availability</th>
                      <th scope="col">Score</th>
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
                                {c.worker.base_location} · {c.worker.engagements_total} engagements
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
                        <td className="small-text">{availabilityText(c.worker.availability_status, c.worker.available_from)}</td>
                        <td>
                          <Score candidate={c} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="legend" aria-hidden="true">
                {SEGMENTS.map(([key, cls, label]) => (
                  <span key={key}>
                    <i className={cls} />
                    {label}
                  </span>
                ))}
              </div>
            </>
          )}
          {candidates.data?.items.length === 0 && (
            <Empty icon={<MagnifyingGlass size={36} aria-hidden="true" />}>No candidates match.</Empty>
          )}
        </Card>
        <FirstShot projectId={projectId} onOpen={setOpenWorker} />
      </div>
      {openWorker && p && <WorkerPanel workerId={openWorker} project={p} onClose={() => setOpenWorker(null)} />}
    </>
  );
}
