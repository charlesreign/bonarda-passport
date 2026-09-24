import { CheckCircle, Info, SealCheck, ShieldStar, WarningCircle } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api, errorText, type Skill } from "./api";

export const TIER_LABEL: Record<string, string> = {
  unrated: "Unrated",
  tier_1: "Tier 1",
  tier_2: "Tier 2 · Trusted",
};

export const ANSWER_LABEL: Record<string, string> = {
  delivered_on_agreed_dates: "Delivered on the agreed dates",
  handled_scope_changes_without_escalation: "Handled scope changes without escalation",
  would_reengage: "Would engage again",
};

export function TierBadge({ tier, large = false, short = false }: { tier: string; large?: boolean; short?: boolean }) {
  const Icon = tier === "tier_2" ? ShieldStar : tier === "tier_1" ? SealCheck : null;
  return (
    <span className={`tier tier-${tier}${large ? " lg" : ""}`}>
      {Icon && <Icon size={large ? 18 : 14} weight="fill" aria-hidden="true" />}
      {short ? (TIER_LABEL[tier] ?? tier).split(" · ")[0] : (TIER_LABEL[tier] ?? tier)}
    </span>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

/** A verified skill carries a text mark as well as colour (never colour alone). */
export function SkillPill({ name, verified }: { name: string; verified: boolean }) {
  return (
    <Pill tone={verified ? "good" : "neutral"}>
      {verified && <SealCheck size={13} weight="fill" aria-hidden="true" />}
      {name}
      {verified && <span className="sr-only"> (verified)</span>}
    </Pill>
  );
}

export function statusTone(status: string): string {
  if (["active", "completed", "resolved", "upheld", "shortlisted", "engaged", "signed"].includes(status))
    return "good";
  if (["cancelled", "passed", "rejected", "unavailable"].includes(status)) return "bad";
  if (["pending_signature", "awaiting_signature", "open", "contacted"].includes(status)) return "warn";
  if (status === "shown") return "info";
  return "neutral";
}

export function Status({ value }: { value: string }) {
  return (
    <span className={`pill pill-${statusTone(value)}`}>
      <span className="status-dot" aria-hidden="true" />
      {value.replaceAll("_", " ")}
    </span>
  );
}

export function Card({
  title,
  subtitle,
  icon,
  actions,
  highlight = false,
  children,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  highlight?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={highlight ? "card highlight" : "card"}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && (
              <h2>
                {icon}
                {title}
              </h2>
            )}
            {subtitle && <p className="card-sub">{subtitle}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="alert alert-error" role="alert">
      <WarningCircle size={18} weight="bold" aria-hidden="true" />
      <span>{errorText(error)}</span>
    </div>
  );
}

export function SuccessNote({ children }: { children: ReactNode }) {
  return (
    <div className="alert alert-success" role="status">
      <CheckCircle size={18} weight="bold" aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}

export function InfoNote({ children }: { children: ReactNode }) {
  return (
    <div className="alert alert-info">
      <Info size={18} weight="bold" aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}

export function Empty({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="empty">
      {icon}
      <p>{children}</p>
    </div>
  );
}

export function Loading({ lines = 3 }: { lines?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  );
}

export function Avatar({ name, large = false }: { name: string; large?: boolean }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  return (
    <span className={large ? "avatar lg" : "avatar"} aria-hidden="true">
      {initials}
    </span>
  );
}

export function date(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));
}

export function dateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

/** Skill id → display name, for cards that only carry ids. */
export function useSkillNames(): (id: string) => string {
  const { data } = useQuery({
    queryKey: ["skills"],
    queryFn: () => api<Skill[]>("/skills?limit=100"),
    staleTime: 5 * 60_000,
  });
  const names = new Map((data ?? []).map((s) => [s.id, s.name_i18n.en ?? s.slug]));
  return (id: string) => names.get(id) ?? "…";
}

export function availabilityText(status: string, from: string | null): string {
  if (status === "available_from") return `Available from ${date(from)}`;
  return status === "available" ? "Available now" : "Unavailable";
}

export function labelFor(slug: string): string {
  return slug.replaceAll("-", " ").replace(/^\w/, (c) => c.toUpperCase());
}
