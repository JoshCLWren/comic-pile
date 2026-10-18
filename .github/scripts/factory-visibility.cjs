const {
  SCHEDULED_WORKER_IDS,
  loadExpectedWorkerIds,
} = require('./factory-expected-workers.cjs');

const {
  expectedWorkers: EXPECTED_WORKER_IDS,
  retiredWorkers: RETIRED_WORKER_IDS,
} = loadExpectedWorkerIds();

const SCHEDULED_OWNER_LABELS = SCHEDULED_WORKER_IDS.map((id) => `factory:${id}`);
const FIXED_MODEL_OWNER_LABELS = [...EXPECTED_WORKER_IDS]
  .sort((left, right) => left - right)
  .map((id) => `factory:${id}`);
// Label definitions and known owner names stay roster-derived. Retired ids are
// kept in OWNER_LABELS so historical leases can still be stripped cleanly.
const RETIRED_OWNER_LABELS = [...RETIRED_WORKER_IDS]
  .sort((left, right) => left - right)
  .map((id) => `factory:${id}`);
const WORKER_OWNER_LABELS = [...SCHEDULED_OWNER_LABELS, ...FIXED_MODEL_OWNER_LABELS];

const DEFINITIONS = {
  factory: ['5319E7', 'Work owned or produced by an autonomous ComicPile factory'],
  ...Object.fromEntries(WORKER_OWNER_LABELS.map((name) => {
    const number = name.slice('factory:'.length);
    return [name, ['0366D6', `Current next-action owner is ComicPile Factory ${number}`]];
  })),
  'factory:local': ['0366D6', 'Current next-action owner is the local OpenCode factory'],
  'factory:unowned': ['BFDADC', 'Factory work has no current next-action owner'],
  'factory:building': ['FBCA04', 'A factory is actively implementing or repairing this work'],
  'factory:review': ['D4C5F9', 'The exact current head needs review or re-review'],
  'factory:changes-requested': ['D73A4A', 'Actionable review findings currently block progress'],
  'factory:ci': ['1D76DB', 'Review passed and required exact-head checks are being verified'],
  'factory:ready': ['0E8A16', 'All exact-head factory merge gates are satisfied'],
  'factory:blocked': ['B60205', 'A genuine human, credential, or external blocker remains'],
};

const OWNER_LABELS = [
  ...new Set([
    ...SCHEDULED_OWNER_LABELS,
    ...FIXED_MODEL_OWNER_LABELS,
    ...RETIRED_OWNER_LABELS,
    'factory:local',
    'factory:unowned',
  ]),
];

function isOwnerLabel(label) {
  return label === 'factory:local'
    || label === 'factory:unowned'
    || /^factory:\d+$/.test(label);
}

const STAGE_LABELS = [
  'factory:building',
  'factory:review',
  'factory:changes-requested',
  'factory:ci',
  'factory:ready',
  'factory:blocked',
];
const ADVANCED_PR_STAGES = new Set(['factory:review', 'factory:ci', 'factory:ready']);
const MANUAL_ONLY_MARKER = '<!-- factory-execution:manual-only -->';

