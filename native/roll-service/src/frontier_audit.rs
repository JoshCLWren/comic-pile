//! Read-only Reading List engine frontier audit (#4198).
//!
//! Identifies the current unread frontier of every active queued Thread that
//! Reading List engine would offer today while an inert legacy or converted `dependencies`
//! row into that frontier from an incomplete source still records possible
//! reader intent. The report exists so a human can decide — manually — whether
//! a reader-authored prerequisite should be authored; it is never an execution
//! input:
//!
//! * Reader-authored `origin='reader'` prerequisites are the only actionable
//!   constraints. Every other dependency row (converted classifications,
//!   archival `cbl-order:` materializations, compiled `canonical:rule:`
//!   adjacency, legacy canonical imports with uncertain source data) stays
//!   inert evidence, exactly as #2366 and #3676 require.
//! * Nothing is blocked, promoted, retired or authored by this module, and no
//!   blanket conversion of the converted/legacy rows is suggested: findings
//!   name single rows and recommend manual review only.
//! * The frontier set comes from
//!   [`ValidatedReadingInputs::frontier_blockers`], the same Reading List engine authority
//!   Roll, Queue and the reading-boundary resources consume, so a frontier
//!   that any actionable constraint protects is never reported.
#![forbid(unsafe_code)]

use crate::{
    option_inputs::{LegacyDependencyRow, OptionInputs},
    reading_constraints::ValidatedReadingInputs,
};
use serde::Serialize;
use std::collections::BTreeMap;

/// Fixed recommendation carried by every finding: a human decides, not Roll.
pub const RECOMMEND_MANUAL_REVIEW: &str = "manual_review";

/// Report-only disclaimer. Converted and legacy rows stay inert (#2366, #3676);
/// only a present reader's own authoring can turn intent into a prerequisite.
pub const AUDIT_NOTE: &str = "Read-only evidence for manual review. Findings never block, \
promote or author prerequisites, and no blanket promotion of converted or legacy rows is \
suggested; only origin='reader' prerequisites have execution authority (#2366, #3676). \
Review each finding against present reader intent before any owner-approved data repair.";

/// Upper bound on findings in one response, mirroring the cycle reporting cap.
pub const MAX_REPORTED_FINDINGS: usize = 40;

/// One owned Reading List placement of the frontier issue, with its gate.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct AuditListMembership {
    pub list_id: i32,
    pub list_name: String,
    pub mode: String,
    pub gate: String,
    pub skipped: bool,
}

/// One inert legacy/converted dependency row into the frontier.
///
/// Source metadata is included only for issues the reader owns; a foreign
/// source keeps its stable row and issue identifiers but never a title,
/// number or status.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct AuditEvidenceEdge {
    pub dependency_id: i32,
    pub source_issue_id: i32,
    pub target_issue_id: i32,
    pub source_owned: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_issue_number: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_series_title: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub origin: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub classification: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provenance: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    pub evidence_class: String,
}

/// One unprotected current unread frontier with its inert evidence.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct FrontierAuditFinding {
    pub thread_id: i32,
    pub thread_title: String,
    pub frontier_issue_id: i32,
    pub frontier_issue_number: String,
    pub frontier_status: String,
    /// Owned Reading List placements of the frontier issue and their gates.
    pub list_memberships: Vec<AuditListMembership>,
    /// Inert dependency rows into this frontier from an incomplete source.
    pub legacy_evidence: Vec<AuditEvidenceEdge>,
    pub recommendation: String,
}

/// The complete read-only audit response for one owner.
#[derive(Debug, Clone, Serialize, utoipa::ToSchema)]
pub struct FrontierAuditReport {
    /// Live frontiers examined (active queued Threads, one next unread each).
    pub frontiers_examined: usize,
    /// Examined frontiers an actionable Reading List engine constraint currently blocks
    /// (reader prerequisite or list order).
    pub frontiers_protected: usize,
    /// Examined frontiers with no actionable Reading List engine constraint while inert
    /// legacy evidence records possible reader intent: the reported gaps.
    pub unprotected_frontiers: usize,
    /// The gap findings, bounded at [`MAX_REPORTED_FINDINGS`].
    pub findings: Vec<FrontierAuditFinding>,
    /// Findings beyond [`MAX_REPORTED_FINDINGS`] omitted from `findings`.
    pub findings_omitted: usize,
    /// Reader-authored prerequisites currently loaded with execution authority.
    pub actionable_reader_prerequisites: usize,
    /// Inert dependency rows examined (owned unread target, incomplete source).
    pub inert_evidence_rows: usize,
    /// Those rows grouped by evidence class.
    pub inert_evidence_counts: BTreeMap<String, usize>,
    /// Report-only disclaimer; the audit is never an execution input.
    pub note: String,
}

