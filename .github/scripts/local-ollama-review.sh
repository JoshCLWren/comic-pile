#!/usr/bin/env bash
set -euo pipefail

# Trusted provider-backed review. Inference may come from Ollama or another
# OpenAI-compatible provider, but only the controller's github-actions[bot]
# attestation can affect factory state. External comments never drive the queue.
PR="${PR_INPUT:-${PR_PAYLOAD:-}}"
[ -n "$PR" ] || { echo "no PR input" >&2; exit 1; }
: "${REVIEW_PROVIDER_URL:=${LOCAL_OLLAMA_URL:-}}"
: "${REVIEW_PROVIDER_KEY:=${LOCAL_OLLAMA_KEY:-ollama}}"
: "${REVIEW_PROVIDER_MODEL:=qwen2.5-coder:7b}"
[ -n "${REVIEW_PROVIDER_URL:-}" ] || { echo "REVIEW_PROVIDER_URL secret missing" >&2; exit 1; }

gh_retry() {
  for attempt in 1 2 3; do
    "$@" && return 0
    echo "gh call failed (attempt $attempt), retrying in 10s" >&2
    sleep 10
  done
  return 1
}

HEAD="$(gh_retry gh api "repos/${GITHUB_REPOSITORY}/pulls/${PR}" --jq .head.sha)"
ISSUE="$(gh pr view "$PR" --json body --jq .body | grep -oE 'Closes #[0-9]+|Fixes #[0-9]+|Resolves #[0-9]+' | grep -oE '[0-9]+' | head -1 || true)"
[ -n "$ISSUE" ] || ISSUE="4825"
gh_retry gh pr diff "$PR" > /tmp/p.patch
truncate -s 16000 /tmp/p.patch || true

# Build the prompt from the authoritative issue rubric and exact changed paths.
# The model must return the complete structured report; this script never
# fabricates acceptance items, citations, evidence, or test names.
python3 - "$HEAD" "$ISSUE" "$PR" "$REVIEW_PROVIDER_MODEL" <<'PY'
import importlib.util
import json
import os
import subprocess
import sys

