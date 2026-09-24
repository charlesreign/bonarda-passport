// Thin fetch wrapper over /api/v1. The access token lives in memory only; the
// refresh token is an httpOnly cookie the browser sends to /api/v1/auth.

let accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function refreshSession(): Promise<boolean> {
  const response = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" });
  if (!response.ok) return false;
  accessToken = (await response.json()).access_token;
  return true;
}

type Options = { method?: string; body?: unknown; headers?: Record<string, string> };

export async function api<T>(path: string, options: Options = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = { ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const response = await fetch(`/api/v1${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    credentials: "include",
  });
  if (response.status === 401 && retry && (await refreshSession())) {
    return api<T>(path, options, false);
  }
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    const detail =
      problem.errors?.[0]?.msg ?? problem.detail ?? response.statusText ?? "Request failed";
    throw new ApiError(response.status, problem.code ?? "error", detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// ---- Shapes the screens use (a subset of the OpenAPI schema) ----

export type Role = "pm" | "people_ops" | "finance" | "worker" | "admin";

export interface Me {
  id: string;
  email: string;
  role: Role;
  worker_id: string | null;
  can_view_governance: boolean;
  locale: string;
}

export interface Skill {
  id: string;
  slug: string;
  name_i18n: Record<string, string>;
}

export interface WorkerSkill {
  skill_id: string;
  slug: string;
  verification_status: string;
}

export interface WorkerView {
  view: "summary" | "detail" | "self";
  id: string;
  full_name: string;
  worker_type: string;
  status: string;
  data_region: string;
  base_location: string | null;
  availability_status: string;
  available_from: string | null;
  standing_tier: string;
  skills: WorkerSkill[];
  languages?: string[];
  email?: string;
}

export interface Feedback {
  id: string;
  structured_answers: Record<string, boolean>;
  free_text: string | null;
  reviewer_id: string | null;
  created_at: string;
}

export interface Engagement {
  id: string;
  worker_id: string;
  project_id: string;
  path: string;
  status: string;
  start_date: string;
  end_date: string | null;
  rate: string;
  currency: string;
  work_mode: string;
  location: string | null;
  contract_terms: { scope: string; access_notes: string | null };
  stuck: boolean;
  feedback: Feedback | null;
}

export interface StandingChange {
  id: string;
  previous_tier: string;
  new_tier: string;
  factors: Record<string, unknown>;
  policy_version: number | null;
  automated: boolean;
  override_reason: string | null;
  occurred_at: string;
}

export interface Standing {
  worker_id: string;
  tier: string;
  evaluated_tier: string;
  policy_version: number;
  window_months: number;
  tiers: {
    tier: string;
    min_completed: number;
    min_distinct_reviewers: number;
    min_positive_ratio: number;
  }[];
  factors: {
    completed: number;
    distinct_reviewers: number;
    positive_ratio: number;
    window_start: string;
  };
  history: StandingChange[];
}

export interface Project {
  id: string;
  name: string;
  client_name: string | null;
  data_region: string;
  required_skill_ids: string[];
  starts_on: string | null;
  ends_on: string | null;
  status: string;
  staff_ids: string[];
}

export interface CandidateCard {
  worker_id: string;
  display_name: string;
  standing_tier: string;
  verified_skill_ids: string[];
  self_reported_skill_ids: string[];
  availability_status: string;
  available_from: string | null;
  base_location: string | null;
  engagements_total: number;
}

export interface ScoreComponent {
  weight: number;
  value: number;
  points: number;
}

export interface Candidate {
  worker: CandidateCard;
  score: number;
  score_breakdown: {
    verified_skills: ScoreComponent;
    self_reported_skills: ScoreComponent;
    availability: ScoreComponent;
    tier: ScoreComponent;
    total: number;
    policy_version: number;
  };
}

export interface FirstShotItem {
  worker: CandidateCard;
  outcome: string;
  reason_code: string | null;
}

export interface Dispute {
  id: string;
  worker_id: string;
  target_type: string;
  target_id: string;
  reason: string;
  status: string;
  resolution: string | null;
  resolution_notes: string | null;
  resolved_at: string | null;
  due_at: string;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface AuditEntry {
  id: number;
  occurred_at: string;
  actor_id: string | null;
  actor_role: string | null;
  action: string;
  target_type: string;
  target_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
}

export interface Consent {
  purpose: string;
  granted: boolean;
}

export interface Prefill {
  prefilled_from_engagement_id: string;
  rate: string;
  currency: string;
  work_mode: string;
  location: string | null;
  contract_terms: { scope: string };
  last_days_to_start: number | null;
}
