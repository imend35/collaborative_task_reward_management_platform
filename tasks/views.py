from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import UserRegistrationForm, WorkspaceForm
from .models import Workspace
from .services import create_workspace_with_owner


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
    workspace = get_object_or_404(
        Workspace.objects.filter(memberships__user=request.user).distinct(),
        pk=pk,
    )
    return render(
        request,
        "tasks/workspace_detail.html",
        {"workspace": workspace},
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