function hasManualOnlyDirective(body) {
  // Referencing this marker in inline or fenced documentation is not an opt-out.
  // Only a standalone directive outside Markdown code spans qualifies.
  const prose = String(body || '')
    .replace(/`{3}[\s\S]*?`{3}/g, '')
    .replace(/`[^`\n]*`/g, '');
  return prose.split(/\r?\n/).some(line => line.trim() === MANUAL_ONLY_MARKER);
}
const TRUSTED_ASSOCIATIONS = new Set(['OWNER', 'MEMBER', 'COLLABORATOR']);
const TRUSTED_APP_SLUGS = new Set(['github-actions']);

function performedViaUntrustedApp(comment) {
  const app = comment?.performed_via_github_app;
  if (!app || typeof app !== 'object') return false;
  const slug = app.slug;
  if (typeof slug !== 'string' || !slug) return false;
  return !TRUSTED_APP_SLUGS.has(slug);
}

function trusted(comment) {
  // Mirror Python trusted_comment_bodies: reject non-github-actions Apps even with a
  // trusted association; accept human OWNER/MEMBER/COLLABORATOR with no App; accept
  // exact github-actions[bot] regardless of association. Never trust any other App.
  if (performedViaUntrustedApp(comment)) return false;
  const association = comment?.author_association;
  if (TRUSTED_ASSOCIATIONS.has(association)) return true;
  return comment?.user?.login === 'github-actions[bot]';
}

// Reviewer bots whose inline findings route a PR to repair. This allowlist is
// deliberately separate from trusted(): a reviewer bot can never author
// factory markers, ownership, or readiness. It only proves that the bot left
// unresolved findings on the exact current head.
const REPAIR_ROUTING_REVIEWER_BOTS = new Set(['greptile-apps[bot]']);

function isRepairRoutingReviewer(review) {
  return REPAIR_ROUTING_REVIEWER_BOTS.has(review?.user?.login);
}

function reviewerGraphqlLogins() {
  // GraphQL reports App actors without the REST "[bot]" suffix.
  return new Set([...REPAIR_ROUTING_REVIEWER_BOTS].flatMap(login => [login, login.replace(/\[bot\]$/, '')]));
}

const REVIEW_THREAD_PAGE_LIMIT = 50;

// Open-thread rule, shared with .github/scripts/factory-review-findings.sh
// (FACTORY_GREPTILE_JQ_DEFS; keep them identical, see
// docs/FACTORY_GITHUB_VISIBILITY.md "Open Greptile findings"). A review thread
// is an OPEN Greptile finding when it is unresolved, not outdated, its first
// comment is by Greptile, and neither of these holds:
//   1. Greptile's latest comment is a reply acknowledging/accepting the answer;
//   2. a trusted responder (OWNER/MEMBER/COLLABORATOR, github-actions, or an
//      opencode-*factory* worker app) replied after Greptile's latest comment.
const GREPTILE_ACK_RE = /^(you['\u2019]?re (absolutely |totally )?right|you are (absolutely |totally )?right|(that|this) (addresses|resolves|answers|fixes|clears up|handles)|good (catch|point|call)|makes sense|fair (point|enough)|agreed|acknowledged|understood|confirmed|thanks|thank you)/i;
const TRUSTED_RESPONDER_LOGIN_RE = /^(github-actions(\[bot\])?|opencode-[a-z0-9-]*factory[a-z0-9-]*(\[bot\])?)$/;

function isGreptileLogin(login) {
  return reviewerGraphqlLogins().has(login || '');
}

function isGreptileAck(body) {
  const text = String(body || '').replace(/<[^>]*>/g, '').replace(/^[\s*_>`"-]+/, '');
  return GREPTILE_ACK_RE.test(text);
}

function isTrustedResponder(comment) {
  return TRUSTED_RESPONDER_LOGIN_RE.test(comment?.author?.login || '')
    || TRUSTED_ASSOCIATIONS.has(comment?.authorAssociation || '');
}

// thread: { isResolved, isOutdated, firstComment: {author,url}, comments: [...] }
// where comments is the most recent window (oldest first). Only the suffix
// after Greptile's latest comment matters, so a bounded recent window is exact
// whenever it contains that comment or any trusted reply.
function greptileThreadState(thread) {
  const first = thread?.firstComment;
  if (!first || !isGreptileLogin(first.author?.login)) return 'other';
  if (thread.isResolved) return 'resolved';
  if (thread.isOutdated) return 'outdated';
  const comments = Array.isArray(thread.comments) ? thread.comments : [];
  let lastGreptile = -1;
  comments.forEach((comment, index) => {
    if (isGreptileLogin(comment?.author?.login)) lastGreptile = index;
  });
  const latest = lastGreptile >= 0 ? comments[lastGreptile] : null;
  const latestIsReply = latest && (!first.url || latest.url !== first.url);
  if (latestIsReply && isGreptileAck(latest.body)) return 'acknowledged';
  if (comments.slice(lastGreptile + 1).some(isTrustedResponder)) return 'answered';
  return 'open';
}

function lastTrustedAnswerAt(thread) {
  const answers = (thread?.comments || []).filter(isTrustedResponder).map(c => c.createdAt).filter(Boolean);
  return answers.length ? answers.sort().at(-1) : null;
}