/// Classify one inert dependency row for the manual review report.
///
/// Reader-authored rows never reach this function (the diagnostics loader
/// excludes `origin='reader'`). The vocabulary follows the Reading List ADR
/// and `docs/DEPENDENCY_PROVENANCE_CENSUS.md`: archival `cbl-order:`
/// materializations, compiled `canonical:rule:` adjacency, converted
/// classifications A-D, and everything else as uncertain source data.
pub fn evidence_class(row: &LegacyDependencyRow) -> &'static str {
    if let Some(note) = row.note.as_deref() {
        if note.starts_with("cbl-order:") {
            return "archival_cbl_order";
        }
        if note.starts_with("canonical:rule:") || note.starts_with("canonical:rule-backfill:") {
            return "compiled_rule_adjacency";
        }
    }
    match (row.origin.as_deref(), row.classification.as_deref()) {
        (Some("converted"), Some("A")) => "converted_classification_a",
        (Some("converted"), Some("B")) => "converted_classification_b",
        (Some("converted"), Some("C")) => "converted_classification_c",
        (Some("converted"), Some("D")) => "converted_classification_d",
        (Some("converted"), _) => "uncertain_source_data",
        (None, _) => "legacy_canonical_unclassified",
        (Some(_), _) => "uncertain_source_data",
    }
}

/// Audit the validated Reading List engine inputs against the inert legacy evidence.
///
/// Pure and read-only: nothing in this function mutates state, and the report
/// never feeds eligibility. A frontier protected by any actionable Reading List engine
/// constraint (reader prerequisite or list order) is never reported.
pub fn audit_frontiers(
    inputs: &OptionInputs,
    validated: &ValidatedReadingInputs,
    legacy: &[LegacyDependencyRow],
) -> FrontierAuditReport {
    // Validated inputs cannot fail here; fail closed to an empty report
    // rather than guessing at frontiers.
    let Ok(frontiers) = validated.frontier_blockers() else {
        return FrontierAuditReport {
            frontiers_examined: 0,
            frontiers_protected: 0,
            unprotected_frontiers: 0,
            findings: vec![],
            findings_omitted: 0,
            actionable_reader_prerequisites: inputs.prerequisites.len(),
            inert_evidence_rows: legacy.len(),
            inert_evidence_counts: count_classes(legacy),
            note: AUDIT_NOTE.to_string(),
        };
    };

    let titles: BTreeMap<i32, String> = inputs
        .core
        .threads
        .iter()
        .map(|thread| (thread.id, thread.title.clone()))
        .collect();
    let issues: BTreeMap<i32, &crate::reading_inputs::ReadingIssue> = inputs
        .core
        .issues
        .iter()
        .map(|issue| (issue.id, issue))
        .collect();

    let mut findings = Vec::new();
    let mut protected = 0usize;
    let mut gaps = 0usize;
    for frontier in &frontiers {
        if !frontier.unsatisfied.is_empty() {
            // An actionable Reading List engine constraint protects this frontier.
            protected += 1;
            continue;
        }
        let evidence: Vec<&LegacyDependencyRow> = legacy
            .iter()
            .filter(|row| row.target_issue_id == frontier.issue_id)
            .collect();
        if evidence.is_empty() {
            continue;
        }
        gaps += 1;
        let Some(frontier_issue) = issues.get(&frontier.issue_id) else {
            continue;
        };
        let list_memberships = inputs
            .lists
            .iter()
            .filter_map(|list| {
                list.entries
                    .iter()
                    .find(|entry| entry.issue_id == frontier.issue_id)
                    .map(|entry| AuditListMembership {
                        list_id: list.list_id,
                        list_name: list.name.clone(),
                        mode: list.mode.clone(),
                        gate: entry.gate.clone(),
                        skipped: entry.skipped,
                    })
            })
            .collect();
        let legacy_evidence = evidence
            .into_iter()
            .map(|row| {
                let source = issues.get(&row.source_issue_id);
                AuditEvidenceEdge {
                    dependency_id: row.id,
                    source_issue_id: row.source_issue_id,
                    target_issue_id: row.target_issue_id,
                    source_owned: row.source_owned,
                    source_issue_number: source.map(|issue| issue.issue_number.clone()),
                    source_series_title: source
                        .and_then(|issue| titles.get(&issue.thread_id).cloned()),
                    source_status: source.map(|issue| issue.status.clone()),
                    origin: row.origin.clone(),
                    classification: row.classification.clone(),
                    provenance: row.provenance.clone(),
                    note: row.note.clone(),
                    evidence_class: evidence_class(row).to_string(),
                }
            })
            .collect();
        findings.push(FrontierAuditFinding {
            thread_id: frontier.thread_id,
            thread_title: titles
                .get(&frontier.thread_id)
                .cloned()
                .unwrap_or_else(|| format!("Thread {}", frontier.thread_id)),
            frontier_issue_id: frontier.issue_id,
            frontier_issue_number: frontier_issue.issue_number.clone(),
            frontier_status: frontier_issue.status.clone(),
            list_memberships,
            legacy_evidence,
            recommendation: RECOMMEND_MANUAL_REVIEW.to_string(),
        });
    }

    let findings_omitted = findings.len().saturating_sub(MAX_REPORTED_FINDINGS);
    findings.truncate(MAX_REPORTED_FINDINGS);
    FrontierAuditReport {
        frontiers_examined: frontiers.len(),
        frontiers_protected: protected,
        unprotected_frontiers: gaps,
        findings,
        findings_omitted,
        actionable_reader_prerequisites: inputs.prerequisites.len(),
        inert_evidence_rows: legacy.len(),
        inert_evidence_counts: count_classes(legacy),
        note: AUDIT_NOTE.to_string(),
    }
}

