<!-- This Source Code Form is subject to the terms of the Mozilla Public
     License, v. 2.0. If a copy of the MPL was not distributed with this
     file, You can obtain one at https://mozilla.org/MPL/2.0/. -->

# Repository Maintenance

How this repository is kept healthy between feature work: what is automated, what
deliberately is not, and the rules that exist because something already went wrong.

Related: [`SECURITY.md`](../SECURITY.md) (vulnerability reporting),
[`CONTRIBUTING.md`](../CONTRIBUTING.md) (PR process),
[`scripts/github-public-launch-settings.sh`](../scripts/github-public-launch-settings.sh)
(the settings themselves, as code).

---

## The rule behind the rules

**A green CI run is evidence, not proof.** Every automation decision below exists
because CI passed on something that was wrong anyway. CI is amd64-only, does not build
the release images, and cannot know whether a base tag is a supported release line.
Where CI's blind spots are known, they are encoded as policy rather than left to
whoever happens to be reading the PR.

---

## Dependabot

### Grouping

Configured in [`.github/dependabot.yml`](../.github/dependabot.yml). Each ecosystem
opens at most two grouped PRs per week:

| Group | Contents | Handling |
|---|---|---|
| `<eco>-patch` | all patch bumps | auto-merged when CI is green |
| `<eco>-minor` | all minor bumps | reviewed and merged by hand |
| *(ungrouped)* | every major | individual PR, always hands-on |

Majors are deliberately excluded from every group. A major is a migration, not a merge
button — grouping one would hide it among routine bumps and block the whole group on
its failure. Keeping them individual is what makes them visible.

Before grouping, a single weekly Dependabot run produced ~15 PRs. That volume is why a
red `main` went unnoticed for nine days: the signal was buried in noise.

### Auto-merge — patch only

[`.github/workflows/dependabot-auto-merge.yml`](../.github/workflows/dependabot-auto-merge.yml)
enables auto-merge on **patch-level updates only**. Minor and major always wait for a
human.

Patch-only is not excessive caution. Several backend dependencies are `0.x`, where
semver grants no stability guarantee at all and a "minor" is routinely breaking.

Two properties this depends on, both easy to break by accident:

- **Required status checks must stay non-empty.** `gh pr merge --auto` with no required
  checks merges *immediately*, without waiting for CI. Auto-merge and required checks
  are a single mechanism; disabling one without the other converts this workflow from a
  convenience into a way to merge untested code automatically.
- **For a grouped PR, `update-type` is the group's *highest* bump.** A group containing
  any minor or major is therefore correctly excluded. This is load-bearing — it is why
  a `*-patch` group cannot smuggle in a larger change.

The workflow runs on `pull_request_target`, which carries write permissions. It never
checks out or executes PR code — it reads metadata and calls the API. **Do not add
`actions/checkout` to it.**

### Base images are not ordinary dependencies

`dependabot.yml` **ignores `node` and `python` base-image majors.** They are bumped by
hand, verified with a real `build-images` workflow dispatch on both architectures.

This rule has been re-learned three times:

| Bump | CI | What actually happened |
|---|---|---|
| `python:3.14-slim` | green | arm64 build fails — `pydantic-core` has no `cp314` aarch64 wheel |
| `node:26-alpine` | green | web build fails — Node removed bundled corepack in v25 |
| `node:25-alpine` | green | never-LTS line, **EOL 2026-06-01** — no security patches, *and* the corepack break |

CI passes all three because it is amd64-only and does not build the images.

