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

export function TierBadge({ tier }: { tier: string }) {
  return <span className={`tier tier-${tier}`}>{TIER_LABEL[tier] ?? tier}</span>;
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

export function statusTone(status: string): string {
  if (["active", "completed", "resolved", "upheld", "shortlisted", "engaged"].includes(status))
    return "good";
  if (["cancelled", "passed", "rejected", "unavailable"].includes(status)) return "bad";
  if (["pending_signature", "awaiting_signature", "open", "contacted"].includes(status))
    return "warn";
  return "neutral";
}

export function Status({ value }: { value: string }) {
  return <Pill tone={statusTone(value)}>{value.replaceAll("_", " ")}</Pill>;
}

export function Card({
  title,
  actions,
  children,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="error">{errorText(error)}</p>;
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
