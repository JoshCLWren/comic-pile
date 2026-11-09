#![allow(clippy::unwrap_used, clippy::expect_used)]
#![allow(dead_code)]

//! Read-only regression-fixture DATA for the ComicPile Rust cutover.
//!
//! Provenance:
//! - 2026-11-04/05 B.P.R.D. outage: comic-pile issues #4651, #4654, #4656.
//! - 2026-11-05 morning destructive QA: issue #4670, finding R1.
//! - 2026-11-05 17:54-18:02 CST QA outage: issue #4670 evening comment
//!   https://github.com/JoshCLWren/comic-pile/issues/4670#issuecomment-6673272874
//!
//! THESE ARE FIXTURE VALUES, NOT COMPLETED TESTS. Connect the data to the real
//! Rust /api/v2 handlers, canonical Option E graph builder/validator, and the
//! Alembic-head PostgreSQL fixture. Do not implement a second test-only graph
//! engine or claim success by asserting only these constant arrays.
//!
//! Production numeric identifiers below are historical evidence and SHOULD
//! NOT be inserted with those PKs into a shared database. On a fresh isolated
//! test DB, allocate owned rows through INSERT ... RETURNING, map symbolic keys
//! to generated IDs, and use the original IDs only in test labels/provenance.

/// Original Issue.position order in B.P.R.D.: Hell on Earth thread #18874.
/// This is reader-authored and intentionally NOT numeric, not an error to fix.
pub const BPRD_THREAD_SOURCE_ID: i64 = 18874;
pub const BPRD_JULIX_STRICT_LIST_SOURCE_ID: i64 = 2;
pub const BPRD_CONTINUITY_PLAN_SOURCE_ID: i64 = 6;
pub const BPRD_BEFORE_ISSUE_NUMBERS: &[u16] = &[
    129, 140, 141, 142, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 143,
];
/// User attempted ONLY to add physical #101 and #102.
pub const BPRD_INSERTED_NUMBERS: &[u16] = &[101, 102];
/// WRONG result produced by the legacy all-numeric sort after insertion.
pub const BPRD_BROKEN_NUMERIC_ORDER: &[u16] = &[
    101, 102, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143,
];
/// The source-authoritative Julix list requires #142 before #130.
/// The wrong series reorder requires #130 ... #139 before #140 ... #142.
/// A graph walk must find this loop (provenance must not be lost):
///   142 --[Julix strict list #2]--> 130
///   130 -> 131 -> ... -> 139 -> 140 -> 141 -> 142
///           [thread #18874 natural series order]
pub const BPRD_CYCLE_PATH: &[u16] = &[
    142, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142,
];

/// Independent identity facts which must survive any repair.
/// The Return of the Master story-arc thread #18873 initially held Issue
/// records 117353..117357 for chapters #1..#5, corresponding to physical
/// B.P.R.D. #98..#102. Existing #3 is the physical #100. Comic Vine's
/// 4050-51622 volume labels chapters #3, #4, #5 as #100, #101, #102.
pub const RETURN_MASTER_THREAD_SOURCE_ID: i64 = 18873;
pub const RETURN_MASTER_ORIGINAL_IDS: &[i64] = &[117353, 117354, 117355, 117356, 117357];
pub const RETURN_MASTER_PHYSICAL_NUMBERS: &[u16] = &[98, 99, 100, 101, 102];
pub const RETURN_MASTER_COMICVINE_VOLUME: &str = "4050-51622";
pub const RETURN_MASTER_DUPLICATE_100_ID: i64 = 1121325;
pub const RETURN_MASTER_COMICVINE_100_ISSUE_ID: i64 = 364132;
pub const BPRD_DUPLICATE_101_102_IDS: &[i64] = &[1121326, 1121327];
/// Recorded later legitimate ratings of original story chapters #4/#5.
/// They are history to preserve, NOT state to rewind in a de-duplication fix.
pub const RETURN_MASTER_LATER_RATING_EVENT_IDS: &[i64] = &[1032543, 1032546];
pub const RETURN_MASTER_LATER_RATING: f32 = 4.5;

/// Three distinct source volumes for physical #103..#109, not a single
/// Comic Vine volume that covers them all.
pub const ABYSS_PHYSICAL_NUMBERS: &[u16] = &[103, 104];
pub const ABYSS_COMICVINE_VOLUME: &str = "4050-55555";
pub const COLD_DAY_PHYSICAL_NUMBERS: &[u16] = &[105, 106];
pub const WASTELAND_PHYSICAL_NUMBERS: &[u16] = &[107, 108, 109];

/// Morning QA destructive case: list #1000096, strict Superman 1-3 then
/// Batman 1-2. The original Superman #2 Issue ID is intentionally NOT known:
/// allocate a generated PK and retain it as a stable reference when a user
/// attempts an edit. Re-adding label "2" creates a DIFFERENT record unless
/// an explicit repair/relink is performed.
pub const QA_MORNING_PLAN_SOURCE_ID: i64 = 1000096;
pub const QA_MORNING_SUPERMAN: &[u16] = &[1, 2, 3];
pub const QA_MORNING_BATMAN: &[u16] = &[1, 2];

/// Exact production exception path from Muse's 2026-11-05 evening rerun.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EdgeOrigin {
    StrictList { source_list_id: i64 },
    NaturalSeries { source_thread_id: i64 },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DirectedConstraint {
    pub from_issue: i64,
    pub to_issue: i64,
    pub origin: EdgeOrigin,
}

pub const QA_EVENING_CYCLE: &[DirectedConstraint] = &[
    DirectedConstraint {
        from_issue: 1121031,
        to_issue: 1121101,
        origin: EdgeOrigin::StrictList {
            source_list_id: 1000111,
        },
    },
    DirectedConstraint {
        from_issue: 1121101,
        to_issue: 1121102,
        origin: EdgeOrigin::NaturalSeries {
            source_thread_id: 1019211,
        },
    },
    DirectedConstraint {
        from_issue: 1121102,
        to_issue: 1121328,
        origin: EdgeOrigin::StrictList {
            source_list_id: 1000109,
        },
    },
    DirectedConstraint {
        from_issue: 1121328,
        to_issue: 1121031,
        origin: EdgeOrigin::NaturalSeries {
            source_thread_id: 1019196,
        },
    },
];

/// The destructive QA plan was created at 17:54:51 CST and deleted at
/// 17:58:41. It does not follow that deleting a plan removed source list
/// #1000111 or every relevant edge. Previously healthy plan #1000097 was
/// still throwing a ReadingCycleError at 18:01:47-18:01:53 CST.
pub const QA_EVENING_NEW_PLAN_SOURCE_ID: i64 = 1000098;
pub const QA_EVENING_PRIOR_PLAN_SOURCE_ID: i64 = 1000097;
pub const QA_EVENING_STRICT_LIST_IDS: &[i64] = &[1000111, 1000109];

/// In integration tests, build a genuinely unrelated list and issue pair in
/// a separate thread for the *same test owner*. It MUST remain readable and
/// rollable if eligible even when the cycle above is persisted. Also create
/// a second owner to prove neither reads nor repairs cross owner boundaries.
pub const UNRELATED_FIXTURE_THREAD: &str = "QA Unrelated Healthy Series";
pub const UNRELATED_FIXTURE_ISSUE_NO: &str = "1";
