//! ComicVine candidate discovery and explainable matching.
//!
//! This module owns the matching heuristics described in #5434: title-tolerant
//! candidate discovery, flexible issue-label normalization, explainable scoring,
//! and partial series-level match planning. It is pure logic over in-memory
//! fixtures so tests can exercise the acceptance contract without provider I/O.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

/// A locally owned issue that needs a ComicVine candidate.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MatchIssue {
    pub issue_id: i32,
    pub series_name: String,
    pub issue_number: String,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    /// Optional explicit hints. These never restrict explicit user confirmation;
    /// they only help discovery rank candidates.
    pub volume_hint_ids: Vec<i32>,
    pub aliases: Vec<String>,
    /// CBL/source volume IDs known to belong to this series.
    pub source_volume_ids: Vec<i32>,
}

/// A ComicVine issue row available for matching.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProviderIssue {
    pub comicvine_issue_id: i32,
    pub comicvine_volume_id: i32,
    pub volume_name: String,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    pub issue_number: Option<String>,
    pub issue_name: Option<String>,
    pub aliases: Vec<String>,
}

/// A volume-level candidate discovered for a series.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct VolumeCandidate {
    pub comicvine_volume_id: i32,
    pub volume_name: String,
    pub publisher: Option<String>,
    pub start_year: Option<i32>,
    pub score: f64,
    pub evidence: Vec<String>,
}

/// A match decision for one issue against a provider issue.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct IssueMatch {
    pub issue_id: i32,
    pub comicvine_issue_id: i32,
    pub comicvine_volume_id: i32,
    pub score: f64,
    pub evidence: Vec<String>,
}

/// An issue that could not be matched unambiguously.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct UnmatchedIssue {
    pub issue_id: i32,
    pub issue_number: String,
    pub reason: String,
    pub next_steps: Vec<String>,
}

/// Partial series-level match result for one volume.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PartialSeriesMatch {
    pub volume: VolumeCandidate,
    pub matched: Vec<IssueMatch>,
    pub unmatched: Vec<UnmatchedIssue>,
    pub actionable_reason: String,
}

const EXACT_TITLE_BONUS: f64 = 0.22;
const FUZZY_TITLE_WEIGHT: f64 = 0.22;
const ISSUE_LABEL_EXACT: f64 = 0.34;
const ISSUE_LABEL_EQUIVALENT: f64 = 0.28;
const PUBLISHER_MATCH: f64 = 0.08;
const YEAR_MATCH: f64 = 0.05;
const YEAR_ADJACENT: f64 = 0.02;
const SIBLING_VOLUME_BONUS: f64 = 0.25;
const SOURCE_VOLUME_BONUS: f64 = 0.20;
const ALIAS_BONUS: f64 = 0.12;
const PUBLISHER_CONFLICT: f64 = -0.10;
const AMBIGUITY_MARGIN: f64 = 0.08;

fn normalize_ws(value: &str) -> String {
    value.split_whitespace().collect::<Vec<_>>().join(" ")
}

pub fn normalize_title(value: &str) -> String {
    let lowered = normalize_ws(&value.to_lowercase().replace('&', " and "));
    let mut out = String::with_capacity(lowered.len());
    let mut prev_space = false;
    for ch in lowered.chars() {
        let mapped = if ch.is_alphanumeric() { ch } else { ' ' };
        if mapped == ' ' {
            if !prev_space {
                out.push(' ');
                prev_space = true;
            }
        } else {
            out.push(mapped);
            prev_space = false;
        }
    }
    let spaced = out.trim().to_string();
    compact_acronym_tokens(&spaced)
}

/// Collapse runs of single-character tokens produced by punctuation-separated
/// acronyms: "b p r d" -> "bprd", but keep normal words separated.
fn compact_acronym_tokens(value: &str) -> String {
    let tokens: Vec<&str> = value.split_whitespace().collect();
    if tokens.is_empty() {
        return String::new();
    }
    let mut out = String::new();
    let mut i = 0;
    while i < tokens.len() {
        let is_single = tokens[i].chars().count() == 1;
        if is_single {
            let start = i;
            while i < tokens.len() && tokens[i].chars().count() == 1 {
                i += 1;
            }
            let run_len = i - start;
            if run_len >= 2 {
                if !out.is_empty() {
                    out.push(' ');
                }
                for t in &tokens[start..i] {
                    out.push_str(t);
                }
            } else {
                if !out.is_empty() {
                    out.push(' ');
                }
                out.push_str(tokens[start]);
            }
        } else {
            if !out.is_empty() {
                out.push(' ');
            }
            out.push_str(tokens[i]);
            i += 1;
        }
    }
    out
}