async function greptileReviewThreads(github, context, number, { pageLimit = REVIEW_THREAD_PAGE_LIMIT } = {}) {
  // Follow every reviewThreads page: an open finding beyond the first 100
  // threads must still route the PR to repair. Returns the normalized threads
  // and whether every page was read; callers must fail closed when incomplete.
  const threads = [];
  let after = null;
  for (let page = 0; page < pageLimit; page += 1) {
    const response = await withRetry(() => github.graphql(
      `query($owner:String!,$name:String!,$number:Int!,$after:String){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{id isResolved isOutdated firstComment:comments(first:1){nodes{databaseId url author{login}}} recent:comments(last:20){nodes{url author{login} authorAssociation body createdAt}}}}}}}`,
      { owner: context.repo.owner, name: context.repo.repo, number, after },
    ));
    const connection = response?.repository?.pullRequest?.reviewThreads;
    if (!Array.isArray(connection?.nodes)) return { threads, complete: false };
    for (const node of connection.nodes) {
      threads.push({
        id: node.id,
        isResolved: Boolean(node.isResolved),
        isOutdated: Boolean(node.isOutdated),
        firstComment: node.firstComment?.nodes?.[0] || null,
        comments: node.recent?.nodes || [],
      });
    }
    if (connection.pageInfo?.hasNextPage === false) return { threads, complete: true };
    if (connection.pageInfo?.hasNextPage !== true || !connection.pageInfo.endCursor) {
      return { threads, complete: false };
    }
    after = connection.pageInfo.endCursor;
  }
  return { threads, complete: false };
}

async function unresolvedReviewerBotThreads(github, context, number, options = {}) {
  const { threads, complete } = await greptileReviewThreads(github, context, number, options);
  return { count: threads.filter(thread => greptileThreadState(thread) === 'open').length, complete };
}

