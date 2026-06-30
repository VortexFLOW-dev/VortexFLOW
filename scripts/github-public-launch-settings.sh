#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Apply public-repo security settings AFTER VortexFlow goes public.
# Prereqs: `gh` CLI authenticated as a repo ADMIN.
# Usage:   REPO=VortexFLOW-dev/VortexFLOW ./scripts/github-public-launch-settings.sh
#
# Idempotent — safe to re-run.
set -euo pipefail
REPO="${REPO:?set REPO=owner/name, e.g. REPO=VortexFLOW-dev/VortexFLOW}"

echo "→ Secret scanning + push protection"
gh api -X PATCH "repos/$REPO" --input - <<'JSON'
{ "security_and_analysis": {
    "secret_scanning": { "status": "enabled" },
    "secret_scanning_push_protection": { "status": "enabled" } } }
JSON

echo "→ Dependabot vulnerability alerts + automated security fixes"
gh api -X PUT "repos/$REPO/vulnerability-alerts"
gh api -X PUT "repos/$REPO/automated-security-fixes"

echo "→ Private vulnerability reporting (the 'Report a vulnerability' button)"
gh api -X PUT "repos/$REPO/private-vulnerability-reporting"

echo "→ Default GITHUB_TOKEN = read-only"
gh api -X PUT "repos/$REPO/actions/permissions/workflow" \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false

echo "→ Branch protection on main"
# NOTE: add your real check names to required_status_checks.contexts once CI has run
# once on the public repo (e.g. "backend", "frontend", "CodeQL"). Empty = require a
# passing check run but don't pin which — tighten after first green run.
gh api -X PUT "repos/$REPO/branches/main/protection" --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": [] },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

cat <<'EOF'
✓ API-settable items done.

Still toggle in the GitHub UI (no stable API):
  • Settings → Actions → General → "Require approval for all outside collaborators"
    (stops fork PRs from running CI) — set to all outside / first-time contributors.
  • Settings → Code security → CodeQL: keep the workflow, or switch on "Default setup".
  • Settings → General: enable Discussions; disable Wiki/Projects if unused.
And org-wide: require 2FA for all members.
EOF
