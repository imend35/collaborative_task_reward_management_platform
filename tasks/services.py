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