// Greptile re-reviews often only rewrite the PR-body summary. Parse its
// findings list for the exact head it reviewed. Returns null when the body has
// no Greptile summary, else { commit, findings: [{ title, discussionId }] }.
function greptileSummaryFindings(body) {
  const lines = String(body || '').split(/\r?\n/);
  const start = lines.findIndex(line => /^\s*<!-- greptile_comment -->\s*$/.test(line));
  if (start < 0) return null;
  let end = lines.findIndex((line, index) => index > start && /^\s*<!-- \/greptile_comment -->\s*$/.test(line));
  if (end < 0) end = lines.length;
  const block = lines.slice(start + 1, end);
  const text = block.join('\n');
  const commit = (text.match(/Last reviewed commit:.*?\/commit\/([0-9a-f]{40})/i) || [])[1] || null;
  const findings = block
    .filter(line => /^\s*\d+\.\s.*<img[^>]*\balt="P\d"/.test(line))
    .map(line => ({
      title: ((line.match(/\*\*([^*]+)\*\*/) || [])[1] || '').trim(),
      discussionId: (line.match(/#discussion_r(\d+)/) || [])[1] || null,
    }));
  return { commit, findings };
}

async function greptileReviewCompletedAt(github, context, sha) {
  const response = await withRetry(() => github.rest.checks.listForRef({
    owner: context.repo.owner,
    repo: context.repo.repo,
    ref: sha,
    per_page: 100,
  }));
  const times = (response?.data?.check_runs || [])
    .filter(run => /greptile/i.test(run.name || '') && run.completed_at)
    .map(run => run.completed_at);
  return times.length ? times.sort().at(-1) : null;
}

// A summary finding counts when Greptile lists it for the live head and its
// linked thread (if any) is not acknowledged/outdated and either still open
// or answered only before Greptile's latest review of this head completed.
function openSummaryFindings(summary, threads, head, reviewedAt) {
  if (!summary || !summary.commit || summary.commit !== head) return [];
  const byComment = new Map(threads
    .filter(thread => thread.firstComment?.databaseId)
    .map(thread => [String(thread.firstComment.databaseId), thread]));
  return summary.findings.filter(finding => {
    const thread = finding.discussionId ? byComment.get(finding.discussionId) : null;
    if (!thread) return true;
    const state = greptileThreadState(thread);
    if (state === 'open') return true;
    if (state !== 'answered' && state !== 'resolved') return false;
    const answeredAt = lastTrustedAnswerAt(thread);
    return Boolean(answeredAt && reviewedAt && reviewedAt > answeredAt);
  });
}

// State-based Greptile routing. Every routing event (any submitted review or
// a PR-body edit) recomputes from the live PR: its head, its review threads,
// and Greptile's PR-body summary. A superseded or replaced pending run is
// therefore harmless, because the next run sees the same live state. Routing
// only ever moves a PR to factory:changes-requested; it never un-routes.
async function routeGreptileFindings(github, context, number) {
  const live = (await withRetry(() => github.rest.pulls.get({
    owner: context.repo.owner,
    repo: context.repo.repo,
    pull_number: number,
  })))?.data;
  if (!live || (live.state && live.state !== 'open')) return { routed: false, reason: 'not-open' };
  const head = live.head?.sha;
  const current = await currentLabels(github, context, number);
  const sameRepo = !live.head?.repo || live.head.repo.full_name === context.payload.repository?.full_name;
  if (!(current.has('factory') || (sameRepo && (live.head?.ref || '').startsWith('factory/')))) {
    return { routed: false, reason: 'not-factory' };
  }
  const { threads, complete } = await greptileReviewThreads(github, context, number);
  const openThreads = threads.filter(thread => greptileThreadState(thread) === 'open');
  const summary = greptileSummaryFindings(live.body);
  let openSummary = [];
  if (summary && summary.commit === head && summary.findings.length) {
    openSummary = openSummaryFindings(summary, threads, head, await greptileReviewCompletedAt(github, context, head));
  }
  if (openThreads.length === 0 && openSummary.length === 0) {
    // Fail closed: never treat a truncated thread listing as "no findings".
    // Failing the run leaves the event visibly red for retry.
    if (!complete) {
      throw new Error(`PR #${number}: review-thread pagination was incomplete; refusing to treat Greptile findings as absent`);
    }
    return { routed: false, reason: 'no-open-findings' };
  }
  if (current.has('factory:changes-requested')) return { routed: false, reason: 'already-routed' };
  await reconcileLabels(github, context, number, {
    owner: [...current].find(isOwnerLabel) || await ownerFromLinkedIssue(github, context, { ...live, number }),
    stage: 'factory:changes-requested',
  });
  return { routed: true, openThreads: openThreads.length, openSummary: openSummary.length };
}

async function livePullRequestHead(github, context, number) {
  const response = await withRetry(() => github.rest.pulls.get({
    owner: context.repo.owner,
    repo: context.repo.repo,
    pull_number: number,
  }));
  return response?.data?.head?.sha || null;
}

function workerFrom(body) {
  for (const pattern of [
    /comic-pile-factory-implement-(?:claim|progress)-v\d+:issue-\d+:([^:\s>]+):/,
    /comic-pile-factory-review-claim-v\d+:[^:\s>]+:([^:\s>]+):/,
    /comic-pile-factory-fix-(?:claim|progress)-v\d+:[^:\s>]+:([^:\s>]+):/,
    /comic-pile-factory-claim-released-v\d+:[^:\s>]+:([^:\s>]+):/,
    /comic-pile-factory-head-contributor-v\d+:[^:\s>]+:[^:\s>]+:worker-(\d+):/,
  ]) {
    const match = body.match(pattern);
    if (match) return match[1];
  }
  return null;
}

function ownerFor(worker) {
  if (worker == null || worker === '') return 'factory:unowned';
  const token = String(worker);

  const scheduled = token.match(/^chatgpt-factory-([1-5])$/);
  if (scheduled) return `factory:${scheduled[1]}`;

  let number = null;
  const fixedModel = token.match(/^opencode-(?:free-model|nvidia|omniroute)-factory-(\d+)$/);
  if (fixedModel) {
    number = Number(fixedModel[1]);
  } else {
    const bare = token.match(/^(?:worker-)?(\d+)$/);
    if (bare) number = Number(bare[1]);
  }
  if (number != null && EXPECTED_WORKER_IDS.has(number)) {
    return `factory:${number}`;
  }

  if (token === 'local' || token === 'local-opencode' || token.startsWith('local-opencode-')) {
    return 'factory:local';
  }
  return 'factory:unowned';
}

function durablePrOwner(current) {
  if (current.has('factory:local')) return 'factory:local';
  // Preserve any non-scheduled numeric owner lease already on the PR. Validity
  // for *new* ownership is roster-gated in ownerFor; durability must not depend
  // on a contiguous 1..N label array.
  for (const label of current) {
    const match = /^factory:(\d+)$/.exec(label);
    if (!match) continue;
    const number = Number(match[1]);
    if (SCHEDULED_WORKER_IDS.includes(number)) continue;
    return label;
  }
  return null;
}

function stageFrom(body) {
  if (/comic-pile-factory-needs-human-v\d+:/.test(body)) return 'factory:blocked';
  if (/comic-pile-factory-ready-v\d+:/.test(body)) return 'factory:ready';
  if (/comic-pile-factory-review-v\d+:[^:\s>]+:changes-required/.test(body)) {
    return 'factory:changes-requested';
  }
  if (/comic-pile-factory-review-v\d+:[^:\s>]+:pass/.test(body)) return 'factory:ci';
  if (/comic-pile-factory-review-claim-v\d+:/.test(body)) return 'factory:review';
  if (
    /comic-pile-factory-implement-(?:claim|progress)-v\d+:/.test(body)
    || /comic-pile-factory-fix-(?:claim|progress)-v\d+:/.test(body)
  ) return 'factory:building';
  return null;
}

function rateLimitDelay(error, now = Date.now()) {
  const headers = error?.response?.headers || error?.headers || {};
  const remaining = Number(headers['x-ratelimit-remaining']);
  const limited = (error?.status === 403 && headers['x-ratelimit-remaining'] != null && remaining === 0)
    || error?.status === 429;
  if (!limited) return null;

  const retryAfter = Number(headers['retry-after']);
  if (headers['retry-after'] != null && Number.isFinite(retryAfter) && retryAfter >= 0) {
    return Math.ceil(retryAfter * 1000);
  }
  const reset = Number(headers['x-ratelimit-reset']);
  if (Number.isFinite(reset) && reset > 0) return Math.max(0, reset * 1000 - now + 1000);
  return null;
}

function isTransient(error) {
  return error?.status === 429
    || (error?.status >= 500 && error?.status <= 599)
    || (error?.status === 403 && rateLimitDelay(error) !== null);
}

async function withRetry(operation, { attempts = 3, delay = 250, maxRateLimitWait = 30000, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)) } = {}) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (!isTransient(error) || attempt === attempts) throw error;
      const rateDelay = rateLimitDelay(error);
      // Never spin on exhausted installation quota. Fail the run if reset is too
      // distant or unknown: Actions can resume on the next scheduled/event run.
      if ((error.status === 403 || error.status === 429)
          && (rateDelay === null || rateDelay > maxRateLimitWait)) throw error;
      await sleep(rateDelay === null ? delay * attempt : rateDelay);
    }
  }
  throw lastError;
}

