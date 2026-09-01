from django.conf import settings
from django.db import models


class WorkspaceType(models.TextChoices):
    HOUSEHOLD = "HOUSEHOLD", "Household / Family"
    BUSINESS = "BUSINESS", "Business / Project Team"
    CONSTRUCTION = "CONSTRUCTION", "Construction Project"
    EDUCATION = "EDUCATION", "Education / Student Group"
    COMMUNITY = "COMMUNITY", "Community"
    ORGANIZATION = "ORGANIZATION", "Organization"
    SPORTS_TEAM = "SPORTS_TEAM", "Sports Team"
    OTHER = "OTHER", "Other"


class MembershipRole(models.TextChoices):
    OWNER = "OWNER", "Owner"
    MANAGER = "MANAGER", "Manager"
    MEMBER = "MEMBER", "Member"


class TaskFrequency(models.TextChoices):
    DAILY = "DAILY", "Daily"
    WEEKLY = "WEEKLY", "Weekly"
    MONTHLY = "MONTHLY", "Monthly"


class TaskDifficulty(models.TextChoices):
    EASY = "EASY", "Easy"
    MEDIUM = "MEDIUM", "Medium"
    HARD = "HARD", "Hard"


class AssignmentType(models.TextChoices):
    SELF_SELECTION = "SELF_SELECTION", "Self-selection"
    MANAGER_ASSIGNMENT = "MANAGER_ASSIGNMENT", "Manager assignment"
    REASSIGNMENT = "REASSIGNMENT", "Reassignment"


class TaskStatus(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE", "Pending acceptance"
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    OVERDUE = "OVERDUE", "Overdue"
    GRACE_PERIOD = "GRACE_PERIOD", "Grace period"
    INCOMPLETE = "INCOMPLETE", "Incomplete"
    PENDING_REASSIGNMENT = "PENDING_REASSIGNMENT", "Pending reassignment"
    REJECTED = "REJECTED", "Rejected"


class TaskEventType(models.TextChoices):
    TASK_CREATED = "TASK_CREATED", "Task created"
    TASK_BECAME_AVAILABLE = "TASK_BECAME_AVAILABLE", "Task became available"
    MEMBER_SELECTED_TASK = "MEMBER_SELECTED_TASK", "Member selected task"
    MANAGER_ASSIGNED_TASK = "MANAGER_ASSIGNED_TASK", "Manager assigned task"
    MEMBER_ACCEPTED_ASSIGNMENT = "MEMBER_ACCEPTED_ASSIGNMENT", "Member accepted assignment"
    MEMBER_REJECTED_ASSIGNMENT = "MEMBER_REJECTED_ASSIGNMENT", "Member rejected assignment"
    TASK_BECAME_OVERDUE = "TASK_BECAME_OVERDUE", "Task became overdue"
    LATE_PENALTY_APPLIED = "LATE_PENALTY_APPLIED", "Late penalty applied"
    GRACE_PERIOD_STARTED = "GRACE_PERIOD_STARTED", "Grace period started"
    TASK_COMPLETED = "TASK_COMPLETED", "Task completed"
    TASK_BECAME_INCOMPLETE = "TASK_BECAME_INCOMPLETE", "Task became incomplete"
    TASK_REASSIGNED = "TASK_REASSIGNED", "Task reassigned"
    DAILY_TASK_ROLLED_OVER = "DAILY_TASK_ROLLED_OVER", "Daily task rolled over"


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Workspace(TimestampedModel):
    name = models.CharField(max_length=255)
    workspace_type = models.CharField(
        max_length=32,
        choices=WorkspaceType.choices,
    )
    custom_workspace_type = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Membership(TimestampedModel):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(
        max_length=16,
        choices=MembershipRole.choices,
    )

    class Meta:
        ordering = ["workspace_id", "user_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="unique_membership_per_workspace_user",
            )
        ]

    def __str__(self):
        return f"{self.user} in {self.workspace} ({self.role})"


class TaskTemplate(TimestampedModel):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="task_templates",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    frequency = models.CharField(
        max_length=16,
        choices=TaskFrequency.choices,
    )
    difficulty = models.CharField(
        max_length=16,
        choices=TaskDifficulty.choices,
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_task_templates",
    )

    class Meta:
        ordering = ["workspace_id", "title", "id"]

    def __str__(self):
        return self.title


class TaskAssignment(TimestampedModel):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="task_assignments",
    )
    task_template = models.ForeignKey(
        TaskTemplate,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_task_assignments",
    )
    assignment_type = models.CharField(
        max_length=32,
        choices=AssignmentType.choices,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=32,
        choices=TaskStatus.choices,
        default=TaskStatus.AVAILABLE,
    )
    title_snapshot = models.CharField(max_length=255)
    description_snapshot = models.TextField(blank=True)
    frequency_snapshot = models.CharField(
        max_length=16,
        choices=TaskFrequency.choices,
    )
    difficulty_snapshot = models.CharField(
        max_length=16,
        choices=TaskDifficulty.choices,
    )
    completion_points_snapshot = models.IntegerField(null=True, blank=True)
    late_penalty_snapshot = models.IntegerField(null=True, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_task_assignments",
    )

    class Meta:
        ordering = ["workspace_id", "status", "id"]

    def __str__(self):
        return f"{self.title_snapshot} [{self.status}]"


class TaskEventHistory(models.Model):
    task_assignment = models.ForeignKey(
        TaskAssignment,
        on_delete=models.CASCADE,
        related_name="history_events",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="task_history_events",
    )
    event_type = models.CharField(
        max_length=40,
        choices=TaskEventType.choices,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_history_actions",
    )
    affected_member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_history_memberships",
    )
    score_change = models.IntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["task_assignment_id", "created_at", "id"]

    def __str__(self):
        return f"{self.event_type} for {self.task_assignment}"
