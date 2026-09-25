import {
  ChartBar,
  Check,
  ClockCountdown,
  FileText,
  Gavel,
  ListMagnifyingGlass,
  SlidersHorizontal,
  Trash,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  type AuditLogPage,
  type Dispute,
  type DisputePage,
  type Overview,
  type PolicyVersion,
  type WorkerView,
} from "../api";
import { useAuth } from "../auth";
import {
  Avatar,
  Card,
  Empty,
  ErrorNote,
  Loading,
  Status,
  SuccessNote,
  TierBadge,
  date,
  dateTime,
  percent,
  tierLabel,
} from "../ui";

function OverrideForm({ workerId }: { workerId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const reasonId = useId();
  const [tier, setTier] = useState("tier_1");
  const [reason, setReason] = useState("");
  const worker = useQuery({ queryKey: ["worker", workerId], queryFn: () => api<WorkerView>(`/workers/${workerId}`) });
  const save = useMutation({
    mutationFn: () => api(`/workers/${workerId}/standing-overrides`, { method: "POST", body: { tier, reason } }),
    onSuccess: () => {
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["worker", workerId] });
    },
  });
  return (
    <div className="inline-form">
      <p className="small-text row wrap">
        {t("ops.override.current")} {worker.data && <TierBadge tier={worker.data.standing_tier} />}
      </p>
      <div className="form-grid" style={{ margin: 0 }}>
        <label className="field">
          {t("ops.override.newTier")}
          <select value={tier} onChange={(e) => setTier(e.target.value)}>
            {["unrated", "tier_1", "tier_2"].map((value) => (
              <option key={value} value={value}>
                {tierLabel(value, true)}
              </option>
            ))}
          </select>
        </label>
        <label className="field span-2" htmlFor={reasonId}>
          {t("ops.reason")} <span className="hint">{t("ops.override.reasonHint")}</span>
          <input id={reasonId} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      </div>
      <div>
        <button className="small" disabled={reason.trim().length < 10 || save.isPending} onClick={() => save.mutate()}>
          {t("ops.override.submit")}
        </button>
      </div>
      {save.isSuccess && <SuccessNote>{t("ops.override.done")}</SuccessNote>}
      <ErrorNote error={save.error} />
    </div>
  );
}

