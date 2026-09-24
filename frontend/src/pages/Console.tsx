import { ArrowRight, Buildings, CalendarBlank, FolderSimple, Globe } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Project } from "../api";
import { Card, Empty, ErrorNote, Loading, Pill, date, useSkillNames } from "../ui";

export default function Console() {
  const skillName = useSkillNames();
  const { data, error, isLoading } = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const live = (data ?? []).filter((p) => !p.name.startsWith("Archive"));
  const archive = (data ?? []).filter((p) => p.name.startsWith("Archive"));
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Staffing</p>
          <h1>My projects</h1>
          <p>Pick a project to see scored candidates and this project's first-shot panel.</p>
        </div>
      </div>
      <ErrorNote error={error} />
      {isLoading && <Loading lines={4} />}
      {data && live.length === 0 && (
        <Empty icon={<FolderSimple size={40} aria-hidden="true" />}>You are not staffed on any live project.</Empty>
      )}
      <div className="project-grid">
        {live.map((p) => (
          <Link key={p.id} to={`/console/projects/${p.id}`} className="project-card">
            <div>
              <h2>{p.name}</h2>
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
            <div className="chips">
              {p.required_skill_ids.map((id) => (
                <Pill key={id}>{skillName(id)}</Pill>
              ))}
            </div>
            <span className="go">
              Open staffing <ArrowRight size={16} aria-hidden="true" />
            </span>
          </Link>
        ))}
      </div>
      {archive.length > 0 && (
        <div className="top-gap" style={{ marginTop: 32 }}>
          <Card title="Past projects" subtitle="Engagement history for reactivation and feedback.">
            {archive.map((p) => (
              <p key={p.id} className="list-item">
                <Link to={`/console/projects/${p.id}`}>{p.name.replace("Archive — ", "")}</Link>
              </p>
            ))}
          </Card>
        </div>
      )}
    </>
  );
}
