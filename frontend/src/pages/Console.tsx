import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Project } from "../api";
import { Card, ErrorNote, Pill, date, useSkillNames } from "../ui";

export default function Console() {
  const skillName = useSkillNames();
  const { data, error } = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const live = (data ?? []).filter((p) => !p.name.startsWith("Archive"));
  const archive = (data ?? []).filter((p) => p.name.startsWith("Archive"));
  return (
    <div className="stack">
      <h1>My projects</h1>
      <ErrorNote error={error} />
      <div className="project-grid">
        {live.map((p) => (
          <Link key={p.id} to={`/console/projects/${p.id}`} className="project-card">
            <h2>{p.name}</h2>
            <p className="muted">
              {p.client_name ?? "Internal"} · {p.data_region} · starts {date(p.starts_on)}
            </p>
            <div className="chips">
              {p.required_skill_ids.map((id) => (
                <Pill key={id}>{skillName(id)}</Pill>
              ))}
            </div>
          </Link>
        ))}
      </div>
      {archive.length > 0 && (
        <Card title="Past projects">
          {archive.map((p) => (
            <p key={p.id}>
              <Link to={`/console/projects/${p.id}`}>{p.name}</Link>
            </p>
          ))}
        </Card>
      )}
    </div>
  );
}