/** Erasure (spec §6.3): irreversible, so it asks for a reason and a second click. */
function EraseForm({ workerId, name }: { workerId: string; name: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const reasonId = useId();
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const erase = useMutation({
    mutationFn: () => api(`/workers/${workerId}/anonymize`, { method: "POST", body: { reason } }),
    onSuccess: () => {
      for (const key of [["worker", workerId], ["disputes"]]) void queryClient.invalidateQueries({ queryKey: key });
    },
  });
  if (erase.isSuccess) return <SuccessNote>{t("ops.erase.done")}</SuccessNote>;
  return (
    <div className="inline-form" style={{ borderLeft: "3px solid var(--color-destructive)" }}>
      <p className="small-text">{t("ops.erase.explain", { name })}</p>
      <label className="field" htmlFor={reasonId}>
        {t("ops.reason")} <span className="hint">{t("ops.erase.reasonHint")}</span>
        <input id={reasonId} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="row wrap">
        {confirming ? (
          <>
            <button className="danger small" onClick={() => erase.mutate()} disabled={erase.isPending}>
              {t("ops.erase.confirm")}
            </button>
            <button className="secondary small" onClick={() => setConfirming(false)}>
              {t("common.cancel")}
            </button>
          </>
        ) : (
          <button className="danger small" disabled={reason.trim().length < 10} onClick={() => setConfirming(true)}>
            {t("ops.erase.submit")}
          </button>
        )}
      </div>
      <ErrorNote error={erase.error} />
    </div>
  );
}

function DisputeCard({ dispute }: { dispute: Dispute }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const notesId = useId();
  const [notes, setNotes] = useState("");
  const [panel, setPanel] = useState<"override" | "erase" | null>(null);
  const worker = useQuery({
    queryKey: ["worker", dispute.worker_id],
    queryFn: () => api<WorkerView>(`/workers/${dispute.worker_id}`),
  });
  const resolve = useMutation({
    mutationFn: (resolution: string) =>
      api(`/disputes/${dispute.id}`, { method: "PATCH", body: { resolution, resolution_notes: notes } }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["disputes"] }),
  });
  const overdue = new Date(dispute.due_at) < new Date();
  const name = worker.data?.full_name ?? "…";
  const target = t(`targets.${dispute.target_type}`);
  const toggle = (which: "override" | "erase") => setPanel((current) => (current === which ? null : which));
  return (
    <article className="list-item">
      <div className="row between wrap">
        <div className="person">
          <Avatar name={name} />
          <div>
            <strong>{name}</strong>
            <p className="muted small-text">{t("ops.disputes.about", { target, date: date(dispute.created_at) })}</p>
          </div>
        </div>
        {dispute.status === "open" ? (
          <span className={overdue ? "pill pill-bad" : "pill pill-warn"}>
            <ClockCountdown size={14} aria-hidden="true" />
            {overdue ? t("ops.disputes.overdueSince", { date: date(dispute.due_at) }) : t("ops.disputes.due", { date: date(dispute.due_at) })}
          </span>
        ) : (
          <Status value={dispute.resolution ?? dispute.status} />
        )}
      </div>
      <p className="quote">{dispute.reason}</p>
      {dispute.status === "open" ? (
        <div className="stack" style={{ gap: 12 }}>
          <label className="field" htmlFor={notesId}>
            {t("ops.disputes.notes")}
            <span className="hint">{t("ops.disputes.notesHint")}</span>
            <textarea id={notesId} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          {dispute.target_type !== "standing_change" && (
            <p className="muted small-text">
              {dispute.target_type === "engagement" ? t("ops.disputes.upholdEngagement") : t("ops.disputes.upholdFeedback")}
            </p>
          )}
          <div className="row wrap">
            <button className="small" disabled={notes.trim().length < 10 || resolve.isPending} onClick={() => resolve.mutate("upheld")}>
              <Check size={16} aria-hidden="true" />
              {t("ops.disputes.uphold")}
            </button>
            <button
              className="secondary small"
              disabled={notes.trim().length < 10 || resolve.isPending}
              onClick={() => resolve.mutate("rejected")}
            >
              <X size={16} aria-hidden="true" />
              {t("ops.disputes.reject")}
            </button>
            <button className="ghost small" aria-expanded={panel === "override"} onClick={() => toggle("override")}>
              <SlidersHorizontal size={16} aria-hidden="true" />
              {t("ops.override.open")}
            </button>
            <button className="ghost small" aria-expanded={panel === "erase"} onClick={() => toggle("erase")}>
              <Trash size={16} aria-hidden="true" />
              {t("ops.erase.open")}
            </button>
          </div>
          {panel === "override" && <OverrideForm workerId={dispute.worker_id} />}
          {panel === "erase" && <EraseForm workerId={dispute.worker_id} name={name} />}
          <ErrorNote error={resolve.error} />
        </div>
      ) : (
        dispute.resolution_notes && (
          <p className="small-text">
            <strong>{t("ops.disputes.notesLabel")}</strong> {dispute.resolution_notes}
          </p>
        )
      )}
    </article>
  );
}

function Disputes() {
  const { t } = useTranslation();
  const [status, setStatus] = useState("open");
  const { data, error, isLoading } = useQuery({
    queryKey: ["disputes", status],
    queryFn: () => api<DisputePage>(`/disputes?status=${status}&limit=50`),
  });
  return (
    <Card
      title={t("ops.tabs.disputes")}
      icon={<Gavel size={20} aria-hidden="true" />}
      subtitle={t("ops.disputes.lead")}
      actions={
        <label className="field">
          <span className="sr-only">{t("ops.disputes.show")}</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">{t("status.open")}</option>
            <option value="resolved">{t("status.resolved")}</option>
          </select>
        </label>
      }
    >
      {isLoading && <Loading />}
      <ErrorNote error={error} />
      {data?.items.length === 0 && <Empty icon={<Gavel size={36} aria-hidden="true" />}>{t("ops.disputes.none")}</Empty>}
      {data?.items.map((d) => <DisputeCard key={d.id} dispute={d} />)}
    </Card>
  );
}