async function currentLabels(github, context, number) {
  const labels = await withRetry(() => github.paginate(github.rest.issues.listLabelsOnIssue, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    issue_number: number,
    per_page: 100,
  }));
  return new Set(labels.map(label => label.name));
}

async function reconcileLabels(github, context, number, { owner, stage }) {
  const current = await currentLabels(github, context, number);
  const next = [...current].filter(
    label => !isOwnerLabel(label) && !STAGE_LABELS.includes(label),
  );
  if (!next.includes('factory')) next.push('factory');
  if (owner) next.push(owner);
  if (stage) next.push(stage);

  // A no-op label replacement still consumes API quota and emits a labels event.
  // Compare sets, since GitHub does not promise stable label ordering.
  if (current.size === next.length && next.every(label => current.has(label))) return;

  await withRetry(() => github.rest.issues.setLabels({
    owner: context.repo.owner,
    repo: context.repo.repo,
    issue_number: number,
    labels: next,
  }));
}

async function ensureLabels(github, context) {
  const existing = await withRetry(() => github.paginate(github.rest.issues.listLabelsForRepo, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    per_page: 100,
  }));
  const byName = new Map(existing.map(label => [label.name, label]));
  for (const [name, [color, description]] of Object.entries(DEFINITIONS)) {
    const current = byName.get(name);
    if (!current) {
      await withRetry(() => github.rest.issues.createLabel({
        owner: context.repo.owner,
        repo: context.repo.repo,
        name,
        color,
        description,
      }));
    } else if (
      current.color.toUpperCase() !== color
      || (current.description || '') !== description
    ) {
      await withRetry(() => github.rest.issues.updateLabel({
        owner: context.repo.owner,
        repo: context.repo.repo,
        name,
        new_name: name,
        color,
        description,
      }));
    }
  }
}

