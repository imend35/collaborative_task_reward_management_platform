# Product Plan — Collaborative Task & Reward Management Platform

## 1. Product Vision

Build a configurable collaborative task management platform that can be used by households, business teams, construction projects, communities, educational groups, organizations, sports teams, and other collaborative groups.

The platform should allow members to:

- view available tasks
- voluntarily select tasks
- accept or reject manager-assigned tasks
- complete tasks before deadlines
- earn points when gamification is enabled
- redeem optional rewards

Managers should be able to:

- create and configure workspaces
- manage members
- create and manage tasks
- configure scoring rules
- configure rewards
- assign tasks manually when needed
- reassign incomplete tasks
- review task history and user performance

The product should prioritize **self-selection before manager assignment**.

---

## 2. Core Product Principle

The default workflow is:

```text
Available Task
    ↓
Member Self-Selection
    ↓
Automatic Assignment
    ↓
Active Task
    ↓
Completion
```

Manager intervention should only be required when:

- tasks remain unselected
- tasks are incomplete
- a manually assigned task is rejected
- a daily task needs to be rolled over
- scoring or reward settings need configuration

---

## 3. Workspace Types

A workspace represents a group where shared tasks are managed.

Supported predefined workspace types:

- Household / Family
- Business / Project Team
- Construction Project
- Education / Student Group
- Community
- Organization
- Sports Team
- Other

If **Other** is selected, the creator must be able to enter a custom workspace type.

Examples:

- Wedding Organization
- Volunteer Group
- Research Team
- Apartment Management

The core task engine must remain the same regardless of workspace type.

---

## 4. Roles

### 4.1 Workspace Owner

The user who creates the workspace becomes the initial owner and manager.

The owner can:

- configure the workspace
- add members
- promote members to managers
- manage scoring
- manage rewards

### 4.2 Manager

A manager can:

- create tasks
- manage task lists
- manually assign tasks
- reassign incomplete tasks
- manage members
- configure gamification
- configure rewards
- view task and score history

A workspace may have multiple managers.

### 4.3 Member

A member can:

- view available tasks
- select eligible tasks
- accept or reject manually assigned tasks
- view active tasks
- complete tasks
- view score and ranking if enabled
- redeem available rewards if enabled

A user may belong to multiple workspaces and may have different roles in each workspace.

---

## 5. Workspace Creation

When creating a workspace, the creator should configure:

1. Workspace name
2. Workspace type
3. Custom type if "Other" is selected
4. Members
5. Managers
6. Gamification enabled / disabled
7. Reward system enabled / disabled
8. Default or custom scoring rules

---

## 6. Task Frequencies

Tasks belong to one of three frequency groups:

- Daily
- Weekly
- Monthly

Each task also has a difficulty level:

- Easy
- Medium
- Hard

Difficulty affects points and penalties.

Frequency affects deadline duration and selection window.

---

## 7. Default Scoring Rules

Gamification is optional per workspace.

When enabled, the platform should offer the following default configuration.

### 7.1 Daily Tasks

| Difficulty | Completion Points | Late Penalty | Deadline |
| ---------- | ----------------: | -----------: | -------: |
| Easy       |                10 |           -5 |    1 day |
| Medium     |                20 |          -10 |    1 day |
| Hard       |                40 |          -20 |    1 day |

All daily tasks must be completed within one day regardless of difficulty.

### 7.2 Weekly Tasks

| Difficulty | Completion Points | Late Penalty | Deadline |
| ---------- | ----------------: | -----------: | -------: |
| Easy       |                25 |          -10 |   7 days |
| Medium     |                50 |          -25 |   7 days |
| Hard       |               100 |          -50 |   7 days |

### 7.3 Monthly Tasks

| Difficulty | Completion Points | Late Penalty | Deadline |
| ---------- | ----------------: | -----------: | -------: |
| Easy       |                50 |          -25 |  30 days |
| Medium     |               100 |          -50 |  30 days |
| Hard       |               200 |         -100 |  30 days |

---

## 8. Scoring Configuration

When gamification is enabled, the workspace creator must be asked:

> Do you want to use the default scoring system?

Options:

- Use default scoring
- Customize scoring

If customization is selected, the manager may change:

- completion points
- late penalties

for every combination of:

- Daily / Weekly / Monthly
- Easy / Medium / Hard

### Historical Integrity Rule

Scoring changes must not modify historical task results.

When a task becomes active, the following values must be stored as a snapshot:

