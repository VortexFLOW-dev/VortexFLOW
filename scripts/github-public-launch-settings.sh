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
#
# This block is a PUT — it replaces the whole protection config, so what is written
# here IS the live config. Keep it matching reality; do not treat it as aspirational.
#
# Two corrections were made 2026-07-15 after this script's original version drifted
# from the settings actually in force:
#
# 1. `"contexts": []` does NOT mean "require some passing check but don't pin which"
#    (the old comment here claimed that, and it is wrong). An empty contexts list means
#    NO required checks at all — the protection looks like it gates CI while gating
#    nothing. The real check names are now pinned below. Update them if a job is
#    renamed: a required context that no longer exists blocks every merge forever.
#
# 2. The maintainer settings below are deliberately SOLO-FRIENDLY and must stay that
#    way while this repo has one maintainer. The original script set enforce_admins,
#    required_pull_request_reviews (1 + code owners), and required_linear_history —
#    none of which were ever in force, because a lone maintainer cannot get a review
#    from someone else. Re-running that version would have locked the only maintainer
#    out of main. When a second maintainer exists, turn these on deliberately.
#
# "SCA · Trivy (informational)" is intentionally NOT required — it is advisory and
# flags new upstream CVEs, which must not block an unrelated merge.
gh api -X PUT "repos/$REPO/branches/main/protection" --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Frontend · types · build",
      "Backend · lint · types · tests",
      "Agent · vet · build · test · scan",
      "Contract drift · sentinel",
      "License compliance (no strong copyleft)",
      "Secret scan · gitleaks"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

echo "→ Auto-merge (required by .github/workflows/dependabot-auto-merge.yml)"
# Auto-merge is only safe BECAUSE required_status_checks above is non-empty:
# `gh pr merge --auto` with no required checks merges immediately, without waiting
# for CI. If the contexts list is ever emptied, disable auto-merge in the same change.
gh api -X PATCH "repos/$REPO" -F allow_auto_merge=true -F delete_branch_on_merge=true >/dev/null

cat <<'EOF'
✓ API-settable items done.

Still toggle in the GitHub UI (no stable API):
  • Settings → Actions → General → "Require approval for all outside collaborators"
    (stops fork PRs from running CI) — set to all outside / first-time contributors.
  • Settings → Code security → CodeQL: keep the workflow, or switch on "Default setup".
  • Settings → General: enable Discussions; disable Wiki/Projects if unused.
And org-wide: require 2FA for all members.

Ongoing maintenance (Dependabot grouping, auto-merge policy, base-image rule,
the daily health check): see docs/MAINTENANCE.md.
EOF
