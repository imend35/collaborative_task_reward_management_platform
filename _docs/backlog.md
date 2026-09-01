# MVP Implementation Backlog

This backlog breaks the MVP in [`_docs/plan.md`](./plan.md) into small, ordered implementation tasks for incremental Django development. Each task is intended to be completed and reviewed before starting the next one.

## Task #1: Define Core Domain Constants and Data Model Skeleton

**Objective**  
Create the minimum domain foundation needed for all later workflow features.

**Implementation Scope**  
- Define the initial Django models for workspace, membership, task template, task assignment, and task event history.
- Add enumerations and choices for workspace type, member role, task frequency, task difficulty, assignment type, and task status.
- Add only the core fields required to support later iterations, without implementing business workflows yet.
- Create and apply the initial database migration.
- Register the new models in Django admin for inspection.

**Acceptance Criteria**  
- The codebase contains model classes for the core domain entities needed by later tasks.
- Choice fields exist for the main statuses and classifications from the plan.
- The initial migration is generated and applies successfully.
- Django system checks pass after the model foundation is added.

## Task #2: Enable Authentication and Basic User Entry Points

**Objective**  
Provide the minimum user authentication flow required before workspace features can be used.

**Implementation Scope**  
- Configure Django authentication views, URL routes, and base templates for login, logout, and registration.
- Implement a simple user registration form using Django’s built-in user model.
- Add a minimal post-login landing page.
- Keep styling minimal and functional.

**Acceptance Criteria**  
- A new user can register with username and password.
- An existing user can log in and log out.
- Anonymous users are redirected away from protected pages.
- Auth-related pages render successfully with no server errors.

## Task #3: Implement Workspace Creation and Owner Setup

**Objective**  
Allow an authenticated user to create a workspace and become its initial owner.

**Implementation Scope**  
- Create a workspace form and view for workspace name, workspace type, and optional custom type.
- Automatically create the owner’s membership record when a workspace is created.
- Ensure the owner is also marked with manager capabilities according to the plan.
- Add basic workspace list and detail pages scoped to the logged-in user.

**Acceptance Criteria**  
- An authenticated user can create a workspace.
- Choosing "Other" supports storing a custom workspace type value.
- Creating a workspace automatically creates the owner membership.
- The creator can see the workspace in their workspace list and detail page.

## Task #4: Implement Workspace Membership Management

**Objective**  
Allow workspace owners and managers to add members and manage roles.

**Implementation Scope**  
- Add forms and views to invite or add existing users to a workspace.
- Support the roles owner, manager, and member through membership records.
- Allow the owner to promote members to manager and demote managers back to member.
- Prevent invalid membership duplication within the same workspace.

**Acceptance Criteria**  
- A manager or owner can add a user to a workspace exactly once.
- The owner can change a member’s role between manager and member.
- Membership records remain scoped to a workspace.
- Non-managers cannot access membership management pages.

## Task #5: Add Workspace Gamification Settings and Default Scoring Rules

**Objective**  
Create the workspace-level configuration needed before score-aware task workflows are introduced.

**Implementation Scope**  
- Add workspace settings for gamification enabled/disabled and reward system enabled/disabled.
- Enforce that rewards cannot be enabled when gamification is disabled.
- Create a scoring rule model covering each frequency and difficulty combination.
- Seed default scoring rules for a new workspace when gamification is enabled.

**Acceptance Criteria**  
- A workspace can store whether gamification is enabled.
- A workspace cannot enable rewards while gamification is off.
- Default scoring rows are created for all daily, weekly, and monthly difficulty combinations when required.
- The configuration is visible in the workspace detail or admin view.

## Task #6: Implement Task Template Creation

**Objective**  
Allow managers to define reusable tasks that members may later select or receive.

**Implementation Scope**  
- Create manager-only CRUD for task templates within a workspace.
- Support task title, description, frequency, difficulty, and active/inactive state.
- Ensure task templates belong to one workspace only.
- Expose task templates in Django admin and manager pages.

