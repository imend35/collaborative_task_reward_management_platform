from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Membership, MembershipRole, TaskTemplate, Workspace, WorkspaceType


class UserRegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)


class WorkspaceForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = ("name", "workspace_type", "custom_workspace_type")

    def clean(self):
        cleaned_data = super().clean()
        workspace_type = cleaned_data.get("workspace_type")
        custom_workspace_type = (cleaned_data.get("custom_workspace_type") or "").strip()

        if workspace_type == WorkspaceType.OTHER and not custom_workspace_type:
            self.add_error(
                "custom_workspace_type",
                "This field is required when workspace type is Other.",
            )

        if workspace_type != WorkspaceType.OTHER:
            cleaned_data["custom_workspace_type"] = ""
        else:
            cleaned_data["custom_workspace_type"] = custom_workspace_type

        return cleaned_data


class WorkspaceMembershipAddForm(forms.Form):
    username = forms.CharField(max_length=150)

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace

    def clean_username(self):
        username = self.cleaned_data["username"].strip()

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise forms.ValidationError("No registered user was found with that username.") from exc

        if Membership.objects.filter(workspace=self.workspace, user=user).exists():
            raise forms.ValidationError("That user is already a member of this workspace.")

        self.cleaned_data["user_obj"] = user
        return username


class WorkspaceMembershipRoleForm(forms.Form):
    role = forms.ChoiceField(
        choices=[
            (MembershipRole.MEMBER, "Member"),
            (MembershipRole.MANAGER, "Manager"),
        ]
    )

    def __init__(self, *args, membership, **kwargs):
        super().__init__(*args, **kwargs)
        self.membership = membership


class WorkspaceGamificationSettingsForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = ("gamification_enabled", "reward_system_enabled")

    def clean(self):
        cleaned_data = super().clean()
        gamification_enabled = cleaned_data.get("gamification_enabled")
        reward_system_enabled = cleaned_data.get("reward_system_enabled")

        if reward_system_enabled and not gamification_enabled:
            self.add_error(
                "reward_system_enabled",
                "Reward system cannot be enabled when gamification is disabled.",
            )

        return cleaned_data


class TaskTemplateForm(forms.ModelForm):
    class Meta:
        model = TaskTemplate
        fields = ("title", "description", "frequency", "difficulty", "is_active")


class AvailableTaskInstanceForm(forms.Form):
    task_template = forms.ModelChoiceField(queryset=TaskTemplate.objects.none())

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["task_template"].queryset = TaskTemplate.objects.filter(
            workspace=workspace,
            is_active=True,
        )
