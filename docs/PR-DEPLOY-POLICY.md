# PR deploy policy

Use draft PRs only for true work-in-progress or review-only branches. For normal
implementation work that the user expects to go live, Cursor agents should open
the PR as non-draft (`draft=false`) once the change is ready for CI.

## Why the WA rollout fix did not deploy automatically

Three gates can block an otherwise ready Cursor branch:

1. No PR exists for the `cursor/*` branch.
2. The PR is still **draft**. Auto-merge intentionally skips draft PRs.
3. The PR touches workflows/deploy/scripts. Auto-merge intentionally skips those
   high-risk ops changes because they can affect production automation.

Any of those leaves a branch unmerged to `main`, so the normal GHCR/build/deploy
chain never runs.

`auto-open-cursor-prs.yml` covers the first gate by opening a non-draft PR for
new `cursor/*` pushes and by sweeping every 15 minutes for existing cursor
branches that still lack PRs.

## Ongoing rules

- **Implementation PRs:** create as non-draft unless the work is knowingly
  incomplete or explicitly review-only.
- **Cursor branches without PRs:** `auto-open-cursor-prs.yml` should open them
  automatically. If it cannot, agents should open the PR directly as non-draft.
- **Draft PRs:** must include a clear reason they are not live.
- **High-risk ops PRs:** if they touch `.github/`, `deploy/`, `scripts/`, or
  compose files, expect manual/explicit deployment or human merge review.
- **Production source of truth:** production code should still land on `main`
  as soon as possible after any emergency branch deploy.

## Agent checklist

Before finalizing work:

1. Run the appropriate tests.
2. Push the branch.
3. Create/update the PR as non-draft for implementation work.
4. If the PR is high-risk ops and cannot auto-merge, say that explicitly and
   either deploy through an approved workflow or document the manual merge need.
5. Verify `/ready` after deploy when deployment was expected.
