/**
 * ComicVine mapping health types for the frontend queue surface.
 */

export type ComicVineMappingStatus =
  | "not_applicable"
  | "fully_mapped"
  | "partial"
  | "unresolved"
  | "needs_review";

export interface ComicVineMappingHealth {
  status: ComicVineMappingStatus;
  tracked_issue_count: number;
  confirmed_issue_count: number;
  needs_mapping_count: number;
  needs_review_count: number;
}