function AuditLog() {
  const { t } = useTranslation();
  const [action, setAction] = useState("");
  const query = useInfiniteQuery({
    queryKey: ["audit", action],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<AuditLogPage>(
        `/governance/audit-log?limit=25${action ? `&action=${encodeURIComponent(action)}` : ""}${
          pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""
        }`,
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = query.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Card
      title={t("ops.tabs.audit")}
      icon={<ListMagnifyingGlass size={20} aria-hidden="true" />}
      subtitle={t("ops.audit.lead")}
      actions={
        <div className="search-field">
          <ListMagnifyingGlass size={18} aria-hidden="true" />
          <input
            type="search"
            aria-label={t("ops.audit.filter")}
            placeholder={t("ops.audit.placeholder")}
            value={action}
            onChange={(e) => setAction(e.target.value.trim())}
          />
        </div>
      }
    >
      {query.isLoading && <Loading lines={5} />}
      <ErrorNote error={query.error} />
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="table audit">
            <thead>
              <tr>
                <th scope="col">{t("ops.audit.when")}</th>
                <th scope="col">{t("ops.audit.action")}</th>
                <th scope="col">{t("ops.audit.by")}</th>
                <th scope="col">{t("ops.audit.target")}</th>
                <th scope="col">{t("ops.audit.change")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="small-text num" style={{ whiteSpace: "nowrap" }}>
                    {dateTime(r.occurred_at)}
                  </td>
                  <td>
                    <code>{r.action}</code>
                  </td>
                  <td className="small-text">{r.actor_role ? t(`roles.${r.actor_role}`, { defaultValue: r.actor_role }) : t("ops.audit.system")}</td>
                  <td className="small-text">
                    {r.target_type} <code>{r.target_id.slice(0, 8)}</code>
                  </td>
                  <td className="small-text">
                    {r.before && <code>{JSON.stringify(r.before)}</code>}
                    {r.before && r.after && " → "}
                    {r.after && <code>{JSON.stringify(r.after)}</code>}
                    {r.reason && (
                      <div className="muted">
                        {t("ops.reason")}: {r.reason}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {query.hasNextPage && (
        <button className="secondary top-gap" onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage}>
          {query.isFetchingNextPage ? t("common.loading") : t("ops.audit.more")}
        </button>
      )}
    </Card>
  );
}

const TIER_ORDER = ["tier_2", "tier_1", "unrated"];

function OverviewTab() {
  const { t } = useTranslation();
  const { data, error, isLoading } = useQuery({
    queryKey: ["governance-overview"],
    queryFn: () => api<Overview>("/governance/overview"),
  });
  if (isLoading) return <Loading lines={5} />;
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;
  const org = data.concentration.find((r) => r.scope === "ORG");
  const tiers = org?.tier_counts ?? {};
  const pool = Object.values(tiers).reduce((a, b) => a + b, 0);
  return (
    <div className="stack">
      <dl className="stats overview-stats">
        <div className="stat">
          <dt>{t("ops.overview.repeatShare")}</dt>
          <dd className={org && org.share > data.alert_share ? "text-bad" : undefined}>{org ? percent(org.share) : "—"}</dd>
        </div>
        <div className="stat">
          <dt>{t("ops.overview.threshold")}</dt>
          <dd>{percent(data.alert_share)}</dd>
        </div>
        <div className="stat">
          <dt>{t("ops.overview.openDisputes")}</dt>
          <dd>{data.disputes.open}</dd>
        </div>
        <div className="stat">
          <dt>{t("ops.overview.overdue")}</dt>
          <dd className={data.disputes.overdue > 0 ? "text-bad" : undefined}>{data.disputes.overdue}</dd>
        </div>
      </dl>
      <Card
        title={t("ops.overview.concentration")}
        icon={<ChartBar size={20} aria-hidden="true" />}
        subtitle={t("ops.overview.concentrationLead", {
          days: data.window_days,
          min: data.repeat_min_engagements,
          version: data.policy_version,
        }) + (org ? ` ${t("ops.overview.lastRun", { date: date(org.period_end) })}` : "")}
      >
        {data.concentration.length === 0 ? (
          <Empty icon={<ChartBar size={36} aria-hidden="true" />}>{t("ops.overview.noRollup")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t("ops.overview.scope")}</th>
                  <th scope="col">{t("ops.overview.engagements")}</th>
                  <th scope="col">{t("ops.overview.repeat")}</th>
                  <th scope="col">{t("ops.overview.shown")}</th>
                  <th scope="col">{t("ops.overview.engaged")}</th>
                </tr>
              </thead>
              <tbody>
                {data.concentration.map((r) => (
                  <tr key={r.scope}>
                    <td>
                      <strong>{r.scope === "ORG" ? t("ops.overview.org") : r.scope}</strong>
                    </td>
                    <td className="num">{r.engagements_total}</td>
                    <td>
                      <div className="share">
                        <span className="num">{percent(r.share)}</span>
                        <div
                          className="sharebar"
                          role="img"
                          aria-label={t("ops.overview.shareAria", { share: percent(r.share), threshold: percent(data.alert_share) })}
                        >
                          <span className={r.share > data.alert_share ? "over" : ""} style={{ width: `${r.share * 100}%` }} />
                          <i style={{ left: `${data.alert_share * 100}%` }} />
                        </div>
                        {r.share > data.alert_share && (
                          <span className="pill pill-bad">
                            <WarningCircle size={14} aria-hidden="true" />
                            {t("ops.overview.above")}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="num">{r.first_shot_shown}</td>
                    <td className="num">
                      {r.first_shot_engaged}
                      {r.first_shot_shown > 0 && (
                        <span className="muted small-text"> ({percent(r.first_shot_engaged / r.first_shot_shown)})</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <div className="grid-2">
        <Card title={t("ops.overview.tiers")} subtitle={t("ops.overview.pool", { count: pool })}>
          {TIER_ORDER.map((tier) => {
            const n = tiers[tier] ?? 0;
            return (
              <div key={tier} className="dist-row">
                <TierBadge tier={tier} />
                <div className="distbar" aria-hidden="true">
                  <span className={`dist-${tier}`} style={{ width: pool ? `${(n / pool) * 100}%` : 0 }} />
                </div>
                <span className="num">
                  {n} <span className="muted small-text">({percent(pool ? n / pool : 0)})</span>
                </span>
              </div>
            );
          })}
        </Card>
        <Card title={t("ops.overview.disputes30")}>
          <dl className="stats">
            <div className="stat">
              <dt>{t("status.resolved")}</dt>
              <dd>{data.disputes.resolved_30d}</dd>
            </div>
            <div className="stat">
              <dt>{t("status.upheld")}</dt>
              <dd>{data.disputes.upheld_30d}</dd>
            </div>
            <div className="stat">
              <dt>{t("ops.overview.openNow")}</dt>
              <dd>{data.disputes.open}</dd>
            </div>
          </dl>
        </Card>
      </div>
    </div>
  );
}

function Policies() {
  const { t } = useTranslation();
  const kinds = ["tiering", "matching", "concentration", "retention"] as const;
  const results = {
    tiering: useQuery({ queryKey: ["policies", "tiering"], queryFn: () => api<PolicyVersion[]>("/policies/tiering/versions") }),
    matching: useQuery({ queryKey: ["policies", "matching"], queryFn: () => api<PolicyVersion[]>("/policies/matching/versions") }),
    concentration: useQuery({
      queryKey: ["policies", "concentration"],
      queryFn: () => api<PolicyVersion[]>("/policies/concentration/versions"),
    }),
    retention: useQuery({ queryKey: ["policies", "retention"], queryFn: () => api<PolicyVersion[]>("/policies/retention/versions") }),
  };
  return (
    <Card title={t("ops.tabs.policies")} icon={<FileText size={20} aria-hidden="true" />} subtitle={t("ops.policies.lead")}>
      {kinds.map((kind) => (
        <section key={kind} className="list-item">
          <h3 style={{ marginTop: 0 }}>{t(`ops.policies.kinds.${kind}`)}</h3>
          <ErrorNote error={results[kind].error} />
          {results[kind].data?.map((v) => (
            <details key={v.version} open={v.status === "active"}>
              <summary className="row" style={{ cursor: "pointer", minHeight: 44 }}>
                <strong>v{v.version}</strong> <Status value={v.status} />
                {v.notes && <span className="muted small-text">{v.notes}</span>}
              </summary>
              <pre>{JSON.stringify(v.rules, null, 2)}</pre>
            </details>
          ))}
        </section>
      ))}
    </Card>
  );
}

export default function Ops() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const tabs = me?.role === "admin" ? ["overview", "audit"] : ["overview", "disputes", "audit", "policies"];
  const [tab, setTab] = useState(tabs[0]);

  function onTabKey(event: KeyboardEvent) {
    const index = tabs.indexOf(tab);
    if (event.key === "ArrowRight") setTab(tabs[(index + 1) % tabs.length]);
    if (event.key === "ArrowLeft") setTab(tabs[(index - 1 + tabs.length) % tabs.length]);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">{t("nav.governance")}</p>
          <h1>{t("roles.people_ops")}</h1>
          <p>{t("ops.lead")}</p>
        </div>
        <div className="tabs" role="tablist" aria-label={t("ops.sections")} onKeyDown={onTabKey}>
          {tabs.map((name) => (
            <button
              key={name}
              role="tab"
              id={`tab-${name}`}
              aria-selected={name === tab}
              aria-controls={`panel-${name}`}
              tabIndex={name === tab ? 0 : -1}
              className="tab"
              onClick={() => setTab(name)}
            >
              {t(`ops.tabs.${name}`)}
            </button>
          ))}
        </div>
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "overview" && <OverviewTab />}
        {tab === "disputes" && <Disputes />}
        {tab === "audit" && <AuditLog />}
        {tab === "policies" && <Policies />}
      </div>
    </>
  );
}
