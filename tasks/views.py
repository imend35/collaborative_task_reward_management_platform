from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    AvailableTaskInstanceForm,
    ManagerTaskAssignmentForm,
    TaskTemplateForm,
    UserRegistrationForm,
    WorkspaceGamificationSettingsForm,
    WorkspaceForm,
    WorkspaceMembershipAddForm,
    WorkspaceMembershipRoleForm,
)
from .models import Membership, MembershipRole, TaskAssignment, TaskStatus, TaskTemplate, Workspace
from .services import (
    add_existing_user_to_workspace,
    create_available_task_assignment,
    assign_task_to_member,
    create_task_template,
    create_workspace_with_owner,
    deactivate_task_template,
    update_task_template,
    update_workspace_membership_role,
    update_workspace_gamification_settings,
    self_select_available_task,
    user_can_manage_gamification,
    user_can_manage_memberships,
    user_can_manage_task_assignments,
    user_can_manage_task_templates,
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


def require_gamification_management_access(*, membership):
    if not user_can_manage_gamification(membership):
        raise PermissionDenied("You do not have permission to manage gamification settings for this workspace.")


def require_task_template_management_access(*, membership):
    if not user_can_manage_task_templates(membership):
        raise PermissionDenied("You do not have permission to manage task templates for this workspace.")


def require_task_assignment_management_access(*, membership):
    if not user_can_manage_task_assignments(membership):
        raise PermissionDenied("You do not have permission to manage task instances for this workspace.")


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
            "can_manage_gamification": user_can_manage_gamification(current_membership),
            "can_manage_task_templates": user_can_manage_task_templates(current_membership),
            "can_manage_task_assignments": user_can_manage_task_assignments(current_membership),
            "scoring_rules": workspace.scoring_rules.all(),
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


@login_required
def workspace_gamification_settings(request, pk):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    require_gamification_management_access(membership=current_membership)

    if request.method == "POST":
        form = WorkspaceGamificationSettingsForm(request.POST, instance=workspace)
        if form.is_valid():
            update_workspace_gamification_settings(
                actor_membership=current_membership,
                workspace=workspace,
                gamification_enabled=form.cleaned_data["gamification_enabled"],
                reward_system_enabled=form.cleaned_data["reward_system_enabled"],
            )
            return redirect("workspace-gamification-settings", pk=workspace.pk)
    else:
        form = WorkspaceGamificationSettingsForm(instance=workspace)

    workspace.refresh_from_db()
    return render(
        request,
        "tasks/workspace_gamification_settings.html",
        {
            "workspace": workspace,
            "current_membership": current_membership,
            "form": form,
            "scoring_rules": workspace.scoring_rules.all(),
        },
    )


@login_required
def task_template_list(request, pk):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    require_task_template_management_access(membership=current_membership)
    task_templates = workspace.task_templates.select_related("created_by")
    return render(
        request,
        "tasks/task_template_list.html",
        {
            "workspace": workspace,
            "task_templates": task_templates,
        },
    )


@login_required
def task_template_create(request, pk):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    require_task_template_management_access(membership=current_membership)

    if request.method == "POST":
        form = TaskTemplateForm(request.POST)
        if form.is_valid():
            create_task_template(actor_membership=current_membership, **form.cleaned_data)
            return redirect("task-template-list", pk=workspace.pk)
    else:
        form = TaskTemplateForm()

    return render(request, "tasks/task_template_form.html", {"workspace": workspace, "form": form})


@login_required
def task_template_edit(request, pk, template_id):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    require_task_template_management_access(membership=current_membership)
    task_template = get_object_or_404(TaskTemplate, pk=template_id, workspace=workspace)

    if request.method == "POST":
        form = TaskTemplateForm(request.POST, instance=task_template)
        if form.is_valid():
            update_task_template(
                actor_membership=current_membership,
                task_template=task_template,
                **form.cleaned_data,
            )
            return redirect("task-template-list", pk=workspace.pk)
    else:
        form = TaskTemplateForm(instance=task_template)

    return render(
        request,
        "tasks/task_template_form.html",
        {"workspace": workspace, "form": form, "task_template": task_template},
    )


@login_required
def task_template_deactivate(request, pk, template_id):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    require_task_template_management_access(membership=current_membership)
    task_template = get_object_or_404(TaskTemplate, pk=template_id, workspace=workspace)

    if request.method == "POST":
        deactivate_task_template(actor_membership=current_membership, task_template=task_template)

    return redirect("task-template-list", pk=workspace.pk)


@login_required
def available_task_instance_list(request, pk):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    require_task_assignment_management_access(membership=current_membership)
    task_assignments = workspace.task_assignments.filter(status=TaskStatus.AVAILABLE).select_related(
        "task_template"
    )
    return render(
        request,
        "tasks/available_task_instance_list.html",
        {"workspace": workspace, "task_assignments": task_assignments},
    )


@login_required
def available_task_instance_create(request, pk):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    require_task_assignment_management_access(membership=current_membership)

    if request.method == "POST":
        form = AvailableTaskInstanceForm(request.POST, workspace=workspace)
        if form.is_valid():
            create_available_task_assignment(
                actor_membership=current_membership,
                task_template=form.cleaned_data["task_template"],
            )
            return redirect("available-task-instance-list", pk=workspace.pk)
    else:
        form = AvailableTaskInstanceForm(workspace=workspace)

    return render(
        request,
        "tasks/available_task_instance_form.html",
        {"workspace": workspace, "form": form},
    )


@login_required
def manager_task_assignment(request, pk):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    require_task_assignment_management_access(membership=current_membership)

    if request.method == "POST":
        form = ManagerTaskAssignmentForm(request.POST, workspace=workspace)
        if form.is_valid():
            try:
                assign_task_to_member(
                    actor_membership=current_membership,
                    task_assignment=form.cleaned_data["task_assignment"],
                    target_membership=form.cleaned_data["target_membership"],
                )
            except ValidationError:
                form.add_error(None, "This task is no longer available.")
            else:
                return redirect("available-task-instance-list", pk=workspace.pk)
    else:
        form = ManagerTaskAssignmentForm(workspace=workspace)

    return render(
        request,
        "tasks/manager_task_assignment_form.html",
        {"workspace": workspace, "form": form},
    )


@login_required
def member_available_task_list(request, pk):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    get_workspace_membership_for_user(user=request.user, workspace=workspace)
    task_assignments = workspace.task_assignments.filter(status=TaskStatus.AVAILABLE).select_related(
        "task_template"
    )
    pending_task_assignments = workspace.task_assignments.filter(
        status=TaskStatus.PENDING_ACCEPTANCE,
        assigned_to=request.user,
    ).select_related("task_template")
    return render(
        request,
        "tasks/member_available_task_list.html",
        {
            "workspace": workspace,
            "task_assignments": task_assignments,
            "pending_task_assignments": pending_task_assignments,
        },
    )


@login_required
@require_POST
def self_select_available_task_view(request, pk, task_assignment_id):
    workspace = get_workspace_for_member(user=request.user, pk=pk)
    current_membership = get_workspace_membership_for_user(user=request.user, workspace=workspace)
    task_assignment = get_object_or_404(
        TaskAssignment,
        pk=task_assignment_id,
        workspace=workspace,
    )

    try:
        self_select_available_task(
            actor_membership=current_membership,
            task_assignment=task_assignment,
        )
    except ValidationError:
        return HttpResponse("This task is no longer available.", status=409)

    return redirect("member-available-task-list", pk=workspace.pk)