- completion points
- late penalty
- frequency
- difficulty

Later changes to workspace scoring rules must affect only new assignments.

---

## 9. Gamification Disabled

If gamification is disabled:

- no completion points are awarded
- no penalties affect a score
- no leaderboard is displayed
- no reward system may be used
- task completion and overdue history must still be tracked

Task management must remain fully functional.

---

## 10. Reward System

The reward system is optional.

It may only be enabled when gamification is enabled.

Managers can create rewards with:

- reward name
- description
- required points
- active / inactive status

Example:

| Reward         | Required Points |
| -------------- | --------------: |
| Movie choice   |             100 |
| Dinner choice  |             150 |
| Special reward |             300 |

---

## 11. Reward Redemption

Rewards must never be granted automatically.

When a member reaches enough points for one or more rewards:

- the member should be notified
- eligible rewards should become selectable

The member may:

- redeem a reward
- keep saving points for a higher-value reward

When a reward is redeemed:

```text
New Balance = Current Balance - Reward Cost
```

The reward is recorded in reward history.

Members may continue earning points after redemption.

Scores are allowed to become negative.

---

## 12. Daily Task Selection

Daily task selection is available until:

> 10:00 every day

Members may voluntarily select any number of available daily tasks.

There is no voluntary daily task limit.

When a member selects a task:

1. the task is immediately assigned to that member
2. manager approval is not required
3. the task disappears from the available-task list of all other members
4. the task deadline is calculated automatically

---

## 13. Daily Unselected Tasks

After 10:00:

- remaining daily tasks may be manually assigned by a manager

A manually assigned task requires member acceptance.

The member can:

- Accept
- Reject

If rejected:

- the task returns to the manager
- the manager may assign it to another member

---

## 14. Weekly Task Selection

Weekly selection closes:

> Every Monday at 10:00

Default requirement:

> Each member should complete 2 weekly tasks.

Members may select weekly tasks themselves before the deadline.

Self-selected tasks are automatically assigned.

If a member selects fewer than 2 weekly tasks:

- a manager may manually assign the remaining required tasks

A manager may not assign more than 2 weekly tasks to the same member during the same weekly period.

Manager-assigned tasks require member acceptance.

---

## 15. Monthly Task Selection

Monthly selection closes:

> At 10:00 on the first day of each month

Default requirement:

> Each member should complete 3 monthly tasks.

If a member selects fewer than 3 monthly tasks:

- the manager may assign remaining required tasks

A manager may not assign more than 3 monthly tasks to the same member during the same monthly period.

Manager-assigned tasks require member acceptance.

---

## 16. Assignment Types

A task may be assigned through:

### 16.1 Self-Selection

Member chooses the task.

Result:

- automatic assignment
- automatic acceptance
- no manager approval

### 16.2 Manager Assignment

Manager selects a member.

Result:

- task enters pending acceptance state

Member must choose:

- Accept
- Reject

Rejected tasks return to the manager.

---

## 17. Deadlines

Deadlines are automatically calculated from task frequency.

### Daily

```text
Assignment Time + 1 day
```

### Weekly

```text
Assignment Time + 7 days
```

### Monthly

```text
Assignment Time + 30 days
```

Difficulty must not change the deadline.

Managers should not manually set deadlines during normal task assignment.

---

## 18. Task Completion

If a task is completed before the deadline:

- mark it completed
- record completion time
- record completing member
- award completion points if gamification is enabled
- add the event to task history

---

## 19. First Overdue Event

If the deadline passes before completion:

1. mark the task as overdue
2. apply the configured late penalty once
3. begin a 24-hour grace period
4. keep the task visible to the assigned member

Example:

```text
Weekly Hard Task
Completion Points: +100
Late Penalty: -50
```

At the first overdue event:

```text
Score Change = -50
```

---

## 20. Completion During Grace Period

The member may still complete the task during the 24-hour grace period.

If completed:

- award the full completion points
- preserve the already-applied late penalty
- mark the task completed

Example:

```text
Late Penalty: -50
Completion Points: +100
Net Effect: +50
```

The purpose of this rule is:

> Late completion is less valuable than on-time completion, but still better than leaving the task incomplete.

---

## 21. Second Overdue Event

If the 24-hour grace period also expires:

1. apply the late penalty a second time
2. mark the task as incomplete
3. remove the task from the member's active task list
4. record the incomplete event in task history
5. send the task to the manager's incomplete-task queue

Example:

