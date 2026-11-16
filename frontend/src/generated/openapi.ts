        NativeSourceSyncFailure: {
            error: string;
            /** Format: int32 */
            plan_id: number;
            /** Format: int32 */
            source_id: number;
            /** Format: int32 */
            thread_id: number;
            /** Format: int32 */
            volume_id: number;
        };
        NativeSyncReport: {
            /** Format: int64 */
            checked_sources: number;
            /** Format: int64 */
            conflicts: number;
            /** Format: int64 */
            created_issues: number;
            /** Format: int64 */
            enabled_sources: number;
            /** Format: int64 */
            excluded_issues?: number;
            /** Format: int64 */
            excluded_sources?: number;
            /** Format: int64 */
            failed_sources: number;
            failures: components["schemas"]["NativeSourceSyncFailure"][];
            /** Format: int64 */
            future_skips: number;
            /** Format: int64 */
            issue_failures: number;
            /** Format: int64 */
            issues_checked: number;
            /** Format: int64 */
            reused_issues: number;
            /** Format: int64 */
            skipped_sources?: number;
            /** Format: int64 */
            successful_sources: number;
            /** Format: int64 */
            total_sources: number;
            /** Format: int64 */
            unknown_date_skips: number;
        };
        NativeSyncRequest: {
            /** Format: date-time */
            as_of: string;
            refresh?: boolean;
        };
        NativeSyncResponse: {
            message: string;
            result: components["schemas"]["NativeSyncReport"];
            success: boolean;
        };
        NativeSyncStatusResponse: {
            /** Format: int64 */
            enabled_sources: number;
            sources: components["schemas"]["NativeSyncStatusSource"][];
            /** Format: int64 */
            total_sources: number;
        };
        NativeSyncStatusSource: {
            enabled: boolean;
            /** Format: int32 */
            external_identity_id: number;
            /** Format: int32 */
            id: number;
            last_synced_at?: string | null;
            provider_volume_id: string;
            /** Format: int32 */
            reading_plan_id: number;
            /** Format: int32 */
            thread_id: number;
        };
        /** @description One prompt-eligible inferred taste pattern shown on Roll. */
        NativeTasteDiscovery: {
            display_name: string;
            /** Format: int32 */
            distinct_thread_count: number;
            /** Format: int32 */
            evidence_count: number;
            external_key: string;
            /** Format: int32 */
            id: number;
            prompt: string;
            signal_type: string;
        };
        /** @description Ranked prompt-eligible discoveries for the authenticated reader. */
        NativeTasteDiscoveryListResponse: {
            discoveries: components["schemas"]["NativeTasteDiscovery"][];
            /** Format: date-time */
            generated_at: string;
        };
        NearMatch: {
            color: string;
            /** Format: int32 */
            id: number;
            name: string;
            normalized_name: string;
            scope: string;
        };
        /**
         * OverlapDecisionItem
         * @description One stored reader-approved overlap choice inside one Reading List.
         */
        OverlapDecisionItem: {
            /** Continuing Volume Id */
            continuing_volume_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: number;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Waiting Volume Id */
            waiting_volume_id: string;
        };
        /**
         * OverlapDecisionSetResponse
         * @description One owned Reading List's overlap decisions and their version token.
         *
         *     ``updated_at`` is the version of this list's decision set. It changes only
         *     when an approved choice changes, so an ordinary membership upsert never
         *     invalidates a stored choice.
         */
        OverlapDecisionSetResponse: {
            /** Candidate Volumes */
            candidate_volumes?: components["schemas"]["OverlapVolumeCandidate"][];
            /** Decisions */
            decisions?: components["schemas"]["OverlapDecisionItem"][];
            /** List Id */
            list_id: number;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * OverlapDecisionWrite
         * @description One reader-approved overlap choice for one owned Reading List.
         */
        OverlapDecisionWrite: {
            /**
             * Continuing Volume Id
             * @description Exact Comic Vine volume allowed to keep progressing.
             */
            continuing_volume_id: string;
            /**
             * Expected Updated At
             * @description Optimistic-concurrency token from GET ``updated_at``. When present, a mismatch returns 409 ``reading_overlap_version_conflict``.
             */
            expected_updated_at?: string | null;
            /**
             * Waiting Volume Id
             * @description Exact Comic Vine volume allowed to keep waiting.
             */
            waiting_volume_id: string;
        };
        /**
         * OverlapVolumeCandidate
         * @description One owned Thread with the exact Comic Vine volume it resolves to.
         */
        OverlapVolumeCandidate: {
            /** Thread Id */
            thread_id: number;
            /** Thread Title */
            thread_title: string;
            /** Volume Id */
            volume_id: string;
        };
        /**
         * OverrideRequest
         * @description Schema for manual thread override.
         */
        OverrideRequest: {
            /** Thread Id */
            thread_id: number;
        };
        /** @description Safe acknowledgement returned whether or not an account exists. */
        PasswordResetResponse: {
            message: string;
        };
        PlanReaderBlocker: {
            explanation: string;
            /** Format: int32 */
            issue_id: number;
            issue_number: string;
            /** Format: int32 */
            thread_id: number;
            thread_title: string;
        };
        PlanReaderIssue: {
            availability: string;
            blockers: components["schemas"]["PlanReaderBlocker"][];
            /** Format: int32 */
            display_position: number;
            is_checkpoint: boolean;
            /** Format: int32 */
            issue_id: number;
            issue_number: string;
            lane_id: string;
            occurrence_id: string;
            source_paths: string[];
            status: string;
            /** Format: int32 */
            thread_id: number;
            thread_title: string;
        };
        PlanReaderLane: {
            id: string;
            issues: components["schemas"]["PlanReaderIssue"][];
            name: string;
            /** Format: int32 */
            order: number;
        };
        PlanReaderProgress: {
            read_issues: number;
            total_issues: number;
        };
        PlanReaderResponse: {
            available_now: components["schemas"]["PlanReaderIssue"][];
            blocked_next: components["schemas"]["PlanReaderIssue"][];
            execution_mode: string;
            lanes: components["schemas"]["PlanReaderLane"][];
            name: string;
            ordering_mode: string;
            /** Format: int32 */
            plan_id: number;
            progress: components["schemas"]["PlanReaderProgress"];
            release_candidates: components["schemas"]["PlanReleaseCandidate"][];
            release_sources: components["schemas"]["PlanReleaseSourceStatus"][];
            sources: components["schemas"]["PlanReaderSource"][];
        };
        PlanReaderSource: {
            adopted_at?: string | null;
            content_hash?: string | null;
            display_name?: string | null;
            /** Format: int32 */
            id: number;
            raw_source_path: string;
            recorded_at: string;
            repository?: string | null;
            revision_sha?: string | null;
            source_path?: string | null;
        };
        PlanRecoveryPreview: {
            candidates: components["schemas"]["RecoveryCandidate"][];
            /** Format: int32 */
            linked_list_id?: number | null;
            /** Format: int32 */
            plan_id: number;
            plan_name: string;
            plan_updated_at: string;
            retained_steps: components["schemas"]["RecoveryStep"][];
            /** @description A linked plan is not eligible for destructive association changes. */
            status: string;
        };
        PlanReleaseCandidate: {
            enableable: boolean;
            /** Format: int32 */
            external_identity_id?: number | null;
            followed: boolean;
            mapping_state: string;
            mapping_status?: string | null;
            /** Format: int32 */
            provider_issue_count?: number | null;
            provider_publisher?: string | null;
            /** Format: int32 */
            provider_start_year?: number | null;
            provider_title?: string | null;
            provider_volume_id?: string | null;
            /** Format: int32 */
            thread_id: number;
            thread_title: string;
        };
        PlanReleaseSourceStatus: {
            enabled: boolean;
            /** Format: int32 */
            external_identity_id: number;
            last_synced_at?: string | null;
            /** Format: int32 */
            provider_issue_count?: number | null;
            provider_publisher?: string | null;
            /** Format: int32 */
            provider_start_year?: number | null;
            provider_title?: string | null;
            provider_volume_id: string;
            /** Format: int32 */
            source_id: number;
            /** Format: int32 */
            thread_id: number;
        };
        PlanRelinkRequest: {
            /** @description Explicit confirmation of the candidate's membership and order differences. */
            confirm: boolean;
            expected_list_updated_at: string;
            expected_plan_updated_at: string;
            /** Format: int32 */
            list_id: number;
        };
        PlanRelinkResult: {
            /** Format: int32 */
            list_id: number;
            /** Format: int32 */
            plan_id: number;
            status: string;
        };
        /**
         * @description Why the Roll pool has no in-play faces.
         *
         *     Derived from the already-loaded Option E inputs and the eligible frontier
         *     set. This is a single reason, never a list or a whole-library report, and it
         *     adds no database work: it exists so a genuinely non-empty library does not
         *     render the false "reading queue is empty" state (#4441).
         * @enum {string}
         */
        PoolReason: "ready" | "no_series" | "all_blocked" | "all_completed" | "all_out_of_pool";
        /**
         * PotentialDuplicateMatch
         * @description One existing series that may already represent the proposed series.
         *
         *     Advisory only: a title resemblance is never treated as identity, and nothing
         *     about an existing series is merged, deleted, or rewritten by producing this
         *     match.
         */
        PotentialDuplicateMatch: {
            /**
             * Comicvine Volume Id
             * @description ComicVine volume the existing series is confirmed as, when known. For a title-only match this is context, never proof of identity.
             */
            comicvine_volume_id?: number | null;
            /**
             * Format
             * @description Normalized format of the existing series
             */
            format: string;
            /**
             * Issues Remaining
             * @description Unread issues on the existing series
             */
            issues_remaining: number;
            /** @description ``same_comicvine_volume`` only when canonical provider identity matches; ``similar_title`` is an uncertain suggestion */
            match_type: components["schemas"]["PotentialDuplicateMatchType"];
            /**
             * Start Year
             * @description Confirmed ComicVine publication start year, when known
             */
            start_year?: number | null;
            /**
             * Status
             * @description Current status of the existing series
             */
            status: string;
            /**
             * Thread Id
             * @description Stable ID of the reader's existing thread
             */
            thread_id: number;
            /**
             * Title
             * @description Display title of the existing series
             */
            title: string;
            /**
             * Total Issues
             * @description Tracked issue total, or None for counter-based series
             */
            total_issues?: number | null;
        };
        /**
         * PotentialDuplicateMatchType
         * @description How strongly an existing series resembles the proposed series.
         * @enum {string}
         */
        PotentialDuplicateMatchType: "same_comicvine_volume" | "similar_title";
        /** @description One release ledger record returned by public-facing endpoints. */
        PublicReleaseResponse: {
            body?: string | null;
            category: string;
            /** Format: date-time */
            created_at: string;
            /** Format: int32 */
            id: number;
            /** Format: date-time */
            released_at: string;
            /** Format: int32 */
            sort_order: number;
            summary: string;
            title: string;
            /** Format: date-time */
            updated_at: string;
        };
        /** @description Resource patch for one queue entry. */
        QueueEntryPatch: {
            /**
             * Format: int32
             * @description Target reader-visible ordinal. Ranks beyond the end place the entry last.
             */
            position: number;
        };
        /** @description Queue entry resource returned by GET and PATCH. */
        QueueEntryResponse: {
            /**
             * Format: int64
             * @description Content revision of the reader's current queue order.
             *
             *     Derived from the durable ordering state on every read, so it changes
             *     whenever any writer changes the order and stays equal while the order is
             *     unchanged. It is a change-detection token, not a persisted per-entry
             *     counter and not the #3227 sparse order key.
             */
            ordering_version: number;
            /**
             * Format: int32
             * @description One-based dense reader-visible Queue ordinal.
             */
            position: number;
            /**
             * Format: int32
             * @description Canonical queue-entry identity: the owned Thread id.
             */
            thread_id: number;
        };
        /** @description Queue-order (shuffle) creation request. */
        QueueOrderRequest: {
            /** @description Client retry key. Replaying a committed key returns the same revision. */
            idempotency_key?: string | null;
        };
        /** @description Durable queue-order revision. */
        QueueOrderResponse: {
            /**
             * Format: int32
             * @description Persisted `events.id` of this queue-order revision.
             */
            event_id: number;
            /** @description True when an identical `idempotency_key` was already committed. */
            replayed: boolean;
            /**
             * Format: int32
             * @description Number of entries whose position this revision wrote.
             */
            shuffled: number;
        };
        /**
         * QueueSeriesMetadata
         * @description Confirmed provider series metadata projected for one Queue row.
         *
         *     Values come only from the reader-owned Thread's own confirmed provider
         *     series identity. A value that is not stored stays ``None`` instead of being
         *     inferred from the display title or a provider numeric id.
         */
        QueueSeriesMetadata: {
            /**
             * Publisher
             * @description Confirmed publisher name
             */
            publisher?: string | null;
            /**
             * Volume
             * @description Confirmed provider run/volume name when it adds identification beyond the thread title. Never a fabricated numeric volume.
             */
            volume?: string | null;
            /**
             * Year
             * @description Confirmed publication/start year.
             */
            year?: number | null;
        };
        /**
         * QueueThreadListItem
         * @description Schema for a single thread in the list/queue view.
         *
         *     A deliberate subset of ThreadResponse. The list view does not need
         *     detail-only fields like last_rating, is_test, or reading_progress,
         *     which reduces payload size for large lists. Queue rows additionally carry
         *     series metadata projected only from the thread's own confirmed provider
         *     identity, so readers can tell same-titled runs apart (issue #3605).
         */
        QueueThreadListItem: {
            /**
             * Blocking Reasons
             * @default []
             */
            blocking_reasons: string[];
            comicvine_mapping?: components["schemas"]["ComicVineMappingHealth"] | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Format */
            format: string;
            /** Id */
            id: number;
            /**
             * Is Blocked
             * @default false
             */
            is_blocked: boolean;
            /** Issues Remaining */
            issues_remaining: number;
            /** Last Activity At */
            last_activity_at: string | null;
            /** Manual Creator Credits */
            manual_creator_credits?: {
                name: string;
                roles: string[];
            }[];
            /** Next Unread Issue Number */
            next_unread_issue_number?: string | null;
            /** Notes */
            notes?: string | null;
            /** Queue Position */
            queue_position: number;
            /** @description Confirmed provider series metadata for this thread. ``None`` means the reader-owned thread has no confirmed series identity (unmapped series). */
            series_metadata?: components["schemas"]["QueueSeriesMetadata"] | null;
            /** Status */
            status: string;
            /** Tags */
            tags?: components["schemas"]["TagResponse"][];
            /** Title */
            title: string;
            /** Total Issues */
            total_issues?: number | null;
        };
        /**
         * QueueThreadListResponse
         * @description Schema for paginated thread list response using the queue-optimized item.
         *
         *     ``active_count`` is the authoritative total number of active threads in the
         *     user's queue. It is computed from the whole queue, never from the loaded
         *     page, and is independent of any search or sort filter (see issue #2568).
         */
        QueueThreadListResponse: {
            /**
             * Active Count
             * @default 0
             */
            active_count: number;
            /** Next Page Token */
            next_page_token?: string | null;
            /** Threads */
            threads: components["schemas"]["QueueThreadListItem"][];
        };
        /**
         * ReactivateRequest
         * @description Schema for reactivating a completed thread.
         */
        ReactivateRequest: {
            /** Issues To Add */
            issues_to_add: number;
            /** Thread Id */
            thread_id: number;
        };
        /**
         * ReaderContextCrossover
         * @description One owned crossover relevant to the requested issue's thread.
         */
        ReaderContextCrossover: {
            /** Applies To Current Issue */
            applies_to_current_issue: boolean;
            /** Average Rating */
            average_rating?: number | null;
            /** Id */
            id: number;
            /**
             * Membership Kind
             * @enum {string}
             */
            membership_kind: "issue" | "thread";
            /** Name */
            name: string;
            next_member?: components["schemas"]["ReaderContextCrossoverNextMember"] | null;
            /**
             * Ratings Count
             * @default 0
             */
            ratings_count: number;
            /**
             * Read Count
             * @default 0
             */
            read_count: number;
        };
        /**
         * ReaderContextCrossoverMembership
         * @description One exact crossover membership held by an owned issue.
         */
        ReaderContextCrossoverMembership: {
            /** Id */
            id: number;
            /** Name */
            name: string;
        };
        /**
         * ReaderContextCrossoverNextMember
         * @description The nearest future exact member of a crossover in the current thread.
         */
        ReaderContextCrossoverNextMember: {
            /** Issue Id */
            issue_id: number;
            /** Issue Number */
            issue_number: string;
        };
        /**
         * ReaderContextEdge
         * @description One persisted one-hop dependency or continuity edge.
         */
        ReaderContextEdge: {
            /** Explanation */
            explanation?: string | null;
            /** Id */
            id: number;
            /**
             * Kind
             * @enum {string}
             */
            kind: "dependency" | "continuity";
            /** Note */
            note?: string | null;
            /** Source Issue Id */
            source_issue_id: number;
            /** Source Issue Number */
            source_issue_number?: string | null;
            /** Source Label */
            source_label?: string | null;
            /** Source Status */
            source_status?: string | null;
            /** Source Thread Id */
            source_thread_id?: number | null;
            /** Source Thread Title */
            source_thread_title?: string | null;
            /** Target Issue Id */
            target_issue_id: number;
            /** Target Issue Number */
            target_issue_number?: string | null;
            /** Target Label */
            target_label?: string | null;
            /** Target Status */
            target_status?: string | null;
            /** Target Thread Id */
            target_thread_id?: number | null;
            /** Target Thread Title */
            target_thread_title?: string | null;
        };
        /**
         * ReaderContextLocalChain
         * @description The bounded local reading neighborhood around the requested issue.
         */
        ReaderContextLocalChain: {
            /** Edges */
            edges?: components["schemas"]["ReaderContextEdge"][];
            /** Issues */
            issues?: components["schemas"]["ReaderContextLocalIssue"][];
        };
        /**
         * ReaderContextLocalIssue
         * @description One bounded local-chain issue centered on the requested issue.
         */
        ReaderContextLocalIssue: {
            /** Crossover Memberships */
            crossover_memberships?: components["schemas"]["ReaderContextCrossoverMembership"][];
            /** Issue Id */
            issue_id: number;
            /** Issue Number */
            issue_number: string;
            /** Position */
            position: number;
            /** Rating */
            rating?: number | null;
            /**
             * Relation
             * @enum {string}
             */
            relation: "previous" | "current" | "next" | "future";
            /** Status */
            status: string;
        };
        /**
         * ReaderContextPreviousIssue
         * @description The immediately preceding issue inside the requested issue's thread.
         */
        ReaderContextPreviousIssue: {
            /** Issue Id */
            issue_id: number;
            /** Issue Number */
            issue_number: string;
            /** Rating */
            rating?: number | null;
        };
        /**
         * ReaderContextRecentRating
         * @description One effective series rating ordered by its effective event timestamp.
         */
        ReaderContextRecentRating: {
            /** Issue Id */
            issue_id: number;
            /** Issue Number */
            issue_number: string;
            /** Rating */
            rating: number;
        };
        /**
         * ReaderContextResponse
         * @description Bounded reader-context for one owned issue.
         */
        ReaderContextResponse: {
            /** Crossovers */
            crossovers?: components["schemas"]["ReaderContextCrossover"][];
            /** Issue Id */
            issue_id: number;
            local_chain: components["schemas"]["ReaderContextLocalChain"];
            series: components["schemas"]["ReaderContextSeries"];
        };
        /**
         * ReaderContextSeries
         * @description Canonical-series reading analytics for the requested issue.
         */
        ReaderContextSeries: {
            /** Average Rating */
            average_rating?: number | null;
            /** Canonical Series Id */
            canonical_series_id?: string | null;
            /** Highest Rating */
            highest_rating?: number | null;
            /**
             * Identity Source
             * @enum {string}
             */
            identity_source: "comicvine" | "unavailable";
            /** Lowest Rating */
            lowest_rating?: number | null;
            previous_issue?: components["schemas"]["ReaderContextPreviousIssue"] | null;
            /**
             * Ratings Count
             * @default 0
             */
            ratings_count: number;
            /** Recent Ratings */
            recent_ratings?: components["schemas"]["ReaderContextRecentRating"][];
            /** Series Name */
            series_name?: string | null;
        };
        /**
         * ReadingBoundaryBatchRequest
         * @description Owned series IDs to explain in one request.
         */
        ReadingBoundaryBatchRequest: {
            /** Thread Ids */
            thread_ids: number[];
        };
        /**
         * ReadingBoundaryBatchResponse
         * @description Canonical explanations keyed by Thread ID.
         */
        ReadingBoundaryBatchResponse: {
            /** Threads */
            threads: {
                [key: string]: components["schemas"]["ReadingBoundaryExplanation"];
            };
        };
        ReadingBoundaryBatchResponseV2: {
            threads: {
                [key: string]: components["schemas"]["ReadingBoundaryExplanationV2"];
            };
        };
        /**
         * ReadingBoundaryBlocker
         * @description One live Option E requirement that currently blocks the next Issue.
         */
        ReadingBoundaryBlocker: {
            editor?: components["schemas"]["BoundaryEditorTarget"] | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "strict_order" | "hold" | "after_previous" | "prerequisite";
            /**
             * Origin
             * @enum {string}
             */
            origin: "reading_list" | "reader_prerequisite";
            /** Reason */
            reason: string;
            /** Waiting On */
            waiting_on?: components["schemas"]["BoundaryIssue"][];
        };
        /**
         * ReadingBoundaryExplanation
         * @description Canonical explanation of one series' reading boundaries.
         */
        ReadingBoundaryExplanation: {
            /** Blockers */
            blockers?: components["schemas"]["ReadingBoundaryBlocker"][];
            /** Historical */
            historical?: components["schemas"]["ReadingBoundaryHistorical"][];
            next?: components["schemas"]["ReadingBoundaryNext"] | null;
            /**
             * State
             * @enum {string}
             */
            state: "blocked" | "available" | "complete" | "unavailable";
            /** Summary */
            summary: string;
            /** Thread Id */
            thread_id: number;
        };
        ReadingBoundaryExplanationV2: {
            blockers: components["schemas"]["NativeReadingBoundaryBlocker"][];
            next?: null | components["schemas"]["NativeReadingBoundaryNext"];
            state: components["schemas"]["BoundaryState"];
            summary: string;
            /** Format: int32 */
            thread_id: number;
        };
        /**
         * ReadingBoundaryHistorical
         * @description A reader-owned association that is not a live blocker.
         *
         *     Historical rows never gate execution. They are listed so the reader can
         *     see an old association without it being presented as a live boundary.
         */
        ReadingBoundaryHistorical: {
            /** Detail */
            detail: string;
            editor?: components["schemas"]["BoundaryEditorTarget"] | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "converted_prerequisite" | "legacy_dependency" | "skipped_entry";
            /** Label */
            label: string;
        };
        /**
         * ReadingBoundaryNext
         * @description The Issue the reader may read now.
         */
        ReadingBoundaryNext: {
            editor?: components["schemas"]["BoundaryEditorTarget"] | null;
            issue: components["schemas"]["BoundaryIssue"];
        };
        /**
         * ReadingGraphBlocker
         * @description One active unread restriction in the reader's language.
         */
        ReadingGraphBlocker: {
            /** Explanation */
            explanation: string;
            /** Gate Issue Id */
            gate_issue_id?: number | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "strict_order" | "hold" | "after_previous" | "prerequisite";
            /** List Id */
            list_id?: number | null;
            /** Waiting On Issue Ids */
            waiting_on_issue_ids?: number[];
        };
        /**
         * ReadingGraphChoiceEffect
         * @description Prospective effect of one answer to a genuine series conflict.
         */
        ReadingGraphChoiceEffect: {
            /**
             * Choice
             * @enum {string}
             */
            choice: "protect_order" | "continue_series";
            /** Detail */
            detail: string;
            /** Label */
            label: string;
            /** Rollable Issue Ids */
            rollable_issue_ids?: number[];
            /** Series */
            series?: components["schemas"]["ReadingGraphSeriesNode"][];
            /** Waiting Issue Ids */
            waiting_issue_ids?: number[];
        };
        /** @description One cycle with its concrete edge path. */
        ReadingGraphCycle: {
            edges: components["schemas"]["ReadingGraphEdge"][];
            message: string;
        };
        /**
         * ReadingGraphCycleError
         * @description A cycle or invalid relationship rejected before any write.
         */
        ReadingGraphCycleError: {
            /** Code */
            code: string;
            /** Message */
            message: string;
        };
        /** @description One stored requirement that participates in a cycle. */
        ReadingGraphEdge: {
            kind: string;
            /** Format: int32 */
            list_id?: number | null;
            list_name?: string | null;
            origin: string;
            /** Format: int32 */
            prerequisite_id?: number | null;
            source: components["schemas"]["ReadingGraphIssue"];
            target: components["schemas"]["ReadingGraphIssue"];
        };
        /** @description One issue endpoint as a reader sees it, never a bare database identifier. */
        ReadingGraphIssue: {
            /** Format: int32 */
            issue_id: number;
            issue_number: string;
            series_title: string;
            /** Format: int32 */
            thread_id: number;
        };
        /**
         * ReadingGraphIssueReference
         * @description One concrete comic the prospective graph may name as waiting or rollable.
         */
        ReadingGraphIssueReference: {
            /** Blockers */
            blockers?: components["schemas"]["ReadingGraphBlocker"][];
            /** Comicvine Volume Id */
            comicvine_volume_id?: string | null;
            /** Issue Id */
            issue_id: number;
            /** Issue Number */
            issue_number: string;
            /** Series Name */
            series_name: string;
        };
        /** @description One affected Reading List. */
        ReadingGraphList: {
            /** Format: int32 */
            list_id: number;
            mode: string;
            name: string;
        };
        /**
         * ReadingGraphOverlap
         * @description One conflict between two exact volumes in the prospective list.
         */
        ReadingGraphOverlap: {
            /** Blocked Issue Ids */
            blocked_issue_ids?: number[];
            /** Choices */
            choices?: components["schemas"]["ReadingGraphChoiceEffect"][];
            continuing_series: components["schemas"]["ReadingGraphSeriesReference"];
            /** Overlap Id */
            overlap_id: string;
            /** Question */
            question: string;
            /** Selected Choice */
            selected_choice?: ("protect_order" | "continue_series") | null;
            waiting_series: components["schemas"]["ReadingGraphSeriesReference"];
        };
        /**
         * ReadingGraphOverlapChoice
         * @description One answer the reader has already given during this preview session.
         */
        ReadingGraphOverlapChoice: {
            /**
             * Choice
             * @enum {string}
             */
            choice: "protect_order" | "continue_series";
            /** Overlap Id */
            overlap_id: string;
        };
        /**
         * ReadingGraphPreview
         * @description Complete read-only graph preview for one source selection.
         */
        ReadingGraphPreview: {
            /** Content Hash */
            content_hash: string;
            /** Cycle Errors */
            cycle_errors?: components["schemas"]["ReadingGraphCycleError"][];
            /** Issues */
            issues?: components["schemas"]["ReadingGraphIssueReference"][];
            /** Overlaps */
            overlaps?: components["schemas"]["ReadingGraphOverlap"][];
            /** Revision Sha */
            revision_sha: string;
            /** Rollable Issue Ids */
            rollable_issue_ids?: number[];
            /** Series */
            series?: components["schemas"]["ReadingGraphSeriesNode"][];
            /** Source List Id */
            source_list_id: number;
            /** Waiting Issue Ids */
            waiting_issue_ids?: number[];
        };
        /**
         * ReadingGraphPreviewRequest
         * @description Read-only request: included source positions plus answers already given.
         */
        ReadingGraphPreviewRequest: {
            /** Included Positions */
            included_positions?: number[];
            /** Overlap Choices */
            overlap_choices?: components["schemas"]["ReadingGraphOverlapChoice"][];
            /** Target List Id */
            target_list_id?: number | null;
        };
        /** @description One owner-scoped repair the reader can preview and apply. */
        ReadingGraphRepairOption: {
            action: string;
            detail: string;
            /** Format: int32 */
            issue_id?: number | null;
            label: string;
            /** Format: int32 */
            list_id?: number | null;
            /** Format: int32 */
            prerequisite_id?: number | null;
        };
        /** @description Flat wire request so a preview never depends on tagged-enum deserialization. */
        ReadingGraphRepairRequest: {
            action: string;
            /** @description Preview by default. A repair applies only when this is explicitly true. */
            confirm?: boolean;
            /** Format: int32 */
            issue_id?: number | null;
            /** Format: int32 */
            list_id?: number | null;
            /** Format: int32 */
            prerequisite_id?: number | null;
        };
        ReadingGraphRepairResponse: {
            applied: boolean;
            graph: components["schemas"]["ReadingGraphResponse"];
            removed: string;
            status_after: string;
            status_before: string;
        };
        /** @description Complete graph state. `status` is `ok`, `cycle`, or `invalid`. */
        ReadingGraphResponse: {
            affected_lists: components["schemas"]["ReadingGraphList"][];
            affected_threads: components["schemas"]["ReadingGraphThread"][];
            cycles: components["schemas"]["ReadingGraphCycle"][];
            cyclic_issue_ids: number[];
            repairs: components["schemas"]["ReadingGraphRepairOption"][];
            status: string;
            unresolved_reference_count: number;
        };
        /**
         * ReadingGraphSeriesNode
         * @description One series node with its prospective eligibility totals.
         */
        ReadingGraphSeriesNode: {
            /** Comicvine Volume Id */
            comicvine_volume_id: string;
            /** Rollable Count */
            rollable_count: number;
            /** Series Name */
            series_name: string;
            /**
             * State
             * @enum {string}
             */
            state: "continues" | "waits" | "mixed";
            /** Unread Count */
            unread_count: number;
            /** Waiting Count */
            waiting_count: number;
            /** Waits For Issue Ids */
            waits_for_issue_ids?: number[];
            /** Year */
            year?: number | null;
        };
        /**
         * ReadingGraphSeriesReference
         * @description Exact Comic Vine series/volume identity plus reader-facing labels.
         */
        ReadingGraphSeriesReference: {
            /** Comicvine Volume Id */
            comicvine_volume_id: string;
            /** Series Name */
            series_name: string;
            /** Year */
            year?: number | null;
        };
        /** @description One affected Thread. */
        ReadingGraphThread: {
            /** Format: int32 */
            thread_id: number;
            title: string;
        };
        ReadingList: {
            created_at: string;
            description?: string | null;
            entries: components["schemas"]["ReadingListEntry"][];
            /** Format: int32 */
            id: number;
            /** Format: int32 */
            issue_count: number;
            mode: string;
            name: string;
            updated_at: string;
            /** Format: int32 */
            user_id: number;
        };
        ReadingListBlockerExplanation: {
            blocking_dependencies: components["schemas"]["ReadingListDependency"][];
            blocking_reasons: string[];
            is_blocked: boolean;
        };
        ReadingListDependency: {
            /** Format: int32 */
            issue_id?: number | null;
            issue_number: string;
            label: string;
            /** Format: int32 */
            thread_id: number;
            thread_title: string;
        };
        ReadingListEntry: {
            checkpoint_target_issue_ids: number[];
            gate: string;
            /** Format: int32 */
            id: number;
            is_checkpoint: boolean;
            /** Format: int32 */
            issue_id: number;
            issue_number: string;
            /** Format: int32 */
            position: number;
            series_name: string;
            skipped: boolean;
            status: string;
            /** Format: int32 */
            thread_id: number;
        };
        /**
         * ReadingListEntryIntent
         * @description Explicit positional intent for one stable member Issue.
         */
        ReadingListEntryIntent: {
            /**
             * Gate
             * @default none
             * @enum {string}
             */
            gate: "none" | "hold" | "after_previous";
            /**
             * Skipped
             * @default false
             */
            skipped: boolean;
        };
        /**
         * ReadingListPredecessorChange
         * @description Named before/after requirements that the reader must acknowledge.
         */
        ReadingListPredecessorChange: {
            /** After Issue Ids */
            after_issue_ids: number[];
            /** After Issue Names */
            after_issue_names: string[];
            /** Before Issue Ids */
            before_issue_ids: number[];
            /** Before Issue Names */
            before_issue_names: string[];
            /** Issue Id */
            issue_id: number;
            /** Issue Name */
            issue_name: string;
        };
        ReadingListReader: {
            entries: components["schemas"]["NativeReadingListReaderEntry"][];
            execution_mode: string;
            /** Format: int32 */
            list_id: number;
            mode: string;
            name: string;
        };
        /**
         * ReadingListReaderEntry
         * @description One current list member with the execution authority's decision.
         */
        ReadingListReaderEntry: {
            /**
             * Availability
             * @enum {string}
             */
            availability: "read" | "available" | "blocked" | "later" | "excluded" | "inactive" | "legacy";
            /** Checkpoint Target Issue Ids */
            checkpoint_target_issue_ids?: number[];
            explanation?: components["schemas"]["BlockingExplanation"] | null;
            /**
             * Gate
             * @default none
             * @enum {string}
             */
            gate: "none" | "hold" | "after_previous";
            /** Id */
            id: number;
            /**
             * Is Checkpoint
             * @default false
             */
            is_checkpoint: boolean;
            /** Issue Id */
            issue_id: number;
            /** Issue Number */
            issue_number: string;
            /** Position */
            position: number;
            /** Series Name */
            series_name: string;
            /**
             * Skipped
             * @default false
             */
            skipped: boolean;
            /** Status */
            status: string;
            /** Thread Id */
            thread_id: number;
        };
        /**
         * ReadingListReaderResponse
         * @description Full current list order; never reconstructed from plan membership.
         */
        ReadingListReaderResponse: {
            /** Entries */
            entries?: components["schemas"]["ReadingListReaderEntry"][];
            /**
             * Execution Mode
             * @enum {string}
             */
            execution_mode: "legacy" | "option_e";
            /** List Id */
            list_id: number;
            /**
             * Mode
             * @enum {string}
             */
            mode: "strict" | "loose";
            /** Name */
            name: string;
        };
        ReadingListSummary: {
            description?: string | null;
            /** Format: int32 */
            id: number;
            /** Format: int32 */
            issue_count: number;
            mode: string;
            name: string;
            updated_at: string;
        };
        ReadingListWrite: {
            checkpoint_issue_ids?: number[] | null;
            checkpoint_targets?: {
                [key: string]: number[];
            } | null;
            /**
             * @description Creation has no predecessor changes to confirm; only update accepts
             *     them. A present value is rejected exactly like the Python create path.
             */
            confirmed_predecessor_changes?: unknown;
            description?: string | null;
            entry_intents?: {
                [key: string]: components["schemas"]["NativeReadingListEntryIntent"];
            } | null;
            issue_ids: number[];
            mode?: string | null;
            name: string;
        };
        /** @description Current reading-mode state for the active session (wire response). */
        ReadingModeResponse: {
            bandwidth?: string | null;
            intent?: string | null;
            source?: string | null;
            suggested: boolean;
        };
        /**
         * @description Set request: `source` is required; `answers` (quiz) or resolved
         *     `bandwidth`+`intent` (manual) supplies the mode, as in Python.
         */
        ReadingModeSetRequest: {
            answers?: {
                [key: string]: string;
            } | null;
            bandwidth?: string | null;
            intent?: string | null;
            source: string;
        };
        /**
         * ReadingOrderAdoptRequest
         * @description Request to adopt a legacy reading order into the canonical plan.
         */
        ReadingOrderAdoptRequest: {
            /**
             * Lane Id
             * @default adopted
             */
            lane_id: string;
            /**
             * Lane Name
             * @default Adopted
             */
            lane_name: string;
            /** Plan Name */
            plan_name?: string | null;
            /** Reading Order Id */
            reading_order_id: number;
        };
        /**
         * ReadingOrderItemResponse
         * @description Response schema for a single item within a reading order.
         */
        ReadingOrderItemResponse: {
            /**
             * Is Read
             * @default false
             */
            is_read: boolean;
            /** Issue Number */
            issue_number?: string | null;
            /** Position */
            position: number;
            /** Thread Id */
            thread_id: number;
            /** Thread Title */
            thread_title: string;
        };
        /** @description Python `ReadingOrderListResponse`. */
        ReadingOrderListResponse: {
            reading_orders: components["schemas"]["ReadingOrderSummary"][];
        };
        /**
         * ReadingOrderProjectionConflict
         * @description A single conflict blocking a projection.
         */
        ReadingOrderProjectionConflict: {
            /** Code */
            code: string;
            /**
             * Existing Positions
             * @default []
             */
            existing_positions: number[];
            /** Message */
            message: string;
            /** Node Id */
            node_id: string;
            /** Thread Id */
            thread_id?: number | null;
        };
        /**
         * ReadingOrderProjectionEntry
         * @description One row in a projected reading order preview.
         */
        ReadingOrderProjectionEntry: {
            /** Position */
            position: number;
            /** Source */
            source: string;
            /** Source Node Id */
            source_node_id?: string | null;
            /** Thread Id */
            thread_id: number;
            /** Thread Title */
            thread_title: string | null;
        };
        /**
         * ReadingOrderProjectionPreview
         * @description Response contract for the preview endpoint.
         */
        ReadingOrderProjectionPreview: {
            /** Conflicts */
            conflicts: components["schemas"]["ReadingOrderProjectionConflict"][];
            /**
             * Dropped Node Ids
             * @default []
             */
            dropped_node_ids: string[];
            /** Entries */
            entries: components["schemas"]["ReadingOrderProjectionEntry"][];
            /** Plan Id */
            plan_id: number;
            /** Plan Name */
            plan_name: string;
            /** Plan Ordering Mode */
            plan_ordering_mode: string;
            /** Reading Order Id */
            reading_order_id: number;
            /** Reading Order Name */
            reading_order_name: string;
            /** Total Positions */
            total_positions: number;
        };
        /**
         * ReadingOrderProjectionRequest
         * @description Request contract for both preview and confirm endpoints.
         */
        ReadingOrderProjectionRequest: {
            /** Reading Order Id */
            reading_order_id: number;
        };
        /**
         * ReadingOrderProjectionResult
         * @description Response contract for the confirm endpoint.
         */
        ReadingOrderProjectionResult: {
            /** Added Count */
            added_count: number;
            /** Kept Count */
            kept_count: number;
            /** Plan Id */
            plan_id: number;
            /** Reading Order Id */
            reading_order_id: number;
            /** Total Positions */
            total_positions: number;
            /** Updated Count */
            updated_count: number;
        };
        /**
         * ReadingOrderResponse
         * @description Response schema for a reading order with items.
         */
        ReadingOrderResponse: {
            /** Completed Items */
            completed_items: number;
            /** Description */
            description?: string | null;
            /** Id */
            id: number;
            /**
             * Items
             * @default []
             */
            items: components["schemas"]["ReadingOrderItemResponse"][];
            /** Name */
            name: string;
            /** Total Items */
            total_items: number;
        };
        /** @description One row of the reading-orders list (Python `ReadingOrderSummary`). */
        ReadingOrderSummary: {
            description?: string | null;
            /** Format: int32 */
            id: number;
            name: string;
            /** Format: int64 */
            total_items: number;
        };
        /**
         * ReadingPlanDependencyLink
         * @description One plan provenance reference to a canonical Dependency edge.
         */
        ReadingPlanDependencyLink: {
            /** Dependency Id */
            dependency_id: number;
            /** Explanation */
            explanation?: string | null;
            /** Source Issue Id */
            source_issue_id: number;
            /** Target Issue Id */
            target_issue_id: number;
        };
        /**
         * ReadingPlanDependencyLinkRequest
         * @description Request to reference one canonical Dependency edge from a plan.
         */
        ReadingPlanDependencyLinkRequest: {
            /** Explanation */
            explanation?: string | null;
        };
        /**
         * ReadingPlanMemberIssue
         * @description One normalized Issue occurrence inside a Reading Plan.
         */
        ReadingPlanMemberIssue: {
            /** Display Position */
            display_position: number;
            /**
             * Is Checkpoint
             * @default false
             */
            is_checkpoint: boolean;
            /** Issue Id */
            issue_id: number;
            /** Label */
            label?: string | null;
            /** Lane Id */
            lane_id: string;
            /** Occurrence Id */
            occurrence_id: string;
            /** Reader Optional */
            reader_optional?: boolean | null;
            /** Reader Role */
            reader_role?: string | null;
            /** Source Metadata */
            source_metadata?: {
                [key: string]: unknown;
            } | null;
        };
        /**
         * ReadingPlanMembershipResponse
         * @description Normalized membership, provenance, and progress for one Reading Plan.
         */
        ReadingPlanMembershipResponse: {
            /** Dependencies */
            dependencies: components["schemas"]["ReadingPlanDependencyLink"][];
            /** Issues */
            issues: components["schemas"]["ReadingPlanMemberIssue"][];
            /** Placements */
            placements: components["schemas"]["ReadingPlanSourcePlacementView"][];
            /** Plan Id */
            plan_id: number;
            progress: components["schemas"]["ReadingPlanProgress"];
            /** Sources */
            sources: components["schemas"]["ReadingPlanSourceSnapshot"][];
        };
        /**
         * ReadingPlanProgress
         * @description Plan progress derived from global Issue read state.
         */
        ReadingPlanProgress: {
            /** Read Issues */
            read_issues: number;
            /** Total Issues */
            total_issues: number;
        };
        /**
         * ReadingPlanReleaseSourceStatus
         * @description One followed ComicVine volume and its sync state on a Reading Plan.
         */
        ReadingPlanReleaseSourceStatus: {
            /** Enabled */
            enabled: boolean;
            /** External Identity Id */
            external_identity_id: number;
            /** Last Synced At */
            last_synced_at?: string | null;
            /** Provider Issue Count */
            provider_issue_count?: number | null;
            /** Provider Publisher */
            provider_publisher?: string | null;
            /** Provider Start Year */
            provider_start_year?: number | null;
            /** Provider Title */
            provider_title?: string | null;
            /** Provider Volume Id */
            provider_volume_id: string;
            /** Source Id */
            source_id: number;
            /** Thread Id */
            thread_id: number;
        };
        /**
         * ReadingPlanSourcePlacementView
         * @description One preserved source-position observation for a plan occurrence.
         */
        ReadingPlanSourcePlacementView: {
            /** Id */
            id: number;
            /** Occurrence Id */
            occurrence_id: string;
            /** Plan Source Id */
            plan_source_id: number;
            /** Source Position */
            source_position?: number | null;
        };
        /**
         * ReadingPlanSourceSnapshot
         * @description One preserved import snapshot referenced by a Reading Plan.
         */
        ReadingPlanSourceSnapshot: {
            /** Adopted At */
            adopted_at?: string | null;
            /** Content Hash */
            content_hash?: string | null;
            /** Display Name */
            display_name?: string | null;
            /** Id */
            id: number;
            /** Raw Source Path */
            raw_source_path: string;
            /**
             * Recorded At
             * Format: date-time
             */
            recorded_at: string;
            /** Repository */
            repository?: string | null;
            /** Revision Sha */
            revision_sha?: string | null;
            /** Source Path */
            source_path?: string | null;
        };
        /** @description Result of the explicit v2 reading-session initialization write. */
        ReadingSessionCreatedResponse: {
            created: boolean;
            /** Format: int32 */
            session_id: number;
        };
        /** @description Summary of one recent reading session. */
        RecentSession: {
            ended_at?: string | null;
            /** Format: int32 */
            id: number;
            /** Format: int32 */
            start_die: number;
            started_at: string;
        };
        /**
         * RecommendationExplanationResponse
         * @description Aggregate recommendation explanation for a single roll event.
         *
         *     Attributes:
         *         event_id: The roll event whose recommendation context was explained.
         *         factors: Ordered list of human-readable explanation elements derived
         *             from the persisted decision-time context. Up to ``MAX_EXPLANATIONS``
         *             factors are returned, ordered deterministically by factor family.
         */
        RecommendationExplanationResponse: {
            /** Event Id */
            event_id: number;
            /** Factors */
            factors: components["schemas"]["ExplainableFactorResponse"][];
        };
        RecoveryCandidate: {
            added_steps: components["schemas"]["RecoveryStep"][];
            /** Format: int32 */
            list_id: number;
            list_updated_at: string;
            mode: string;
            name: string;
            order_changed: boolean;
            removed_steps: components["schemas"]["RecoveryStep"][];
            steps: components["schemas"]["RecoveryStep"][];
        };
        RecoveryStep: {
            /** Format: int32 */
            issue_id: number;
            label: string;
        };
        /** @description Optional request body for token refresh; the refresh cookie is also accepted. */
        RefreshTokenRequest: {
            refresh_token: string;
        };
        /** @description Request body for account registration. */
        RegisterRequest: {
            email: string;
            password: string;
            username: string;
        };
        /** @description Related issue derived from a confirmed explicit story-arc relationship. */
        RelatedIssue: {
            comicpile_matches: components["schemas"]["ComicPileMatch"][];
            comicvine_issue_id: string;
            comicvine_url?: string | null;
            cover_date?: string | null;
            issue_number?: string | null;
            name?: string | null;
            series_name?: string | null;
        };
        /** @description Paginated published releases for What's New. */
        ReleaseListResponse: {
            /** Format: int32 */
            limit: number;
            /** Format: int32 */
            offset: number;
            releases: components["schemas"]["PublicReleaseResponse"][];
            /** Format: int64 */
            total: number;
        };
        /** @description One complete release ledger record returned to trusted automation. */
        ReleaseResponse: {
            body?: string | null;
            category: string;
            /** Format: date-time */
            created_at: string;
            /** Format: int32 */
            id: number;
            /** Format: date-time */
            merged_at: string;
            provenance_json: unknown;
            /** Format: date-time */
            released_at: string;
            /** Format: int32 */
            sort_order: number;
            source_merge_sha?: string | null;
            /** Format: int32 */
            source_pr_number?: number | null;
            source_repository: string;
            status: string;
            summary: string;
            title: string;
            /** Format: date-time */
            updated_at: string;
            visibility: string;
        };
        /**
         * ReleaseSourceCreate
         * @description Create a release source subscription.
         */
        ReleaseSourceCreate: {
            /** External Identity Id */
            external_identity_id: number;
            /** Plan Id */
            plan_id: number;
            /** Thread Id */
            thread_id: number;
        };
        /**
         * ReleaseSourceResponse
         * @description A release source with provider display metadata.
         */
        ReleaseSourceResponse: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Enabled */
            enabled: boolean;
            /** External Identity Id */
            external_identity_id: number;
            /** Id */
            id: number;
            /** Last Synced At */
            last_synced_at: string | null;
            /** Plan Id */
            plan_id: number;
            /** Provider */
            provider: string;
            /** Provider Title */
            provider_title: string | null;
            /** Provider Volume Id */
            provider_volume_id: string;
            /** Thread Id */
            thread_id: number;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * ReleaseSourceUpdate
         * @description Update a release source (enable/disable).
         */
        ReleaseSourceUpdate: {
            /** Enabled */
            enabled: boolean;
        };
        /** @description Idempotent release publication payload from trusted automation. */
        ReleaseUpsertRequest: {
            body?: string | null;
            category: string;
            /** Format: date-time */
            merged_at?: string;
            provenance_json?: unknown;
            /** Format: date-time */
            released_at: string;
            /** Format: int32 */
            sort_order?: number;
            source_merge_sha?: string | null;
            /** Format: int32 */
            source_pr_number?: number | null;
            source_repository: string;
            status?: string;
            summary: string;
            title: string;
            visibility?: string;
        };
        /**
         * ReplaceIdentityRequest
         * @description Request to replace the current confirmed identity with a new one.
         */
        ReplaceIdentityRequest: {
            /**
             * Comicvine Issue Id
             * @description New ComicVine issue ID to confirm
             */
            comicvine_issue_id: number;
            /**
             * Reason
             * @description Optional reason for replacement
             */
            reason?: string | null;
        };
        /**
         * @description Report kind, mirroring Python `ReportType = Literal["bug", "feature"]`.
         * @enum {string}
         */
        ReportType: "bug" | "feature";
        ResetDiceRequest: {
            idempotency_key: string;
        };
        ResetDiceResponse: {
            /** Format: int32 */
            die: number;
            replayed: boolean;
        };
        /** @description Request body for completing a password reset with a single-use token. */
        ResetPasswordRequest: {
            new_password: string;
            token: string;
        };
        /** @description The reader's current logical die and the approved ladder. */
        RollDieStateResponse: {
            /**
             * Format: int32
             * @description The die an explicit reset returns to.
             */
            default_die: number;
            /**
             * Format: int32
             * @description The current logical die.
             */
            die: number;
            /** @description The approved dice ladder, smallest to largest. */
            ladder: number[];
            last_roll?: null | components["schemas"]["RollLastRoll"];
        };
        /** @description The ordered eligible issue identifiers for the current die. */
        RollEligibleIssueIdsResponse: {
            /**
             * Format: int32
             * @description The logical die that bounded the list.
             */
            die: number;
            /** @description The eligible issue identifiers, in queue order. */
            issue_ids: number[];
            /**
             * @description Why an empty in-play pool has no faces, when it does.
             *     Derived from the already-loaded Option E inputs and the eligible
             *     frontiers before the die bound and browser snoozes, exactly as
             *     `GET /api/v2/roll/bootstrap` reports it. `ready` means at least one
             *     frontier is eligible; the other variants name why an empty pool has
             *     no in-play faces (`no_series`, `all_blocked`, `all_completed`,
             *     `all_out_of_pool`). It never carries a list or whole-library report.
             */
            pool_reason: components["schemas"]["PoolReason"];
            /** @description The owning thread identifiers, parallel to `issue_ids`. */
            thread_ids: number[];
        };
        /** @description The most recent Roll recorded for this reader. */
        RollLastRoll: {
            /**
             * Format: int32
             * @description The die that produced the roll.
             */
            die?: number | null;
            /**
             * Format: int32
             * @description The rolled issue.
             */
            issue_id?: number | null;
            /** @description The rolled issue number. */
            issue_number?: string | null;
            /**
             * Format: int32
             * @description The recorded roll result.
             */
            result?: number | null;
            /** @description When the roll was recorded. */
            rolled_at?: string | null;
            /**
             * Format: int32
             * @description The rolled thread.
             */
            thread_id?: number | null;
        };
        RollOfferRequest: {
            /**
             * Format: int32
             * @description A Queue action may only reroll the exact pending thread shown to the user.
             */
            expected_pending_thread_id?: number | null;
            /** @description Stable client key; retries return the original offer without re-rolling. */
            idempotency_key: string;
            /** @description Threads this browser has temporarily snoozed (cookie authority only). */
            snoozed_thread_ids?: number[];
            /** @description Browser timezone used only by the retained session bridge. */
            timezone?: string | null;
        };
        RollOfferResponse: {
            /** Format: int32 */
            die_size: number;
            explanation?: string | null;
            format: string;
            /** Format: int32 */
            issue_id?: number | null;
            issue_number?: string | null;
            /** Format: int32 */
            issues_remaining: number;
            /** Format: int32 */
            last_rolled_result?: number | null;
            /** Format: int32 */
            next_issue_id?: number | null;
            next_issue_number?: string | null;
            /** Format: int32 */
            offset: number;
            /** Format: int32 */
            queue_position: number;
            reading_progress?: string | null;
            /** Format: int32 */
            result: number;
            /** Format: int32 */
            snoozed_count: number;
            /**
             * Format: int32
             * @description Thread snoozed by this request so the browser can extend its cookie.
             */
            snoozed_thread_id?: number | null;
            /** Format: int32 */
            thread_id: number;
            title: string;
            /** Format: int32 */
            total_issues?: number | null;
        };
        /**
         * RollPrerequisiteSwitchRequest
         * @description One recovery recommendation selected from the current Roll guidance.
         */
        RollPrerequisiteSwitchRequest: {
            /** Node Id */
            node_id: number;
            /**
             * Node Type
             * @constant
             */
            node_type: "issue";
        };
        /**
         * RollPrerequisiteSwitchResponse
         * @description Durable active-target state after accepting a recovery recommendation.
         */
        RollPrerequisiteSwitchResponse: {
            /** Changed */
            changed: boolean;
            /** Original Thread Id */
            original_thread_id: number;
            /** Target Issue Id */
            target_issue_id: number;
            /** Target Issue Number */
            target_issue_number: string;
            /** Target Thread Id */
            target_thread_id: number;
            /** Target Thread Title */
            target_thread_title: string;
        };
        /**
         * RollResponse
         * @description Schema for roll response.
         */
        RollResponse: {
            /** Die Size */
            die_size: number;
            /** Explanation */
            explanation?: string | null;
            /** Format */
            format: string;
            /** Issue Id */
            issue_id?: number | null;
            /** Issue Number */
            issue_number?: string | null;
            /** Issues Remaining */
            issues_remaining: number;
            /** Next Issue Id */
            next_issue_id?: number | null;
            /** Next Issue Number */
            next_issue_number?: string | null;
            /** Offset */
            offset: number;
            /** Queue Position */
            queue_position: number;
            /** Reading Progress */
            reading_progress?: string | null;
            /** Result */
            result: number;
            /** Snoozed Count */
            snoozed_count: number;
            /** Thread Id */
            thread_id: number;
            /** Title */
            title: string;
            /** Total Issues */
            total_issues?: number | null;
        };
        /**
         * RouteTrafficCounter
         * @description One aggregated (method, route template, status class) tally.
         */
        RouteTrafficCounter: {
            /**
             * Count
             * @description Requests observed since process start.
             */
            count: number;
            /**
             * Method
             * @description HTTP method, e.g. GET.
             */
            method: string;
            /**
             * Route
             * @description Routed path template, e.g. /api/v1/threads/{thread_id}.
             */
            route: string;
            /**
             * Status Class
             * @description Response status class, e.g. 2xx or 4xx.
             */
            status_class: string;
        };
        /**
         * SeriesDecision
         * @description Series-level decision for CBL adoption.
         */
        SeriesDecision: {
            /** @description Include or exclude this entire series */
            decision: components["schemas"]["SourceBackedDecision"];
            /**
             * Series Name
             * @description Series name
             */
            series_name: string;
        };
        /** @description Wire parity with Python `SeriesImportStatusResponse`. */
        SeriesImportStatusResponse: {
            /** Format: int32 */
            comicvine_volume_id: number;
            imported: boolean;
            /** Format: int32 */
            issue_count?: number | null;
            series_name?: string | null;
            /** Format: int32 */
            thread_id?: number | null;
        };
        /**
         * SeriesMappingPreviewCounts
         * @description Schema for classification counts in preview responses.
         */
        SeriesMappingPreviewCounts: {
            /**
             * Already Confirmed
             * @description Number of already confirmed mappings
             */
            already_confirmed: number;
            /**
             * Excluded Special
             * @description Number of excluded special/annual issues
             */
            excluded_special: number;
            /**
             * Needs Review Ambiguous
             * @description Number of issues needing review due to ambiguity
             */
            needs_review_ambiguous: number;
            /**
             * Needs Review Conflict
             * @description Number of issues needing review due to conflicts
             */
            needs_review_conflict: number;
            /**
             * Safe Exact Match
             * @description Number of safe exact matches
             */
            safe_exact_match: number;
            /**
             * Unresolved
             * @description Number of unresolved issues
             */
            unresolved: number;
        };
        /**
         * SeriesMappingPreviewProviderSeries
         * @description Schema for provider series information in preview responses.
         */
        SeriesMappingPreviewProviderSeries: {
            /**
             * Count Of Issues
             * @description Total number of issues in the series
             */
            count_of_issues?: number | null;
            /**
             * Id
             * @description Provider series ID
             */
            id: string;
            /**
             * Image
             * @description Image information
             */
            image?: {
                [key: string]: unknown;
            } | null;
            /**
             * Name
             * @description Series name, when provider metadata is available
             */
            name?: string | null;
            /**
             * Publisher
             * @description Publisher name
             */
            publisher?: string | null;
            /**
             * Site Detail Url
             * @description URL to the series on the provider site
             */
            site_detail_url?: string | null;
            /**
             * Start Year
             * @description Start year
             */
            start_year?: number | null;
        };
        /**
         * SeriesMappingPreviewRequest
         * @description Schema for series mapping preview requests.
         */
        SeriesMappingPreviewRequest: {
            /**
             * Origin Issue Id
             * @description The anchor issue ID for the mapping preview
             */
            origin_issue_id: number;
            /**
             * Provider
             * @description External provider name (e.g., comicvine)
             */
            provider: string;
            /**
             * Provider Series External Id
             * @description Provider-specific series identifier
             */
            provider_series_external_id: string;
            /**
             * Scope Mode
             * @description Preview scope mode: 'confirmed_origin' (generic, requires confirmed origin evidence for sibling scope) or 'queue_thread_bootstrap' (queue repair may propose the anchor's whole owned thread, including its first issue)
             * @default confirmed_origin
             */
            scope_mode: string;
        };
        /**
         * SeriesMappingPreviewResponse
         * @description Schema for series mapping preview responses.
         */
        SeriesMappingPreviewResponse: {
            /** @description Classification counts */
            counts: components["schemas"]["SeriesMappingPreviewCounts"];
            /**
             * Expires At
             * @description Token expiration timestamp (Unix epoch)
             */
            expires_at?: number | null;
            /**
             * Issued At
             * @description Token issuance timestamp (Unix epoch)
             */
            issued_at: number;
            /**
             * Preview Token
             * @description Preview token when scope is available
             */
            preview_token?: string | null;
            /** @description Provider series information */
            provider_series?: components["schemas"]["SeriesMappingPreviewProviderSeries"] | null;
            /**
             * Rows
             * @description Individual issue mappings
             */
            rows?: components["schemas"]["SeriesMappingPreviewRow"][];
            /** @description Scope information */
            scope: components["schemas"]["SeriesMappingPreviewScope"];
        };
        /**
         * SeriesMappingPreviewRow
         * @description Schema for individual rows in preview responses.
         */
        SeriesMappingPreviewRow: {
            /**
             * Classification
             * @description Classification: already_confirmed, safe_exact_match, needs_review_ambiguous, needs_review_conflict, unresolved, excluded_special
             */
            classification: string;
            /**
             * Current Mapping Status
             * @description Current mapping status if any
             */
            current_mapping_status?: string | null;
            /**
             * Default Selected
             * @description Whether this safe mapping or verified metadata refresh is selected by default
             */
            default_selected: boolean;
            /**
             * External Id
             * @description Provider-specific identifier
             */
            external_id?: string | null;
            /**
             * Issue Id
             * @description Internal issue ID
             */
            issue_id: number;
            /**
             * Issue Number
             * @description Issue number
             */
            issue_number: string;
            /**
             * Metadata Refresh Required
             * @description Verified existing identity has no usable metadata and may be refreshed without replacing it
             * @default false
             */
            metadata_refresh_required: boolean;
            /**
             * Proposed Mapping
             * @description Whether this issue would be mapped in the proposed scope
             */
            proposed_mapping: boolean;
            /**
             * Provider
             * @description External provider name
             */
            provider?: string | null;
            /**
             * Reason
             * @description Explanation for the classification
             */
            reason?: string | null;
            /**
             * Row Id
             * @description Stable row identifier, for example 'issue:789'
             */
            row_id: string;
            /**
             * Thread Id
             * @description Thread ID if the issue belongs to a thread
             */
            thread_id?: number | null;
            /**
             * Thread Title
             * @description Thread title if applicable
             */
            thread_title?: string | null;
            /**
             * Title
             * @description Issue title
             */
            title?: string | null;
        };
        /**
         * SeriesMappingPreviewScope
         * @description Schema for the scope information in preview responses.
         */
        SeriesMappingPreviewScope: {
            /**
             * Basis
             * @description Basis for scope determination
             */
            basis?: string | null;
            /**
             * Origin Issue Id
             * @description Origin issue ID
             */
            origin_issue_id: number;
            /**
             * Scope Key
             * @description Opaque scope key when available
             */
            scope_key?: string | null;
            /**
             * Series Label
             * @description Series label when available
             */
            series_label?: string | null;
            /**
             * Status
             * @description Scope status: 'available' or 'unavailable'
             */
            status: string;
        };
        /** @description Active (pending or freshly rolled) thread projection for one session. */
        SessionActiveThread: {
            format: string;
            /** Format: int32 */
            id: number;
            /** Format: int32 */
            issue_id?: number | null;
            issue_number?: string | null;
            /** Format: int32 */
            issues_read?: number | null;
            /** Format: int32 */
            issues_remaining: number;
            /** Format: double */
            last_rating?: number | null;
            /** Format: int32 */
            last_rolled_result?: number | null;
            /** Format: int32 */
            next_issue_id?: number | null;
            next_issue_number?: string | null;
            /** Format: int32 */
            queue_position: number;
            reading_progress?: string | null;
            tags: components["schemas"]["SessionTag"][];
            title: string;
            /** Format: int32 */
            total_issues?: number | null;
        };
        /**
         * SessionBandwidthState
         * @description Canonical ephemeral bandwidth state for the active reading session.
         *
         *     Every field is always present but nullable so legacy sessions that predate
         *     bandwidth tracking serialize to a stable, safe shape instead of a missing
         *     or partially shaped object. This is the single canonical source consumed by
         *     later weighting and UI work.
         */
        SessionBandwidthState: {
            /** Active Bandwidth */
            active_bandwidth: ("light" | "balanced" | "deep") | null;
            /** Confidence */
            confidence: number | null;
            /** Mode Version */
            mode_version: string | null;
            /** Predicted Bandwidth */
            predicted_bandwidth: ("light" | "balanced" | "deep") | null;
            /** Source */
            source: ("inferred" | "manual" | "snooze" | "quiz") | null;
        };
        /** @description Wire shape of Python `SessionResponse` for `get_session`. */
        SessionDetailResponse: {
            active_thread?: null | components["schemas"]["SessionActiveThread"];
            bandwidth?: null | components["schemas"]["NativeSessionBandwidthState"];
            correction?: unknown;
            /** Format: int32 */
            current_die: number;
            ended_at?: string | null;
            has_restore_point: boolean;
            /** Format: int32 */
            id: number;
            intent?: null | components["schemas"]["NativeSessionIntentState"];
            ladder_path: string;
            /** Format: int32 */
            last_rolled_result?: number | null;
            /** Format: int32 */
            manual_die?: number | null;
            /** Format: int32 */
            pending_thread_id?: number | null;
            reading_bandwidth?: string | null;
            reading_intent?: string | null;
            reading_mode_source?: string | null;
            reading_mode_suggested: boolean;
            skipped_thread_ids: number[];
            skipped_threads: components["schemas"]["SessionThreadSummary"][];
            /** Format: int32 */
            snapshot_count: number;
            snoozed_thread_ids: number[];
            snoozed_threads: components["schemas"]["SessionThreadSummary"][];
            /** Format: int32 */
            start_die: number;
            started_at: string;
            timezone?: string | null;
            /** Format: int32 */
            user_id: number;
        };
        /**
         * SessionDetailsResponse
         * @description Schema for session details with all events.
         */
        SessionDetailsResponse: {
            /** Current Die */
            current_die: number;
            /** Ended At */
            ended_at: string | null;
            /** Events */
            events: components["schemas"]["EventDetail"][];
            /** Ladder Path */
            ladder_path: string;
            /** Narrative Summary */
            narrative_summary: {
                [key: string]: string[];
            };
            /** Session Id */
            session_id: number;
            /** Start Die */
            start_die: number;
            /** Started At */
            started_at: string | null;
            /** Timezone */
            timezone?: string | null;
        };
        /**
         * SessionHistoryListResponse
         * @description Schema for paginated session history list response.
         */
        SessionHistoryListResponse: {
            /** Next Page Token */
            next_page_token?: string | null;
            /** Sessions */
            sessions: components["schemas"]["SessionListItem"][];
        };
        /**
         * SessionIntentState
         * @description Canonical ephemeral reading-intent state for the active reading session.
         *
         *     Symmetric to :class:`SessionBandwidthState`. Every field is always present
         *     but nullable so legacy sessions that predate intent tracking serialize to a
         *     stable, safe shape instead of a missing or partially shaped object. A fully
         *     null object means the session defaults to the balanced intent.
         */
        SessionIntentState: {
            /** Active Intent */
            active_intent: ("balanced" | "momentum" | "familiar" | "explore" | "random") | null;
            /** Confidence */
            confidence: number | null;
            /** Mode Version */
            mode_version: string | null;
            /** Predicted Intent */
            predicted_intent: ("balanced" | "momentum" | "familiar" | "explore" | "random") | null;
            /** Source */
            source: ("inferred" | "manual" | "snooze" | "quiz") | null;
        };
        /**
         * SessionListItem
         * @description Schema for a single session in the history list view.
         *
         *     A deliberate subset of SessionResponse. The list view does not need
         *     snoozed_thread_ids, snoozed_threads, pending_thread_id, or timezone,
         *     which reduces payload size for session history lists.
         */
        SessionListItem: {
            active_thread: components["schemas"]["ActiveThreadInfo"] | null;
            /** Current Die */
            current_die: number;
            /** Ended At */
            ended_at: string | null;
            /** Has Restore Point */
            has_restore_point: boolean;
            /** Id */
            id: number;
            /** Ladder Path */
            ladder_path: string;
            /** Last Rolled Result */
            last_rolled_result: number | null;
            /** Manual Die */
            manual_die: number | null;
            /** Reading Bandwidth */
            reading_bandwidth?: string | null;
            /** Reading Intent */
            reading_intent?: string | null;
            /** Reading Mode Source */
            reading_mode_source?: string | null;
            /**
             * Reading Mode Suggested
             * @default false
             */
            reading_mode_suggested: boolean;
            /** Snapshot Count */
            snapshot_count: number;
            /** Start Die */
            start_die: number;
            /** Started At */
            started_at: string | null;
            /** User Id */
            user_id: number;
        };
        /**
         * SessionResponse
         * @description Schema for session response.
         */
        SessionResponse: {
            active_thread: components["schemas"]["ActiveThreadInfo"] | null;
            /** @description Canonical ephemeral bandwidth state for the session. Null on endpoints that do not load bandwidth state. */
            bandwidth?: components["schemas"]["SessionBandwidthState"] | null;
            /** @description Structured correction result from the most recent Snooze. Null when no correction was applied. */
            correction?: components["schemas"]["SnoozeCorrectionInfo"] | null;
            /** Current Die */
            current_die: number;
            /** Ended At */
            ended_at: string | null;
            /** Has Restore Point */
            has_restore_point: boolean;
            /** Id */
            id: number;
            /** @description Canonical ephemeral reading-intent state for the session. Null on endpoints that do not load intent state. */
            intent?: components["schemas"]["SessionIntentState"] | null;
            /** Ladder Path */
            ladder_path: string;
            /** Last Rolled Result */
            last_rolled_result: number | null;
            /** Manual Die */
            manual_die: number | null;
            /** Pending Thread Id */
            pending_thread_id?: number | null;
            /** Reading Bandwidth */
            reading_bandwidth?: string | null;
            /** Reading Intent */
            reading_intent?: string | null;
            /** Reading Mode Source */
            reading_mode_source?: string | null;
            /**
             * Reading Mode Suggested
             * @default false
             */
            reading_mode_suggested: boolean;
            /**
             * Skipped Thread Ids
             * @default []
             */
            skipped_thread_ids: number[];
            /**
             * Skipped Threads
             * @default []
             */
            skipped_threads: components["schemas"]["SnoozedThreadInfo"][];
            /** Snapshot Count */
            snapshot_count: number;
            /**
             * Snoozed Thread Ids
             * @default []
             */
            snoozed_thread_ids: number[];
            /**
             * Snoozed Threads
             * @default []
             */
            snoozed_threads: components["schemas"]["SnoozedThreadInfo"][];
            /** Start Die */
            start_die: number;
            /** Started At */
            started_at: string | null;
            /** Timezone */
            timezone?: string | null;
            /** User Id */
            user_id: number;
        };
        SessionSnapshotItem: {
            created_at: string;
            description?: string | null;
            /** Format: int32 */
            event_id?: number | null;
            /** Format: int32 */
            id: number;
            /** Format: int32 */
            session_id: number;
        };
        SessionSnapshotsResponse: {
            /** Format: int32 */
            session_id: number;
            snapshots: components["schemas"]["SessionSnapshotItem"][];
        };
        /** @description One direct visible tag on the active thread. */
        SessionTag: {
            color: string;
            created_at: string;
            /** Format: int32 */
            id: number;
            name: string;
            normalized_name: string;
            /** Format: int32 */
            owner_user_id?: number | null;
            scope: string;
            updated_at: string;
        };
        /**
         * @description Compact thread summary used for the (empty on this endpoint) snoozed and
         *     skipped lists, kept typed so the contract stays explicit.
         */
        SessionThreadSummary: {
            /** Format: int32 */
            id: number;
            title: string;
        };
        /**
         * SetCurrentIssueRequest
         * @description Schema for atomically correcting the current issue in an active thread.
         */
        SetCurrentIssueRequest: {
            /**
             * Issue Number
             * @description Target issue number to set as current
             */
            issue_number: string;
        };
        /**
         * SetCurrentIssueResponse
         * @description Response after atomically correcting the current issue.
         */
        SetCurrentIssueResponse: {
            /** Format */
            format: string;
            /** Issue Id */
            issue_id?: number | null;
            /** Issue Number */
            issue_number?: string | null;
            /** Issues Remaining */
            issues_remaining: number;
            /** Next Issue Id */
            next_issue_id?: number | null;
            /** Next Issue Number */
            next_issue_number?: string | null;
            /** Queue Position */
            queue_position: number;
            /** Reading Progress */
            reading_progress?: string | null;
            /** Thread Id */
            thread_id: number;
            /** Title */
            title: string;
            /** Total Issues */
            total_issues?: number | null;
        };
        /**
         * SnapshotResponse
         * @description Schema for snapshot response.
         */
        SnapshotResponse: {
            /** Created At */
            created_at: string;
            /** Description */
            description: string | null;
            /** Event Id */
            event_id?: number | null;
            /** Id */
            id: number;
            /** Session Id */
            session_id: number;
        };
        /**
         * SnapshotsListResponse
         * @description Schema for snapshots list response.
         */
        SnapshotsListResponse: {
            /** Session Id */
            session_id: number;
            /** Snapshots */
            snapshots: components["schemas"]["SnapshotResponse"][];
        };
        /**
         * SnoozeCorrectionInfo
         * @description Structured Snooze correction guidance for the client (#1726).
         *
         *     Returned with every Snooze response so the frontend can later decide
         *     whether to show a clarification sheet, without implementing modal UI in
         *     this phase. Fields are compact codes and flags, never prose.
         */
        SnoozeCorrectionInfo: {
            /**
             * Active Bandwidth
             * @description Active bandwidth level after correction: light, balanced, or deep
             */
            active_bandwidth?: string | null;
            /**
             * Active Confidence
             * @description Confidence in the proposed active bandwidth (0.0-1.0)
             */
            active_confidence?: number | null;
            /**
             * Bandwidth Changed
             * @description Whether the active bandwidth level changed after this snooze
             */
            bandwidth_changed: boolean;
            /**
             * Predicted Bandwidth
             * @description Original launch prediction bandwidth (unchanged)
             */
            predicted_bandwidth?: string | null;
            /**
             * Reason Code
             * @description Compact reason code: heavy_snooze_shift, light_snooze_deflate, confidence_degrade, no_correction, or clarification_needed
             * @enum {string}
             */
            reason_code: "heavy_snooze_shift" | "light_snooze_deflate" | "confidence_degrade" | "no_correction" | "clarification_needed";
            /**
             * Suggest Clarification
             * @description True when repeated contradictory snoozes make the mode uncertain
             * @default false
             */
            suggest_clarification: boolean;
        };
        /**
         * SnoozedThreadInfo
         * @description Schema for snoozed thread information in session response.
         */
        SnoozedThreadInfo: {
            /** Id */
            id: number;
            /** Title */
            title: string;
        };
        /**
         * SourceBackedDecision
         * @description Decision values for source-backed adoption.
         * @enum {string}
         */
        SourceBackedDecision: "include" | "exclude";
        /**
         * SourceSyncFailure
         * @description One source that could not be evaluated during a sync run.
         */
        SourceSyncFailure: {
            /** Error */
            error: string;
            /** Plan Id */
            plan_id: number;
            /** Source Id */
            source_id: number;
            /** Thread Id */
            thread_id: number;
            /** Volume Id */
            volume_id: number;
        };
        StartupMetricsResponse: {
            /** Format: double */
            startup_duration?: number | null;
            /** Format: double */
            startup_time?: number | null;
        };
        /** @description A provider story arc with bounded related issues and a correct total. */
        StoryArc: {
            /** Format: int32 */
            comicvine_arc_id: number;
            comicvine_url?: string | null;
            name: string;
            related_issues: components["schemas"]["RelatedIssue"][];
            /** Format: int32 */
            total_related_count?: number | null;
        };
        /**
         * SyncReport
         * @description Structured per-run counters for observability.
         */
        SyncReport: {
            /** Checked Sources */
            checked_sources: number;
            /** Conflicts */
            conflicts: number;
            /** Created Issues */
            created_issues: number;
            /** Enabled Sources */
            enabled_sources: number;
            /**
             * Excluded Issues
             * @default 0
             */
            excluded_issues: number;
            /**
             * Excluded Sources
             * @default 0
             */
            excluded_sources: number;
            /** Failed Sources */
            failed_sources: number;
            /** Failures */
            failures: components["schemas"]["SourceSyncFailure"][];
            /** Future Skips */
            future_skips: number;
            /** Issue Failures */
            issue_failures: number;
            /** Issues Checked */
            issues_checked: number;
            /** Reused Issues */
            reused_issues: number;
            /**
             * Skipped Sources
             * @default 0
             */
            skipped_sources: number;
            /** Successful Sources */
            successful_sources: number;
            /** Total Sources */
            total_sources: number;
            /** Unknown Date Skips */
            unknown_date_skips: number;
        };
        /**
         * SyncRequest
         * @description Request one release-source sync run for the authenticated user.
         */
        SyncRequest: {
            /**
             * As Of
             * Format: date-time
             * @description UTC timestamp defining the release boundary. Only issues whose ComicVine store_date is on or before this instant are adopted.
             */
            as_of: string;
            /**
             * Refresh
             * @description Force live provider requests instead of reading the ComicVine cache.
             * @default true
             */
            refresh: boolean;
        };
        /**
         * SyncResponse
         * @description Response of a completed release-source sync run.
         */
        SyncResponse: {
            /** Message */
            message: string;
            result: components["schemas"]["SyncReport"];
            /** Success */
            success: boolean;
        };
        /**
         * SyncStatusResponse
         * @description Sync state for every release source owned by the authenticated user.
         */
        SyncStatusResponse: {
            /** Enabled Sources */
            enabled_sources: number;
            /** Sources */
            sources: components["schemas"]["SyncStatusSource"][];
            /** Total Sources */
            total_sources: number;
        };
        /**
         * SyncStatusSource
         * @description One release source's persisted sync state.
         */
        SyncStatusSource: {
            /** Enabled */
            enabled: boolean;
            /** External Identity Id */
            external_identity_id: number;
            /** Id */
            id: number;
            /** Last Synced At */
            last_synced_at: string | null;
            /** Provider Volume Id */
            provider_volume_id: string;
            /** Reading Plan Id */
            reading_plan_id: number;
            /** Thread Id */
            thread_id: number;
        };
        Tag: {
            color: string;
            created_at: string;
            /** Format: int32 */
            id: number;
            name: string;
            normalized_name: string;
            /** Format: int32 */
            owner_user_id?: number | null;
            scope: string;
            updated_at: string;
        };
        TagAssignmentResponse: {
            created_at: string;
            /** Format: int32 */
            id: number;
            /** Format: int32 */
            tag_id: number;
            /** Format: int32 */
            target_id: number;
            target_type: string;
        };
        TagDeleteResponse: {
            /** Format: int64 */
            assignments_removed: number;
            references_removed_by_consumers: {
                [key: string]: number;
            };
            /** Format: int32 */
            tag_id: number;
        };
        TagListResponse: {
            tags: components["schemas"]["Tag"][];
        };
        /**
         * TagResponse
         * @description A tag response.
         */
        TagResponse: {
            /** Color */
            color: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: number;
            /** Name */
            name: string;
            /** Normalized Name */
            normalized_name: string;
            /** Owner User Id */
            owner_user_id: number | null;
            /** Scope */
            scope: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        TagUsageResponse: {
            assignments_by_target_type: {
                [key: string]: number;
            };
            references_removed_by_consumers: {
                [key: string]: number;
            };
            /** Format: int32 */
            tag_id: number;
            /** Format: int64 */
            total_assignments: number;
        };
        /**
         * TasteDiscovery
         * @description One prompt-eligible inferred taste pattern shown on Roll.
         */
        TasteDiscovery: {
            /** Display Name */
            display_name: string;
            /** Distinct Thread Count */
            distinct_thread_count: number;
            /** Evidence Count */
            evidence_count: number;
            /** External Key */
            external_key: string;
            /** Id */
            id: number;
            /** Prompt */
            prompt: string;
            /** Signal Type */
            signal_type: string;
        };
        /**
         * TasteDiscoveryListResponse
         * @description Ranked prompt-eligible discoveries for the authenticated user.
         */
        TasteDiscoveryListResponse: {
            /** Discoveries */
            discoveries: components["schemas"]["TasteDiscovery"][];
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
        };
        /** @description Wire parity with Python `{"dismissed": True}`. */
        TasteDismissResponse: {
            dismissed: boolean;
        };
        /** @description All Taste Bank signals owned by the authenticated user. */
        TasteSignalListResponse: {
            signals: components["schemas"]["TasteSignalResponse"][];
        };
        /** @description Canonical representation of one persisted Taste Bank signal. */
        TasteSignalResponse: {
            /** Format: double */
            affinity_estimate?: number | null;
            /** Format: double */
            confidence?: number | null;
            display_name: string;
            /** Format: int32 */
            distinct_thread_count: number;
            /** Format: int32 */
            evidence_count: number;
            external_key: string;
            first_observed_at?: string | null;
            last_observed_at?: string | null;
            last_prompted_at?: string | null;
            signal_type: string;
            /** Format: int32 */
            user_id: number;
            user_verdict?: string | null;
            verdict_at?: string | null;
        };
        /** @description Explicit user verdict on one Taste Bank signal. */
        TasteVerdictRequest: {
            verdict: string;
        };
        /**
         * ThreadConnectedResponse
         * @description Schema for thread dependency connectivity info.
         */
        ThreadConnectedResponse: {
            /** Connected Threads */
            connected_threads: components["schemas"]["ConnectedThreadInfo"][];
            /** Thread Id */
            thread_id: number;
        };
        /**
         * ThreadCreate
         * @description Schema for creating a new thread.
         */
        ThreadCreate: {
            /** Format */
            format: string;
            /**
             * Is Test
             * @default false
             */
            is_test: boolean;
            /** Issues Remaining */
            issues_remaining: number;
            /** Manual Creator Credits */
            manual_creator_credits?: {
                name: string;
                roles: string[];
            }[];
            /** Notes */
            notes?: string | null;
            /** Title */
            title: string;
            /** Total Issues */
            total_issues?: number | null;
        };
        /**
         * @description Wire parity with Python `ThreadDependenciesResponse`
         *     (`app/schemas/dependency.py`): the `blocking` list holds edges where this
         *     thread's issues block others, `blocked_by` holds edges where this thread's
         *     issues are blocked. Each entry is the enriched `DependencyResponse`.
         */
        ThreadDependenciesResponse: {
            blocked_by: components["schemas"]["DependencyResponse"][];
            blocking: components["schemas"]["DependencyResponse"][];
        };
        /**
         * ThreadDependencyOrderCheckResponse
         * @description Schema for thread dependency order validation.
         */
        ThreadDependencyOrderCheckResponse: {
            /** Conflicts */
            conflicts: components["schemas"]["DependencyOrderConflict"][];
            /** Thread Id */
            thread_id: number;
        };
        /** @description The legacy single-thread response retained for the v1 and bare aliases. */
        ThreadDetailResponse: {
            blocking_reasons: string[];
            created_at: string;
            format: string;
            /** Format: int32 */
            id: number;
            is_blocked: boolean;
            is_test: boolean;
            /** Format: int32 */
            issues_remaining: number;
            last_activity_at?: string | null;
            /** Format: double */
            last_rating?: number | null;
            manual_creator_credits: unknown;
            /** Format: int32 */
            next_unread_issue_id?: number | null;
            next_unread_issue_number?: string | null;
            notes?: string | null;
            /** Format: int32 */
            queue_position: number;
            reading_progress?: string | null;
            status: string;
            title: string;
            /** Format: int32 */
            total_issues?: number | null;
        };
        /**
         * ThreadIssueCreatorsResponse
         * @description Bulk per-issue ComicVine creator credits for one thread.
         *
         *     Issues without a confirmed ComicVine mapping (or without stored credit
         *     arrays) are omitted; callers fall back to the series' manual creator
         *     credits for those rows.
         */
        ThreadIssueCreatorsResponse: {
            /** Issues */
            issues?: components["schemas"]["IssueCreatorsEntry"][];
            /** Thread Id */
            thread_id: number;
        };
        /** @description Wire parity with Python `ThreadIssueDependenciesResponse`. */
        ThreadIssueDependenciesResponse: {
            issues: components["schemas"]["IssueDependenciesResponse"][];
            /** Format: int32 */
            thread_id: number;
        };
        ThreadIssueListResponse: {
            issues: components["schemas"]["IssueDetailResponse"][];
            next_page_token?: string | null;
            /** Format: int64 */
            page_size: number;
            /** Format: int64 */
            total_count: number;
        };
        ThreadIssuesEffectiveTagsResponse: {
            issues: components["schemas"]["EffectiveTagsResponse"][];
            /** Format: int32 */
            thread_id: number;
        };
        /** @description One reader threads collection item. */
        ThreadListItem: {
            blocking_reasons: string[];
            comicvine_mapping?: null | components["schemas"]["NativeComicVineMappingHealth"];
            created_at: string;
            format: string;
            /** Format: int32 */
            id: number;
            is_blocked: boolean;
            /** Format: int32 */
            issues_remaining: number;
            last_activity_at?: string | null;
            manual_creator_credits: unknown;
            next_unread_issue_number?: string | null;
            notes?: string | null;
            /** Format: int32 */
            queue_position: number;
            series_metadata?: null | components["schemas"]["NativeQueueSeriesMetadata"];
            status: string;
            tags: components["schemas"]["ThreadTag"][];
            title: string;
            /** Format: int32 */
            total_issues?: number | null;
        };
        /** @description Paginated reader threads collection. */
        ThreadListResponse: {
            /** Format: int32 */
            active_count: number;
            next_page_token?: string | null;
            threads: components["schemas"]["ThreadListItem"][];
        };
        ThreadProgress: {
            /** Format: int32 */
            issues_remaining: number;
            /** Format: double */
            last_rating?: number | null;
            /** Format: int32 */
            next_unread_issue_id?: number | null;
            reading_progress?: string | null;
            status: string;
            /** Format: int32 */
            thread_id: number;
        };
        /**
         * ThreadReadingOrdersResponse
         * @description Response schema for reading orders containing a specific thread.
         */
        ThreadReadingOrdersResponse: {
            /** Reading Orders */
            reading_orders: components["schemas"]["ReadingOrderResponse"][];
        };
        /**
         * ThreadResponse
         * @description Schema for thread response.
         */
        ThreadResponse: {
            /**
             * Blocking Reasons
             * @default []
             */
            blocking_reasons: string[];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Format */
            format: string;
            /** Id */
            id: number;
            /**
             * Is Blocked
             * @default false
             */
            is_blocked: boolean;
            /** Is Test */
            is_test: boolean;
            /** Issues Remaining */
            issues_remaining: number;
            /** Last Activity At */
            last_activity_at: string | null;
            /** Last Rating */
            last_rating: number | null;
            /** Manual Creator Credits */
            manual_creator_credits?: {
                name: string;
                roles: string[];
            }[];
            /** Next Unread Issue Id */
            next_unread_issue_id?: number | null;
            /** Next Unread Issue Number */
            next_unread_issue_number?: string | null;
            /** Notes */
            notes: string | null;
            /** Queue Position */
            queue_position: number;
            /** Reading Progress */
            reading_progress?: string | null;
            /** Status */
            status: string;
            /** Title */
            title: string;
            /** Total Issues */
            total_issues?: number | null;
        };
        /** @description One tag visible to the reader. */
        ThreadTag: {
            color: string;
            created_at: string;
            /** Format: int32 */
            id: number;
            name: string;
            normalized_name: string;
            /** Format: int32 */
            owner_user_id?: number | null;
            scope: string;
            updated_at: string;
        };
        /**
         * ThreadUpdate
         * @description Schema for updating a thread.
         */
        ThreadUpdate: {
            /** Format */
            format?: string | null;
            /** Is Test */
            is_test?: boolean | null;
            /** Issues Remaining */
            issues_remaining?: number | null;
            /** Manual Creator Credits */
            manual_creator_credits?: {
                name: string;
                roles: string[];
            }[] | null;
            /** Notes */
            notes?: string | null;
            /** Title */
            title?: string | null;
        };
        /** @description Response body for token endpoints, matching the Python wire contract. */
        TokenResponse: {
            access_token: string;
            refresh_token: string;
            token_type: string;
        };
        /** @description Summary of one highly rated thread. */
        TopRatedThread: {
            format: string;
            /** Format: int32 */
            id: number;
            /** Format: double */
            rating: number;
            title: string;
        };
        /**
         * TrafficMetricsSnapshot
         * @description Process-local traffic counters for one serverless instance.
         *
         *     Counters are monotonic within a process lifetime, so a collector can
         *     reconstruct fleet-wide totals by keeping the maximum count per key across
         *     polls of the same ``instance_id``.
         */
        TrafficMetricsSnapshot: {
            /**
             * Counters
             * @description Aggregated request tallies sorted deterministically.
             */
            counters?: components["schemas"]["RouteTrafficCounter"][];
            /**
             * Instance Id
             * @description Stable identifier for this process instance.
             */
            instance_id: string;
        };
        UpdateTagRequest: {
            color?: string | null;
            name?: string | null;
        };
        /**
         * @description Partial update of the authenticated user's preferences.
         *
         *     `theme` is optional: when omitted or explicit JSON null the current
         *     preference is left unchanged and a missing row is seeded with the
         *     default, exactly like the Python `UserPreferencesPatchRequest`.
         */
        UserPreferencesPatchRequest: {
            theme?: string | null;
        };
        /** @description Current preference values for the authenticated user. */
        UserPreferencesResponse: {
            theme: string;
            /** Format: int32 */
            user_id: number;
        };
        /** @description Response body for the current-user endpoint. */
        UserResponse: {
            email?: string | null;
            /** Format: int32 */
            id: number;
            is_admin: boolean;
            username: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    serve_root__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_metrics_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Simple application startup metrics */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StartupMetricsResponse"];
                };
            };
        };
    };
    ping_api_ping_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    csrf_documentation___api_v1_auth_csrf: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Double-submit CSRF token */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CsrfResponse"];
                };
            };
        };
    };
    forgot_password_documentation___api_v1_auth_forgot_password: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ForgotPasswordRequest"];
            };
        };
        responses: {
            /** @description Enumeration-safe acknowledgement */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PasswordResetResponse"];
                };
            };
            /** @description Request payload failed validation */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Password-recovery rate limit exceeded */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    login_documentation___api_v1_auth_login: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Credentials accepted and bearer tokens issued */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Username field contained an email address */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Incorrect username or password */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Request payload failed validation */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Login rate limit exceeded */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    logout_documentation___api_v1_auth_logout: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Bearer token revoked and refresh cookie cleared */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    me_documentation___api_v1_auth_me: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Authenticated account profile */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Not authenticated or token invalid */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    refresh_documentation___api_v1_auth_refresh: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": null | components["schemas"]["RefreshTokenRequest"];
            };
        };
        responses: {
            /** @description Refreshed bearer tokens issued */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Missing, invalid, revoked or stale refresh token */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Refresh rate limit exceeded */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    register_documentation___api_v1_auth_register: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegisterRequest"];
            };
        };
        responses: {
            /** @description Account created and bearer tokens issued */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Username or email is already registered */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Request payload failed validation */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Registration rate limit exceeded */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    reset_password_documentation___api_v1_auth_reset_password: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResetPasswordRequest"];
            };
        };
        responses: {
            /** @description Password reset completed */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PasswordResetResponse"];
                };
            };
            /** @description Invalid or expired reset request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Request payload failed validation */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Password-recovery rate limit exceeded */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    get_bootstrap_alias_metrics_api_v1_bootstrap_alias_metrics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BootstrapAliasSnapshotSchema"];
                };
            };
        };
    };
    create_v1_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BugReportCreate"];
            };
        };
        responses: {
            /** @description GitHub issue created */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BugReportResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid or blank title/description, or invalid diagnostics */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Non-admin GitHub issue rate limit reached */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description GitHub issue creation failed */
            502: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description GitHub integration not configured */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    commit_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CommitRequest"];
            };
        };
        responses: {
            /** @description Commit result */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CommitResponse"];
                };
            };
            /** @description Authentication required */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description preview_stale, preview_expired, confirmed_mapping_conflict, or idempotency_conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description invalid_approved_row */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    preview_series_mapping_api_v1_catalog_series_mappings_preview_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SeriesMappingPreviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeriesMappingPreviewResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_cbl_adoption_commit_api_v1_cbl__list_id__adoption_commit_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CBLAdoptionCommitRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLAdoptionCommitResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_targeted_cbl_adoption_commit_api_v1_cbl__list_id__reading_plans__plan_id__adoption_commit_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CBLAdoptionCommitRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLAdoptionCommitResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_exclusions_api_v1_collection_exclusions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CollectionExclusionResponse"][];
                };
            };
        };
    };
    create_exclusion_api_v1_collection_exclusions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CollectionExclusionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CollectionExclusionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_exclusion_api_v1_collection_exclusions__exclusion_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                exclusion_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_get_issue_identity_api_v1_comicvine_issues__issue_id__identity_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssueIdentityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_remove_identity_api_v1_comicvine_issues__issue_id__identity_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssueIdentityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_confirm_identity_api_v1_comicvine_issues__issue_id__identity_confirm_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConfirmIdentityRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssueIdentityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_replace_identity_api_v1_comicvine_issues__issue_id__identity_replace_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReplaceIdentityRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssueIdentityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_apply_correction_api_v1_comicvine_issues__issue_id__metadata_correct_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MetadataCorrectionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataCorrectionsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_list_corrections_api_v1_comicvine_issues__issue_id__metadata_corrections_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataCorrectionsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_refresh_metadata_api_v1_comicvine_issues__issue_id__metadata_refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataRefreshResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_revert_correction_api_v1_comicvine_issues__issue_id__metadata_revert_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MetadataCorrectionRevertRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetadataCorrectionsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_import_issue_api_v1_comicvine_issues_import_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ImportIssueRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportIssueResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_resolve_comicvine_input_api_v1_comicvine_resolve_get: {
        parameters: {
            query: {
                /** @description Search text or a pasted ComicVine issue/volume URL */
                input: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ComicVineResolveResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_search_comicvine_series_api_v1_comicvine_search_series_get: {
        parameters: {
            query: {
                /** @description Series search query */
                q: string;
                /** @description Maximum results */
                limit?: number;
                /** @description Zero-based result offset */
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ComicVineSeriesSearchResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    series_import_status_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description ComicVine volume ID */
                comicvine_volume_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Owned import status */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeriesImportStatusResponse"];
                };
            };
            /** @description Invalid or revoked access token */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    api_get_series_issues_api_v1_comicvine_series__comicvine_volume_id__issues_get: {
        parameters: {
            query?: {
                /** @description Optional pre-fetched series name */
                series_name?: string;
            };
            header?: never;
            path: {
                comicvine_volume_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ComicVineSeriesIssuesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_import_series_api_v1_comicvine_series_import_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ImportSeriesRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportSeriesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_continuity_plans_api_v1_continuity_plans__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContinuityPlanListItem"][];
                };
            };
        };
    };
    create_continuity_plan_api_v1_continuity_plans__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContinuityPlanWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContinuityPlanResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    adopt_reading_order_api_v1_continuity_plans_from_reading_order_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReadingOrderAdoptRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContinuityPlanResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_release_source_api_v1_continuity_plans_release_sources__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReleaseSourceCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReleaseSourceResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_release_source_api_v1_continuity_plans_release_sources__source_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                source_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_release_source_api_v1_continuity_plans_release_sources__source_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                source_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReleaseSourceUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReleaseSourceResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_continuity_plan_api_v1_continuity_plans__plan_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContinuityPlanResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_continuity_plan_api_v1_continuity_plans__plan_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContinuityPlanWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContinuityPlanResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_continuity_plan_api_v1_continuity_plans__plan_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    link_plan_dependency_edge_api_v1_continuity_plans__plan_id__dependencies__dependency_id__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
                dependency_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReadingPlanDependencyLinkRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingPlanDependencyLink"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    unlink_plan_dependency_edge_api_v1_continuity_plans__plan_id__dependencies__dependency_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
                dependency_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_continuity_plan_membership_api_v1_continuity_plans__plan_id__membership_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingPlanMembershipResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    confirm_plan_projection_api_v1_continuity_plans__plan_id__reading_orders_project_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReadingOrderProjectionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingOrderProjectionResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_plan_projection_api_v1_continuity_plans__plan_id__reading_orders_project_preview_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReadingOrderProjectionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingOrderProjectionPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_release_sources_api_v1_continuity_plans__plan_id__release_sources__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReleaseSourceResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_release_sources_for_reader_api_v1_continuity_plans__plan_id__release_sources_reader_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingPlanReleaseSourceStatus"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    continuity_rules_list: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContinuityRuleResponse"][];
                };
            };
        };
    };
    continuity_rules_create: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContinuityRuleRequest"];
            };
        };
        responses: {
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContinuityRuleResponse"];
                };
            };
        };
    };
    continuity_rules_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                rule_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContinuityRuleResponse"];
                };
            };
        };
    };
    continuity_rules_update: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                rule_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContinuityRuleRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContinuityRuleResponse"];
                };
            };
        };
    };
    continuity_rules_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                rule_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    list_creators_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                search: string | null;
                sort: string | null;
                limit: number | null;
                offset: number | null;
                min_ratings: number | null;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Creator list */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorListResponse"];
                };
            };
            /** @description Invalid filters */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    compare_creators_endpoint_api_v1_creators_compare_get: {
        parameters: {
            query?: {
                /** @description Comma-separated canonical creator keys (2-4) */
                keys?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorComparisonResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_creator_discoveries_endpoint_api_v1_creators_discoveries_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorDiscoveryResponse"];
                };
            };
        };
    };
    get_summaries_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                keys: string | null;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Creator summaries */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorSummariesResponse"];
                };
            };
            /** @description Invalid creator keys */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    get_creator_team_chemistry_endpoint_api_v1_creators_team_chemistry_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorTeamChemistryResponse"];
                };
            };
        };
    };
    get_creator_detail_endpoint_api_v1_creators__creator_key__get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number | null;
            };
            header?: never;
            path: {
                creator_key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_creator_rating_distribution_drilldown_endpoint_api_v1_creators__creator_key__metrics_rating_distribution__rating_value__get: {
        parameters: {
            query?: {
                /** @description Page number for paginated results */
                page?: number;
                /** @description Number of items per page */
                page_size?: number;
            };
            header?: never;
            path: {
                creator_key: string;
                rating_value: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorRatingDistributionDrilldown"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_creator_role_drilldown_endpoint_api_v1_creators__creator_key__metrics_role_stats__role__get: {
        parameters: {
            query?: {
                /** @description Page number for paginated results */
                page?: number;
                /** @description Number of items per page */
                page_size?: number;
            };
            header?: never;
            path: {
                creator_key: string;
                role: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorRoleDrilldown"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_creator_series_drilldown_endpoint_api_v1_creators__creator_key__metrics_series_stats__series_key__get: {
        parameters: {
            query?: {
                /** @description Page number for paginated results */
                page?: number;
                /** @description Number of issues per page */
                page_size?: number;
            };
            header?: never;
            path: {
                creator_key: string;
                series_key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorSeriesDrilldown"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_creator_metric_drilldown_endpoint_api_v1_creators__creator_key__metrics__metric_type__get: {
        parameters: {
            query?: {
                /** @description Specific role for role-based metrics */
                role?: string | null;
                /** @description Specific rating value for distribution metrics */
                rating_value?: string | null;
                /** @description Specific series key for series metrics */
                series_key?: string | null;
                /** @description Page number for paginated results */
                page?: number;
                /** @description Number of items per page */
                page_size?: number;
            };
            header?: never;
            path: {
                creator_key: string;
                metric_type: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorMetricDrilldown"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_creator_series_issues_endpoint_api_v1_creators__creator_key__series__series_key__issues_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number | null;
            };
            header?: never;
            path: {
                creator_key: string;
                series_key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreatorSeriesIssueListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_custom_cbl_lists_api_v1_custom_cbls_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CustomCBLListItem"][];
                };
            };
        };
    };
    create_custom_cbl_api_v1_custom_cbls_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CustomCBLWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CustomCBLResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    search_custom_cbl_issues_api_v1_custom_cbls_issue_search_get: {
        parameters: {
            query?: {
                q?: string;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CustomCBLIssueSearchResult"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_custom_cbl_api_v1_custom_cbls__list_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CustomCBLResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_custom_cbl_api_v1_custom_cbls__list_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CustomCBLWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CustomCBLResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_custom_cbl_api_v1_custom_cbls__list_id__export_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_custom_cbl_overlap_decisions_api_v1_custom_cbls__list_id__overlap_decisions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OverlapDecisionSetResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    save_custom_cbl_overlap_decision_api_v1_custom_cbls__list_id__overlap_decisions_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OverlapDecisionWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OverlapDecisionSetResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_custom_cbl_overlap_decision_api_v1_custom_cbls__list_id__overlap_decisions__decision_id__delete: {
        parameters: {
            query?: {
                expected_updated_at?: string | null;
            };
            header?: never;
            path: {
                list_id: number;
                decision_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OverlapDecisionSetResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_custom_cbl_api_v1_custom_cbls__list_id__reader_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingListReaderResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    apply_custom_cbl_api_v1_custom_cbls__list_id__reading_plans__plan_id__apply_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CustomCBLApplyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CustomCBLApplyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_legacy_dependency: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DependencyCreateRequest"];
            };
        };
        responses: {
            /** @description Created dependency */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyResponse"];
                };
            };
            /** @description Invalid dependency */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Issue not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reading constraint cycle: nothing was changed */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation failed */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    list_blocked_legacy_dependencies: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Blocked thread ids */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": number[];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    get_legacy_dependency: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Dependency id */
                dependency_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Dependency */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Dependency not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    delete_legacy_dependency: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Dependency id */
                dependency_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Deleted */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Dependency not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    update_legacy_dependency: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Dependency id */
                dependency_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DependencyNoteUpdate"];
            };
        };
        responses: {
            /** @description Dependency */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Dependency not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Note must be at most 255 characters or validation failed */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    list_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IdentityInboxResponse"];
                };
            };
        };
    };
    search_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IdentityInboxSearchResponse"];
                };
            };
        };
    };
    get_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Mapping id */
                mapping_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IdentityInboxResponse"];
                };
            };
        };
    };
    confirm_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Mapping id */
                mapping_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActionRequest"];
            };
        };
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IdentityInboxActionResponse"];
                };
            };
        };
    };
    defer_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Mapping id */
                mapping_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IdentityInboxActionResponse"];
                };
            };
        };
    };
    reject_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Mapping id */
                mapping_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ActionRequest"];
            };
        };
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IdentityInboxActionResponse"];
                };
            };
        };
    };
    skip_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Mapping id */
                mapping_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IdentityInboxActionResponse"];
                };
            };
        };
    };
    discover_cbl_source_lists_api_v1_issue_identity_cbl_sources_get: {
        parameters: {
            query?: {
                q?: string | null;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLSourceListDiscoveryItem"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    browse_cbl_source_catalog_api_v1_issue_identity_cbl_sources_browse_get: {
        parameters: {
            query?: {
                folder?: string;
                q?: string | null;
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLCatalogBrowseResponse"];
                };
            };
            /** @description Invalid folder path or search query. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLErrorResponse"];
                };
            };
            /** @description Folder not found. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLErrorResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Catalog query or database connection temporarily unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLErrorResponse"] | components["schemas"]["CBLDatabaseUnavailableResponse"];
                };
            };
        };
    };
    find_cbl_sources_by_comicvine_issue_api_v1_issue_identity_cbl_sources_by_comicvine_issue__comicvine_issue_id__get: {
        parameters: {
            query?: {
                offset?: number;
                limit?: number;
            };
            header?: never;
            path: {
                comicvine_issue_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLComicvineOccurrencePage"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    compare_cbl_sources_api_v1_issue_identity_cbl_sources_compare_post: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CBLSourceComparisonRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLSourceComparisonResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_cbl_source_folders_api_v1_issue_identity_cbl_sources_folders_get: {
        parameters: {
            query?: {
                folder?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLFolderListingResponse"];
                };
            };
            /** @description Invalid folder path. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLErrorResponse"];
                };
            };
            /** @description Folder not found. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLErrorResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Catalog query or database connection temporarily unavailable. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLErrorResponse"] | components["schemas"]["CBLDatabaseUnavailableResponse"];
                };
            };
        };
    };
    get_cbl_source_list_api_v1_issue_identity_cbl_sources__list_id__get: {
        parameters: {
            query?: {
                offset?: number;
                limit?: number;
            };
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLSourceListDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_cbl_adoption_plan_api_v1_issue_identity_cbl__list_id__adoption_plan_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CBLAdoptionPlanRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLAdoptionPreviewResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    api_cbl_adoption_preview_api_v1_issue_identity_cbl__list_id__adoption_preview_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLAdoptionPreviewResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_cbl_reading_graph_api_v1_issue_identity_cbl__list_id__reading_graph_preview_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReadingGraphPreviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingGraphPreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    find_cbl_candidates_for_reading_list_api_v1_issue_identity_reading_lists__list_id__cbl_candidates_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path: {
                list_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CBLReadingListCandidatesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_issue_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Issue identifier */
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Issue detail */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssueDetailResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Issue not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    issue_intelligence_docs___api_v1_issues__issue_id__comicvine: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owner-scoped ComicPile issue id */
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Stored ComicVine intelligence, or null without a mapping */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": null | components["schemas"]["IssueIntelligence"];
                };
            };
            /** @description Invalid or revoked access token */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Issue is not owned by the reader */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    get_issue_dependencies_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Issue identifier */
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Issue dependencies */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssueDependenciesResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Issue not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    get_issue_reader_context_api_v1_issues__issue_id__reader_context_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReaderContextResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    mark_issue_read_api_v1_issues__issue_id__markRead_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    mark_issue_unread_api_v1_issues__issue_id__markUnread_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    move_issue_api_v1_issues__issue_id__move_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IssueMoveRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bulk_mark_issue_read_api_v1_issues_bulkMarkRead_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IssueBulkMarkReadRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bulk_mark_issue_unread_api_v1_issues_bulkMarkUnread_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IssueBulkMarkUnreadRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_v1_metrics_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Simple application startup metrics */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StartupMetricsResponse"];
                };
            };
        };
    };
    get_reading_boundary_batch_api_v1_reading_boundaries_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReadingBoundaryBatchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingBoundaryBatchResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_reading_boundary_api_v1_reading_boundaries__thread_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingBoundaryExplanation"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_reading_mode_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Current reading-mode state */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingModeResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    set_reading_mode_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReadingModeSetRequest"];
            };
        };
        responses: {
            /** @description Newly stored reading-mode state */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingModeResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid source, quiz resolution, or mode values */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    dismiss_reading_mode_suggestion_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Unchanged reading-mode state with suggestion cleared */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingModeResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    suggest_reading_mode_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Reading-mode state with suggestion enabled */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingModeResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    list_groups_api_v1_reading_order_groups__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyGroupResponse"][];
                };
            };
        };
    };
    create_group_api_v1_reading_order_groups__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DependencyGroupCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyGroupResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_thread_groups_api_v1_reading_order_groups_threads__thread_id__groups_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyGroupSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_group_api_v1_reading_order_groups__group_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyGroupResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_group_api_v1_reading_order_groups__group_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_group_api_v1_reading_order_groups__group_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DependencyGroupUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyGroupResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_group_detail_api_v1_reading_order_groups__group_id__detail_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyGroupDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_issue_range_api_v1_reading_order_groups__group_id__issue_ranges_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DependencyGroupIssueRangeCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyGroupIssueRangeResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_member_api_v1_reading_order_groups__group_id__members_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DependencyGroupMemberCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyGroupMemberResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    remove_member_api_v1_reading_order_groups__group_id__members__member_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
                member_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_group_order_api_v1_reading_order_groups__group_id__order_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DependencyGroupOrderUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyGroupResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_crossover_plans_api_v1_reading_order_groups__group_id__plans_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyGroupSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reading_orders_list: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Reading orders owned by the caller, ordered by name */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingOrderListResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    reading_orders_insert_item: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                reading_order_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InsertReadingOrderItemRequest"];
            };
        };
        responses: {
            /** @description Thread seated at the requested position */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InsertReadingOrderItemResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reading order or thread not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Request payload failed validation */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    reading_plan_sync_status: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Sync state for every release source owned by the caller */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NativeSyncStatusResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    reading_plan_sync: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NativeSyncRequest"];
            };
        };
        responses: {
            /** @description User-triggered sync report */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NativeSyncResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid request */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    releases_list: {
        parameters: {
            query?: {
                /** @description Maximum releases to return (1-100, default 20) */
                limit?: number;
                /** @description Number of matching releases to skip (default 0) */
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReleaseListResponse"];
                };
            };
            /** @description Invalid pagination */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    releases_publish: {
        parameters: {
            query?: never;
            header: {
                /** @description Server-only release-writer credential */
                "x-release-writer-token": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReleaseUpsertRequest"];
            };
        };
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReleaseResponse"];
                };
            };
            /** @description Invalid release writer credential */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Source identities conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Request payload failed validation */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Release writer authorization is not configured */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    releases_reconcile: {
        parameters: {
            query: {
                source_repository: string;
                source_pr_number?: number;
                source_merge_sha?: string;
            };
            header: {
                /** @description Server-only release-writer credential */
                "x-release-writer-token": string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NativeReleaseSourceResponse"];
                };
            };
            /** @description Invalid release writer credential */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Source identities identify different records */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Missing source identity or invalid query */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Release writer authorization is not configured */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    releases_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                release_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicReleaseResponse"];
                };
            };
            /** @description Release not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    releases_retract: {
        parameters: {
            query?: never;
            header: {
                /** @description Server-only release-writer credential */
                "x-release-writer-token": string;
            };
            path: {
                release_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReleaseResponse"];
                };
            };
            /** @description Invalid release writer credential */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Release not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Release writer authorization is not configured */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    dismiss_pending_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description No Content. Pending thread cleared. */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    get_roll_recommendation_explanation_api_v1_roll_events__event_id__recommendation_explanation_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                event_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationExplanationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    override_roll_api_v1_roll_override_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OverrideRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RollResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    switch_roll_prerequisite_api_v1_roll_switch_prerequisite_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RollPrerequisiteSwitchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RollPrerequisiteSwitchResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_sessions_api_v1_sessions__get: {
        parameters: {
            query?: {
                /** @description Number of sessions to return per page (default 50, max 200) */
                page_size?: number;
                /** @description Token for pagination continuation (started_at,session_id) */
                page_token?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionHistoryListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_correction_sheet_examples_api_v1_sessions_correction_examples_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CorrectionSheetExamplesResponse"];
                };
            };
        };
    };
    get_current_session_api_v1_sessions_current__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionResponse"];
                };
            };
        };
    };
    get_session_v1_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned reading session */
                session_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Single session */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionDetailResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Session not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    get_session_details_api_v1_sessions__session_id__details_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionDetailsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_reading_session_start_api_v1_sessions__session_id__restore_session_start_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_session_snapshots_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned reading session */
                session_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Session restore snapshots */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionSnapshotsResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Session not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    list_tags_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TagListResponse"];
                };
            };
        };
    };
    create_tag_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateTagRequest"];
            };
        };
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreateTagResponse"];
                };
            };
        };
    };
    effective_issue_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Issue id */
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EffectiveTagsResponse"];
                };
            };
        };
    };
    effective_plan_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Plan id */
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EffectiveTagsResponse"];
                };
            };
        };
    };
    effective_thread_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Thread id */
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EffectiveTagsResponse"];
                };
            };
        };
    };
    effective_thread_issues_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Thread id */
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadIssuesEffectiveTagsResponse"];
                };
            };
        };
    };
    get_tag_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Tag id */
                tag_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Tag"];
                };
            };
        };
    };
    update_tag_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Tag id */
                tag_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateTagRequest"];
            };
        };
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Tag"];
                };
            };
        };
    };
    delete_tag_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Tag id */
                tag_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TagDeleteResponse"];
                };
            };
        };
    };
    assign_tag_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Tag id */
                tag_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssignTagRequest"];
            };
        };
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TagAssignmentResponse"];
                };
            };
        };
    };
    bulk_assign_tag_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Tag id */
                tag_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BulkAssignRequest"];
            };
        };
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BulkAssignResponse"];
                };
            };
        };
    };
    bulk_unassign_tag_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Tag id */
                tag_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BulkAssignRequest"];
            };
        };
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BulkAssignResponse"];
                };
            };
        };
    };
    unassign_tag_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Tag id */
                tag_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssignTagRequest"];
            };
        };
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TagAssignmentResponse"];
                };
            };
        };
    };
    usage_tag_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Tag id */
                tag_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description ok */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TagUsageResponse"];
                };
            };
        };
    };
    list_taste_discoveries: {
        parameters: {
            query?: {
                /** @description Maximum discoveries to return (1-3, default 3). */
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Ranked discoveries */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NativeTasteDiscoveryListResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description limit is outside the allowed range */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    dismiss_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned taste signal identifier */
                signal_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Dismissed */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TasteDismissResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Taste discovery not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    create_thread_api_v1_threads__post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ThreadCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    check_potential_duplicates_api_v1_threads_check_duplicates_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CheckPotentialDuplicatesRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CheckPotentialDuplicatesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_completed_threads_documentation: {
        parameters: {
            query?: {
                /** @description Case-insensitive title search */
                search?: string;
                /** @description position, title, or created */
                sort?: string;
                /** @description 1-200 rows per page (default 50) */
                page_size?: number;
                /** @description Opaque continuation cursor */
                page_token?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Owner-scoped completed threads page */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadListResponse"];
                };
            };
            /** @description Invalid sort or page token */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid bounds */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    list_excluded_threads_api_v1_threads_excluded_threads_get: {
        parameters: {
            query?: {
                search?: string | null;
                /** @description Sort order: title or created */
                sort?: string;
                /** @description Number of threads to return per page (default 50, max 200) */
                page_size?: number;
                /** @description Opaque cursor token for pagination continuation */
                page_token?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueueThreadListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_thread_groups_batch_api_v1_threads_groups_batch_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DependencyGroupThreadBatchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: components["schemas"]["DependencyGroupSummary"][];
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reactivate_thread_api_v1_threads_reactivate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReactivateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_stale_threads_api_v1_threads_stale_get: {
        parameters: {
            query?: {
                days?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_thread_detail_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Thread identifier */
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Owned thread detail */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadDetailResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Thread not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    update_thread_api_v1_threads__thread_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ThreadUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_thread_api_v1_threads__thread_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_thread_connected_threads_api_v1_threads__thread_id__connected_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadConnectedResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_thread_dependencies_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned thread identifier */
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Thread dependencies */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadDependenciesResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Thread not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    check_thread_dependency_order_api_v1_threads__thread_id__dependency_order_check_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadDependencyOrderCheckResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    exclude_thread_api_v1_threads__thread_id__exclude_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_thread_issue_dependencies_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned thread identifier */
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Thread issue dependencies */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadIssueDependenciesResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Thread not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    list_thread_issues_documentation: {
        parameters: {
            query?: {
                /** @description Optional read or unread filter */
                status?: string;
                /** @description 1-100 issues (default 50) */
                page_size?: number;
                /** @description position,id continuation cursor */
                page_token?: string;
            };
            header?: never;
            path: {
                /** @description Owned thread ID */
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Owner-scoped, paginated issues */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadIssueListResponse"];
                };
            };
            /** @description Invalid page token */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Thread not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid status or page size */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    create_issues_api_v1_threads__thread_id__issues_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IssueCreateRange"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssueListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_thread_issue_creators_api_v1_threads__thread_id__issues_creators_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadIssueCreatorsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reorder_issues_api_v1_threads__thread_id__issues_reorder_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IssueReorderRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    validate_issue_order_api_v1_threads__thread_id__issues_validateOrder_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssueOrderValidationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_thread_reading_orders_api_v1_threads__thread_id__reading_orders_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadReadingOrdersResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    restore_thread_api_v1_threads__thread_id__restore_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_pending_thread_api_v1_threads__thread_id__set_pending_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["Body_set_pending_thread_api_v1_threads__thread_id__set_pending_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RollResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    backdate_thread_for_testing_api_v1_threads__thread_id__test_backdate_put: {
        parameters: {
            query: {
                /** @description Number of days to backdate the thread */
                days_ago: number;
            };
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_thread_blocking_info_api_v1_threads__thread_id__getBlockingInfo_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BlockingExplanation"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    migrate_thread_to_issues_api_v1_threads__thread_id__migrateToIssues_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MigrateToIssuesRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    migrate_thread_to_issues_simple_api_v1_threads__thread_id__migrateToIssuesSimple_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MigrateToIssuesSimpleRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_current_issue_api_v1_threads__thread_id__setCurrentIssue_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetCurrentIssueRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetCurrentIssueResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_threads_blocking_info_api_v1_threads_getBlockingInfo_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BatchBlockingExplanationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BatchBlockingExplanationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_traffic_metrics_api_v1_traffic_metrics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TrafficMetricsSnapshot"];
                };
            };
        };
    };
    list_session_snapshots_api_v1_undo__session_id__snapshots_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotsListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    undo_to_snapshot_api_v1_undo__session_id__undo__snapshot_id__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: number;
                snapshot_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_user_preferences_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The authenticated user's preferences */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserPreferencesResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    patch_user_preferences_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserPreferencesPatchRequest"];
            };
        };
        responses: {
            /** @description The user's preferences after the update */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserPreferencesResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unknown theme id */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    list_taste_signals_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Every Taste Bank signal owned by the authenticated user */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TasteSignalListResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    set_taste_signal_verdict_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Category of the targeted signal */
                signal_type: string;
                /** @description Stable normalized key of the targeted feature */
                external_key: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TasteVerdictRequest"];
            };
        };
        responses: {
            /** @description The canonical updated signal after the verdict is persisted */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TasteSignalResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unknown signal type, verdict, or oversized external key */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    metrics_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Owner-scoped bounded reading metrics */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalyticsMetricsResponse"];
                };
            };
            /** @description Not authenticated, revoked token, or stale credential epoch */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    csrf_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Double-submit CSRF token */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CsrfResponse"];
                };
            };
        };
    };
    forgot_password_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ForgotPasswordRequest"];
            };
        };
        responses: {
            /** @description Enumeration-safe acknowledgement */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PasswordResetResponse"];
                };
            };
            /** @description Request payload failed validation */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Password-recovery rate limit exceeded */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    login_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Credentials accepted and bearer tokens issued */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Username field contained an email address */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Incorrect username or password */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Request payload failed validation */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Login rate limit exceeded */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    logout_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Bearer token revoked and refresh cookie cleared */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    me_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Authenticated account profile */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Not authenticated or token invalid */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    refresh_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": null | components["schemas"]["RefreshTokenRequest"];
            };
        };
        responses: {
            /** @description Refreshed bearer tokens issued */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Missing, invalid, revoked or stale refresh token */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Refresh rate limit exceeded */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    register_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegisterRequest"];
            };
        };
        responses: {
            /** @description Account created and bearer tokens issued */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Username or email is already registered */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Request payload failed validation */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Registration rate limit exceeded */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    reset_password_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResetPasswordRequest"];
            };
        };
        responses: {
            /** @description Password reset completed */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PasswordResetResponse"];
                };
            };
            /** @description Invalid or expired reset request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Request payload failed validation */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Password-recovery rate limit exceeded */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    read_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Reading Plan identifier */
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Option E plan projected from its authoritative Reading List */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlanReaderResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reading Plan not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Plan missing its authoritative Reading List */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    preview_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Reading Plan identifier */
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Owner-scoped recovery preview */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlanRecoveryPreview"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Plan not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    relink_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Reading Plan identifier */
                plan_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlanRelinkRequest"];
            };
        };
        responses: {
            /** @description Relinked or idempotently already linked */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlanRelinkResult"];
                };
            };
            /** @description Confirmation required */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Plan or list not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Stale preview or different authoritative list */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    read_demo_roll_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Deterministic sample Roll */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DemoRoll"];
                };
            };
        };
    };
    create_dependency_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DependencyCreateRequest"];
            };
        };
        responses: {
            /** @description Created dependency */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DependencyResponse"];
                };
            };
            /** @description Invalid or duplicate dependency */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Issue not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reading constraint cycle: nothing was changed */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    delete_dependency_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Dependency id */
                dependency_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Deleted */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Dependency not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    issue_cards_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IssueCardsRequest"];
            };
        };
        responses: {
            /** @description Owner-scoped cards in request order */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssueCardsResponse"];
                };
            };
            /** @description Invalid or unbounded issue id list */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    delete_issue_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Issue identifier */
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Issue deleted and positions compacted */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Issue not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Issue is referenced; nothing was changed */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    issue_read_rate_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Exact owned issue identifier */
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IssueReadRateRequest"];
            };
        };
        responses: {
            /** @description Reconciled issue and thread state */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IssueReadRateResponse"];
                };
            };
            /** @description Issue not found for this reader */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Idempotency key reused for a different action */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid status, rating or idempotency key */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    issue_intelligence_docs: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owner-scoped ComicPile issue id */
                issue_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Stored ComicVine intelligence, or null without a mapping */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": null | components["schemas"]["IssueIntelligence"];
                };
            };
            /** @description Invalid or revoked access token */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Issue is not owned by the reader */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    get_queue_entry_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Thread identifier */
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Queue entry */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueueEntryResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Queue entry not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    update_queue_entry_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Thread identifier */
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QueueEntryPatch"];
            };
        };
        responses: {
            /** @description Updated queue entry */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueueEntryResponse"];
                };
            };
            /** @description Invalid target position */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Queue entry not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    create_queue_order_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QueueOrderRequest"];
            };
        };
        responses: {
            /** @description Idempotent replay of the recorded revision */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueueOrderResponse"];
                };
            };
            /** @description Queue-order revision created */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueueOrderResponse"];
                };
            };
            /** @description Invalid idempotency key */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    reading_boundary_batch_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NativeReadingBoundaryBatchRequest"];
            };
        };
        responses: {
            /** @description Explanation projection for the requested owned threads */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingBoundaryBatchResponseV2"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description A requested thread is not owned by the reader */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Batch must contain between 1 and 200 thread ids */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    reading_graph_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Graph status, cycles and safe repair options */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingGraphResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid reading snapshot */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    repair_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReadingGraphRepairRequest"];
            };
        };
        responses: {
            /** @description Repair preview or applied result with the remaining graph */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingGraphRepairResponse"];
                };
            };
            /** @description Invalid repair request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Constraint not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid reading snapshot */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    list_reading_lists_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Owned Reading Lists */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingListSummary"][];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    create_reading_list_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReadingListWrite"];
            };
        };
        responses: {
            /** @description Created Reading List */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingList"];
                };
            };
            /** @description Invalid list metadata or membership */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Projected reading graph would cycle; nothing was changed */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    get_reading_list_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Reading List identifier */
                list_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Reading List with ordered entries */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingList"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reading List not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    update_reading_list_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Reading List identifier */
                list_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReadingListWrite"];
            };
        };
        responses: {
            /** @description Updated owner-scoped Reading List */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingList"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reading List not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Predecessor changes must be acknowledged */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid Issue or checkpoint */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    delete_reading_list_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Reading List identifier */
                list_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Reading List deleted; entries cascade */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reading List not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    read_reading_list_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Reading List identifier */
                list_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Reader with canonical availability */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingListReader"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reading List not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    initialize_session_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InitializeSessionRequest"];
            };
        };
        responses: {
            /** @description Created or resumed reading-session identity */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadingSessionCreatedResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    bootstrap_documentation: {
        parameters: {
            query?: {
                /** @description IANA timezone override for the active session */
                timezone?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Projected Roll bootstrap payload */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BootstrapResponseV2"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid native Roll projection */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    manual_die_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ManualDieRequest"];
            };
        };
        responses: {
            /** @description Manual die command receipt */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DiceCommandReceipt"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid die or idempotency key */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    die_state_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Current logical die, approved ladder and last roll */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RollDieStateResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid native Roll projection */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    eligible_issue_ids_documentation: {
        parameters: {
            query?: {
                /** @description Comma-separated browser-owned temporary snoozed thread identifiers */
                snoozed?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Ordered eligible issue identifiers for the current die */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RollEligibleIssueIdsResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid temporary snooze identifiers */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid native Roll projection */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    offer_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RollOfferRequest"];
            };
        };
        responses: {
            /** @description Recorded Roll offer for the active session */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RollOfferResponse"];
                };
            };
            /** @description No eligible thread remains for this roll */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reading session changed during the offer */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid idempotency key or too many temporary snoozes */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Roll offer projection unavailable */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    reset_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResetDiceRequest"];
            };
        };
        responses: {
            /** @description Reset die command receipt */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResetDiceResponse"];
                };
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Reading session changed during the reset */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid idempotency key */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    list_threads_documentation: {
        parameters: {
            query?: {
                /** @description Case-insensitive title search */
                search?: string;
                /** @description position, title, or created */
                sort?: string;
                /** @description 1-200 rows per page (default 50) */
                page_size?: number;
                /** @description Opaque continuation cursor */
                page_token?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Owner-scoped active threads page */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadListResponse"];
                };
            };
            /** @description Invalid sort or page token */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid bounds or retired collection_id */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    issue_order_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Thread identifier */
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IssueOrderRequest"];
            };
        };
        responses: {
            /** @description Issue order replaced */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description issue_ids must contain every thread issue exactly once */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Thread not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Projected reading graph would cycle; nothing was changed */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    create_issues_documentation: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Owned Thread identifier */
                thread_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateIssuesRequest"];
            };
        };
        responses: {
            /** @description Created issues */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NativeIssueListResponse"];
                };
            };
            /** @description Invalid issue range or no new issues */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not authenticated */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Thread not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Projected reading graph would cycle; nothing was changed */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Invalid reading snapshot */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Database temporarily unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    health_check_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    serve_react_redirect_react_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    serve_react_redirect_slash_react__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    serve_robots_txt_robots_txt_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    serve_sitemap_xml_sitemap_xml_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    serve_vite_svg_vite_svg_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    serve_react_spa__full_path__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                full_path: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
