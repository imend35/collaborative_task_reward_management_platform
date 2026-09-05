from django import forms
from django.forms import BaseModelFormSet, modelformset_factory
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import (
    Membership,
    MembershipRole,
    TaskAssignment,
    ScoringRule,
    TaskDifficulty,
    TaskFrequency,
    TaskStatus,
    TaskTemplate,
    Workspace,
    WorkspaceType,
)


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


class ScoringRuleForm(forms.ModelForm):
    class Meta:
        model = ScoringRule
        fields = ("completion_points", "late_penalty")

    def clean_completion_points(self):
        value = self.cleaned_data["completion_points"]
        if value < 0:
            raise forms.ValidationError("Completion points must be zero or greater.")
        return value

    def clean_late_penalty(self):
        value = self.cleaned_data["late_penalty"]
        if value > 0:
            raise forms.ValidationError("Late penalties must be zero or less.")
        return value


class BaseScoringRuleFormSet(BaseModelFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        submitted_ids = [form.cleaned_data["id"].pk for form in self.forms]
        if len(submitted_ids) != len(set(submitted_ids)):
            raise forms.ValidationError("Each scoring rule may be submitted only once.")
        expected_ids = set(self.queryset.values_list("pk", flat=True))
        submitted_id_set = set(submitted_ids)
        if submitted_id_set != expected_ids:
            raise forms.ValidationError("The complete workspace scoring configuration is required.")


def scoring_rule_formset(*args, workspace, **kwargs):
    formset_class = modelformset_factory(
        ScoringRule,
        form=ScoringRuleForm,
        formset=BaseScoringRuleFormSet,
        extra=0,
    )
    return formset_class(
        *args,
        queryset=ScoringRule.objects.filter(workspace=workspace).order_by("frequency", "difficulty", "pk"),
        **kwargs,
    )


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


class ManagerTaskAssignmentForm(forms.Form):
    task_assignment = forms.ModelChoiceField(queryset=TaskAssignment.objects.none())
    target_membership = forms.ModelChoiceField(queryset=Membership.objects.none())

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["task_assignment"].queryset = TaskAssignment.objects.filter(
            workspace=workspace,
            status=TaskStatus.AVAILABLE,
            assigned_to__isnull=True,
        )
        self.fields["target_membership"].queryset = Membership.objects.filter(
            workspace=workspace,
        ).select_related("user")


class ReassignIncompleteTaskForm(forms.Form):
    task_assignment = forms.ModelChoiceField(queryset=TaskAssignment.objects.none())
    target_membership = forms.ModelChoiceField(queryset=Membership.objects.none())

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["task_assignment"].queryset = TaskAssignment.objects.filter(
            workspace=workspace,
            status=TaskStatus.INCOMPLETE,
        )
        self.fields["target_membership"].queryset = Membership.objects.filter(
            workspace=workspace,
        ).select_related("user")

    def clean(self):
        cleaned = super().clean()
        assignment = cleaned.get("task_assignment")
        target = cleaned.get("target_membership")
        if assignment and target and assignment.assigned_to_id == target.user_id:
            self.add_error("target_membership", "Select a different member for reassignment.")
        return cleaned