```text
Monthly Hard Task
Penalty 1: -100
Penalty 2: -100
Total incomplete penalty: -200
```

---

## 22. Incomplete Task Reassignment

Incomplete tasks must appear in a manager view.

The manager may manually assign the task to another member.

The new member:

- receives a fresh deadline
- must accept or reject the assignment

The new deadline must be recalculated using the task frequency:

- Daily → 1 day
- Weekly → 7 days
- Monthly → 30 days

The old member's task history and penalties must remain unchanged.

---

## 23. Daily Task Rollover

An incomplete daily task may optionally be rolled over to the next day.

This requires manager approval.

When rolled over:

- the task returns to the next day's available daily-task list
- a new deadline is calculated
- members may select it again

The task history must still show that it was incomplete in the previous period.

---

## 24. Task Visibility

An available task must be visible to eligible workspace members.

As soon as a member selects it:

- it must disappear from other members' available-task lists

This prevents multiple members from selecting the same task simultaneously.

---

## 25. Task Statuses

The initial status model should support at least:

```text
AVAILABLE
PENDING_ACCEPTANCE
ACTIVE
COMPLETED
OVERDUE
GRACE_PERIOD
INCOMPLETE
PENDING_REASSIGNMENT
REJECTED
```

Exact implementation may be refined during development.

---

## 26. Task History / Audit Trail

Important task events must be recorded.

Examples:

```text
Task created
Task became available
Member selected task
Manager assigned task
Member accepted assignment
Member rejected assignment
Task became overdue
Late penalty applied
Grace period started
Task completed
Task became incomplete
Task reassigned
Daily task rolled over
```

History records should include:

- event type
- timestamp
- affected member
- manager if applicable
- score change if applicable

---

## 27. Member Dashboard

The member dashboard should eventually show:

### Available Tasks

- daily
- weekly
- monthly

### My Tasks

- active
- overdue
- grace period
- pending acceptance

### Progress

- weekly task count
- monthly task count

### Gamification

When enabled:

- current score
- workspace ranking
- available rewards
- reward history

---

## 28. Manager Dashboard

Managers should eventually be able to see:

- workspace members
- available tasks
- unselected tasks
- assignments waiting for acceptance
- rejected assignments
- overdue tasks
- incomplete tasks
- tasks waiting for reassignment
- task history
- scoring configuration
- rewards

---

## 29. Initial MVP

The first working version should prioritize the core workflow.

### MVP Scope

- user registration and login
- workspace creation
- workspace type
- member roles
- daily / weekly / monthly tasks
- difficulty levels
- self-selection
- manual assignment
- accept / reject
- automatic deadlines
- task completion
- overdue state
- 24-hour grace period
- incomplete task handling
- reassignment
- optional gamification
- configurable scoring
- optional rewards
- basic dashboards
- automated tests

---

## 30. Out of Scope for Initial MVP

Do not prioritize the following until the core workflow is stable:

- native mobile application
- SMS integration
- email notification infrastructure
- calendar integrations
- real-time chat
- advanced analytics
- multilingual UI
- AI-generated task suggestions
- external project-management integrations
- push notifications

These may be considered in later iterations.

---

## 31. Main Feature Areas

For the homework, the specification settles on four main features:

### Feature 1 — Configurable Workspace Management

Create collaborative workspaces for households, projects, teams, communities, and custom use cases with owners, managers, and members.

### Feature 2 — Self-Service & Manager-Assisted Task Management

Support daily, weekly, and monthly tasks with self-selection, manual assignment, acceptance, deadlines, overdue handling, and reassignment.

### Feature 3 — Configurable Gamification

Provide optional scoring, late penalties, ranking, and customizable scoring rules.

### Feature 4 — Optional Rewards

Provide an optional configurable reward catalog where members may spend accumulated points.

---

## 32. Development Approach

This project must follow a specification-driven AI-assisted workflow.

```text
Specification
    ↓
Context
    ↓
Backlog
    ↓
Implementation
    ↓
Automated Tests
    ↓
Independent QA
    ↓
Iteration
```

The coding agent used for implementation is:

> Codex CLI

Development should proceed one backlog task at a time.

Do not implement the entire system in one prompt.

---

## 33. First Technical Goal

After this plan is committed:

1. Install Django
2. Create the Django project
3. Create the initial Django app
4. Add the app to `INSTALLED_APPS`
5. Generate a small implementation backlog from this plan
6. Implement tasks incrementally
7. Add tests
8. Run independent QA review
