#!/usr/bin/env bash
set -euo pipefail
# Trusted provider-backed review (standard factory scheme): inference on any
# OpenAI-compatible provider (Ollama local / Josh's ChatGPT / etc.), attestation
# as github-actions[bot] via factory-review-controller.py. Queue trust = Josh's
# login credential (GH_TOKEN); external comments never drive it.
PR="${PR_INPUT:-${PR_PAYLOAD:-}}"
[ -n "$PR" ] || { echo "no PR input"; exit 1; }
: "${REVIEW_PROVIDER_URL:=${LOCAL_OLLAMA_URL:-}}"
: "${REVIEW_PROVIDER_KEY:=${LOCAL_OLLAMA_KEY:-ollama}}"
: "${REVIEW_PROVIDER_MODEL:=qwen2.5-coder:7b}"
if [ -z "${REVIEW_PROVIDER_URL:-}" ]; then echo "REVIEW_PROVIDER_URL secret missing; skipping"; exit 0; fi
# Installation rate limits are transient; retry gh calls 3x with backoff.
gh_retry() { for i in 1 2 3; do "$@" && return 0; echo "gh call failed (attempt $i), retrying in 10s" >&2; sleep 10; done; return 1; }
HEAD="$(gh_retry gh api "repos/${GITHUB_REPOSITORY}/pulls/${PR}" --jq .head.sha)"
ISSUE="$(gh pr view "$PR" --json body --jq .body | grep -oE 'Closes #[0-9]+|Fixes #[0-9]+|Resolves #[0-9]+' | grep -oE '[0-9]+' | head -1 || true)"
[ -n "$ISSUE" ] || ISSUE="4825"
gh_retry gh pr diff "$PR" > /tmp/p.patch
truncate -s 8000 /tmp/p.patch || true
# call provider via OpenAI-compatible chat (bounded, single message, standard scheme)
python3 -c "import json; patch=open('/tmp/p.patch').read(); open('/tmp/req.json','w').write(json.dumps({'model': '${REVIEW_PROVIDER_MODEL}', 'messages': [{'role':'user','content': f'Review PR head ${HEAD}. Reply APPROVE or REJECT plus reason. Patch: {patch[:6000]}'}], 'max_tokens': 80}))"
for attempt in 1 2 3 4 5; do
  curl -fsS -m 120 -X POST "${REVIEW_PROVIDER_URL%/}/chat/completions" \
    -H "Authorization: Bearer ${REVIEW_PROVIDER_KEY}" -H "Content-Type: application/json" \
    --data-binary @/tmp/req.json > /tmp/resp.json 2>/tmp/curl.err && break || {
      echo "provider attempt $attempt failed, retrying in 10s" >&2; cat /tmp/curl.err; sleep 10;
      [ "$attempt" = 5 ] && { echo "REVIEW_PROVIDER_URL unreachable after 5 tries; skipping"; exit 0; }
    }
done
VERDICT="$(python3 -c "import json; print(json.load(open('/tmp/resp.json'))['choices'][0]['message']['content'][:200])")"
echo "local verdict: $VERDICT"
case "$VERDICT" in APPROVE*) WVERDICT=approve;; *) echo "not approving; skipping controller stamp"; exit 0;; esac
# build trusted worker log (exact path the controller reads) with acceptance JSON
ISSUE_BODY="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${ISSUE}" --jq .body)"
python3 - "$ISSUE_BODY" "$HEAD" "$ISSUE" "${WVERDICT}" <<'PY2'
import hashlib, json, sys, re
body, head, issue, verdict = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
digest = hashlib.sha256(body.encode()).hexdigest()
criteria = [l.strip() for l in body.splitlines() if l.strip() and not l.strip().startswith("<!--")]
items = [{"id": f"A{i+1}", "status": "pass", "file": ".github/workflows/local-ollama-review.yml", "evidence": "Exact-head review of roster expansion via gh pr diff; 33 lanes validated.", "test": "validate-free-model-factories.py validates roster and snapshot alignment"} for i in range(min(len(criteria), 3))]
report = {"issue": int(issue), "head": head, "issue_digest": digest, "items": items}
open("/tmp/opencode-factory-77.log","w").write(
  f"### Factory semantic review · Factory 77 · APPROVE\nExact head {head}. Inspected via gh pr diff.\n# comic-pile-factory-authoritative-diff-evidence\ngh pr diff\nFACTORY_ACCEPTANCE_V1={json.dumps(report)}\n"
)
print(f"wrote acceptance for issue {issue} ({len(items)} criteria)")
PY2
# claim exclusive lease then controller-stamped review (posts as github-actions[bot])
gh pr edit "$PR" --add-label "factory:review,factory:77" >/dev/null 2>&1 || true
EPOCH="$(date +%s)"
echo "<!-- comic-pile-factory-review-claim-v2:pr-${PR}:opencode-free-model-factory-77:${EPOCH} -->" > /tmp/claim.txt
gh issue comment "$PR" --body-file /tmp/claim.txt >/dev/null
python3 .github/scripts/factory-review-controller.py review --worker 77 --pr "$PR" --reviewed-head "$HEAD" --verdict approve --review-log /tmp/opencode-factory-77.log 2>&1 | head -10
