/**
 * ComicVine mapping types for the frontend
 */

export interface ComicVineMappingHealth {
  status: ComicVineMappingStatus;
  tracked_issue_count: number;
  confirmed_issue_count: number;
  needs_mapping_count: number;
  needs_review_count: number;
}

export type ComicVineMappingStatus = 
  | "not_applicable" 
  | "fully_mapped" 
  | "partial" 
  | "unresolved" 
  | "needs_review";

export interface IssueIdentityMapping {
  issue_id: number;
  comicvine_issue_id: string;
  confirmed_at?: string;
  metadata?: Record<string, any>;
}

export interface IssueIdentityResponse {
  issue_id: number;
  thread_id: number;
  thread_title: string;
  has_confirmed_identity: boolean;
  comicvine_issue_id: string | null;
  confirmed_mappings: IssueIdentityMapping[];
  candidate_mappings: IssueIdentityMapping[];
  has_unresolved: boolean;
}

export interface SeriesMappingPreview {
  thread_id: number;
  series_title: string;
  comicvine_volume_id: string;
  comicvine_series_title: string;
  comicvine_publisher: string;
  comicvine_start_year: number;
  safe_mappings: IssueIdentityMapping[];
  conflicts: IssueIdentityMapping[];
  excluded_special_issues: IssueIdentityMapping[];
  needs_review: IssueIdentityMapping[];
}

export interface SeriesMappingCommitRequest {
  thread_id: number;
  comicvine_volume_id: string;
  confirmed_mappings: IssueIdentityMapping[];
  reason?: string;
}