async function ownerFromLinkedIssue(github, context, pullRequest) {
  const closing = (pullRequest.body || '').match(
    /(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)/i,
  );
  const fixedModelBranch = pullRequest.head.ref.match(
    /^factory\/\d+-(\d+)-(?:nvidia|omni|opencode-free)(?:-|$)/,
  );
  const legacyBranch = pullRequest.head.ref.match(/^factory\/(\d+)(?:-|$)/);
  const issueNumber = Number(closing?.[1] || fixedModelBranch?.[1] || legacyBranch?.[1] || 0);
  if (!issueNumber) return 'factory:unowned';

  const comments = await withRetry(() => github.paginate(github.rest.issues.listComments, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    issue_number: issueNumber,
    per_page: 100,
  }));
  comments.sort((left, right) => new Date(right.created_at) - new Date(left.created_at));
  for (const comment of comments) {
    if (!trusted(comment)) continue;
    const body = comment.body || '';
    if (/comic-pile-factory-claim-released-v\d+:/.test(body)) return 'factory:unowned';
    const worker = workerFrom(body);
    if (worker) return ownerFor(worker);
  }
  return 'factory:unowned';
}

async function reconcileMissingPrLabels({ github, context }) {
  const candidates = context.eventName === 'pull_request_target'
    ? [context.payload.pull_request]
    : await withRetry(() => github.paginate(github.rest.pulls.list, {
      ...context.repo, state: 'open', per_page: 100,
    }));
  for (const pr of candidates) {
    if (pr.state !== 'open' || pr.draft
      || pr.head.repo?.full_name !== `${context.repo.owner}/${context.repo.repo}`
      || /^(dependabot|renovate)(\[bot\])?$/.test(pr.user?.login || '')) continue;
    // Manual-only PRs are operator-managed and must never be enrolled into the
    // factory queue (enroll would otherwise default them to factory:review).
    if (hasManualOnlyDirective(pr.body)) continue;
    const current = await currentLabels(github, context, pr.number);
    // A local factory lease is a real active owner, not an exemption from
    // factory review. Preserve it until the local session explicitly releases
    // ownership; never take it over during an enrollment sweep.
    const owners = [...current].filter(isOwnerLabel);
    const stages = STAGE_LABELS.filter(label => current.has(label));
    if (current.has('factory') && owners.length === 1 && stages.length === 1) continue;

    // Repair missing metadata without taking an existing lease or downgrading
    // review/CI state. Never manufacture readiness from green checks alone.
    let stage = stages.length === 1 ? stages[0] : 'factory:review';
    if (stages.length === 0) {
      const comments = await withRetry(() => github.paginate(github.rest.issues.listComments, {
        ...context.repo, issue_number: pr.number, per_page: 100,
      }));
      for (const comment of [...comments].sort(
        (left, right) => new Date(right.created_at) - new Date(left.created_at),
      )) {
        if (!trusted(comment)) continue;
        const match = (comment.body || '').match(
          /comic-pile-factory-review-v\d+:([a-f0-9]{40}):(pass|changes-required)/,
        );
        if (match?.[1] !== pr.head.sha) continue;
        stage = match[2] === 'pass' ? 'factory:ci' : 'factory:changes-requested';
        break;
      }
    }
    await reconcileLabels(github, context, pr.number, {
      // Never interpret a contradictory local+unowned label pair as a lease
      // release. Keep the active local owner until its session hands off.
      owner: current.has('factory:local')
        ? 'factory:local'
        : owners.length === 1 ? owners[0] : 'factory:unowned',
      stage,
    });
  }
}

