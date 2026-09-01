from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Workspace, WorkspaceType


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
