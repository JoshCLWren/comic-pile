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

function isTransient(error) {
  return error?.status === 429 || (error?.status >= 500 && error?.status <= 599);
}

async function withRetry(operation, { attempts = 3, delay = 250 } = {}) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (!isTransient(error) || attempt === attempts) throw error;
      await new Promise(resolve => setTimeout(resolve, delay * attempt));
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
    const current = await currentLabels(github, context, pr.number);
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
      owner: owners.length === 1 ? owners[0] : 'factory:unowned', stage,
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
    if (!trusted(review)) return;
    const state = (review.state || '').toUpperCase();
    // Native APPROVED must never rewrite labels. A wired pull_request_review
    // path must not reset controller-set factory:ci / factory:ready back to
    // factory:review. Only CHANGES_REQUESTED (and dismissed above) mutate.
    if (state === 'APPROVED') return;
    if (state !== 'CHANGES_REQUESTED') return;
    await reconcileLabels(github, context, pullRequest.number, {
      owner: currentOwner || await ownerFromLinkedIssue(github, context, pullRequest),
      stage: 'factory:changes-requested',
    });
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
  workerFrom,
  trusted,
  performedViaUntrustedApp,
  TRUSTED_APP_SLUGS,
  TRUSTED_ASSOCIATIONS,
  EXPECTED_WORKER_IDS,
  FIXED_MODEL_OWNER_LABELS,
  WORKER_OWNER_LABELS,
};