async function reconcile({ github, context }) {
  await ensureLabels(github, context);

  if (context.eventName === 'issue_comment') {
    const comment = context.payload.comment;
    const body = comment?.body || '';
    if (!body.includes('comic-pile-factory-')) return;
    if (!trusted(comment)) return;

    const number = context.payload.issue.number;
    const current = await currentLabels(github, context, number);
    const released = /comic-pile-factory-claim-released-v\d+:/.test(body);
    const worker = workerFrom(body);
    const currentOwner = [...current].find(isOwnerLabel) || null;
    const currentStage = STAGE_LABELS.find(label => current.has(label));
    const requestedStage = stageFrom(body);
    const preserveAdvancedPrStage = Boolean(context.payload.issue.pull_request)
      && requestedStage === 'factory:building'
      && ADVANCED_PR_STAGES.has(currentStage);

    await reconcileLabels(github, context, number, {
      owner: released ? 'factory:unowned' : worker ? ownerFor(worker) : currentOwner,
      stage: preserveAdvancedPrStage ? currentStage : requestedStage || currentStage,
    });
    return;
  }

  if (context.eventName === 'pull_request_target' && context.payload.action === 'edited') {
    // Greptile re-reviews that only rewrite the PR-body summary still route.
    if (!context.payload.changes?.body) return;
    if (!/^\s*<!-- greptile_comment -->\s*$/m.test(context.payload.pull_request?.body || '')) return;
    await routeGreptileFindings(github, context, context.payload.pull_request.number);
    return;
  }

  if (context.eventName === 'pull_request_target') {
    const pullRequest = context.payload.pull_request;
    const sameRepo = pullRequest.head.repo?.full_name === context.payload.repository.full_name;
    const alreadyFactory = (pullRequest.labels || []).some(label => label.name === 'factory');
    const isFactory = alreadyFactory || (
      sameRepo
      && (
        pullRequest.head.ref.startsWith('factory/')
        || (pullRequest.body || '').includes('comic-pile-factory-')
      )
    );
    if (!isFactory) return;

    const current = await currentLabels(github, context, pullRequest.number);
    const prLocalOwner = durablePrOwner(current);

    await reconcileLabels(github, context, pullRequest.number, {
      // Local and fixed-model workers write durable PR-local ownership before
      // review workflows refresh visibility. Preserve that stronger signal even
      // when the linked issue has since been released for other work.
      owner: prLocalOwner || await ownerFromLinkedIssue(github, context, pullRequest),
      stage: 'factory:review',
    });
    return;
  }

  if (context.eventName === 'pull_request_review') {
    const pullRequest = context.payload.pull_request;
    const current = await currentLabels(github, context, pullRequest.number);
    const sameRepo = pullRequest.head.repo?.full_name === context.payload.repository.full_name;
    if (!(current.has('factory') || (sameRepo && pullRequest.head.ref.startsWith('factory/')))) {
      return;
    }

    const currentOwner = [...current].find(isOwnerLabel) || null;
    if (context.payload.action === 'dismissed') {
      await reconcileLabels(github, context, pullRequest.number, {
        owner: currentOwner || await ownerFromLinkedIssue(github, context, pullRequest),
        stage: 'factory:review',
      });
      return;
    }

    const review = context.payload.review;
    if (trusted(review) && (review.state || '').toUpperCase() === 'CHANGES_REQUESTED') {
      await reconcileLabels(github, context, pullRequest.number, {
        owner: currentOwner || await ownerFromLinkedIssue(github, context, pullRequest),
        stage: 'factory:changes-requested',
      });
      return;
    }
    // Any other submitted review (Greptile's COMMENTED review, a thread reply,
    // or a review that replaced a still-pending run in this PR's concurrency
    // group) recomputes Greptile routing from live state. Native APPROVED
    // never moves labels by itself.
    await routeGreptileFindings(github, context, pullRequest.number);
    return;
  }
}

module.exports = reconcile;
module.exports.reconcileMissingPrLabels = reconcileMissingPrLabels;
module.exports._test = {
  durablePrOwner,
  ownerFor,
  isOwnerLabel,
  reconcileLabels,
  withRetry,
  rateLimitDelay,
  workerFrom,
  trusted,
  isRepairRoutingReviewer,
  unresolvedReviewerBotThreads,
  greptileReviewThreads,
  greptileThreadState,
  greptileSummaryFindings,
  openSummaryFindings,
  routeGreptileFindings,
  isGreptileAck,
  livePullRequestHead,
  REVIEW_THREAD_PAGE_LIMIT,
  REPAIR_ROUTING_REVIEWER_BOTS,
  performedViaUntrustedApp,
  TRUSTED_APP_SLUGS,
  TRUSTED_ASSOCIATIONS,
  EXPECTED_WORKER_IDS,
  FIXED_MODEL_OWNER_LABELS,
  WORKER_OWNER_LABELS,
};
