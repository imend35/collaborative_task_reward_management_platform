from django.contrib.auth import views as auth_views
from django.urls import path

from .views import (
    dashboard,
    register,
    workspace_create,
    workspace_detail,
    workspace_gamification_settings,
    workspace_list,
    workspace_membership_add,
    workspace_membership_list,
    workspace_membership_role_update,
    task_template_create,
    task_template_deactivate,
    task_template_edit,
    task_template_list,
    available_task_instance_create,
    available_task_instance_list,
    manager_task_assignment,
    accept_pending_task_view,
    complete_active_task_view,
    reject_pending_task_view,
    member_available_task_list,
    self_select_available_task_view,
)


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("workspaces/", workspace_list, name="workspace-list"),
    path("workspaces/create/", workspace_create, name="workspace-create"),
    path("workspaces/<int:pk>/", workspace_detail, name="workspace-detail"),
    path(
        "workspaces/<int:pk>/settings/gamification/",
        workspace_gamification_settings,
        name="workspace-gamification-settings",
    ),
    path("workspaces/<int:pk>/memberships/", workspace_membership_list, name="workspace-memberships"),
    path("workspaces/<int:pk>/memberships/add/", workspace_membership_add, name="workspace-membership-add"),
    path(
        "workspaces/<int:pk>/memberships/<int:membership_id>/role/",
        workspace_membership_role_update,
        name="workspace-membership-role-update",
    ),
    path("workspaces/<int:pk>/task-templates/", task_template_list, name="task-template-list"),
    path("workspaces/<int:pk>/task-templates/create/", task_template_create, name="task-template-create"),
    path(
        "workspaces/<int:pk>/task-templates/<int:template_id>/edit/",
        task_template_edit,
        name="task-template-edit",
    ),
    path(
        "workspaces/<int:pk>/task-templates/<int:template_id>/deactivate/",
        task_template_deactivate,
        name="task-template-deactivate",
    ),
    path(
        "workspaces/<int:pk>/available-tasks/",
        available_task_instance_list,
        name="available-task-instance-list",
    ),
    path(
        "workspaces/<int:pk>/available-tasks/create/",
        available_task_instance_create,
        name="available-task-instance-create",
    ),
    path(
        "workspaces/<int:pk>/available-tasks/assign/",
        manager_task_assignment,
        name="manager-task-assignment",
    ),
    path(
        "workspaces/<int:pk>/tasks/available/",
        member_available_task_list,
        name="member-available-task-list",
    ),
    path(
        "workspaces/<int:pk>/tasks/<int:task_assignment_id>/select/",
        self_select_available_task_view,
        name="self-select-available-task",
    ),
    path(
        "workspaces/<int:pk>/tasks/<int:task_assignment_id>/accept/",
        accept_pending_task_view,
        name="accept-pending-task",
    ),
    path(
        "workspaces/<int:pk>/tasks/<int:task_assignment_id>/reject/",
        reject_pending_task_view,
        name="reject-pending-task",
    ),
    path(
        "workspaces/<int:pk>/tasks/<int:task_assignment_id>/complete/",
        complete_active_task_view,
        name="complete-active-task",
    ),
    path("accounts/register/", register, name="register"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
]
