from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    UserRegistrationForm,
    WorkspaceForm,
    WorkspaceMembershipAddForm,
    WorkspaceMembershipRoleForm,
)
from .models import Membership, MembershipRole, Workspace
from .services import (
    add_existing_user_to_workspace,
    create_workspace_with_owner,
    update_workspace_membership_role,
    user_can_manage_memberships,
)


@login_required
def dashboard(request):
    return render(request, "tasks/dashboard.html")


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard")
    else:
        form = UserRegistrationForm()

    return render(request, "registration/register.html", {"form": form})


def get_workspace_membership_for_user(*, user, workspace):
    return get_object_or_404(Membership, workspace=workspace, user=user)


def get_workspace_for_member(*, user, pk):
    return get_object_or_404(
        Workspace.objects.filter(memberships__user=user).distinct(),
        pk=pk,
    )


def require_membership_management_access(*, membership):
    if not user_can_manage_memberships(membership):
        raise PermissionDenied("You do not have permission to manage memberships for this workspace.")


@login_required
def workspace_list(request):
    workspaces = Workspace.objects.filter(
        memberships__user=request.user,
    ).distinct()
    return render(
        request,
        "tasks/workspace_list.html",
        {"workspaces": workspaces},
    )


@login_required
def workspace_detail(request, pk):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    return render(
        request,
        "tasks/workspace_detail.html",
        {
            "workspace": workspace,
            "current_membership": current_membership,
            "can_manage_memberships": user_can_manage_memberships(current_membership),
        },
    )


@login_required
def workspace_create(request):
    if request.method == "POST":
        form = WorkspaceForm(request.POST)
        if form.is_valid():
            workspace = create_workspace_with_owner(
                user=request.user,
                name=form.cleaned_data["name"],
                workspace_type=form.cleaned_data["workspace_type"],
                custom_workspace_type=form.cleaned_data["custom_workspace_type"],
            )
            return redirect("workspace-detail", pk=workspace.pk)
    else:
        form = WorkspaceForm()

    return render(request, "tasks/workspace_form.html", {"form": form})


@login_required
def workspace_membership_list(request, pk):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    require_membership_management_access(membership=current_membership)

    add_form = WorkspaceMembershipAddForm(workspace=workspace)
    memberships = workspace.memberships.select_related("user").order_by("role", "user__username")
    return render(
        request,
        "tasks/workspace_membership_list.html",
        {
            "workspace": workspace,
            "memberships": memberships,
            "current_membership": current_membership,
            "add_form": add_form,
            "membership_role_choices": {
                MembershipRole.MEMBER: "Member",
                MembershipRole.MANAGER: "Manager",
            },
        },
    )


@login_required
def workspace_membership_add(request, pk):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    require_membership_management_access(membership=current_membership)

    if request.method != "POST":
        return redirect("workspace-memberships", pk=workspace.pk)

    form = WorkspaceMembershipAddForm(request.POST, workspace=workspace)
    if form.is_valid():
        add_existing_user_to_workspace(
            actor_membership=current_membership,
            username=form.cleaned_data["username"],
        )
        return redirect("workspace-memberships", pk=workspace.pk)

    memberships = workspace.memberships.select_related("user").order_by("role", "user__username")
    return render(
        request,
        "tasks/workspace_membership_list.html",
        {
            "workspace": workspace,
            "memberships": memberships,
            "current_membership": current_membership,
            "add_form": form,
            "membership_role_choices": {
                MembershipRole.MEMBER: "Member",
                MembershipRole.MANAGER: "Manager",
            },
        },
        status=200,
    )


@login_required
def workspace_membership_role_update(request, pk, membership_id):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    target_membership = get_object_or_404(
        Membership.objects.select_related("user", "workspace"),
        pk=membership_id,
        workspace=workspace,
    )

    if request.method != "POST":
        return redirect("workspace-memberships", pk=workspace.pk)

    form = WorkspaceMembershipRoleForm(request.POST, membership=target_membership)
    if form.is_valid():
        update_workspace_membership_role(
            actor_membership=current_membership,
            target_membership=target_membership,
            new_role=form.cleaned_data["role"],
        )

    return redirect("workspace-memberships", pk=workspace.pk)
