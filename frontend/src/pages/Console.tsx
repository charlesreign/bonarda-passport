import { ArrowRight, Buildings, CalendarBlank, FolderSimple, Globe } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api, type Project } from "../api";
import { Card, Empty, ErrorNote, Loading, Pill, date, useSkillNames } from "../ui";

const ARCHIVE_PREFIX = "Archive — ";

export default function Console() {
  const { t } = useTranslation();
  const skillName = useSkillNames();
  const { data, error, isLoading } = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const live = (data ?? []).filter((p) => !p.name.startsWith(ARCHIVE_PREFIX));
  const archive = (data ?? []).filter((p) => p.name.startsWith(ARCHIVE_PREFIX));
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">{t("nav.staffing")}</p>
          <h1>{t("console.title")}</h1>
          <p>{t("console.lead")}</p>
        </div>
      </div>
      <ErrorNote error={error} />
      {isLoading && <Loading lines={4} />}
      {data && live.length === 0 && (
        <Empty icon={<FolderSimple size={40} aria-hidden="true" />}>{t("console.none")}</Empty>
      )}
      <div className="project-grid">
        {live.map((p) => (
          <Link key={p.id} to={`/console/projects/${p.id}`} className="project-card">
            <div>
              <h2>{p.name}</h2>
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
            <div className="chips">
              {p.required_skill_ids.map((id) => (
                <Pill key={id}>{skillName(id)}</Pill>
              ))}
            </div>
            <span className="go">
              {t("console.open")} <ArrowRight size={16} aria-hidden="true" />
            </span>
          </Link>
        ))}
      </div>
      {archive.length > 0 && (
        <div style={{ marginTop: 32 }}>
          <Card title={t("console.past")} subtitle={t("console.pastLead")}>
            {archive.map((p) => (
              <p key={p.id} className="list-item">
                <Link to={`/console/projects/${p.id}`}>{p.name.replace(ARCHIVE_PREFIX, "")}</Link>
              </p>
            ))}
          </Card>
        </div>
      )}
    </>
  );
}
