from django.contrib.auth import views as auth_views
from django.urls import path

from .views import (
    dashboard,
    register,
    workspace_create,
    workspace_detail,
    workspace_list,
    workspace_membership_add,
    workspace_membership_list,
    workspace_membership_role_update,
)


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("workspaces/", workspace_list, name="workspace-list"),
    path("workspaces/create/", workspace_create, name="workspace-create"),
    path("workspaces/<int:pk>/", workspace_detail, name="workspace-detail"),
    path("workspaces/<int:pk>/memberships/", workspace_membership_list, name="workspace-memberships"),
    path("workspaces/<int:pk>/memberships/add/", workspace_membership_add, name="workspace-membership-add"),
    path(
        "workspaces/<int:pk>/memberships/<int:membership_id>/role/",
        workspace_membership_role_update,
        name="workspace-membership-role-update",
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