fn count_classes(legacy: &[LegacyDependencyRow]) -> BTreeMap<String, usize> {
    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    for row in legacy {
        *counts.entry(evidence_class(row).to_string()).or_insert(0) += 1;
    }
    counts
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::option_inputs::{OverlapDecision, Prerequisite, ReadingEntry, ReadingList};
    use crate::reading_constraints::ValidatedReadingInputs;
    use crate::reading_inputs::{
        CoreReadingInputs, ReadingIssue, ReadingThread, StoredThreadEligibility,
    };
    use std::collections::BTreeSet;

    /// The issue #4198 fixture chain:
    /// `UXM #360 (read) -> X-Men #80 (unread) -> X-Men #1/2 (unread) -> UXM #361 (unread)`.
    /// UXM #361 is the Uncanny X-Men frontier; X-Men #80 is the X-Men frontier.
    fn fixture_inputs() -> OptionInputs {
        OptionInputs {
            core: CoreReadingInputs {
                threads: vec![
                    ReadingThread {
                        id: 305,
                        status: "active".into(),
                        title: "Uncanny X-Men".into(),
                    },
                    ReadingThread {
                        id: 306,
                        status: "active".into(),
                        title: "X-Men".into(),
                    },
                ],
                issues: vec![
                    ReadingIssue {
                        id: 2028,
                        thread_id: 305,
                        position: 1,
                        status: "read".into(),
                        issue_number: "360".into(),
                    },
                    ReadingIssue {
                        id: 2029,
                        thread_id: 305,
                        position: 2,
                        status: "unread".into(),
                        issue_number: "361".into(),
                    },
                    ReadingIssue {
                        id: 2101,
                        thread_id: 306,
                        position: 1,
                        status: "unread".into(),
                        issue_number: "80".into(),
                    },
                    ReadingIssue {
                        id: 2102,
                        thread_id: 306,
                        position: 2,
                        status: "unread".into(),
                        issue_number: "1/2".into(),
                    },
                ],
                stored: vec![
                    StoredThreadEligibility {
                        thread_id: 305,
                        next_issue_id: Some(2029),
                        is_blocked: false,
                        queue_position: 1,
                    },
                    StoredThreadEligibility {
                        thread_id: 306,
                        next_issue_id: Some(2101),
                        is_blocked: false,
                        queue_position: 2,
                    },
                ],
            },
            thread_volumes: BTreeMap::new(),
            lists: vec![ReadingList {
                list_id: 7,
                mode: "loose".into(),
                name: "90s crossovers".into(),
                entries: vec![ReadingEntry {
                    issue_id: 2029,
                    gate: "none".into(),
                    skipped: false,
                }],
                overlap_decisions: vec![] as Vec<OverlapDecision>,
            }],
            prerequisites: vec![],
            excluded_issue_ids: BTreeSet::new(),
            unresolved: vec![],
        }
    }

    /// The legacy canonical edge from the issue: `X-Men #1/2 -> UXM #361`,
    /// `origin=NULL`, no classification, no provenance (Dependency 1860 shape).
    fn legacy_edge() -> LegacyDependencyRow {
        LegacyDependencyRow {
            id: 1860,
            source_issue_id: 2102,
            target_issue_id: 2029,
            origin: None,
            classification: None,
            provenance: None,
            note: None,
            source_owned: true,
        }
    }

    fn validated(inputs: OptionInputs) -> ValidatedReadingInputs {
        ValidatedReadingInputs::contained(
            inputs,
            &BTreeMap::from([(7, "90s crossovers".to_string())]),
        )
        .expect("fixture inputs validate")
    }

    #[test]
    fn unprotected_frontier_with_legacy_evidence_is_reported() {
        let inputs = fixture_inputs();
        let validated = validated(inputs.clone());
        // The Reading List engine authority offers UXM #361 today: the gap.
        let eligible: Vec<i32> = validated
            .eligible_frontiers()
            .expect("eligibility")
            .into_iter()
            .map(|frontier| frontier.issue_id)
            .collect();
        assert!(
            eligible.contains(&2029),
            "UXM #361 must be eligible before the correction"
        );
        assert!(eligible.contains(&2101), "X-Men #80 stays eligible");

        let report = audit_frontiers(&inputs, &validated, &[legacy_edge()]);
        assert_eq!(report.frontiers_examined, 2);
        assert_eq!(report.frontiers_protected, 0);
        assert_eq!(report.unprotected_frontiers, 1);
        assert_eq!(report.findings.len(), 1);
        let finding = &report.findings[0];
        assert_eq!(finding.thread_id, 305);
        assert_eq!(finding.frontier_issue_id, 2029);
        assert_eq!(finding.frontier_issue_number, "361");
        assert_eq!(finding.frontier_status, "unread");
        assert_eq!(finding.recommendation, "manual_review");
        assert_eq!(finding.list_memberships.len(), 1);
        assert_eq!(finding.list_memberships[0].list_id, 7);
        assert_eq!(finding.list_memberships[0].gate, "none");
        let edge = &finding.legacy_evidence[0];
        assert_eq!(edge.dependency_id, 1860);
        assert_eq!(edge.source_issue_id, 2102);
        assert_eq!(edge.source_status.as_deref(), Some("unread"));
        assert_eq!(edge.source_series_title.as_deref(), Some("X-Men"));
        assert_eq!(edge.evidence_class, "legacy_canonical_unclassified");
        assert!(report.note.contains("#2366"));
        assert!(report.note.contains("#3676"));
        assert_eq!(report.actionable_reader_prerequisites, 0);
        assert_eq!(report.inert_evidence_rows, 1);
    }

    #[test]
    fn authored_prerequisite_protects_frontier_and_leaves_other_thread_eligible() {
        let mut inputs = fixture_inputs();
        inputs.prerequisites.push(Prerequisite {
            prerequisite_id: 9001,
            source_issue_id: 2102,
            target_issue_id: 2029,
            origin: "reader".into(),
            provenance: vec!["Reader-authored through the Dependency Builder".to_string()],
        });
        let validated = validated(inputs.clone());
        let eligible: Vec<i32> = validated
            .eligible_frontiers()
            .expect("eligibility")
            .into_iter()
            .map(|frontier| frontier.issue_id)
            .collect();
        // Reading List engine blocks #361 until the authored prerequisite is read; the
        // unrelated X-Men frontier stays eligible.
        assert!(
            !eligible.contains(&2029),
            "UXM #361 must be blocked after authoring"
        );
        assert!(eligible.contains(&2101), "X-Men #80 must remain eligible");

        let report = audit_frontiers(&inputs, &validated, &[legacy_edge()]);
        assert!(
            report.findings.is_empty(),
            "a protected frontier must never be reported"
        );
        assert_eq!(report.actionable_reader_prerequisites, 1);
        assert_eq!(report.frontiers_protected, 1);
        assert_eq!(report.unprotected_frontiers, 0);
    }

    #[test]
    fn actionable_and_inert_rows_are_differentiated() {
        let inputs = fixture_inputs();
        let validated = validated(inputs.clone());
        let legacy = vec![
            legacy_edge(),
            LegacyDependencyRow {
                id: 1861,
                source_issue_id: 2102,
                target_issue_id: 2029,
                origin: None,
                classification: None,
                provenance: None,
                note: Some("cbl-order:legacy-materialization".to_string()),
                source_owned: true,
            },
            LegacyDependencyRow {
                id: 1862,
                source_issue_id: 2102,
                target_issue_id: 2029,
                origin: None,
                classification: None,
                provenance: None,
                note: Some("canonical:rule:31".to_string()),
                source_owned: true,
            },
            LegacyDependencyRow {
                id: 1863,
                source_issue_id: 2102,
                target_issue_id: 2029,
                origin: Some("converted".to_string()),
                classification: Some("C".to_string()),
                provenance: Some("generation evidence".to_string()),
                note: None,
                source_owned: true,
            },
        ];
        let report = audit_frontiers(&inputs, &validated, &legacy);
        assert_eq!(report.actionable_reader_prerequisites, 0);
        assert_eq!(report.inert_evidence_rows, 4);
        assert_eq!(
            report.inert_evidence_counts.get("archival_cbl_order"),
            Some(&1)
        );
        assert_eq!(
            report.inert_evidence_counts.get("compiled_rule_adjacency"),
            Some(&1)
        );
        assert_eq!(
            report
                .inert_evidence_counts
                .get("converted_classification_c"),
            Some(&1)
        );
        assert_eq!(
            report
                .inert_evidence_counts
                .get("legacy_canonical_unclassified"),
            Some(&1)
        );
        let finding = &report.findings[0];
        let classes: Vec<&str> = finding
            .legacy_evidence
            .iter()
            .map(|edge| edge.evidence_class.as_str())
            .collect();
        assert!(classes.contains(&"archival_cbl_order"));
        assert!(classes.contains(&"compiled_rule_adjacency"));
        assert!(classes.contains(&"converted_classification_c"));
    }

    #[test]
    fn foreign_source_keeps_ids_but_never_metadata() {
        let inputs = fixture_inputs();
        let validated = validated(inputs.clone());
        let foreign = LegacyDependencyRow {
            id: 1864,
            source_issue_id: 101875,
            target_issue_id: 2029,
            origin: None,
            classification: None,
            provenance: None,
            note: None,
            source_owned: false,
        };
        let report = audit_frontiers(&inputs, &validated, &[foreign]);
        let edge = &report.findings[0].legacy_evidence[0];
        assert!(!edge.source_owned);
        assert_eq!(edge.source_issue_id, 101875);
        assert!(edge.source_issue_number.is_none());
        assert!(edge.source_series_title.is_none());
        assert!(edge.source_status.is_none());
    }

    #[test]
    fn findings_are_bounded_and_omissions_counted() {
        // One gap per frontier: 45 extra independent threads plus the fixture
        // chain's UXM frontier, so 46 findings collapse to the 40 reported.
        let extra_threads = 45usize;
        let mut inputs = fixture_inputs();
        let mut legacy = vec![legacy_edge()];
        for offset in 0..extra_threads {
            let thread_id = 1000 + i32::try_from(offset).unwrap_or(i32::MAX);
            let source_id = 4000 + i32::try_from(offset * 2).unwrap_or(i32::MAX);
            let target_id = source_id + 1;
            inputs.core.threads.push(ReadingThread {
                id: thread_id,
                status: "active".into(),
                title: format!("Series {offset}"),
            });
            inputs.core.issues.push(ReadingIssue {
                id: source_id,
                thread_id,
                position: 1,
                status: "unread".into(),
                issue_number: "1".into(),
            });
            inputs.core.issues.push(ReadingIssue {
                id: target_id,
                thread_id,
                position: 2,
                status: "unread".into(),
                issue_number: "2".into(),
            });
            inputs.core.stored.push(StoredThreadEligibility {
                thread_id,
                next_issue_id: Some(source_id),
                is_blocked: false,
                queue_position: i32::try_from(3 + offset).unwrap_or(i32::MAX),
            });
            legacy.push(LegacyDependencyRow {
                id: 3000 + i32::try_from(offset).unwrap_or(i32::MAX),
                source_issue_id: target_id,
                target_issue_id: source_id,
                origin: None,
                classification: None,
                provenance: None,
                note: None,
                source_owned: true,
            });
        }
        let validated = validated(inputs.clone());
        let report = audit_frontiers(&inputs, &validated, &legacy);
        let expected_gaps = MAX_REPORTED_FINDINGS + 6;
        assert_eq!(report.findings.len(), MAX_REPORTED_FINDINGS);
        assert_eq!(report.findings_omitted, 6);
        assert_eq!(report.inert_evidence_rows, expected_gaps);
        assert_eq!(report.unprotected_frontiers, expected_gaps);
        assert_eq!(report.frontiers_examined, expected_gaps + 1);
    }

    #[test]
    fn excluded_or_protected_frontiers_are_not_examined_as_unprotected() {
        let mut inputs = fixture_inputs();
        // Excluding the frontier removes it from the live candidate set.
        inputs.excluded_issue_ids.insert(2029);
        let validated = validated(inputs.clone());
        let report = audit_frontiers(&inputs, &validated, &[legacy_edge()]);
        assert!(report.findings.is_empty());
        assert_eq!(report.frontiers_examined, 1);
        assert_eq!(report.frontiers_protected, 0);
        assert_eq!(report.unprotected_frontiers, 0);
    }
}
