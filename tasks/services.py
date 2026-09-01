from django.core.exceptions import PermissionDenied
from django.db import transaction

from .models import Membership, MembershipRole, Workspace


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
