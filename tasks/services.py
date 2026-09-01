from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    AssignmentType,
    Membership,
    MembershipRole,
    ScoringRule,
    TaskAssignment,
    TaskDifficulty,
    TaskEventHistory,
    TaskEventType,
    TaskFrequency,
    TaskStatus,
    TaskTemplate,
    Workspace,
)


DEFAULT_SCORING_RULES = {
    (TaskFrequency.DAILY, TaskDifficulty.EASY): {"completion_points": 10, "late_penalty": -5},
    (TaskFrequency.DAILY, TaskDifficulty.MEDIUM): {"completion_points": 20, "late_penalty": -10},
    (TaskFrequency.DAILY, TaskDifficulty.HARD): {"completion_points": 40, "late_penalty": -20},
    (TaskFrequency.WEEKLY, TaskDifficulty.EASY): {"completion_points": 25, "late_penalty": -10},
    (TaskFrequency.WEEKLY, TaskDifficulty.MEDIUM): {"completion_points": 50, "late_penalty": -25},
    (TaskFrequency.WEEKLY, TaskDifficulty.HARD): {"completion_points": 100, "late_penalty": -50},
    (TaskFrequency.MONTHLY, TaskDifficulty.EASY): {"completion_points": 50, "late_penalty": -25},
    (TaskFrequency.MONTHLY, TaskDifficulty.MEDIUM): {"completion_points": 100, "late_penalty": -50},
    (TaskFrequency.MONTHLY, TaskDifficulty.HARD): {"completion_points": 200, "late_penalty": -100},
}


@transaction.atomic
def create_workspace_with_owner(*, user, name, workspace_type, custom_workspace_type=""):
    workspace = Workspace.objects.create(
        name=name,
        workspace_type=workspace_type,
        custom_workspace_type=custom_workspace_type,
    )
    Membership.objects.create(
        workspace=workspace,
        user=user,
        role=MembershipRole.OWNER,
    )
    return workspace


def user_can_manage_memberships(membership):
    return membership.role in {MembershipRole.OWNER, MembershipRole.MANAGER}


@transaction.atomic
def add_existing_user_to_workspace(*, actor_membership, username):
    if not user_can_manage_memberships(actor_membership):
        raise PermissionDenied("You do not have permission to manage memberships for this workspace.")

    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user = user_model.objects.get(username=username)

    membership, created = Membership.objects.get_or_create(
        workspace=actor_membership.workspace,
        user=user,
        defaults={"role": MembershipRole.MEMBER},
    )

    return membership, created


@transaction.atomic
def update_workspace_membership_role(*, actor_membership, target_membership, new_role):
    if actor_membership.role != MembershipRole.OWNER:
        raise PermissionDenied("Only workspace owners can change membership roles.")

    if target_membership.workspace_id != actor_membership.workspace_id:
        raise PermissionDenied("You cannot manage memberships outside your workspace.")

    if target_membership.role == MembershipRole.OWNER:
        raise PermissionDenied("Owner membership cannot be modified.")

    if new_role not in {MembershipRole.MEMBER, MembershipRole.MANAGER}:
        raise PermissionDenied("Invalid role change.")

    target_membership.role = new_role
    target_membership.save(update_fields=["role", "updated_at"])
    return target_membership


def user_can_manage_gamification(membership):
    return membership.role in {MembershipRole.OWNER, MembershipRole.MANAGER}


def user_can_manage_task_templates(membership):
    return membership.role in {MembershipRole.OWNER, MembershipRole.MANAGER}


def _require_task_template_management_access(*, actor_membership, workspace):
    if actor_membership.workspace_id != workspace.id:
        raise PermissionDenied("You cannot manage task templates outside your workspace.")

    if not user_can_manage_task_templates(actor_membership):
        raise PermissionDenied("You do not have permission to manage task templates for this workspace.")


@transaction.atomic
def create_task_template(*, actor_membership, title, description, frequency, difficulty, is_active):
    workspace = actor_membership.workspace
    _require_task_template_management_access(
        actor_membership=actor_membership,
        workspace=workspace,
    )
    return TaskTemplate.objects.create(
        workspace=workspace,
        created_by=actor_membership.user,
        title=title,
        description=description,
        frequency=frequency,
        difficulty=difficulty,
        is_active=is_active,
    )


