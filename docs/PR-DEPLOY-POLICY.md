# PR deploy policy

Use draft PRs only for true work-in-progress or review-only branches. For normal
implementation work that the user expects to go live, Cursor agents should open
the PR as non-draft (`draft=false`) once the change is ready for CI.

## Why the WA rollout fix did not deploy automatically

Two gates blocked it:

1. The PR was still **draft**. Auto-merge intentionally skips draft PRs.
2. The PR touched workflows/deploy/scripts. Auto-merge intentionally skips those
   high-risk ops changes because they can affect production automation.

The result was a CI-green branch that was not merged to `main`, so the normal
GHCR/build/deploy chain never ran.

## Ongoing rules

- **Implementation PRs:** create as non-draft unless the work is knowingly
  incomplete or explicitly review-only.
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
