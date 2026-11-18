export type Platform = 'wellfound' | 'uplers' | 'naukri' | 'hirist' | 'instahyre';
export type JobStatus = 'pending' | 'approved' | 'rejected';
export type RunStatus = 'running' | 'succeeded' | 'failed' | 'stopped';
export type ApplyMode = 'inherit' | 'dry' | 'live';

export const PLATFORMS: Platform[] = ['wellfound', 'uplers', 'naukri', 'hirist', 'instahyre'];

export interface RunRecord {
  id: string;
  kind: 'discovery' | 'apply';
  platform: string;
  started_at: string;
  status: RunStatus;
  finished_at: string | null;
  error: string | null;
  discovered: number;
  applied: number;
  log?: string;
}

export interface Blocker {
  code: string;
  blocks: string[];
  message: string;
  fix: string;
}

export interface Status {
  automation: {
    busy: boolean;
    paused: boolean;
    current: RunRecord | null;
    runs: RunRecord[];
    apply_mode: ApplyMode;
    discovery_limit: number;
    effective_dry_run: boolean;
    require_review: boolean;
  };
  counts: {
    discovered: number;
    pending: number;
    approved: number;
    rejected: number;
    applied: number;
    failures: number;
    questions: number;
  };
  by_platform: Record<
    string,
    { pending: number; approved: number; rejected: number; enabled: boolean; label: string }
  >;
  blockers: Blocker[];
  config: {
    resume: string;
    resume_exists: boolean;
    email: boolean;
    review_dir: string;
    min_inr_salary_lpa: number;
    one_job_per_company: boolean;
    skip_ineligible_salary: boolean;
    parallel_platforms: boolean;
  };
}

export interface Job {
  job_key: string;
  platform: string;
  job_id: string;
  title: string;
  company: string;
  url: string;
  status: JobStatus;
  easy_apply: boolean;
  external_ats: boolean;
  external_url: string | null;
  jd: string;
  cover_letter: string;
  salary_display: string;
  salary_eligible: boolean | null;
  salary_reason: string;
  location_blocked: boolean;
  resume: string;
  score: number;
  salary_score: number;
  profile_score: number;
  eligible: boolean | null;
  score_reason: string;
}

export interface ApplicationRow {
  job_key: string;
  manual?: boolean;
  applied_at: string;
  relative: string;
  ts: number;
  platform_key: string;
  platform: string;
  role: string;
  company: string;
  initial: string;
  avatar_color: string;
  family: string;
  status: string;
  job_id: string;
  url: string;
  reason: string;
}

export interface FailureRecord {
  source: string;
  title: string;
  company: string;
  url: string;
  reason: string;
  first_seen: string;
  last_seen: string;
  count: number;
}

export interface Preferences {
  paused: boolean;
  apply_mode: ApplyMode;
  discovery_limit: number;
  platforms: Record<string, { enabled: boolean | null; keywords: string }>;
}

export interface PreferencesResponse {
  preferences: Preferences;
  resolved: Record<string, boolean>;
  apply_modes: ApplyMode[];
  config_dry_run: boolean;
  config_jobs_per_platform: number;
  note: string;
}

export interface PlatformInfo {
  name: string;
  label: string;
  enabled: boolean;
  config_enabled: boolean;
  keywords: string;
  keywords_editable: boolean;
  search_urls: string[];
  feed_count: number;
}
