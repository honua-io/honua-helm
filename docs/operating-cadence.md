# Operating Cadence: Weekly Backlog Review, Scope Gate, and Close Hygiene

This document defines the repeatable weekly operating rhythm for this repository:
a backlog review, a scope gate for new work, and a done/close hygiene pass. The
goal is a backlog that is always triaged, work that is always scoped before it
starts, and an issue tracker whose open count reflects reality.

This is the same process across the Honua repositories that adopt it; the
checklist and policy are intentionally identical so a contributor moving between
repos finds the same rhythm.

## Cadence

- **Frequency:** weekly. Pick a fixed day/time and keep it.
- **Timebox:** 30 minutes. If a topic needs longer, capture it as a follow-up
  issue rather than expanding the meeting.
- **Record:** the owner posts a single dated comment on the repository's
  operating-cadence tracking issue summarizing outcomes and decisions — what was
  triaged, what scope changed, what was closed, and any escalations. The comment
  is the durable record; no separate minutes are required.
- **Async-friendly:** the review may run async (a thread instead of a call) as
  long as the dated summary comment is still posted.

## Who Attends

- **Owner (required):** the repository maintainer or rotating owner who runs the
  review and posts the summary. Accountable for the backlog being triaged and the
  hygiene pass being done.
- **Contributors (as needed):** whoever holds in-flight or blocked work, to give
  status and surface blockers.
- **Cross-repo stakeholder (as needed):** pulled in when a blocker or scope
  change crosses into another repository (commonly `honua-server` or
  `honua-devops`).

A quorum is just the owner; the review still happens if no one else is available.

## Weekly Checklist

### Backlog Review

- [ ] New issues since last review are triaged: `area/*`, `priority/*`,
  `effort/*`, `phase/*`, assignee, and milestone are set.
- [ ] The next two weeks have enough `ready-to-start` work for the people
  expected to pick it up.
- [ ] Blocked issues carry an explicit dependency note (what they wait on, and
  where that work lives).

### Scope Gate

- [ ] New scope has an explicit tradeoff recorded: what was deferred or removed
  to make room for it.
- [ ] The MVP / Beta / GA mix is still intentional for the current goals (we are
  not quietly gold-plating Beta features while MVP gaps remain).
- [ ] Oversized tickets (`effort/XL`) are split into shippable slices or
  explicitly accepted as a single large item with a reason.

### Done / Close Hygiene

- [ ] Completed work is closed within 24 hours of merge.
- [ ] Partially complete work has a comment listing the exact remaining tasks.
- [ ] Stale items are rephased (re-milestoned / re-prioritized) or closed per the
  policy below.

## Scope-Gate Criteria

Before new work is accepted into the active plan it must clear all of:

1. **Labeled** — it has `area/*`, `priority/*`, `effort/*`, and `phase/*` so it
   can be filtered and sequenced.
2. **Tradeoff stated** — if it displaces planned work, the comment says what
   moved out. New scope is never free; the cost is named.
3. **Sized** — `effort/XL` is split or explicitly accepted. Prefer the smallest
   slice that delivers value.
4. **Phase-honest** — its `phase/*` matches reality. MVP-blocking work is not
   labeled GA to dodge the bar, and polish is not labeled MVP to jump the queue.
5. **Dependencies explicit** — cross-repo or cross-issue dependencies are linked,
   not implied.

Work that cannot clear the gate stays in the backlog (or is closed as
out-of-scope) rather than silently entering the active plan.

## Stale-Issue Close Policy

An issue is **stale** when it has had no substantive update for **30 days** and
is not actively blocked by a linked dependency. Bot bumps and label churn do not
count as updates.

At each weekly review, for each stale issue choose one:

- **Rephase** — still wanted: re-milestone and/or re-prioritize, and add a one
  line note on why it is still open.
- **Close** — no longer wanted, superseded, or duplicate: close with a reason and
  a link to the superseding issue if any.
- **Hold** — genuinely blocked: keep open but ensure the blocking dependency is
  linked and the `blocked` state is explicit.

Issues with no decision after **60 days** of staleness are closed by default;
reopening is cheap if the work returns. Closing for hygiene is not a judgment on
the idea — it keeps the open count honest.

## Metrics

Track a small, stable set each week and include them in the summary comment.
Trends matter more than absolute values.

| Metric | What it tells you |
| --- | --- |
| Open issues (total, and by `priority/*`) | Overall load and where it concentrates |
| Issues opened vs. closed this week | Whether the backlog is growing or shrinking |
| `ready-to-start` count for the next two weeks | Whether contributors will have work |
| Blocked issue count (and oldest blocker age) | Where flow is stuck |
| Stale issues actioned this week (rephased / closed / held) | Whether hygiene is keeping up |
| Median age of open `priority/P0`–`P1` issues | Whether the important work is moving |

If a metric is consistently bad (e.g., blocked count only grows), raise it as an
escalation rather than letting it ride.

## Escalation

The owner posts the dated weekly summary with outcomes and decisions. Unresolved
cross-repo blockers are escalated to `honua-server` or `honua-devops` (whichever
owns the dependency) with a link back to the blocked issue, so the blocker has a
home outside this repo's tracker.