head, issue, pr, model = sys.argv[1:]
spec = importlib.util.spec_from_file_location("factory_issue_acceptance", ".github/scripts/factory_issue_acceptance.py")
assert spec and spec.loader
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
repo = os.environ["GITHUB_REPOSITORY"]
body = json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/issues/{issue}"], text=True))["body"]
pr_data = json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/pulls/{pr}"], text=True))
changed = [path for path in subprocess.check_output(["gh", "pr", "diff", pr, "--name-only"], text=True).splitlines() if path]
checks = subprocess.run(
    ["gh", "pr", "checks", pr],
    text=True,
    capture_output=True,
    check=False,
).stdout
prompt = (
    "You are the independent semantic reviewer for a factory PR. Inspect the exact PR head and "
    "decide whether every issue criterion is actually satisfied by this diff. Do not infer or "
    "fabricate evidence. Return one JSON object only with this shape: "
    '{"verdict":"APPROVE"|"REJECT","reason":"...","acceptance":{"issue":NUMBER,'
    '"head":"FULL_SHA","issue_digest":"SHA256","items":[{"id":"A1","status":"pass",'
    '"file":"CHANGED_FILE","evidence":"specific fact from the diff, at least 30 characters",'
    '"test":"named test or check and what it verifies"}]}}. '
    "For REJECT, still include every rubric item with status pass only where justified; the "
    "runner fails closed if the report is incomplete. Each cited file must be one of the changed "
    "paths. Use the exact issue number, full head, and digest below.\n\nIssue rubric:\n" +
    acceptance.rubric(body) + "\n\nChanged paths:\n" + "\n".join(changed) +
    "\n\nExact head: " + head + "\nIssue: " + issue +
    "\nIssue digest: " + acceptance.digest(body) +
    "\n\nPR title:\n" + pr_data.get("title", "") +
    "\n\nPR body (authoritative validation claims; verify them against the diff):\n" +
    pr_data.get("body", "")[:8000] +
    "\n\nCurrent CI checks for the exact PR head:\n" + checks[:6000] +
    "\n\nPatch:\n" +
    open("/tmp/p.patch", encoding="utf-8").read()[:14000]
)
json.dump({"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1400}, open("/tmp/req.json", "w"))
PY

for attempt in 1 2 3 4 5; do
  if curl -fsS -m 120 -X POST "${REVIEW_PROVIDER_URL%/}/v1/chat/completions" \
    -H "Authorization: Bearer ${REVIEW_PROVIDER_KEY}" -H "Content-Type: application/json" \
    --data-binary @/tmp/req.json > /tmp/resp.json 2>/tmp/curl.err; then
    break
  fi
  echo "provider attempt $attempt failed, retrying in 10s" >&2
  cat /tmp/curl.err >&2
  [ "$attempt" = 5 ] && { echo "REVIEW_PROVIDER_URL unreachable after 5 tries; failing loudly" >&2; exit 1; }
  sleep 10
done

# Validate the model's complete report against the fresh issue body and exact
# diff before invoking the trusted controller.
review_status=0
python3 - "$HEAD" "$ISSUE" "$PR" <<'PY' || review_status=$?
import importlib.util
import json
import os
import subprocess
import sys

head, issue, pr = sys.argv[1:]
spec = importlib.util.spec_from_file_location("factory_issue_acceptance", ".github/scripts/factory_issue_acceptance.py")
assert spec and spec.loader
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
repo = os.environ["GITHUB_REPOSITORY"]
body = json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/issues/{issue}"], text=True))["body"]
response = json.load(open("/tmp/resp.json", encoding="utf-8"))
content = response["choices"][0]["message"]["content"]
start = content.find("{")
if start < 0:
    raise SystemExit("provider did not return a JSON review")
payload = json.JSONDecoder().raw_decode(content[start:])[0]
verdict = str(payload.get("verdict", "")).upper()
report = payload.get("acceptance")
log = f"### Factory semantic review · Factory 77 · {verdict or 'UNKNOWN'}\nExact head {head}.\n{payload.get('reason', '')}\n"
if verdict != "APPROVE":
    open("/tmp/opencode-factory-77.log", "w", encoding="utf-8").write(log)
    print(f"local verdict: {verdict or 'UNKNOWN'}")
    raise SystemExit(10)
changed = [path for path in subprocess.check_output(["gh", "pr", "diff", pr, "--name-only"], text=True).splitlines() if path]
errors = acceptance.validate(report, int(issue), head, body, changed)
if errors:
    raise SystemExit("invalid provider acceptance report: " + "; ".join(errors))
open("/tmp/opencode-factory-77.log", "w", encoding="utf-8").write(
    log + "# comic-pile-factory-authoritative-diff-evidence\ngh pr diff\n" +
    "FACTORY_ACCEPTANCE_V1=" + json.dumps(report, separators=(",", ":")) + "\n"
)
print(f"validated provider acceptance for issue {issue}")
PY
[ "$review_status" -eq 0 ] || {
  [ "$review_status" -eq 10 ] && exit 0
  exit "$review_status"
}

# Only the trusted controller posts the review attestation as github-actions[bot].
gh pr edit "$PR" --add-label "factory:review,factory:77" >/dev/null 2>&1 || true
epoch="$(date +%s)"
echo "<!-- comic-pile-factory-review-claim-v2:pr-${PR}:opencode-free-model-factory-77:${epoch} -->" > /tmp/claim.txt
gh issue comment "$PR" --body-file /tmp/claim.txt >/dev/null
python3 .github/scripts/factory-review-controller.py review --worker 77 --pr "$PR" \
  --reviewed-head "$HEAD" --verdict approve --review-log /tmp/opencode-factory-77.log
