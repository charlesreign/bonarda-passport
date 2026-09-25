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

// ---- Shapes the screens use: aliases of the generated OpenAPI types ----
// Regenerate with `npm run gen:api` after a backend change; `npm run check:api`
// fails when openapi.json or the generated file is stale (contract drift).

import type { components } from "./api-schema";

type S = components["schemas"];

export type Role = S["UserRole"];
export type Me = S["MeResponse"];
export type Skill = S["SkillRead"];
export type WorkerSkill = S["WorkerSkill"];
export type WorkerSelf = S["WorkerSelf"];
export type WorkerView = S["WorkerSummary"] | S["WorkerDetail"] | S["WorkerSelf"];
export type Feedback = S["FeedbackRead"];
export type Engagement = S["EngagementRead-Output"];
export type StandingChange = S["StandingChangeRead"];
export type Standing = S["StandingExplanation"];
export type Project = S["ProjectRead"];
export type CandidateCard = S["CandidateCard"];
export type ScoreComponent = S["ScoreComponent"];
export type Candidate = S["Candidate"];
export type CandidatePage = S["CandidatePage"];
export type FirstShotItem = S["FirstShotItem"];
export type FirstShotPanel = S["FirstShotPanel"];
export type Dispute = S["DisputeRead"];
export type DisputePage = S["DisputePage"];
export type DisputeStatusRead = S["DisputeStatusRead"];
export type AuditEntry = S["AuditEntryRead"];
export type AuditLogPage = S["AuditLogPage"];
export type Consent = S["ConsentRead"];
export type Prefill = S["ReactivationPrefill"];
export type Overview = S["GovernanceOverview"];
export type Rollup = S["ConcentrationRollupRead"];
export type PolicyVersion = S["PolicyRead"];
export type DemoAccount = S["DemoAccount"];

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}