fn compact_title(value: &str) -> String {
    normalize_title(value).replace(' ', "")
}

fn title_tokens(value: &str) -> BTreeSet<String> {
    normalize_title(value)
        .split_whitespace()
        .filter(|t| !t.is_empty())
        .map(|t| t.to_string())
        .collect()
}

fn dice_coefficient(a: &str, b: &str) -> f64 {
    let na = normalize_title(a);
    let nb = normalize_title(b);
    if na.is_empty() || nb.is_empty() {
        return 0.0;
    }
    if na == nb {
        return 1.0;
    }
    let ca = compact_title(a);
    let cb = compact_title(b);
    if !ca.is_empty() && ca == cb {
        return 1.0;
    }
    let ta = title_tokens(a);
    let tb = title_tokens(b);
    if ta.is_empty() || tb.is_empty() {
        return 0.0;
    }
    let intersection = ta.intersection(&tb).count() as f64;
    let token_score = (2.0 * intersection) / (ta.len() as f64 + tb.len() as f64);
    // Also score by character bigrams on compact form for acronym/punctuation variance.
    let bigram_score = bigram_dice(&ca, &cb);
    token_score.max(bigram_score)
}

fn bigram_dice(a: &str, b: &str) -> f64 {
    fn bigrams(s: &str) -> Vec<String> {
        let chars: Vec<char> = s.chars().collect();
        if chars.len() < 2 {
            return vec![s.to_string()];
        }
        chars.windows(2).map(|w| w.iter().collect()).collect()
    }
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    if a == b {
        return 1.0;
    }
    let ba = bigrams(a);
    let bb = bigrams(b);
    let mut bcount: BTreeMap<&str, usize> = BTreeMap::new();
    // use owned strings - easier
    let ba_owned = ba;
    let bb_owned = bb;
    let mut map: BTreeMap<String, usize> = BTreeMap::new();
    for bg in &ba_owned {
        *map.entry(bg.clone()).or_insert(0) += 1;
    }
    let mut inter = 0usize;
    for bg in &bb_owned {
        if let Some(c) = map.get_mut(bg) {
            if *c > 0 {
                *c -= 1;
                inter += 1;
            }
        }
    }
    let _ = bcount;
    (2.0 * inter as f64) / (ba_owned.len() as f64 + bb_owned.len() as f64)
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct NormalizedIssueLabel {
    raw: String,
    canonical: String,
    kind: LabelKind,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum LabelKind {
    Numeric { value: String },
    Decimal { value: String },
    Fraction { numerator: u32, denominator: u32 },
    Annual { value: Option<String> },
    Special { value: Option<String> },
    PointOne { base: String, suffix: String },
    Text(String),
}

fn normalize_simple_label(value: &str) -> String {
    normalize_ws(&value.trim().trim_start_matches('#').to_lowercase())
}

fn parse_fraction(value: &str) -> Option<(u32, u32)> {
    let s = normalize_simple_label(value)
        .replace('\u{00BD}', "1/2")
        .replace('\u{00BC}', "1/4")
        .replace('\u{00BE}', "3/4");
    let (n, d) = s.split_once('/')?;
    let n = n.trim().parse::<u32>().ok()?;
    let d = d.trim().parse::<u32>().ok()?;
    if d == 0 { None } else { Some((n, d)) }
}

fn parse_numeric(value: &str) -> Option<String> {
    let s = normalize_simple_label(value);
    if s.is_empty() {
        return None;
    }
    if s.chars().all(|c| c.is_ascii_digit()) {
        let trimmed = s.trim_start_matches('0');
        return Some(if trimmed.is_empty() { "0".to_string() } else { trimmed.to_string() });
    }
    if let Some((a, b)) = s.split_once('.') {
        if !a.is_empty()
            && !b.is_empty()
            && a.chars().all(|c| c.is_ascii_digit())
            && b.chars().all(|c| c.is_ascii_digit())
        {
            let a_trim = a.trim_start_matches('0');
            let a_norm = if a_trim.is_empty() { "0" } else { a_trim };
            let b_trim = b.trim_end_matches('0');
            if b_trim.is_empty() {
                return Some(a_norm.to_string());
            }
            return Some(format!("{a_norm}.{b_trim}"));
        }
    }
    None
}

fn parse_point_one(value: &str) -> Option<(String, String)> {
    let s = normalize_simple_label(value);
    let (base, suffix) = s.split_once('.')?;
    let base_norm = parse_numeric(base)?;
    let suffix_norm = normalize_simple_label(suffix).replace(|c: char| !c.is_alphanumeric(), "");
    if suffix_norm.is_empty() || suffix_norm.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    Some((base_norm, suffix_norm.to_uppercase()))
}

fn extract_prefixed_number(prefix: &str, value: &str) -> Option<Option<String>> {
    let s = normalize_simple_label(value);
    let rest = s.strip_prefix(prefix)?;
    let rest = rest.trim_start_matches([' ', '#', '-', ':']).trim();
    if rest.is_empty() {
        return Some(None);
    }
    if let Some(n) = parse_numeric(rest) {
        return Some(Some(n));
    }
    let cleaned = rest.replace(|c: char| !c.is_alphanumeric(), "");
    if cleaned.is_empty() { Some(None) } else { Some(Some(cleaned.to_uppercase())) }
}

pub fn normalize_issue_label(value: &str) -> NormalizedIssueLabel {
    let raw = value.to_string();
    let simple = normalize_simple_label(value);
    if simple.is_empty() {
        return NormalizedIssueLabel { raw, canonical: String::new(), kind: LabelKind::Text(String::new()) };
    }
    if let Some((n, d)) = parse_fraction(&simple) {
        return NormalizedIssueLabel {
            canonical: format!("{n}/{d}"),
            raw,
            kind: LabelKind::Fraction { numerator: n, denominator: d },
        };
    }
    if let Some((base, suffix)) = parse_point_one(&simple) {
        return NormalizedIssueLabel {
            canonical: format!("{base}.{suffix}"),
            raw,
            kind: LabelKind::PointOne { base, suffix },
        };
    }
    if let Some(number) = parse_numeric(&simple) {
        let kind = if number.contains('.') {
            LabelKind::Decimal { value: number.clone() }
        } else {
            LabelKind::Numeric { value: number.clone() }
        };
        return NormalizedIssueLabel { canonical: number, raw, kind };
    }
    if let Some(num) = extract_prefixed_number("annual", &simple) {
        return NormalizedIssueLabel {
            canonical: match &num { Some(n) => format!("annual {n}"), None => "annual".to_string() },
            raw,
            kind: LabelKind::Annual { value: num },
        };
    }
    if let Some(num) = extract_prefixed_number("special", &simple) {
        return NormalizedIssueLabel {
            canonical: match &num { Some(n) => format!("special {n}"), None => "special".to_string() },
            raw,
            kind: LabelKind::Special { value: num },
        };
    }
    NormalizedIssueLabel {
        canonical: simple.clone(),
        raw,
        kind: LabelKind::Text(simple),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LabelMatch {
    Exact,
    Equivalent,
    None,
}

pub fn compare_issue_labels(local: &str, provider: &str) -> LabelMatch {
    let l = normalize_issue_label(local);
    let p = normalize_issue_label(provider);
    if l.canonical.is_empty() || p.canonical.is_empty() {
        return LabelMatch::None;
    }
    if l.canonical == p.canonical {
        return LabelMatch::Exact;
    }
    match (&l.kind, &p.kind) {
        (LabelKind::Numeric { value: a }, LabelKind::Decimal { value: b })
        | (LabelKind::Decimal { value: a }, LabelKind::Numeric { value: b }) => {
            if normalize_decimal(a) == normalize_decimal(b) { LabelMatch::Equivalent } else { LabelMatch::None }
        }
        (LabelKind::PointOne { base: ab, suffix: asuf }, LabelKind::PointOne { base: bb, suffix: bsuf }) => {
            if ab == bb && asuf == bsuf { LabelMatch::Exact } else { LabelMatch::None }
        }
        (LabelKind::Fraction { numerator: an, denominator: ad }, LabelKind::Fraction { numerator: bn, denominator: bd }) => {
            if an * bd == bn * ad { LabelMatch::Equivalent } else { LabelMatch::None }
        }
        (LabelKind::Fraction { numerator, denominator }, LabelKind::Decimal { value })
        | (LabelKind::Decimal { value }, LabelKind::Fraction { numerator, denominator }) => {
            if decimal_matches_fraction(value, *numerator, *denominator) {
                LabelMatch::Equivalent
            } else {
                LabelMatch::None
            }
        }
        (LabelKind::Annual { value: a }, LabelKind::Annual { value: b })
        | (LabelKind::Special { value: a }, LabelKind::Special { value: b }) => {
            if a == b { LabelMatch::Exact } else { LabelMatch::None }
        }
        (LabelKind::Text(a), LabelKind::Text(b)) => {
            if a == b { LabelMatch::Exact } else { LabelMatch::None }
        }
        _ => LabelMatch::None,
    }
}

fn normalize_decimal(value: &str) -> String {
    if let Some((a, b)) = value.split_once('.') {
        let a_trim = a.trim_start_matches('0');
        let a_norm = if a_trim.is_empty() { "0" } else { a_trim };
        let b_trim = b.trim_end_matches('0');
        if b_trim.is_empty() {
            a_norm.to_string()
        } else {
            format!("{a_norm}.{b_trim}")
        }
    } else {
        parse_numeric(value).unwrap_or_else(|| value.to_string())
    }
}

fn decimal_matches_fraction(value: &str, numerator: u32, denominator: u32) -> bool {
    let Some((int_part, frac_part)) = normalize_decimal(value).split_once('.').map(|(a, b)| (a.to_string(), b.to_string())) else {
        // integer decimal like "1" - only matches n/d if exact
        if let Ok(int_val) = normalize_decimal(value).parse::<i64>() {
            return int_val * denominator as i64 == numerator as i64;
        }
        return false;
    };
    // Compare value == numerator/denominator by cross-multiplying with decimal scale.
    let scale = 10_i64.pow(frac_part.len() as u32);
    let Ok(int_val) = int_part.parse::<i64>() else { return false };
    let Ok(frac_val) = frac_part.parse::<i64>() else { return false };
    let scaled = int_val.saturating_mul(scale).saturating_add(frac_val);
    scaled.saturating_mul(denominator as i64) == (numerator as i64).saturating_mul(scale)
}

fn normalized_publisher(value: &str) -> String {
    normalize_title(value)
}

pub fn discover_volume_candidates(issue: &MatchIssue, provider_issues: &[ProviderIssue]) -> Vec<VolumeCandidate> {
    let mut by_volume: BTreeMap<i32, Vec<&ProviderIssue>> = BTreeMap::new();
    for row in provider_issues {
        by_volume.entry(row.comicvine_volume_id).or_default().push(row);
    }
    let mut out = Vec::new();
    for (volume_id, rows) in by_volume {
        let Some(first) = rows.first() else { continue };
        let mut score = 0.0;
        let mut evidence = Vec::new();

        let mut best_title = 0.0f64;
        let mut best_title_name = first.volume_name.clone();
        let mut title_exact = false;
        let names_to_check: Vec<String> = std::iter::once(first.volume_name.clone())
            .chain(first.aliases.clone())
            .collect();
        for name in &names_to_check {
            let sim = dice_coefficient(&issue.series_name, name);
            if sim > best_title {
                best_title = sim;
                best_title_name = name.clone();
            }
            if normalize_title(&issue.series_name) == normalize_title(name) {
                title_exact = true;
            }
        }
        for alias in &issue.aliases {
            for name in &names_to_check {
                let sim = dice_coefficient(alias, name);
                if sim > best_title {
                    best_title = sim;
                    best_title_name = name.clone();
                }
                if normalize_title(alias) == normalize_title(name) {
                    title_exact = true;
                }
            }
        }

        if title_exact {
            score += EXACT_TITLE_BONUS;
            evidence.push(format!("exact title match: {}", best_title_name));
        } else if best_title >= 0.45 {
            let bonus = FUZZY_TITLE_WEIGHT * best_title;
            score += bonus;
            evidence.push(format!("fuzzy title match {:.0}%: {}", best_title * 100.0, best_title_name));
        }

        if issue.volume_hint_ids.contains(&volume_id) {
            score += SIBLING_VOLUME_BONUS;
            evidence.push("confirmed sibling issue is in this volume".to_string());
        }
        if issue.source_volume_ids.contains(&volume_id) {
            score += SOURCE_VOLUME_BONUS;
            evidence.push("CBL/source volume hint matches".to_string());
        }
        let alias_hit = issue.aliases.iter().any(|a| names_to_check.iter().any(|n| normalize_title(a) == normalize_title(n)));
        if alias_hit {
            score += ALIAS_BONUS;
            evidence.push("known alias matches volume name".to_string());
        }

        if let (Some(lp), Some(pp)) = (&issue.publisher, &first.publisher) {
            if normalized_publisher(lp) == normalized_publisher(pp) {
                score += PUBLISHER_MATCH;
                evidence.push(format!("publisher matches: {}", pp));
            } else if best_title < 0.80 {
                score += PUBLISHER_CONFLICT;
                evidence.push(format!("publisher differs: local={} provider={}", lp, pp));
            }
        }
        if let (Some(ly), Some(py)) = (issue.start_year, first.start_year) {
            if ly == py {
                score += YEAR_MATCH;
                evidence.push(format!("start year matches: {py}"));
            } else if (ly - py).abs() <= 1 {
                score += YEAR_ADJACENT;
                evidence.push(format!("start year adjacent: local={ly} provider={py}"));
            }
        }

        let has_issue_label_evidence = rows.iter().any(|r| {
            let Some(pn) = r.issue_number.as_deref().or(r.issue_name.as_deref()) else { return false };
            compare_issue_labels(&issue.issue_number, pn) != LabelMatch::None
        });
        if has_issue_label_evidence {
            evidence.push(format!("issue label {} present on volume", issue.issue_number));
        }

        // Do not surface volumes with no meaningful evidence.
        if score <= 0.0 && !has_issue_label_evidence {
            continue;
        }
        // If only issue label matched but title/publisher/year/hints gave nothing,
        // keep it only when there is at least some series-title signal.
        if score <= 0.0 && has_issue_label_evidence {
            if best_title >= 0.35 {
                score = 0.05;
                evidence.push("weak candidate: issue label exists but series evidence is weak".to_string());
            } else {
                continue;
            }
        }

        out.push(VolumeCandidate {
            comicvine_volume_id: volume_id,
            volume_name: first.volume_name.clone(),
            publisher: first.publisher.clone(),
            start_year: first.start_year,
            score: (score * 10000.0).round() / 10000.0,
            evidence,
        });
    }
    out.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal).then(a.comicvine_volume_id.cmp(&b.comicvine_volume_id)));
    out
}

pub fn match_issue_in_volume(issue: &MatchIssue, volume_id: i32, provider_issues: &[ProviderIssue]) -> Result<IssueMatch, UnmatchedIssue> {
    let mut candidates: Vec<IssueMatch> = Vec::new();
    for row in provider_issues.iter().filter(|r| r.comicvine_volume_id == volume_id) {
        let mut best = LabelMatch::None;
        let mut evidence = Vec::new();
        if let Some(num) = row.issue_number.as_deref() {
            let m = compare_issue_labels(&issue.issue_number, num);
            if m != LabelMatch::None {
                best = m;
                evidence.push(format!("issue number match: local={} provider={}", issue.issue_number, num));
            }
        }
        if best == LabelMatch::None {
            if let Some(name) = row.issue_name.as_deref() {
                let m = compare_issue_labels(&issue.issue_number, name);
                if m != LabelMatch::None {
                    best = m;
                    evidence.push(format!("issue name match: local={} provider={}", issue.issue_number, name));
                }
            }
        }
        let score = match best {
            LabelMatch::Exact => ISSUE_LABEL_EXACT,
            LabelMatch::Equivalent => ISSUE_LABEL_EQUIVALENT,
            LabelMatch::None => continue,
        };
        if best == LabelMatch::Equivalent {
            evidence.push("equivalent issue label normalization".to_string());
        }
        candidates.push(IssueMatch {
            issue_id: issue.issue_id,
            comicvine_issue_id: row.comicvine_issue_id,
            comicvine_volume_id: volume_id,
            score,
            evidence,
        });
    }
    candidates.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal).then(a.comicvine_issue_id.cmp(&b.comicvine_issue_id)));
    match candidates.as_slice() {
        [] => {
            let reason = format!(
                "volume {} found but issue {} not on it",
                volume_id, issue.issue_number
            );
            Err(UnmatchedIssue {
                issue_id: issue.issue_id,
                issue_number: issue.issue_number.clone(),
                reason,
                next_steps: default_next_steps(&issue.series_name),
            })
        }
        [one] => Ok(one.clone()),
        [first, second, ..] => {
            if first.score - second.score >= AMBIGUITY_MARGIN {
                Ok(first.clone())
            } else {
                Err(UnmatchedIssue {
                    issue_id: issue.issue_id,
                    issue_number: issue.issue_number.clone(),
                    reason: format!(
                        "ambiguous issue match for {} in volume {}: candidates {} and {}",
                        issue.issue_number, volume_id, first.comicvine_issue_id, second.comicvine_issue_id
                    ),
                    next_steps: default_next_steps(&issue.series_name),
                })
            }
        }
    }
}