**Acceptance Criteria**  
- A manager can create, edit, and deactivate a task template.
- Task templates store frequency and difficulty choices.
- Members cannot manage task templates.
- Task templates appear only inside their own workspace.

## Task #7: Generate Available Task Instances From Templates

**Objective**  
Separate reusable task definitions from workflow instances that move through statuses.

**Implementation Scope**  
- Introduce task assignment or task instance creation from task templates.
- Support initial `AVAILABLE` state for instances visible to eligible members.
- Store the relevant task snapshot fields needed by later scoring and history work.
- Add simple manager tooling to create available tasks manually for now.

**Acceptance Criteria**  
- A manager can create an available task instance from a task template.
- The created instance stores workspace, template, frequency, difficulty, and current status.
- Task instances are distinct from task templates.
- Available task instances can be listed per workspace.

## Task #8: Implement Member Self-Selection of Available Tasks

**Objective**  
Support the primary workflow where members voluntarily select tasks for themselves.

**Implementation Scope**  
- Add a member-facing available-task list filtered to their workspaces.
- Implement self-selection for eligible available tasks.
- On self-selection, assign the task to the member, mark it active, and remove it from others’ available lists.
- Record a task history event for self-selection.

**Acceptance Criteria**  
- A member can see available tasks for a workspace they belong to.
- Selecting an available task assigns it to that member and changes the status from `AVAILABLE` to `ACTIVE`.
- The same task cannot be selected by two members.
- A task history record is created for the self-selection event.

## Task #9: Add Automatic Deadline Calculation on Assignment

**Objective**  
Ensure every assignment receives a deadline derived from task frequency rather than manual input.

**Implementation Scope**  
- Implement deadline calculation logic for daily, weekly, and monthly tasks.
- Apply deadline calculation during self-selection and manager assignment flows.
- Store assignment time and due time on the task instance.
- Keep deadline logic centralized in a service, model method, or utility.

**Acceptance Criteria**  
- Daily assignments receive a due time of assignment time plus 1 day.
- Weekly assignments receive a due time of assignment time plus 7 days.
- Monthly assignments receive a due time of assignment time plus 30 days.
- Managers do not manually enter deadlines during normal assignment flows.

## Task #10: Implement Manager Assignment With Pending Acceptance

**Objective**  
Allow managers to assign unselected tasks to members while keeping member acceptance explicit.

**Implementation Scope**  
- Add manager UI to assign an available task to a selected workspace member.
- Set assigned tasks to `PENDING_ACCEPTANCE` rather than `ACTIVE`.
- Record the assigning manager and assignment type.
- Create history records for manager assignment events.

**Acceptance Criteria**  
- A manager can assign an available task to a workspace member.
- The task enters `PENDING_ACCEPTANCE` status after manager assignment.
- The assigned member can see the task waiting for their response.
- A task history event records the manager assignment.

## Task #11: Implement Accept and Reject Flows for Manager-Assigned Tasks

**Objective**  
Complete the member decision step for manager-assigned work.

**Implementation Scope**  
- Add member actions to accept or reject a pending assignment.
- On accept, activate the task without changing its assignment target.
- On reject, remove the assignee, update status appropriately, and return the task to the manager’s queue.
- Record accept and reject events in task history.

**Acceptance Criteria**  
- The assigned member can accept a pending task and move it to `ACTIVE`.
- The assigned member can reject a pending task and return it for reassignment.
- Other members cannot accept or reject someone else’s task.
- Task history records whether the assignment was accepted or rejected.

## Task #12: Implement Task Completion Workflow

**Objective**  
Allow an active task to be completed and recorded correctly.

**Implementation Scope**  
- Add member action to mark an active task as completed.
- Store completion timestamp and completing member.
- Update task status to `COMPLETED`.
- Add task history records for completion.
- If gamification is enabled, defer full scoring behavior until the scoring task, but preserve fields needed for it.

**Acceptance Criteria**  
- An assigned member can complete their own active task.
- Completing a task updates status and completion timestamp.
- Completed tasks no longer appear in active-task lists.
- A completion event is written to task history.

