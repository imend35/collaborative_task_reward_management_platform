from django.contrib import admin

from .models import Membership, TaskAssignment, TaskEventHistory, TaskTemplate, Workspace


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace_type", "created_at", "updated_at")
    search_fields = ("name", "custom_workspace_type")
    list_filter = ("workspace_type",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("workspace", "user", "role", "created_at")
    search_fields = ("workspace__name", "user__username")
    list_filter = ("role",)


@admin.register(TaskTemplate)
class TaskTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "frequency", "difficulty", "is_active")
    search_fields = ("title", "workspace__name")
    list_filter = ("frequency", "difficulty", "is_active")


@admin.register(TaskAssignment)
class TaskAssignmentAdmin(admin.ModelAdmin):
    list_display = ("title_snapshot", "workspace", "status", "assigned_to", "assignment_type")
    search_fields = ("title_snapshot", "workspace__name", "assigned_to__username")
    list_filter = ("status", "assignment_type", "frequency_snapshot", "difficulty_snapshot")


@admin.register(TaskEventHistory)
class TaskEventHistoryAdmin(admin.ModelAdmin):
    list_display = ("event_type", "task_assignment", "workspace", "actor", "affected_member", "created_at")
    search_fields = ("task_assignment__title_snapshot", "workspace__name", "actor__username")
    list_filter = ("event_type",)