fn default_next_steps(series_name: &str) -> Vec<String> {
    vec![
        format!("Search by a different name (try an alias for \"{}\")", series_name),
        "Paste a ComicVine volume or issue URL".to_string(),
        "Map the issue manually in the Identity Inbox".to_string(),
    ]
}

pub fn plan_partial_series_match(
    issues: &[MatchIssue],
    provider_issues: &[ProviderIssue],
) -> Vec<PartialSeriesMatch> {
    if issues.is_empty() {
        return Vec::new();
    }
    let representative = &issues[0];
    let volume_candidates = discover_volume_candidates(representative, provider_issues);
    let mut plans = Vec::new();
    for volume in volume_candidates {
        let mut matched = Vec::new();
        let mut unmatched = Vec::new();
        for issue in issues {
            match match_issue_in_volume(issue, volume.comicvine_volume_id, provider_issues) {
                Ok(m) => matched.push(m),
                Err(u) => unmatched.push(u),
            }
        }
        if matched.is_empty() && unmatched.iter().all(|u| u.reason.contains("not on it")) && volume.score < 0.15 {
            continue;
        }
        let actionable_reason = if unmatched.is_empty() {
            format!(
                "All {} issue(s) matched unambiguously in {} (volume {}).",
                matched.len(), volume.volume_name, volume.comicvine_volume_id
            )
        } else if !matched.is_empty() {
            format!(
                "Partial match in {} (volume {}): {} matched, {} need review.",
                volume.volume_name, volume.comicvine_volume_id, matched.len(), unmatched.len()
            )
        } else {
            format!(
                "No unambiguous issue matches in {} (volume {}): {} issue(s) need review.",
                volume.volume_name, volume.comicvine_volume_id, unmatched.len()
            )
        };
        plans.push(PartialSeriesMatch { volume, matched, unmatched, actionable_reason });
    }
    plans
}