@transaction.atomic
def update_task_template(
    *, actor_membership, task_template, title, description, frequency, difficulty, is_active
):
    _require_task_template_management_access(
        actor_membership=actor_membership,
        workspace=task_template.workspace,
    )
    task_template.title = title
    task_template.description = description
    task_template.frequency = frequency
    task_template.difficulty = difficulty
    task_template.is_active = is_active
    task_template.save(
        update_fields=["title", "description", "frequency", "difficulty", "is_active", "updated_at"]
    )
    return task_template


@transaction.atomic
def deactivate_task_template(*, actor_membership, task_template):
    _require_task_template_management_access(
        actor_membership=actor_membership,
        workspace=task_template.workspace,
    )
    task_template.is_active = False
    task_template.save(update_fields=["is_active", "updated_at"])
    return task_template


def user_can_manage_task_assignments(membership):
    return membership.role in {MembershipRole.OWNER, MembershipRole.MANAGER}


def _require_task_assignment_management_access(*, actor_membership, workspace):
    if actor_membership.workspace_id != workspace.id:
        raise PermissionDenied("You cannot manage task instances outside your workspace.")

    if not user_can_manage_task_assignments(actor_membership):
        raise PermissionDenied("You do not have permission to manage task instances for this workspace.")


@transaction.atomic
def create_available_task_assignment(*, actor_membership, task_template):
    workspace = actor_membership.workspace
    _require_task_assignment_management_access(
        actor_membership=actor_membership,
        workspace=workspace,
    )

    if task_template.workspace_id != workspace.id:
        raise PermissionDenied("You cannot create a task instance from a template outside your workspace.")

    if not task_template.is_active:
        raise PermissionDenied("You cannot create a task instance from an inactive template.")

    return TaskAssignment.objects.create(
        workspace=workspace,
        task_template=task_template,
        status=TaskStatus.AVAILABLE,
        title_snapshot=task_template.title,
        description_snapshot=task_template.description,
        frequency_snapshot=task_template.frequency,
        difficulty_snapshot=task_template.difficulty,
    )


@transaction.atomic
def self_select_available_task(*, actor_membership, task_assignment):
    workspace = actor_membership.workspace

    if not Membership.objects.filter(
        pk=actor_membership.pk,
        workspace=workspace,
        user=actor_membership.user,
    ).exists():
        raise PermissionDenied("You must be a member of this workspace to select a task.")

    if task_assignment.workspace_id != workspace.id:
        raise PermissionDenied("You cannot select a task outside your workspace.")

    updated = TaskAssignment.objects.filter(
        pk=task_assignment.pk,
        workspace=workspace,
        status=TaskStatus.AVAILABLE,
        assigned_to__isnull=True,
    ).update(
        assigned_to=actor_membership.user,
        assignment_type=AssignmentType.SELF_SELECTION,
        status=TaskStatus.ACTIVE,
        updated_at=timezone.now(),
    )

    if updated != 1:
        raise ValidationError("This task is no longer available.")

    task_assignment.refresh_from_db()
    TaskEventHistory.objects.create(
        task_assignment=task_assignment,
        workspace=workspace,
        event_type=TaskEventType.MEMBER_SELECTED_TASK,
        actor=actor_membership.user,
        affected_member=actor_membership.user,
    )
    return task_assignment


@transaction.atomic
def seed_default_scoring_rules(*, workspace):
    created_rules = []

    for (frequency, difficulty), values in DEFAULT_SCORING_RULES.items():
        rule, created = ScoringRule.objects.get_or_create(
            workspace=workspace,
            frequency=frequency,
            difficulty=difficulty,
            defaults={
                "completion_points": values["completion_points"],
                "late_penalty": values["late_penalty"],
            },
        )
        if created:
            created_rules.append(rule)

    return created_rules


@transaction.atomic
def update_workspace_gamification_settings(
    *,
    actor_membership,
    workspace,
    gamification_enabled,
    reward_system_enabled,
):
    if actor_membership.workspace_id != workspace.id:
        raise PermissionDenied("You cannot manage gamification settings outside your workspace.")

    if not user_can_manage_gamification(actor_membership):
        raise PermissionDenied("You do not have permission to manage gamification settings for this workspace.")

    if reward_system_enabled and not gamification_enabled:
        raise PermissionDenied("Reward system cannot be enabled when gamification is disabled.")

    workspace.gamification_enabled = gamification_enabled
    workspace.reward_system_enabled = reward_system_enabled if gamification_enabled else False
    workspace.save(update_fields=["gamification_enabled", "reward_system_enabled", "updated_at"])

    if workspace.gamification_enabled:
        seed_default_scoring_rules(workspace=workspace)

    return workspace
