# Collaborative Task & Reward Management Platform

A configurable collaborative task management platform for households, business projects, construction projects, communities, educational groups, organizations, and other teams.

This project is being developed as part of the **AI Dev Tools Zoomcamp 2026** by DataTalksClub, using an AI-assisted, specification-driven development workflow.

---

## Project Overview

The project started from a deliberately vague idea:

> "A tool for managing shared household chores."

Instead of immediately generating code from that single sentence, the idea was explored and transformed into a structured product specification.

The resulting concept expands beyond household chores into a configurable platform where different groups can organize, select, assign, track, and complete shared tasks.

Depending on the workspace configuration, the platform can also support:

- task scoring
- late penalties
- leaderboards
- reward systems
- task reassignment
- configurable gamification rules

The goal is to keep the core task-management engine generic while allowing each workspace to adapt it to its own context.

---

## Supported Use Cases

A workspace can represent different collaborative environments, including:

-  Household / Family
-  Business / Project Team
-  Construction Project
-  Education / Student Group
-  Community
-  Organization
-  Sports Team
-  Custom Use Case

If none of the predefined categories fit, users will be able to define their own workspace type.

---

##  Core Features

The initial product specification focuses on four main feature areas.

### 1. Configurable Workspace Management

Users will be able to create workspaces for different collaborative contexts.

A workspace can contain:

- an owner
- one or more managers
- members
- task configuration
- optional scoring
- optional rewards

A single user may participate in multiple workspaces and may have different roles in each one.

---

### 2. Self-Service & Manager-Assisted Task Management

Tasks are organized into:

- Daily tasks
- Weekly tasks
- Monthly tasks

Whenever possible, members select the tasks they want to perform themselves.

Tasks selected by a member are automatically assigned to that member and removed from the available-task lists of other members.

Tasks that remain unselected can later be manually assigned by a manager.

Manager-assigned tasks require member acceptance.

The task workflow is planned to support:

- self-selection
- manual assignment
- acceptance or rejection
- automatic deadlines
- overdue tracking
- grace periods
- incomplete-task handling
- reassignment

---

### 3. Configurable Gamification

Gamification is optional for each workspace.

When enabled, tasks can award points based on:

- task frequency
- difficulty
- completion
- lateness

The platform will provide a default scoring model, while workspace managers will be able to customize scoring and penalty values.

Historical task scores will remain unchanged if scoring rules are modified later.

---

### 4. Optional Reward System

A workspace may optionally enable a reward system when scoring is enabled.

Managers will be able to create rewards with:

- reward name
- description
- required points
- active/inactive status

Reaching a point threshold will not automatically redeem a reward.

Members may continue saving their points for a higher-value reward or choose an available reward and spend the required points.

---

##  Default Task Model

The initial specification defines the following default configuration.

| Frequency | Difficulty | Completion Points | Late Penalty | Deadline |
|---|---|---:|---:|---|
| Daily | Easy | 10 | -5 | 1 day |
| Daily | Medium | 20 | -10 | 1 day |
| Daily | Hard | 40 | -20 | 1 day |
| Weekly | Easy | 25 | -10 | 7 days |
| Weekly | Medium | 50 | -25 | 7 days |
| Weekly | Hard | 100 | -50 | 7 days |
| Monthly | Easy | 50 | -25 | 30 days |
| Monthly | Medium | 100 | -50 | 30 days |
| Monthly | Hard | 200 | -100 | 30 days |

These values are defaults and are intended to be configurable when gamification is enabled.

---

##  Task Selection Rules

The current specification defines the following default selection windows:

### Daily Tasks

Members may select available daily tasks until **10:00 each day**.

There is no predefined maximum number of daily tasks a member may voluntarily select.

### Weekly Tasks

Members may select weekly tasks until **Monday at 10:00**.

The default target is **2 weekly tasks per member**.

### Monthly Tasks

Members may select monthly tasks until **10:00 on the first day of each month**.

The default target is **3 monthly tasks per member**.

Tasks that remain unselected after the relevant selection window may be manually assigned by a manager.

---

## ⏳ Overdue & Reassignment Workflow

When a task reaches its deadline without being completed:

1. The task becomes overdue.
2. The configured late penalty is applied.
3. A 24-hour grace period begins.
4. The member may still complete the task during the grace period and earn its completion points.
5. If the grace period also expires, a second late penalty is applied.
6. The task becomes incomplete and is removed from the member's active task list.
7. The task is returned to the manager for reassignment.
8. A newly assigned member receives a new deadline based on the task frequency.

For daily tasks, managers may also choose to roll an incomplete task into the next day's available task list.

---

##  AI-Assisted Development Workflow

This project follows the workflow introduced in Module 1 of the AI Dev Tools Zoomcamp:

```text
Vague Idea
    ↓
Product Brainstorming
    ↓
Specification
    ↓
Context Engineering
    ↓
Implementation Plan
    ↓
Backlog
    ↓
AI-Assisted Implementation
    ↓
Testing
    ↓
Independent QA
    ↓
Iteration
```

The project intentionally follows a **spec-first, code-second** approach.

---

##  Coding Agent

The coding agent selected for this project is:

**Codex CLI**

The same coding agent will be used throughout the homework implementation.

---

##  Planned Technology Stack

- Python
- Django
- SQLite for initial development
- HTML / CSS
- Django Templates
- Git
- GitHub
- Codex CLI
- `uv` for Python environment and dependency management

The technical stack may evolve as the project progresses.

---

##  Initial Repository Structure

```text
collaborative_task_reward_management_platform/
├── .gitignore
├── README.md
└── _docs/
    └── plan.md
```

The Django application structure will be added during implementation.

---

##  Project Status

**Status: Specification & Planning**

Current progress:

- [x] Initial vague idea analyzed
- [x] Product scope brainstormed
- [x] Core feature areas defined
- [x] Coding agent selected
- [ ] Product plan finalized
- [ ] Django project initialized
- [ ] Development backlog generated
- [ ] First backlog task implemented
- [ ] Automated tests added
- [ ] Independent QA review completed

---

##  Learning Objectives

This project is intended to practice:

- Specification-Driven Development
- Context Engineering
- AI-Assisted Software Development
- Product Manager / Software Engineer / QA role separation
- Backlog-Driven Development
- Loop Engineering
- Graph Engineering
- Automated Testing
- Git & GitHub workflows

---

##  Course

Developed as part of:

**DataTalksClub — AI Dev Tools Zoomcamp 2026**

Module 1: **AI-Native Developer Workflow**

---

## 👩‍💻 Author

**Esila Nur Demirci**

AI Dev Tools Zoomcamp 2026
