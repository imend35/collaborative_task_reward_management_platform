from django.core.exceptions import PermissionDenied
from django.db import transaction

from .models import Membership, MembershipRole, ScoringRule, TaskDifficulty, TaskFrequency, Workspace


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