## Task #13: Apply Score Snapshots and Completion Scoring

**Objective**  
Introduce gamification without destabilizing the core task workflow.

**Implementation Scope**  
- Snapshot completion points and late penalty values onto task instances when they become active.
- Add a member score ledger or equivalent score-tracking model.
- On task completion, apply completion points only when gamification is enabled.
- Preserve no-score behavior when gamification is disabled.

**Acceptance Criteria**  
- Active tasks store scoring snapshot values from the workspace configuration.
- Completing a task in a gamified workspace creates the correct positive score change.
- Completing a task in a non-gamified workspace creates no score change.
- Later rule edits do not alter previously snapshotted task values.

## Task #14: Implement Overdue Detection and 24-Hour Grace Period

**Objective**  
Support the first late workflow stage and preserve the task for late completion.

**Implementation Scope**  
- Add logic to detect tasks whose deadline has passed.
- Apply the first late penalty when a task first becomes overdue, only if gamification is enabled.
- Mark the task as overdue and start a 24-hour grace period window.
- Keep overdue tasks visible to the assigned member.
- Record overdue and penalty history events.

**Acceptance Criteria**  
- A task past its deadline can transition into overdue processing.
- The first late penalty is applied exactly once per overdue event.
- A grace-period end timestamp is stored or derivable.
- The member can still see and complete the task during the grace period.

## Task #15: Implement Incomplete State and Reassignment Queue

**Objective**  
Handle tasks that remain unfinished after the grace period.

**Implementation Scope**  
- Detect expiry of the 24-hour grace period.
- Apply the second late penalty when gamification is enabled.
- Mark the task `INCOMPLETE` and move it out of the member’s active list.
- Surface incomplete tasks in a manager-facing reassignment queue.
- Record incomplete-task history events.

**Acceptance Criteria**  
- A task that passes the grace-period deadline becomes incomplete.
- The second late penalty is applied exactly once when required.
- Incomplete tasks are no longer shown as active for the member.
- Managers can see incomplete tasks awaiting action.

## Task #16: Implement Reassignment of Incomplete Tasks

**Objective**  
Allow managers to recover incomplete work by assigning it to another member.

**Implementation Scope**  
- Add a manager action to reassign an incomplete task.
- Recalculate deadline based on frequency for the newly assigned member.
- Preserve the previous assignee’s history and penalties.
- Require accept/reject behavior for reassigned manager assignments.

**Acceptance Criteria**  
- A manager can reassign an incomplete task to another member.
- The new assignment receives a fresh deadline based on frequency.
- Previous history remains intact and visible.
- The reassigned task enters the same pending-acceptance flow as other manager assignments.

## Task #17: Implement Daily Task Rollover

**Objective**  
Support the optional manager-approved rollover for incomplete daily tasks.

**Implementation Scope**  
- Add a manager action for rolling an incomplete daily task back into the next day’s available queue.
- Restrict rollover to daily tasks only.
- Recalculate the deadline for the new cycle.
- Record rollover in task history.

**Acceptance Criteria**  
- Only incomplete daily tasks can be rolled over.
- Rolling over returns the task to an available state for the next cycle.
- A new deadline is set for the new cycle.
- Task history preserves both the incomplete event and the rollover event.

## Task #18: Implement Configurable Scoring Management

**Objective**  
Allow managers to customize scoring rules after the default system is in place.

**Implementation Scope**  
- Add manager UI or forms to edit completion points and late penalties per frequency/difficulty pair.
- Validate that only authorized users can change scoring.
- Keep score configuration scoped per workspace.
- Preserve the snapshot rule so future edits affect only new activations.

**Acceptance Criteria**  
- A manager can update scoring rules for their workspace.
- The workspace retains separate rules for each frequency and difficulty combination.
- Existing active or completed tasks keep their original score snapshot values.
- Non-managers cannot edit scoring rules.

## Task #19: Implement Leaderboard and Member Score Views