pub fn explain_no_match(issue: &MatchIssue, provider_issues: &[ProviderIssue]) -> UnmatchedIssue {
    let volumes = discover_volume_candidates(issue, provider_issues);
    if volumes.is_empty() {
        return UnmatchedIssue {
            issue_id: issue.issue_id,
            issue_number: issue.issue_number.clone(),
            reason: format!("no volume found for title \"{}\"", issue.series_name),
            next_steps: default_next_steps(&issue.series_name),
        };
    }
    let best = &volumes[0];
    match match_issue_in_volume(issue, best.comicvine_volume_id, provider_issues) {
        Ok(_) => UnmatchedIssue {
            issue_id: issue.issue_id,
            issue_number: issue.issue_number.clone(),
            reason: "candidate found but requires explicit confirmation".to_string(),
            next_steps: default_next_steps(&issue.series_name),
        },
        Err(u) => u,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn issue(id: i32, series: &str, number: &str) -> MatchIssue {
        MatchIssue {
            issue_id: id,
            series_name: series.to_string(),
            issue_number: number.to_string(),
            publisher: None,
            start_year: None,
            volume_hint_ids: vec![],
            aliases: vec![],
            source_volume_ids: vec![],
        }
    }

    fn provider(id: i32, volume_id: i32, volume: &str, number: &str) -> ProviderIssue {
        ProviderIssue {
            comicvine_issue_id: id,
            comicvine_volume_id: volume_id,
            volume_name: volume.to_string(),
            publisher: None,
            start_year: None,
            issue_number: Some(number.to_string()),
            issue_name: None,
            aliases: vec![],
        }
    }

    #[test]
    fn normalizes_variant_issue_labels() {
        assert_eq!(compare_issue_labels("1.MU", "1.MU"), LabelMatch::Exact);
        assert_eq!(compare_issue_labels("1", "1.0"), LabelMatch::Exact);
        assert_eq!(compare_issue_labels("½", "1/2"), LabelMatch::Exact);
        assert_eq!(compare_issue_labels("½", "0.5"), LabelMatch::Equivalent);
        assert_eq!(compare_issue_labels("Annual 1", "annual #1"), LabelMatch::Exact);
        assert_eq!(compare_issue_labels("Special", "special"), LabelMatch::Exact);
    }

    #[test]
    fn mismatched_series_name_uses_fuzzy_title_and_alias() {
        let mut local = issue(1, "BPRD", "1");
        local.aliases.push("B.P.R.D.".to_string());
        let providers = vec![provider(100, 10, "B.P.R.D.", "1")];
        let volumes = discover_volume_candidates(&local, &providers);
        assert!(!volumes.is_empty());
        assert_eq!(volumes[0].comicvine_volume_id, 10);
        assert!(volumes[0].evidence.iter().any(|e| e.contains("fuzzy title") || e.contains("alias")));
    }

    #[test]
    fn variant_label_matches_in_volume() {
        let local = issue(1, "Hulk", "1.MU");
        let providers = vec![provider(200, 20, "Hulk", "1.MU")];
        let m = match_issue_in_volume(&local, 20, &providers).expect("match");
        assert_eq!(m.comicvine_issue_id, 200);
    }

    #[test]
    fn mixed_volume_series_produces_partial_match() {
        let issues = vec![issue(1, "Saga", "1"), issue(2, "Saga", "2"), issue(3, "Saga", "3")];
        let providers = vec![
            provider(101, 30, "Saga", "1"),
            provider(102, 30, "Saga", "2"),
            // issue 3 missing from volume 30
        ];
        let plans = plan_partial_series_match(&issues, &providers);
        assert!(!plans.is_empty());
        let plan = &plans[0];
        assert_eq!(plan.matched.len(), 2);
        assert_eq!(plan.unmatched.len(), 1);
        assert!(plan.actionable_reason.contains("Partial match"));
        assert!(plan.unmatched[0].reason.contains("not on it"));
    }

    #[test]
    fn explain_no_match_is_actionable() {
        let local = issue(1, "Totally Unknown Series", "1");
        let providers = vec![provider(100, 10, "Different", "1")];
        let u = explain_no_match(&local, &providers);
        assert!(u.reason.contains("no volume found"));
        assert!(!u.next_steps.is_empty());
        assert!(u.next_steps.iter().any(|s| s.to_lowercase().contains("different name")));
        assert!(u.next_steps.iter().any(|s| s.to_lowercase().contains("url")));
        assert!(u.next_steps.iter().any(|s| s.to_lowercase().contains("manual")));
    }

    #[test]
    fn volume_found_but_issue_missing_gives_actionable_reason() {
        let local = issue(1, "Saga", "1.MU");
        let providers = vec![provider(101, 30, "Saga", "1"), provider(102, 30, "Saga", "2")];
        let u = explain_no_match(&local, &providers);
        assert!(u.reason.contains("volume"));
        assert!(u.reason.contains("1.MU"));
        assert!(u.reason.contains("not on it"));
        assert!(!u.next_steps.is_empty());
    }

    #[test]
    fn bprd_hellboy_real_case_mismatched_name_maps() {
        // #4667/#4651 real cases: local naming often differs from ComicVine.
        // B.P.R.D. Hell on Earth #105-106 are A Cold Day in Hell parts 1-2.
        let mut i105 = issue(1051, "B.P.R.D. Hell on Earth", "105");
        i105.aliases = vec!["BPRD: Hell on Earth".to_string(), "B.P.R.D.: Hell on Earth".to_string()];
        let mut i106 = issue(1052, "B.P.R.D. Hell on Earth", "106");
        i106.aliases = i105.aliases.clone();
        let providers = vec![
            ProviderIssue {
                comicvine_issue_id: 391845,
                comicvine_volume_id: 4050_31409,
                volume_name: "B.P.R.D.: Hell on Earth".to_string(),
                publisher: Some("Dark Horse Comics".to_string()),
                start_year: Some(2010),
                issue_number: Some("105".to_string()),
                issue_name: Some("A Cold Day in Hell, Part 1".to_string()),
                aliases: vec![],
            },
            ProviderIssue {
                comicvine_issue_id: 397545,
                comicvine_volume_id: 4050_31409,
                volume_name: "B.P.R.D.: Hell on Earth".to_string(),
                publisher: Some("Dark Horse Comics".to_string()),
                start_year: Some(2010),
                issue_number: Some("106".to_string()),
                issue_name: Some("A Cold Day in Hell, Part 2".to_string()),
                aliases: vec![],
            },
        ];
        let plans = plan_partial_series_match(&[i105, i106], &providers);
        assert!(!plans.is_empty(), "should find a volume candidate");
        let plan = plans.iter().find(|p| p.volume.comicvine_volume_id == 4050_31409).expect("BPRD volume");
        assert_eq!(plan.matched.len(), 2, "both issues should match: {:?}", plan.unmatched);
        assert!(plan.unmatched.is_empty());
    }

    #[test]
    fn hellboy_mismatched_series_name_alias_maps() {
        let mut local = issue(1, "Hellboy", "1");
        local.aliases.push("Hellboy: Seed of Destruction".to_string());
        let providers = vec![ProviderIssue {
            comicvine_issue_id: 9001,
            comicvine_volume_id: 501,
            volume_name: "Hellboy: Seed of Destruction".to_string(),
            publisher: Some("Dark Horse Comics".to_string()),
            start_year: Some(1994),
            issue_number: Some("1".to_string()),
            issue_name: None,
            aliases: vec![],
        }];
        let volumes = discover_volume_candidates(&local, &providers);
        assert!(!volumes.is_empty());
        assert_eq!(volumes[0].comicvine_volume_id, 501);
        let m = match_issue_in_volume(&local, 501, &providers).expect("issue match");
        assert_eq!(m.comicvine_issue_id, 9001);
    }

    #[test]
    fn variant_label_fixture_point_one_fraction_annual() {
        let providers = vec![
            provider(201, 40, "Spider-Man", "1.MU"),
            provider(202, 40, "Spider-Man", "0.5"),
            provider(203, 40, "Spider-Man", "Annual 1"),
        ];
        let m1 = match_issue_in_volume(&issue(1, "Spider-Man", "1.MU"), 40, &providers).expect("point one");
        assert_eq!(m1.comicvine_issue_id, 201);
        let m2 = match_issue_in_volume(&issue(2, "Spider-Man", "½"), 40, &providers).expect("fraction");
        assert_eq!(m2.comicvine_issue_id, 202);
        let m3 = match_issue_in_volume(&issue(3, "Spider-Man", "Annual #1"), 40, &providers).expect("annual");
        assert_eq!(m3.comicvine_issue_id, 203);
    }
}
