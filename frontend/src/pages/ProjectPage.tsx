import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api, type Candidate, type FirstShotItem, type Project } from "../api";
import { Card, ErrorNote, Pill, Status, TierBadge, availabilityText, date, useSkillNames } from "../ui";
import WorkerPanel from "./WorkerPanel";

const PASS_REASONS = [
  "skills_mismatch",
  "availability_mismatch",
  "rate_mismatch",
  "location_mismatch",
  "already_staffed",
  "other",
];

function ScoreBar({ candidate }: { candidate: Candidate }) {
  const b = candidate.score_breakdown;
  const parts: [string, number, string][] = [
    ["verified", b.verified_skills.points, "Verified skills"],
    ["self", b.self_reported_skills.points, "Self-reported skills"],
    ["avail", b.availability.points, "Availability"],
    ["tier", b.tier.points, "Tier (capped at 15%)"],
  ];
  return (
    <div className="scorebar" title={parts.map(([, v, l]) => `${l}: ${v.toFixed(2)}`).join("\n")}>
      {parts.map(([key, value]) => (
        <span key={key} className={`seg seg-${key}`} style={{ width: `${value * 100}%` }} />
      ))}
    </div>
  );
}

function FirstShot({ projectId, onOpen }: { projectId: string; onOpen: (id: string) => void }) {
  const queryClient = useQueryClient();
  const [passing, setPassing] = useState<string | null>(null);
  const [reason, setReason] = useState(PASS_REASONS[0]);
  const { data, error } = useQuery({
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
      title="First shot"
      actions={<span className="muted">Qualified people you have not worked with much</span>}
    >
      <ErrorNote error={error} />
      {data?.items.length === 0 && <p className="muted">No one new qualifies right now.</p>}
      {data?.items.map((item) => (
        <div key={item.worker.worker_id} className="fs-item">
          <div className="row between">
            <button className="link" onClick={() => onOpen(item.worker.worker_id)}>
              {item.worker.display_name}
            </button>
            <Status value={item.outcome} />
          </div>
          <p className="muted small-text">
            <TierBadge tier={item.worker.standing_tier} /> · {item.worker.base_location} ·{" "}
            {availabilityText(item.worker.availability_status, item.worker.available_from)} ·{" "}
            {item.worker.engagements_total} past engagements
          </p>
          <div className="row wrap">
            <button className="small" onClick={() => review.mutate({ workerId: item.worker.worker_id, outcome: "shortlisted" })}>
              Shortlist
            </button>
            <button className="small ghost" onClick={() => review.mutate({ workerId: item.worker.worker_id, outcome: "contacted" })}>
              Contacted
            </button>
            {passing === item.worker.worker_id ? (
              <>
                <select value={reason} onChange={(e) => setReason(e.target.value)}>
                  {PASS_REASONS.map((r) => (
                    <option key={r} value={r}>
                      {r.replaceAll("_", " ")}
                    </option>
                  ))}
                </select>
                <button
                  className="small danger"
                  onClick={() =>
                    review.mutate({ workerId: item.worker.worker_id, outcome: "passed", reason_code: reason })
                  }
                >
                  Confirm pass
                </button>
              </>
            ) : (
              <button className="small ghost" onClick={() => setPassing(item.worker.worker_id)}>
                Pass…
              </button>
            )}
          </div>
        </div>
      ))}
      <ErrorNote error={review.error} />
    </Card>
  );
}

export default function ProjectPage() {
  const { projectId = "" } = useParams();
  const skillName = useSkillNames();
  const [openWorker, setOpenWorker] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api<Project>(`/projects/${projectId}`),
  });
  const candidates = useQuery({
    queryKey: ["candidates", projectId, q],
    queryFn: () =>
      api<{ items: Candidate[] }>(
        `/projects/${projectId}/candidates?limit=25${q ? `&q=${encodeURIComponent(q)}` : ""}`,
      ),
  });
  const p = project.data;
  return (
    <div className="stack">
      <ErrorNote error={project.error} />
      {p && (
        <div className="row between wrap">
          <div>
            <h1>{p.name}</h1>
            <p className="muted">
              {p.client_name ?? "Internal"} · {p.data_region} · starts {date(p.starts_on)}
            </p>
          </div>
          <div className="chips">
            {p.required_skill_ids.map((id) => (
              <Pill key={id}>{skillName(id)}</Pill>
            ))}
          </div>
        </div>
      )}
      <div className="grid-staffing">
        <Card
          title="Candidates"
          actions={
            <input
              className="search"
              placeholder="Search by name"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          }
        >
          <ErrorNote error={candidates.error} />
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Tier</th>
                <th>Skills</th>
                <th>Availability</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {candidates.data?.items.map((c) => (
                <tr key={c.worker.worker_id} onClick={() => setOpenWorker(c.worker.worker_id)} className="clickable">
                  <td>
                    <b>{c.worker.display_name}</b>
                    <div className="muted small-text">
                      {c.worker.base_location} · {c.worker.engagements_total} engagements
                    </div>
                  </td>
                  <td>
                    <TierBadge tier={c.worker.standing_tier} />
                  </td>
                  <td>
                    {c.worker.verified_skill_ids.map((id) => (
                      <Pill key={id} tone="good">
                        {skillName(id)} ✓
                      </Pill>
                    ))}
                    {c.worker.self_reported_skill_ids.map((id) => (
                      <Pill key={id}>{skillName(id)}</Pill>
                    ))}
                  </td>
                  <td className="small-text">
                    {availabilityText(c.worker.availability_status, c.worker.available_from)}
                  </td>
                  <td>
                    <b>{c.score.toFixed(2)}</b>
                    <ScoreBar candidate={c} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {candidates.data?.items.length === 0 && <p className="muted">No candidates match.</p>}
        </Card>
        <FirstShot projectId={projectId} onOpen={setOpenWorker} />
      </div>
      {openWorker && p && (
        <WorkerPanel workerId={openWorker} project={p} onClose={() => setOpenWorker(null)} />
      )}
    </div>
  );
}