**Objective**  
Expose score visibility once the scoring engine is stable.

**Implementation Scope**  
- Add member and manager views for current score totals by workspace.
- Build a simple leaderboard ordered by current score.
- Hide or disable leaderboard content when gamification is off.
- Include basic score history visibility if already available from the ledger.

**Acceptance Criteria**  
- A gamified workspace displays a leaderboard ordered by score.
- Members can see their current score in the workspace.
- A non-gamified workspace does not show a leaderboard.
- Score totals are derived from recorded score events rather than hardcoded values.

## Task #20: Implement Reward Catalog Management

**Objective**  
Add the optional reward inventory only after scoring and balances are usable.

**Implementation Scope**  
- Create a reward model linked to a workspace.
- Add manager CRUD for reward name, description, required points, and active/inactive status.
- Restrict reward management to workspaces with gamification enabled.
- Show available rewards to eligible members.

**Acceptance Criteria**  
- A manager can create and manage rewards in a gamified workspace.
- Rewards cannot be enabled in a workspace without gamification.
- Members can view active rewards in their workspace.
- Reward records remain scoped to one workspace.

## Task #21: Implement Reward Redemption and Reward History

**Objective**  
Allow members to spend accumulated points without automatic redemption.

**Implementation Scope**  
- Add member action to redeem an eligible reward manually.
- Check that the member has enough current points.
- Deduct the reward cost through the score ledger or equivalent balance mechanism.
- Record redemption history for the member and workspace.

**Acceptance Criteria**  
- A member with enough points can redeem an active reward.
- A member without enough points cannot redeem the reward.
- Redeeming a reward reduces the member’s balance by the reward cost.
- Reward redemption is recorded in history and does not happen automatically.

## Task #22: Build Member Dashboard

**Objective**  
Provide a practical member-facing summary of work, progress, and rewards.

**Implementation Scope**  
- Build a member dashboard showing available tasks, active tasks, overdue tasks, grace-period tasks, and pending assignments.
- Add weekly and monthly progress counts.
- When gamification is enabled, show score, reward eligibility, and recent reward history.
- Keep the dashboard query scope limited to the current workspace and current member.

**Acceptance Criteria**  
- A member can view their available and assigned tasks from one page.
- The dashboard distinguishes active, overdue, grace-period, and pending-acceptance tasks.
- Weekly and monthly progress counts are visible.
- Gamification panels are hidden or disabled when the workspace does not use scoring.

## Task #23: Build Manager Dashboard

**Objective**  
Give managers a single operational view of the workflow queues they must supervise.

**Implementation Scope**  
- Build a manager dashboard with workspace members, available tasks, unselected tasks, pending acceptances, rejected assignments, overdue tasks, incomplete tasks, and reassignment queue items.
- Include access to scoring configuration and reward management links.
- Include a basic task history view or recent activity section.
- Keep the interface simple and admin-oriented.

**Acceptance Criteria**  
- A manager can see the main operational task queues from one dashboard.
- Incomplete and reassignment-related items are visible without digging through unrelated pages.
- Managers can navigate to task, membership, scoring, and reward actions from the dashboard.
- Non-managers cannot access the manager dashboard.

## Task #24: Add Automated Test Coverage for Core Workflows

**Objective**  
Protect the MVP with automated tests after the main behaviors exist.

**Implementation Scope**  
- Add model, service, and view tests for workspace creation, membership roles, task creation, self-selection, manager assignment, accept/reject, deadlines, completion, overdue handling, reassignment, scoring, and rewards.
- Focus first on high-risk workflow transitions and permission rules.
- Use Django’s test framework and factories or helper builders where helpful.
- Keep tests readable enough for iterative AI-assisted maintenance.

**Acceptance Criteria**  
- Automated tests cover the main workflow transitions and permission boundaries.
- Tests verify score behavior for gamified and non-gamified workspaces.
- Tests verify reward redemption rules and insufficient-balance behavior.
- The test suite runs successfully in the local Django project.