**Check the release line before the version number.** Node's odd-numbered lines are
never LTS and are supported for roughly eight months. Verify against
[nodejs/Release](https://github.com/nodejs/Release/blob/main/schedule.json) —
`node:25` was already six weeks past EOL when Dependabot proposed it.

Current pins: **python 3.12**, **node 22** (LTS, maintained to 2027-04-30). The next
node move is **24-alpine** (LTS to 2028-04-30), by hand.

### Majors: the `needs-migration` label

A major that needs real work gets labelled **`needs-migration`** and a comment saying
what the work is. The label means *parked deliberately*, not *forgotten* — it stops the
PR from being re-triaged from scratch every week, and tells the daily health check not
to nag about it.

### Known quirk

`@dependabot ignore …` works. `@dependabot merge` / `squash and merge` / `rebase` are
**silently ignored on this repo** — no acknowledgement, no action. Merge via the API or
`gh` instead. To refresh a stale merge-ref, close and reopen the PR (a plain re-run
pins the old merge commit).

---

## Branch protection

Live config is the PUT block in
[`scripts/github-public-launch-settings.sh`](../scripts/github-public-launch-settings.sh).
That block is the source of truth: it replaces the entire protection config, so it must
always match what is actually in force.

Six required checks. `SCA · Trivy (informational)` is intentionally **not** required —
it is advisory and flags new upstream CVEs, which must not block an unrelated merge.

Two traps worth knowing:

- **`"contexts": []` requires nothing.** It does not mean "require some passing check
  but don't pin which". An empty list means no required checks at all — protection that
  appears to gate CI while gating nothing. This repo shipped in that state from launch
  until 2026-07-15.
- **Renaming a CI job breaks merges.** A required context that no longer exists can
  never report, so every PR blocks forever. Rename the job and the context together.

`enforce_admins`, `required_pull_request_reviews`, and `required_linear_history` are
**off on purpose** while this repo has a single maintainer — a lone maintainer cannot
obtain an approving review from someone else, so enabling them locks the only person
with commit rights out of `main`. Turn them on deliberately when a second maintainer
exists.

---

## The daily check

The failure mode this guards against: **nothing about a public repository's inbound
maintenance is visible from a local clone.** PRs, security alerts and scheduled scan
results all live on GitHub. A local `git log` sweep cannot see any of them.

CodeQL was red on `main` from 2026-07-06 to 2026-07-15 — a version skew *inside* the
workflow (init loading a `4.36.3` config while analyze ran `4.36.2`). The fix was
sitting in an open Dependabot PR the whole time. Nothing surfaced it, because
`codeql.yml` runs on a weekly cron and a cron failure notifies nobody.

Worth checking daily, in rough priority order:

1. **Latest run per workflow on `main`** — especially cron-only workflows, which have
   no other way to tell anyone they broke.
2. **Open Dependabot *security* alerts** — categorically different from a version-bump
   PR. Each one is a real finding.
3. **Open PRs and their CI state** — green routine bumps are a count, not a list.
   Anything failing for more than ~2 weeks is drifting.
4. **Code-scanning counts** — a hygiene backlog; news only when it moves.

```bash
REPO=VortexFLOW-dev/VortexFLOW
for wf in CI CodeQL "Licenses & SCA" "Sentinel (online)" Scorecard; do
  gh run list --repo "$REPO" --workflow "$wf" --branch main --limit 1 \
    --json workflowName,conclusion --jq '.[] | "\(.workflowName): \(.conclusion)"'
done
gh api "repos/$REPO/dependabot/alerts?state=open" \
  --jq 'if length == 0 then "no open security alerts" else (.[] | "\(.security_advisory.severity) \(.dependency.package.name)") end'
gh pr list --repo "$REPO" --state open --json number,title,statusCheckRollup \
  --jq '.[] | "\(.number) \(.title) — \([.statusCheckRollup[]?.conclusion] | map(select(. == "FAILURE")) | length) failing"'
```

---

## Known gaps

- **`codeql.yml` has no `push` / `pull_request` trigger.** It runs on a weekly cron
  plus manual dispatch — a leftover from when this repo was private and code scanning
  was unavailable. The workflow's own header comment says to add those triggers once
  public. It has been public since 2026-07-01. Until that is done, CodeQL gates
  nothing and its failures surface only via the daily check above.
- **Scorecard `PinnedDependenciesID`** findings (unpinned base images and pip installs
  in Dockerfiles) are an open hygiene backlog, tracked in code scanning.
