from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    AssignmentType,
    Membership,
    MembershipRole,
    MemberScoreLedger,
    ScoreTransactionType,
    ScoringRule,
    TaskAssignment,
    TaskDifficulty,
    TaskEventHistory,
    TaskEventType,
    TaskFrequency,
    TaskStatus,
    TaskTemplate,
    Workspace,
    WorkspaceType,
)
from .services import (
    accept_pending_task,
    assign_task_to_member,
    calculate_due_at,
    complete_active_task,
    create_available_task_assignment,
    seed_default_scoring_rules,
    self_select_available_task,
    reject_pending_task,
    process_overdue_task,
    process_grace_expiry,
    reassign_incomplete_task,
)


class TaskOverdueTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="overdue_owner", password="pass")
        self.manager = user_model.objects.create_user(username="overdue_manager", password="pass")
        self.member = user_model.objects.create_user(username="overdue_member", password="pass")
        self.workspace = Workspace.objects.create(name="Overdue", workspace_type=WorkspaceType.BUSINESS, gamification_enabled=True)
        self.owner_membership = Membership.objects.create(workspace=self.workspace, user=self.owner, role=MembershipRole.OWNER)
        self.manager_membership = Membership.objects.create(workspace=self.workspace, user=self.manager, role=MembershipRole.MANAGER)
        self.member_membership = Membership.objects.create(workspace=self.workspace, user=self.member, role=MembershipRole.MEMBER)
        self.rule = ScoringRule.objects.create(workspace=self.workspace, frequency=TaskFrequency.DAILY, difficulty=TaskDifficulty.EASY, completion_points=10, late_penalty=-5)
        template = TaskTemplate.objects.create(workspace=self.workspace, title="Late task", frequency=TaskFrequency.DAILY, difficulty=TaskDifficulty.EASY, created_by=self.owner)
        self.assignment = create_available_task_assignment(actor_membership=self.owner_membership, task_template=template)
        self_select_available_task(actor_membership=self.member_membership, task_assignment=self.assignment)

    def test_overdue_transition_penalty_and_grace_are_atomic_and_idempotent(self):
        now = self.assignment.due_at + timedelta(seconds=1)
        process_overdue_task(task_assignment=self.assignment, now=now)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, TaskStatus.GRACE_PERIOD)
        self.assertEqual(self.assignment.grace_period_ends_at, now + timedelta(hours=24))
        ledger = MemberScoreLedger.objects.get(task_assignment=self.assignment, transaction_type=ScoreTransactionType.LATE_PENALTY)
        self.assertEqual(ledger.score_change, -5)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type=TaskEventType.LATE_PENALTY_APPLIED).count(), 1)
        with self.assertRaises(ValidationError):
            process_overdue_task(task_assignment=self.assignment, now=now + timedelta(hours=1))
        self.assertEqual(MemberScoreLedger.objects.filter(task_assignment=self.assignment, transaction_type=ScoreTransactionType.LATE_PENALTY).count(), 1)
        events = TaskEventHistory.objects.filter(task_assignment=self.assignment)
        self.assertEqual(events.filter(event_type=TaskEventType.TASK_BECAME_OVERDUE).count(), 1)
        self.assertEqual(events.filter(event_type=TaskEventType.GRACE_PERIOD_STARTED).count(), 1)
        self.assertTrue(all(event.actor is None for event in events.filter(event_type__in=[TaskEventType.TASK_BECAME_OVERDUE, TaskEventType.LATE_PENALTY_APPLIED, TaskEventType.GRACE_PERIOD_STARTED])))

    def test_exact_deadline_and_missing_due_are_rejected(self):
        with self.assertRaises(ValidationError):
            process_overdue_task(task_assignment=self.assignment, now=self.assignment.due_at)
        self.assignment.due_at = None
        self.assignment.save(update_fields=["due_at", "updated_at"])
        with self.assertRaises(ValidationError):
            process_overdue_task(task_assignment=self.assignment, now=timezone.now() + timedelta(days=1))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, TaskStatus.ACTIVE)
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type=TaskEventType.TASK_BECAME_OVERDUE).exists())

    def test_disabled_gamification_still_enters_grace_without_penalty(self):
        self.workspace.gamification_enabled = False
        self.workspace.save(update_fields=["gamification_enabled", "updated_at"])
        process_overdue_task(task_assignment=self.assignment, now=self.assignment.due_at + timedelta(seconds=1))
        self.assertEqual(MemberScoreLedger.objects.filter(task_assignment=self.assignment).count(), 0)
        self.assertTrue(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type=TaskEventType.GRACE_PERIOD_STARTED).exists())

    def test_missing_penalty_snapshot_fails_without_mutation(self):
        self.assignment.late_penalty_snapshot = None
        self.assignment.save(update_fields=["late_penalty_snapshot", "updated_at"])
        with self.assertRaises(ValidationError):
            process_overdue_task(task_assignment=self.assignment, now=self.assignment.due_at + timedelta(seconds=1))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, TaskStatus.ACTIVE)
        self.assertFalse(MemberScoreLedger.objects.filter(task_assignment=self.assignment).exists())
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type=TaskEventType.TASK_BECAME_OVERDUE).exists())

    def test_task_snapshots_and_template_are_preserved(self):
        snapshots = (self.assignment.title_snapshot, self.assignment.description_snapshot, self.assignment.frequency_snapshot, self.assignment.difficulty_snapshot)
        template = self.assignment.task_template
        process_overdue_task(task_assignment=self.assignment, now=self.assignment.due_at + timedelta(seconds=1))
        self.assignment.refresh_from_db()
        self.assertEqual((self.assignment.title_snapshot, self.assignment.description_snapshot, self.assignment.frequency_snapshot, self.assignment.difficulty_snapshot), snapshots)
        template.refresh_from_db()
        self.assertEqual(template.title, "Late task")

    def test_grace_period_completion_preserves_deadline_and_adds_completion_score(self):
        process_overdue_task(task_assignment=self.assignment, now=self.assignment.due_at + timedelta(seconds=1))
        due_at = self.assignment.due_at
        complete_active_task(actor_membership=self.member_membership, task_assignment=self.assignment)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, TaskStatus.COMPLETED)
        self.assertEqual(self.assignment.due_at, due_at)
        self.assertEqual(MemberScoreLedger.objects.filter(task_assignment=self.assignment).count(), 2)
        self.assertTrue(MemberScoreLedger.objects.filter(task_assignment=self.assignment, transaction_type=ScoreTransactionType.COMPLETION_SCORE).exists())

    def test_cross_workspace_assignment_template_mismatch_is_rejected_without_side_effects(self):
        other_workspace = Workspace.objects.create(name="Other", workspace_type=WorkspaceType.BUSINESS, gamification_enabled=True)
        other_template = TaskTemplate.objects.create(workspace=other_workspace, title="Other", frequency=TaskFrequency.DAILY, difficulty=TaskDifficulty.EASY)
        self.assignment.task_template = other_template
        self.assignment.save(update_fields=["task_template", "updated_at"])
        original_due = self.assignment.due_at
        with self.assertRaises(ValidationError):
            process_overdue_task(task_assignment=self.assignment, now=original_due + timedelta(seconds=1))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, TaskStatus.ACTIVE)
        self.assertEqual(self.assignment.grace_period_ends_at, None)
        self.assertFalse(MemberScoreLedger.objects.filter(task_assignment=self.assignment, transaction_type=ScoreTransactionType.LATE_PENALTY).exists())
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type__in=[TaskEventType.TASK_BECAME_OVERDUE, TaskEventType.LATE_PENALTY_APPLIED, TaskEventType.GRACE_PERIOD_STARTED]).exists())

    def test_stale_assignment_object_cannot_overwrite_changed_database_state(self):
        stale = TaskAssignment.objects.get(pk=self.assignment.pk)
        TaskAssignment.objects.filter(pk=self.assignment.pk).update(status=TaskStatus.COMPLETED)
        with self.assertRaises(ValidationError):
            process_overdue_task(task_assignment=stale, now=stale.due_at + timedelta(seconds=1))
        current = TaskAssignment.objects.get(pk=self.assignment.pk)
        self.assertEqual(current.status, TaskStatus.COMPLETED)
        self.assertIsNone(current.grace_period_ends_at)
        self.assertFalse(MemberScoreLedger.objects.filter(task_assignment=self.assignment, transaction_type=ScoreTransactionType.LATE_PENALTY).exists())
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type__in=[TaskEventType.TASK_BECAME_OVERDUE, TaskEventType.LATE_PENALTY_APPLIED, TaskEventType.GRACE_PERIOD_STARTED]).exists())

    def test_competing_overdue_attempts_are_idempotent(self):
        now = self.assignment.due_at + timedelta(seconds=1)
        process_overdue_task(task_assignment=self.assignment, now=now)
        with self.assertRaises(ValidationError):
            process_overdue_task(task_assignment=TaskAssignment.objects.get(pk=self.assignment.pk), now=now)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, TaskStatus.GRACE_PERIOD)
        self.assertEqual(MemberScoreLedger.objects.filter(task_assignment=self.assignment, transaction_type=ScoreTransactionType.LATE_PENALTY).count(), 1)
        self.assertEqual(self.assignment.grace_period_ends_at, now + timedelta(hours=24))
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type=TaskEventType.TASK_BECAME_OVERDUE).count(), 1)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type=TaskEventType.GRACE_PERIOD_STARTED).count(), 1)

    def test_completion_wins_over_stale_overdue_processing_without_mixed_state(self):
        stale = TaskAssignment.objects.get(pk=self.assignment.pk)
        complete_active_task(actor_membership=self.member_membership, task_assignment=self.assignment)
        with self.assertRaises(ValidationError):
            process_overdue_task(task_assignment=stale, now=stale.due_at + timedelta(seconds=1))
        current = TaskAssignment.objects.get(pk=self.assignment.pk)
        self.assertEqual(current.status, TaskStatus.COMPLETED)
        self.assertIsNone(current.grace_period_ends_at)
        self.assertEqual(MemberScoreLedger.objects.filter(task_assignment=self.assignment).count(), 1)
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type=TaskEventType.TASK_BECAME_OVERDUE).exists())

    def test_missing_scoring_rule_and_penalty_snapshot_fail_atomically(self):
        self.rule.delete()
        self.assignment.late_penalty_snapshot = None
        self.assignment.save(update_fields=["late_penalty_snapshot", "updated_at"])
        with self.assertRaises(ValidationError):
            process_overdue_task(task_assignment=self.assignment, now=self.assignment.due_at + timedelta(seconds=1))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, TaskStatus.ACTIVE)
        self.assertIsNone(self.assignment.grace_period_ends_at)
        self.assertFalse(MemberScoreLedger.objects.filter(task_assignment=self.assignment).exists())
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type__in=[TaskEventType.TASK_BECAME_OVERDUE, TaskEventType.LATE_PENALTY_APPLIED, TaskEventType.GRACE_PERIOD_STARTED]).exists())

    def test_grace_expiry_marks_incomplete_and_preserves_assignment_audit_fields(self):
        process_overdue_task(task_assignment=self.assignment, now=self.assignment.due_at + timedelta(seconds=1))
        original = {field: getattr(self.assignment, field) for field in ("assigned_to_id", "assigned_by_id", "assignment_type", "assigned_at", "due_at", "grace_period_ends_at")}
        expiry = self.assignment.grace_period_ends_at + timedelta(seconds=1)
        process_grace_expiry(task_assignment=self.assignment, now=expiry)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, TaskStatus.INCOMPLETE)
        for field, value in original.items():
            self.assertEqual(getattr(self.assignment, field), value)
        self.assertEqual(MemberScoreLedger.objects.filter(task_assignment=self.assignment, transaction_type=ScoreTransactionType.GRACE_EXPIRY_PENALTY).get().score_change, -5)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type=TaskEventType.TASK_BECAME_INCOMPLETE).count(), 1)
        penalty_event = TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type=TaskEventType.LATE_PENALTY_APPLIED).order_by("-id").first()
        self.assertIsNone(penalty_event.actor)
        self.assertEqual(penalty_event.affected_member, self.member)

    def test_grace_expiry_exact_boundary_and_repeated_processing_are_rejected(self):
        process_overdue_task(task_assignment=self.assignment, now=self.assignment.due_at + timedelta(seconds=1))
        expiry = self.assignment.grace_period_ends_at
        with self.assertRaises(ValidationError):
            process_grace_expiry(task_assignment=self.assignment, now=expiry)
        process_grace_expiry(task_assignment=self.assignment, now=expiry + timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            process_grace_expiry(task_assignment=TaskAssignment.objects.get(pk=self.assignment.pk), now=expiry + timedelta(hours=1))
        self.assertEqual(MemberScoreLedger.objects.filter(task_assignment=self.assignment, transaction_type=ScoreTransactionType.GRACE_EXPIRY_PENALTY).count(), 1)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=self.assignment, event_type=TaskEventType.TASK_BECAME_INCOMPLETE).count(), 1)

    def test_disabled_gamification_expires_without_second_penalty(self):
        self.workspace.gamification_enabled = False
        self.workspace.save(update_fields=["gamification_enabled", "updated_at"])
        process_overdue_task(task_assignment=self.assignment, now=self.assignment.due_at + timedelta(seconds=1))
        process_grace_expiry(task_assignment=self.assignment, now=self.assignment.grace_period_ends_at + timedelta(seconds=1))
        self.assertEqual(self.assignment.__class__.objects.get(pk=self.assignment.pk).status, TaskStatus.INCOMPLETE)
        self.assertFalse(MemberScoreLedger.objects.filter(task_assignment=self.assignment, transaction_type=ScoreTransactionType.GRACE_EXPIRY_PENALTY).exists())

    def test_incomplete_task_is_not_self_selectable_and_manager_queue_is_scoped(self):
        process_overdue_task(task_assignment=self.assignment, now=self.assignment.due_at + timedelta(seconds=1))
        process_grace_expiry(task_assignment=self.assignment, now=self.assignment.grace_period_ends_at + timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            self_select_available_task(actor_membership=self.member_membership, task_assignment=self.assignment)
        self.client.force_login(self.owner)
        page = self.client.get(reverse("available-task-instance-list", args=[self.workspace.pk]))
        self.assertContains(page, "Late task")
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse("available-task-instance-list", args=[self.workspace.pk])), "Late task")
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("available-task-instance-list", args=[self.workspace.pk])).status_code, 403)


class TaskReassignmentTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="reassign_owner", password="pass")
        self.manager = user_model.objects.create_user(username="reassign_manager", password="pass")
        self.member = user_model.objects.create_user(username="reassign_member", password="pass")
        self.target = user_model.objects.create_user(username="reassign_target", password="pass")
        self.workspace = Workspace.objects.create(name="Reassign", workspace_type=WorkspaceType.BUSINESS, gamification_enabled=True)
        self.owner_membership = Membership.objects.create(workspace=self.workspace, user=self.owner, role=MembershipRole.OWNER)
        self.manager_membership = Membership.objects.create(workspace=self.workspace, user=self.manager, role=MembershipRole.MANAGER)
        self.member_membership = Membership.objects.create(workspace=self.workspace, user=self.member, role=MembershipRole.MEMBER)
        self.target_membership = Membership.objects.create(workspace=self.workspace, user=self.target, role=MembershipRole.MEMBER)
        self.template = TaskTemplate.objects.create(workspace=self.workspace, title="Incomplete", description="Old", frequency=TaskFrequency.WEEKLY, difficulty=TaskDifficulty.HARD, created_by=self.owner)
        self.assigned_at = datetime(2026, 1, 1, 10, tzinfo=datetime_timezone.utc)
        self.source = TaskAssignment.objects.create(
            workspace=self.workspace, task_template=self.template, assigned_to=self.member,
            assigned_by=self.manager, assignment_type=AssignmentType.MANAGER_ASSIGNMENT,
            status=TaskStatus.INCOMPLETE, title_snapshot="Incomplete", description_snapshot="Old",
            frequency_snapshot=TaskFrequency.WEEKLY, difficulty_snapshot=TaskDifficulty.HARD,
            completion_points_snapshot=100, late_penalty_snapshot=-50,
            assigned_at=self.assigned_at, due_at=self.assigned_at + timedelta(days=7),
            grace_period_ends_at=self.assigned_at + timedelta(days=8),
        )

    def test_manager_reassignment_creates_new_pending_child_and_preserves_source(self):
        original = {field: getattr(self.source, field) for field in ("assigned_to_id", "assigned_by_id", "assignment_type", "status", "title_snapshot", "description_snapshot", "frequency_snapshot", "difficulty_snapshot", "completion_points_snapshot", "late_penalty_snapshot", "assigned_at", "due_at", "grace_period_ends_at")}
        reassigned_at = datetime(2026, 2, 1, 9, tzinfo=datetime_timezone.utc)
        with patch("tasks.services.timezone.now", return_value=reassigned_at):
            child = reassign_incomplete_task(actor_membership=self.manager_membership, task_assignment=self.source, target_membership=self.target_membership)
        self.source.refresh_from_db()
        for field, value in original.items():
            self.assertEqual(getattr(self.source, field), value)
        self.assertNotEqual(child.pk, self.source.pk)
        self.assertEqual(child.reassigned_from_id, self.source.pk)
        self.assertEqual(child.workspace_id, self.workspace.pk)
        self.assertEqual(child.task_template_id, self.template.pk)
        self.assertEqual(child.assigned_to_id, self.target.id)
        self.assertEqual(child.assignment_type, AssignmentType.REASSIGNMENT)
        self.assertEqual(child.status, TaskStatus.PENDING_ACCEPTANCE)
        self.assertEqual(child.assigned_at, reassigned_at)
        self.assertEqual(child.due_at, reassigned_at + timedelta(days=7))
        self.assertIsNone(child.grace_period_ends_at)
        self.assertEqual(child.completion_points_snapshot, 100)
        self.assertEqual(child.late_penalty_snapshot, -50)
        event = TaskEventHistory.objects.get(task_assignment=child, event_type=TaskEventType.TASK_REASSIGNED)
        self.assertEqual(event.actor, self.manager)
        self.assertEqual(event.affected_member, self.target)

    def test_only_incomplete_same_workspace_different_member_can_be_reassigned(self):
        with self.assertRaises(ValidationError):
            reassign_incomplete_task(actor_membership=self.manager_membership, task_assignment=self.source, target_membership=self.member_membership)
        active = TaskAssignment.objects.create(workspace=self.workspace, task_template=self.template, status=TaskStatus.ACTIVE, assigned_to=self.member, title_snapshot="A", frequency_snapshot=TaskFrequency.WEEKLY, difficulty_snapshot=TaskDifficulty.HARD)
        with self.assertRaises(ValidationError):
            reassign_incomplete_task(actor_membership=self.manager_membership, task_assignment=active, target_membership=self.target_membership)
        self.assertFalse(TaskAssignment.objects.filter(reassigned_from=self.source).exists())
        self.assertFalse(TaskEventHistory.objects.filter(event_type=TaskEventType.TASK_REASSIGNED).exists())

    def test_member_cross_workspace_and_same_source_target_are_rejected(self):
        with self.assertRaises(PermissionDenied):
            reassign_incomplete_task(actor_membership=self.member_membership, task_assignment=self.source, target_membership=self.target_membership)
        other_workspace = Workspace.objects.create(name="Other Reassign", workspace_type=WorkspaceType.BUSINESS)
        other_membership = Membership.objects.create(workspace=other_workspace, user=self.target, role=MembershipRole.MEMBER)
        with self.assertRaises(PermissionDenied):
            reassign_incomplete_task(actor_membership=self.manager_membership, task_assignment=self.source, target_membership=other_membership)
        with self.assertRaises(ValidationError):
            reassign_incomplete_task(actor_membership=self.manager_membership, task_assignment=self.source, target_membership=self.member_membership)

    def test_repeated_live_reassignment_is_rejected_and_rejection_does_not_touch_source(self):
        child = reassign_incomplete_task(actor_membership=self.manager_membership, task_assignment=self.source, target_membership=self.target_membership)
        with self.assertRaises(ValidationError):
            reassign_incomplete_task(actor_membership=self.manager_membership, task_assignment=self.source, target_membership=self.owner_membership)
        reject_pending_task(actor_membership=self.target_membership, task_assignment=child)
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, TaskStatus.INCOMPLETE)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=child, event_type=TaskEventType.TASK_REASSIGNED).count(), 1)
        child.refresh_from_db()
        self.assertEqual(child.status, TaskStatus.AVAILABLE)

    def test_reassignment_acceptance_uses_existing_pending_flow(self):
        child = reassign_incomplete_task(actor_membership=self.manager_membership, task_assignment=self.source, target_membership=self.target_membership)
        accept_pending_task(actor_membership=self.target_membership, task_assignment=child)
        child.refresh_from_db()
        self.assertEqual(child.status, TaskStatus.ACTIVE)
        self.assertEqual(child.completion_points_snapshot, self.source.completion_points_snapshot)
        self.assertEqual(child.late_penalty_snapshot, self.source.late_penalty_snapshot)

    def test_manager_queue_reassignment_form_is_owner_manager_only(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("manager-reassign-incomplete-task", args=[self.workspace.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Incomplete")
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("manager-reassign-incomplete-task", args=[self.workspace.pk])).status_code, 403)


class TaskDomainModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="password123",
        )
        self.workspace = Workspace.objects.create(
            name="Household Alpha",
            workspace_type=WorkspaceType.HOUSEHOLD,
        )

    def test_membership_is_unique_per_workspace_and_user(self):
        Membership.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=MembershipRole.OWNER,
        )

        with self.assertRaises(IntegrityError):
            Membership.objects.create(
                workspace=self.workspace,
                user=self.user,
                role=MembershipRole.MANAGER,
            )

    def test_task_assignment_uses_snapshot_and_status_choices(self):
        template = TaskTemplate.objects.create(
            workspace=self.workspace,
            title="Take out trash",
            frequency=TaskFrequency.DAILY,
            difficulty=TaskDifficulty.EASY,
            created_by=self.user,
        )

        assignment = TaskAssignment.objects.create(
            workspace=self.workspace,
            task_template=template,
            status=TaskStatus.AVAILABLE,
            assignment_type=AssignmentType.SELF_SELECTION,
            title_snapshot=template.title,
            description_snapshot=template.description,
            frequency_snapshot=template.frequency,
            difficulty_snapshot=template.difficulty,
        )

        self.assertEqual(assignment.status, TaskStatus.AVAILABLE)
        self.assertEqual(assignment.frequency_snapshot, TaskFrequency.DAILY)
        self.assertEqual(assignment.difficulty_snapshot, TaskDifficulty.EASY)

    def test_task_event_history_records_domain_event(self):
        template = TaskTemplate.objects.create(
            workspace=self.workspace,
            title="Clean kitchen",
            frequency=TaskFrequency.WEEKLY,
            difficulty=TaskDifficulty.MEDIUM,
        )
        assignment = TaskAssignment.objects.create(
            workspace=self.workspace,
            task_template=template,
            title_snapshot=template.title,
            description_snapshot=template.description,
            frequency_snapshot=template.frequency,
            difficulty_snapshot=template.difficulty,
        )

        event = TaskEventHistory.objects.create(
            task_assignment=assignment,
            workspace=self.workspace,
            event_type=TaskEventType.TASK_CREATED,
            actor=self.user,
            affected_member=self.user,
        )

        self.assertEqual(event.event_type, TaskEventType.TASK_CREATED)
        self.assertEqual(event.workspace, self.workspace)


class AuthenticationFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="member1",
            password="strong-pass-123",
        )

    def test_registration_creates_user_and_logs_them_in(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "newmember",
                "password1": "complex-pass-123",
                "password2": "complex-pass-123",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(get_user_model().objects.filter(username="newmember").exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), get_user_model().objects.get(username="newmember").pk)

    def test_existing_user_can_log_in(self):
        response = self.client.post(
            reverse("login"),
            {"username": "member1", "password": "strong-pass-123"},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_logged_in_user_can_log_out(self):
        self.client.login(username="member1", password="strong-pass-123")

        response = self.client.post(reverse("logout"))

        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_anonymous_user_is_redirected_from_dashboard(self):
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_auth_pages_render_without_server_errors(self):
        login_response = self.client.get(reverse("login"))
        register_response = self.client.get(reverse("register"))

        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(register_response.status_code, 200)


class WorkspaceFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="creator",
            password="strong-pass-123",
        )
        self.member_user = get_user_model().objects.create_user(
            username="member",
            password="strong-pass-123",
        )
        self.outsider = get_user_model().objects.create_user(
            username="outsider",
            password="strong-pass-123",
        )

    def test_authenticated_user_can_create_workspace(self):
        self.client.login(username="creator", password="strong-pass-123")

        response = self.client.post(
            reverse("workspace-create"),
            {
                "name": "Alpha House",
                "workspace_type": WorkspaceType.HOUSEHOLD,
                "custom_workspace_type": "",
            },
        )

        workspace = Workspace.objects.get(name="Alpha House")
        self.assertRedirects(response, reverse("workspace-detail", kwargs={"pk": workspace.pk}))

    def test_creator_automatically_receives_owner_membership(self):
        self.client.login(username="creator", password="strong-pass-123")

        self.client.post(
            reverse("workspace-create"),
            {
                "name": "Owner Test",
                "workspace_type": WorkspaceType.BUSINESS,
                "custom_workspace_type": "",
            },
        )

        workspace = Workspace.objects.get(name="Owner Test")
        membership = Membership.objects.get(workspace=workspace, user=self.user)
        self.assertEqual(membership.role, MembershipRole.OWNER)

    def test_other_requires_custom_workspace_type(self):
        self.client.login(username="creator", password="strong-pass-123")

        response = self.client.post(
            reverse("workspace-create"),
            {
                "name": "Custom Group",
                "workspace_type": WorkspaceType.OTHER,
                "custom_workspace_type": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required when workspace type is Other.")
        self.assertFalse(Workspace.objects.filter(name="Custom Group").exists())

    def test_non_other_workspace_creation_works_without_custom_workspace_type(self):
        self.client.login(username="creator", password="strong-pass-123")

        self.client.post(
            reverse("workspace-create"),
            {
                "name": "School Team",
                "workspace_type": WorkspaceType.EDUCATION,
                "custom_workspace_type": "",
            },
        )

        workspace = Workspace.objects.get(name="School Team")
        self.assertEqual(workspace.custom_workspace_type, "")

    def test_workspace_list_contains_only_user_memberships(self):
        visible_workspace = Workspace.objects.create(
            name="Visible Workspace",
            workspace_type=WorkspaceType.HOUSEHOLD,
        )
        hidden_workspace = Workspace.objects.create(
            name="Hidden Workspace",
            workspace_type=WorkspaceType.BUSINESS,
        )
        Membership.objects.create(
            workspace=visible_workspace,
            user=self.user,
            role=MembershipRole.MEMBER,
        )
        Membership.objects.create(
            workspace=hidden_workspace,
            user=self.member_user,
            role=MembershipRole.MEMBER,
        )

        self.client.login(username="creator", password="strong-pass-123")
        response = self.client.get(reverse("workspace-list"))

        self.assertContains(response, "Visible Workspace")
        self.assertNotContains(response, "Hidden Workspace")

    def test_workspace_member_can_access_detail_page(self):
        workspace = Workspace.objects.create(
            name="Shared Workspace",
            workspace_type=WorkspaceType.COMMUNITY,
        )
        Membership.objects.create(
            workspace=workspace,
            user=self.member_user,
            role=MembershipRole.MEMBER,
        )

        self.client.login(username="member", password="strong-pass-123")
        response = self.client.get(reverse("workspace-detail", kwargs={"pk": workspace.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shared Workspace")

    def test_non_member_cannot_access_detail_page(self):
        workspace = Workspace.objects.create(
            name="Private Workspace",
            workspace_type=WorkspaceType.ORGANIZATION,
        )
        Membership.objects.create(
            workspace=workspace,
            user=self.user,
            role=MembershipRole.OWNER,
        )

        self.client.login(username="outsider", password="strong-pass-123")
        response = self.client.get(reverse("workspace-detail", kwargs={"pk": workspace.pk}))

        self.assertEqual(response.status_code, 404)

    def test_anonymous_users_cannot_access_protected_workspace_pages(self):
        workspace = Workspace.objects.create(
            name="Restricted Workspace",
            workspace_type=WorkspaceType.HOUSEHOLD,
        )
        Membership.objects.create(
            workspace=workspace,
            user=self.user,
            role=MembershipRole.OWNER,
        )

        list_response = self.client.get(reverse("workspace-list"))
        create_response = self.client.get(reverse("workspace-create"))
        detail_response = self.client.get(reverse("workspace-detail", kwargs={"pk": workspace.pk}))

        self.assertRedirects(list_response, f"{reverse('login')}?next={reverse('workspace-list')}")
        self.assertRedirects(create_response, f"{reverse('login')}?next={reverse('workspace-create')}")
        self.assertRedirects(
            detail_response,
            f"{reverse('login')}?next={reverse('workspace-detail', kwargs={'pk': workspace.pk})}",
        )


class WorkspaceMembershipManagementTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="owner_user",
            password="strong-pass-123",
        )
        self.manager = get_user_model().objects.create_user(
            username="manager_user",
            password="strong-pass-123",
        )
        self.member = get_user_model().objects.create_user(
            username="member_user",
            password="strong-pass-123",
        )
        self.new_user = get_user_model().objects.create_user(
            username="new_user",
            password="strong-pass-123",
        )
        self.outsider = get_user_model().objects.create_user(
            username="outsider_user",
            password="strong-pass-123",
        )
        self.workspace = Workspace.objects.create(
            name="Managed Workspace",
            workspace_type=WorkspaceType.BUSINESS,
        )
        self.owner_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=MembershipRole.OWNER,
        )
        self.manager_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.manager,
            role=MembershipRole.MANAGER,
        )
        self.member_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=MembershipRole.MEMBER,
        )

    def test_authorized_owner_can_view_workspace_memberships(self):
        self.client.login(username="owner_user", password="strong-pass-123")

        response = self.client.get(reverse("workspace-memberships", kwargs={"pk": self.workspace.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "owner_user")
        self.assertContains(response, "manager_user")
        self.assertContains(response, "member_user")

    def test_authorized_owner_can_add_existing_user(self):
        self.client.login(username="owner_user", password="strong-pass-123")

        response = self.client.post(
            reverse("workspace-membership-add", kwargs={"pk": self.workspace.pk}),
            {"username": "new_user"},
        )

        self.assertRedirects(response, reverse("workspace-memberships", kwargs={"pk": self.workspace.pk}))
        self.assertTrue(Membership.objects.filter(workspace=self.workspace, user=self.new_user).exists())

    def test_newly_added_user_receives_member_role(self):
        self.client.login(username="owner_user", password="strong-pass-123")

        self.client.post(
            reverse("workspace-membership-add", kwargs={"pk": self.workspace.pk}),
            {"username": "new_user"},
        )

        membership = Membership.objects.get(workspace=self.workspace, user=self.new_user)
        self.assertEqual(membership.role, MembershipRole.MEMBER)

    def test_duplicate_membership_cannot_be_created(self):
        self.client.login(username="owner_user", password="strong-pass-123")

        response = self.client.post(
            reverse("workspace-membership-add", kwargs={"pk": self.workspace.pk}),
            {"username": "member_user"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "That user is already a member of this workspace.")
        self.assertEqual(
            Membership.objects.filter(workspace=self.workspace, user=self.member).count(),
            1,
        )

    def test_owner_can_promote_member_to_manager(self):
        self.client.login(username="owner_user", password="strong-pass-123")

        response = self.client.post(
            reverse(
                "workspace-membership-role-update",
                kwargs={"pk": self.workspace.pk, "membership_id": self.member_membership.pk},
            ),
            {"role": MembershipRole.MANAGER},
        )

        self.assertRedirects(response, reverse("workspace-memberships", kwargs={"pk": self.workspace.pk}))
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, MembershipRole.MANAGER)

    def test_owner_can_demote_manager_to_member(self):
        self.client.login(username="owner_user", password="strong-pass-123")

        response = self.client.post(
            reverse(
                "workspace-membership-role-update",
                kwargs={"pk": self.workspace.pk, "membership_id": self.manager_membership.pk},
            ),
            {"role": MembershipRole.MEMBER},
        )

        self.assertRedirects(response, reverse("workspace-memberships", kwargs={"pk": self.workspace.pk}))
        self.manager_membership.refresh_from_db()
        self.assertEqual(self.manager_membership.role, MembershipRole.MEMBER)

    def test_owner_membership_cannot_be_modified_through_task_four(self):
        self.client.login(username="owner_user", password="strong-pass-123")

        response = self.client.post(
            reverse(
                "workspace-membership-role-update",
                kwargs={"pk": self.workspace.pk, "membership_id": self.owner_membership.pk},
            ),
            {"role": MembershipRole.MEMBER},
        )

        self.assertEqual(response.status_code, 403)
        self.owner_membership.refresh_from_db()
        self.assertEqual(self.owner_membership.role, MembershipRole.OWNER)

    def test_manager_can_view_memberships_and_add_existing_user_as_member(self):
        self.client.login(username="manager_user", password="strong-pass-123")

        list_response = self.client.get(reverse("workspace-memberships", kwargs={"pk": self.workspace.pk}))
        add_response = self.client.post(
            reverse("workspace-membership-add", kwargs={"pk": self.workspace.pk}),
            {"username": "new_user"},
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertRedirects(add_response, reverse("workspace-memberships", kwargs={"pk": self.workspace.pk}))
        membership = Membership.objects.get(workspace=self.workspace, user=self.new_user)
        self.assertEqual(membership.role, MembershipRole.MEMBER)

    def test_manager_cannot_change_membership_roles(self):
        self.client.login(username="manager_user", password="strong-pass-123")

        response = self.client.post(
            reverse(
                "workspace-membership-role-update",
                kwargs={"pk": self.workspace.pk, "membership_id": self.member_membership.pk},
            ),
            {"role": MembershipRole.MANAGER},
        )

        self.assertEqual(response.status_code, 403)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, MembershipRole.MEMBER)

    def test_member_cannot_perform_membership_management_actions(self):
        self.client.login(username="member_user", password="strong-pass-123")

        list_response = self.client.get(reverse("workspace-memberships", kwargs={"pk": self.workspace.pk}))
        add_response = self.client.post(
            reverse("workspace-membership-add", kwargs={"pk": self.workspace.pk}),
            {"username": "new_user"},
        )
        role_response = self.client.post(
            reverse(
                "workspace-membership-role-update",
                kwargs={"pk": self.workspace.pk, "membership_id": self.manager_membership.pk},
            ),
            {"role": MembershipRole.MEMBER},
        )

        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(add_response.status_code, 403)
        self.assertEqual(role_response.status_code, 403)
        self.assertFalse(Membership.objects.filter(workspace=self.workspace, user=self.new_user).exists())
        self.manager_membership.refresh_from_db()
        self.assertEqual(self.manager_membership.role, MembershipRole.MANAGER)

    def test_non_member_cannot_manage_another_workspace(self):
        self.client.login(username="outsider_user", password="strong-pass-123")

        list_response = self.client.get(reverse("workspace-memberships", kwargs={"pk": self.workspace.pk}))
        add_response = self.client.post(
            reverse("workspace-membership-add", kwargs={"pk": self.workspace.pk}),
            {"username": "new_user"},
        )

        self.assertEqual(list_response.status_code, 404)
        self.assertEqual(add_response.status_code, 404)
        self.assertFalse(Membership.objects.filter(workspace=self.workspace, user=self.new_user).exists())

    def test_anonymous_users_cannot_access_membership_management_pages(self):
        list_response = self.client.get(reverse("workspace-memberships", kwargs={"pk": self.workspace.pk}))
        add_response = self.client.get(reverse("workspace-membership-add", kwargs={"pk": self.workspace.pk}))
        role_response = self.client.get(
            reverse(
                "workspace-membership-role-update",
                kwargs={"pk": self.workspace.pk, "membership_id": self.member_membership.pk},
            )
        )

        self.assertRedirects(
            list_response,
            f"{reverse('login')}?next={reverse('workspace-memberships', kwargs={'pk': self.workspace.pk})}",
        )
        self.assertRedirects(
            add_response,
            f"{reverse('login')}?next={reverse('workspace-membership-add', kwargs={'pk': self.workspace.pk})}",
        )
        self.assertRedirects(
            role_response,
            f"{reverse('login')}?next={reverse('workspace-membership-role-update', kwargs={'pk': self.workspace.pk, 'membership_id': self.member_membership.pk})}",
        )


class WorkspaceGamificationSettingsTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="gamify_owner",
            password="strong-pass-123",
        )
        self.manager = get_user_model().objects.create_user(
            username="gamify_manager",
            password="strong-pass-123",
        )
        self.member = get_user_model().objects.create_user(
            username="gamify_member",
            password="strong-pass-123",
        )
        self.outsider = get_user_model().objects.create_user(
            username="gamify_outsider",
            password="strong-pass-123",
        )
        self.workspace = Workspace.objects.create(
            name="Gamified Workspace",
            workspace_type=WorkspaceType.COMMUNITY,
        )
        Membership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=MembershipRole.OWNER,
        )
        Membership.objects.create(
            workspace=self.workspace,
            user=self.manager,
            role=MembershipRole.MANAGER,
        )
        Membership.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=MembershipRole.MEMBER,
        )

    def test_default_workspace_settings_are_disabled(self):
        self.assertFalse(self.workspace.gamification_enabled)
        self.assertFalse(self.workspace.reward_system_enabled)

    def test_owner_can_enable_gamification_settings(self):
        self.client.login(username="gamify_owner", password="strong-pass-123")

        response = self.client.post(
            reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}),
            {"gamification_enabled": "on", "reward_system_enabled": ""},
        )

        self.assertRedirects(response, reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}))
        self.workspace.refresh_from_db()
        self.assertTrue(self.workspace.gamification_enabled)
        self.assertFalse(self.workspace.reward_system_enabled)

    def test_manager_can_access_and_update_gamification_settings(self):
        self.client.login(username="gamify_manager", password="strong-pass-123")

        response = self.client.post(
            reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}),
            {"gamification_enabled": "on", "reward_system_enabled": "on"},
        )

        self.assertRedirects(response, reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}))
        self.workspace.refresh_from_db()
        self.assertTrue(self.workspace.gamification_enabled)
        self.assertTrue(self.workspace.reward_system_enabled)

    def test_invalid_reward_and_gamification_combination_is_rejected(self):
        self.client.login(username="gamify_owner", password="strong-pass-123")

        response = self.client.post(
            reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}),
            {"gamification_enabled": "", "reward_system_enabled": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reward system cannot be enabled when gamification is disabled.")
        self.workspace.refresh_from_db()
        self.assertFalse(self.workspace.gamification_enabled)
        self.assertFalse(self.workspace.reward_system_enabled)

    def test_default_scoring_rules_are_created_when_gamification_is_enabled(self):
        self.client.login(username="gamify_owner", password="strong-pass-123")

        self.client.post(
            reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}),
            {"gamification_enabled": "on", "reward_system_enabled": ""},
        )

        self.assertEqual(self.workspace.scoring_rules.count(), 9)

    def test_default_rule_seeding_is_idempotent(self):
        created_once = seed_default_scoring_rules(workspace=self.workspace)
        created_twice = seed_default_scoring_rules(workspace=self.workspace)

        self.assertEqual(len(created_once), 9)
        self.assertEqual(len(created_twice), 0)
        self.assertEqual(self.workspace.scoring_rules.count(), 9)

    def test_scoring_rule_uniqueness_is_enforced(self):
        ScoringRule.objects.create(
            workspace=self.workspace,
            frequency=TaskFrequency.DAILY,
            difficulty=TaskDifficulty.EASY,
            completion_points=10,
            late_penalty=-5,
        )

        with self.assertRaises(IntegrityError):
            ScoringRule.objects.create(
                workspace=self.workspace,
                frequency=TaskFrequency.DAILY,
                difficulty=TaskDifficulty.EASY,
                completion_points=999,
                late_penalty=-999,
            )

    def test_member_cannot_access_or_update_gamification_settings(self):
        self.client.login(username="gamify_member", password="strong-pass-123")

        get_response = self.client.get(reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}))
        post_response = self.client.post(
            reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}),
            {"gamification_enabled": "on", "reward_system_enabled": ""},
        )

        self.assertEqual(get_response.status_code, 403)
        self.assertEqual(post_response.status_code, 403)

    def test_non_member_cannot_access_or_update_gamification_settings(self):
        self.client.login(username="gamify_outsider", password="strong-pass-123")

        get_response = self.client.get(reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}))
        post_response = self.client.post(
            reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}),
            {"gamification_enabled": "on", "reward_system_enabled": ""},
        )

        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(post_response.status_code, 404)

    def test_anonymous_user_is_redirected_from_gamification_settings(self):
        get_response = self.client.get(reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}))
        post_response = self.client.post(
            reverse("workspace-gamification-settings", kwargs={"pk": self.workspace.pk}),
            {"gamification_enabled": "on", "reward_system_enabled": ""},
        )

        self.assertRedirects(
            get_response,
            f"{reverse('login')}?next={reverse('workspace-gamification-settings', kwargs={'pk': self.workspace.pk})}",
        )
        self.assertRedirects(
            post_response,
            f"{reverse('login')}?next={reverse('workspace-gamification-settings', kwargs={'pk': self.workspace.pk})}",
        )


class TaskTemplateManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="template_owner", password="strong-pass-123")
        self.manager = user_model.objects.create_user(username="template_manager", password="strong-pass-123")
        self.member = user_model.objects.create_user(username="template_member", password="strong-pass-123")
        self.outsider = user_model.objects.create_user(username="template_outsider", password="strong-pass-123")
        self.workspace = Workspace.objects.create(
            name="Template Workspace",
            workspace_type=WorkspaceType.HOUSEHOLD,
        )
        self.other_workspace = Workspace.objects.create(
            name="Other Template Workspace",
            workspace_type=WorkspaceType.COMMUNITY,
        )
        Membership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=MembershipRole.OWNER,
        )
        Membership.objects.create(
            workspace=self.workspace,
            user=self.manager,
            role=MembershipRole.MANAGER,
        )
        Membership.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=MembershipRole.MEMBER,
        )
        Membership.objects.create(
            workspace=self.other_workspace,
            user=self.manager,
            role=MembershipRole.MANAGER,
        )
        self.task_template = TaskTemplate.objects.create(
            workspace=self.workspace,
            title="Clean kitchen",
            description="Wipe counters and mop the floor.",
            frequency=TaskFrequency.WEEKLY,
            difficulty=TaskDifficulty.MEDIUM,
            created_by=self.owner,
        )
        self.other_task_template = TaskTemplate.objects.create(
            workspace=self.other_workspace,
            title="Other workspace task",
            frequency=TaskFrequency.MONTHLY,
            difficulty=TaskDifficulty.HARD,
            created_by=self.manager,
        )

    def template_urls(self, workspace=None, task_template=None):
        workspace = workspace or self.workspace
        task_template = task_template or self.task_template
        return {
            "list": reverse("task-template-list", kwargs={"pk": workspace.pk}),
            "create": reverse("task-template-create", kwargs={"pk": workspace.pk}),
            "edit": reverse(
                "task-template-edit",
                kwargs={"pk": workspace.pk, "template_id": task_template.pk},
            ),
            "deactivate": reverse(
                "task-template-deactivate",
                kwargs={"pk": workspace.pk, "template_id": task_template.pk},
            ),
        }

    def template_data(self, **overrides):
        data = {
            "title": "Take out recycling",
            "description": "Put recycling bins at the curb.",
            "frequency": TaskFrequency.DAILY,
            "difficulty": TaskDifficulty.EASY,
            "is_active": "on",
        }
        data.update(overrides)
        return data

    def test_owner_can_list_create_edit_and_deactivate_a_task_template(self):
        self.client.login(username="template_owner", password="strong-pass-123")
        urls = self.template_urls()

        list_response = self.client.get(urls["list"])
        create_response = self.client.post(urls["create"], self.template_data())
        created_template = TaskTemplate.objects.get(title="Take out recycling")
        edit_response = self.client.post(
            self.template_urls(task_template=created_template)["edit"],
            self.template_data(
                title="Take out recycling and trash",
                description="",
                frequency=TaskFrequency.MONTHLY,
                difficulty=TaskDifficulty.HARD,
            ),
        )
        deactivate_response = self.client.post(
            self.template_urls(task_template=created_template)["deactivate"]
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, self.task_template.title)
        self.assertRedirects(create_response, urls["list"])
        self.assertEqual(created_template.workspace, self.workspace)
        self.assertEqual(created_template.created_by, self.owner)
        self.assertRedirects(edit_response, urls["list"])
        self.assertRedirects(deactivate_response, urls["list"])
        created_template.refresh_from_db()
        self.assertEqual(created_template.title, "Take out recycling and trash")
        self.assertEqual(created_template.description, "")
        self.assertEqual(created_template.frequency, TaskFrequency.MONTHLY)
        self.assertEqual(created_template.difficulty, TaskDifficulty.HARD)
        self.assertFalse(created_template.is_active)
        self.assertTrue(TaskTemplate.objects.filter(pk=created_template.pk).exists())
        list_after_deactivation = self.client.get(urls["list"])
        self.assertContains(list_after_deactivation, "Take out recycling and trash")
        self.assertContains(list_after_deactivation, "Inactive")

    def test_manager_can_create_and_manage_task_templates(self):
        self.client.login(username="template_manager", password="strong-pass-123")
        urls = self.template_urls()

        create_response = self.client.post(urls["create"], self.template_data())
        created_template = TaskTemplate.objects.get(title="Take out recycling")
        list_response = self.client.get(urls["list"])
        edit_response = self.client.post(
            self.template_urls(task_template=created_template)["edit"],
            self.template_data(title="Updated manager task"),
        )
        deactivate_response = self.client.post(
            self.template_urls(task_template=created_template)["deactivate"]
        )

        self.assertRedirects(create_response, urls["list"])
        self.assertEqual(created_template.created_by, self.manager)
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, self.task_template.title)
        self.assertRedirects(edit_response, urls["list"])
        self.assertRedirects(deactivate_response, urls["list"])
        created_template.refresh_from_db()
        self.assertEqual(created_template.title, "Updated manager task")
        self.assertFalse(created_template.is_active)

    def test_templates_are_listed_only_for_their_workspace(self):
        self.client.login(username="template_manager", password="strong-pass-123")

        response = self.client.get(self.template_urls()["list"])

        self.assertContains(response, self.task_template.title)
        self.assertNotContains(response, self.other_task_template.title)

    def test_invalid_frequency_and_difficulty_are_rejected(self):
        self.client.login(username="template_owner", password="strong-pass-123")

        response = self.client.post(
            self.template_urls()["create"],
            self.template_data(frequency="YEARLY", difficulty="IMPOSSIBLE"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "frequency", "Select a valid choice. YEARLY is not one of the available choices.")
        self.assertFormError(response.context["form"], "difficulty", "Select a valid choice. IMPOSSIBLE is not one of the available choices.")
        self.assertFalse(TaskTemplate.objects.filter(title="Take out recycling").exists())

    def test_member_cannot_manage_task_templates(self):
        self.client.login(username="template_member", password="strong-pass-123")
        urls = self.template_urls()

        responses = [
            self.client.get(urls["list"]),
            self.client.get(urls["create"]),
            self.client.post(urls["create"], self.template_data()),
            self.client.get(urls["edit"]),
            self.client.post(urls["edit"], self.template_data(title="Unauthorized update")),
            self.client.get(urls["deactivate"]),
            self.client.post(urls["deactivate"]),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 403)
        self.task_template.refresh_from_db()
        self.assertEqual(self.task_template.title, "Clean kitchen")
        self.assertTrue(self.task_template.is_active)
        self.assertFalse(TaskTemplate.objects.filter(title="Take out recycling").exists())

    def test_non_member_cannot_access_task_template_resources(self):
        self.client.login(username="template_outsider", password="strong-pass-123")
        urls = self.template_urls()

        responses = [
            self.client.get(urls["list"]),
            self.client.get(urls["create"]),
            self.client.post(urls["create"], self.template_data()),
            self.client.get(urls["edit"]),
            self.client.post(urls["edit"], self.template_data()),
            self.client.get(urls["deactivate"]),
            self.client.post(urls["deactivate"]),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 404)
        self.task_template.refresh_from_db()
        self.assertTrue(self.task_template.is_active)

    def test_cross_workspace_template_access_is_rejected(self):
        self.client.login(username="template_manager", password="strong-pass-123")
        cross_workspace_urls = self.template_urls(
            workspace=self.workspace,
            task_template=self.other_task_template,
        )

        edit_response = self.client.get(cross_workspace_urls["edit"])
        update_response = self.client.post(
            cross_workspace_urls["edit"],
            self.template_data(title="Cross-workspace update"),
        )
        deactivate_response = self.client.post(cross_workspace_urls["deactivate"])

        self.assertEqual(edit_response.status_code, 404)
        self.assertEqual(update_response.status_code, 404)
        self.assertEqual(deactivate_response.status_code, 404)
        self.other_task_template.refresh_from_db()
        self.assertEqual(self.other_task_template.title, "Other workspace task")
        self.assertTrue(self.other_task_template.is_active)

    def test_anonymous_users_are_redirected_from_task_template_management(self):
        urls = self.template_urls()

        for url in urls.values():
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('login')}?next={url}")

        response = self.client.post(urls["create"], self.template_data())
        self.assertRedirects(response, f"{reverse('login')}?next={urls['create']}")
        self.assertFalse(TaskTemplate.objects.filter(title="Take out recycling").exists())

    def test_workspace_detail_shows_management_link_only_to_owner_and_manager(self):
        detail_url = reverse("workspace-detail", kwargs={"pk": self.workspace.pk})

        self.client.login(username="template_owner", password="strong-pass-123")
        owner_response = self.client.get(detail_url)
        self.client.login(username="template_manager", password="strong-pass-123")
        manager_response = self.client.get(detail_url)
        self.client.login(username="template_member", password="strong-pass-123")
        member_response = self.client.get(detail_url)

        management_url = self.template_urls()["list"]
        self.assertContains(owner_response, management_url)
        self.assertContains(manager_response, management_url)
        self.assertNotContains(member_response, management_url)


class AvailableTaskInstanceManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="assignment_owner", password="strong-pass-123")
        self.manager = user_model.objects.create_user(username="assignment_manager", password="strong-pass-123")
        self.member = user_model.objects.create_user(username="assignment_member", password="strong-pass-123")
        self.outsider = user_model.objects.create_user(username="assignment_outsider", password="strong-pass-123")
        self.workspace = Workspace.objects.create(
            name="Assignment Workspace",
            workspace_type=WorkspaceType.HOUSEHOLD,
        )
        self.other_workspace = Workspace.objects.create(
            name="Other Assignment Workspace",
            workspace_type=WorkspaceType.COMMUNITY,
        )
        self.owner_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=MembershipRole.OWNER,
        )
        self.manager_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.manager,
            role=MembershipRole.MANAGER,
        )
        Membership.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=MembershipRole.MEMBER,
        )
        Membership.objects.create(
            workspace=self.other_workspace,
            user=self.manager,
            role=MembershipRole.MANAGER,
        )
        self.active_template = TaskTemplate.objects.create(
            workspace=self.workspace,
            title="Clean kitchen",
            description="Wipe counters and mop the floor.",
            frequency=TaskFrequency.WEEKLY,
            difficulty=TaskDifficulty.MEDIUM,
            created_by=self.owner,
        )
        self.inactive_template = TaskTemplate.objects.create(
            workspace=self.workspace,
            title="Archived task",
            frequency=TaskFrequency.DAILY,
            difficulty=TaskDifficulty.EASY,
            is_active=False,
            created_by=self.owner,
        )
        self.other_template = TaskTemplate.objects.create(
            workspace=self.other_workspace,
            title="Other workspace task",
            frequency=TaskFrequency.MONTHLY,
            difficulty=TaskDifficulty.HARD,
            created_by=self.manager,
        )

    def instance_urls(self, workspace=None):
        workspace = workspace or self.workspace
        return {
            "list": reverse("available-task-instance-list", kwargs={"pk": workspace.pk}),
            "create": reverse("available-task-instance-create", kwargs={"pk": workspace.pk}),
        }

    def generate_instance(self, username):
        self.client.login(username=username, password="strong-pass-123")
        response = self.client.post(
            self.instance_urls()["create"],
            {"task_template": self.active_template.pk},
        )
        return response, TaskAssignment.objects.get(task_template=self.active_template)

    def assert_available_instance_matches_template(self, task_assignment):
        self.assertEqual(task_assignment.workspace, self.workspace)
        self.assertEqual(task_assignment.task_template, self.active_template)
        self.assertEqual(task_assignment.status, TaskStatus.AVAILABLE)
        self.assertIsNone(task_assignment.assigned_to)
        self.assertIsNone(task_assignment.assigned_by)
        self.assertIsNone(task_assignment.assignment_type)
        self.assertIsNone(task_assignment.assigned_at)
        self.assertIsNone(task_assignment.due_at)
        self.assertEqual(task_assignment.title_snapshot, self.active_template.title)
        self.assertEqual(task_assignment.description_snapshot, self.active_template.description)
        self.assertEqual(task_assignment.frequency_snapshot, self.active_template.frequency)
        self.assertEqual(task_assignment.difficulty_snapshot, self.active_template.difficulty)

    def test_owner_can_generate_an_available_task_instance(self):
        response, task_assignment = self.generate_instance("assignment_owner")

        self.assertRedirects(response, self.instance_urls()["list"])
        self.assert_available_instance_matches_template(task_assignment)

    def test_manager_can_generate_an_available_task_instance(self):
        response, task_assignment = self.generate_instance("assignment_manager")

        self.assertRedirects(response, self.instance_urls()["list"])
        self.assert_available_instance_matches_template(task_assignment)

    def test_multiple_available_instances_can_be_generated_from_one_template(self):
        self.client.login(username="assignment_manager", password="strong-pass-123")

        first_response = self.client.post(
            self.instance_urls()["create"],
            {"task_template": self.active_template.pk},
        )
        second_response = self.client.post(
            self.instance_urls()["create"],
            {"task_template": self.active_template.pk},
        )

        self.assertRedirects(first_response, self.instance_urls()["list"])
        self.assertRedirects(second_response, self.instance_urls()["list"])
        self.assertEqual(
            TaskAssignment.objects.filter(
                workspace=self.workspace,
                task_template=self.active_template,
                status=TaskStatus.AVAILABLE,
            ).count(),
            2,
        )

    def test_only_active_templates_from_current_workspace_appear_in_create_form(self):
        self.client.login(username="assignment_manager", password="strong-pass-123")

        response = self.client.get(self.instance_urls()["create"])
        queryset = response.context["form"].fields["task_template"].queryset

        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(queryset, [self.active_template])
        self.assertContains(response, self.active_template.title)
        self.assertNotContains(response, self.inactive_template.title)
        self.assertNotContains(response, self.other_template.title)

    def test_inactive_template_is_rejected(self):
        self.client.login(username="assignment_manager", password="strong-pass-123")

        response = self.client.post(
            self.instance_urls()["create"],
            {"task_template": self.inactive_template.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "task_template",
            f"Select a valid choice. That choice is not one of the available choices.",
        )
        self.assertFalse(TaskAssignment.objects.filter(task_template=self.inactive_template).exists())

    def test_member_cannot_access_or_create_available_task_instances(self):
        self.client.login(username="assignment_member", password="strong-pass-123")
        urls = self.instance_urls()

        list_response = self.client.get(urls["list"])
        create_get_response = self.client.get(urls["create"])
        create_post_response = self.client.post(urls["create"], {"task_template": self.active_template.pk})

        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(create_get_response.status_code, 403)
        self.assertEqual(create_post_response.status_code, 403)
        self.assertFalse(TaskAssignment.objects.filter(workspace=self.workspace).exists())

    def test_non_member_cannot_access_workspace_task_instance_resources(self):
        self.client.login(username="assignment_outsider", password="strong-pass-123")
        urls = self.instance_urls()

        list_response = self.client.get(urls["list"])
        create_get_response = self.client.get(urls["create"])
        create_post_response = self.client.post(urls["create"], {"task_template": self.active_template.pk})

        self.assertEqual(list_response.status_code, 404)
        self.assertEqual(create_get_response.status_code, 404)
        self.assertEqual(create_post_response.status_code, 404)
        self.assertFalse(TaskAssignment.objects.filter(workspace=self.workspace).exists())

    def test_anonymous_users_are_redirected_from_task_instance_management(self):
        urls = self.instance_urls()

        for url in urls.values():
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('login')}?next={url}")

        post_response = self.client.post(urls["create"], {"task_template": self.active_template.pk})
        self.assertRedirects(post_response, f"{reverse('login')}?next={urls['create']}")

    def test_cross_workspace_template_post_is_rejected(self):
        self.client.login(username="assignment_manager", password="strong-pass-123")

        response = self.client.post(
            self.instance_urls()["create"],
            {"task_template": self.other_template.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "task_template",
            "Select a valid choice. That choice is not one of the available choices.",
        )
        self.assertFalse(TaskAssignment.objects.filter(workspace=self.workspace).exists())
        self.assertFalse(TaskAssignment.objects.filter(workspace=self.other_workspace).exists())

    def test_service_rejects_cross_workspace_template(self):
        with self.assertRaises(PermissionDenied):
            create_available_task_assignment(
                actor_membership=self.manager_membership,
                task_template=self.other_template,
            )

        self.assertFalse(TaskAssignment.objects.exists())

    def test_available_task_instance_list_is_workspace_scoped(self):
        local_instance = create_available_task_assignment(
            actor_membership=self.manager_membership,
            task_template=self.active_template,
        )
        other_membership = Membership.objects.get(workspace=self.other_workspace, user=self.manager)
        other_instance = create_available_task_assignment(
            actor_membership=other_membership,
            task_template=self.other_template,
        )
        self.client.login(username="assignment_manager", password="strong-pass-123")

        response = self.client.get(self.instance_urls()["list"])

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, local_instance.title_snapshot)
        self.assertNotContains(response, other_instance.title_snapshot)

    def test_available_task_instance_list_excludes_non_available_instances(self):
        available_instance = create_available_task_assignment(
            actor_membership=self.manager_membership,
            task_template=self.active_template,
        )
        active_instance = TaskAssignment.objects.create(
            workspace=self.workspace,
            task_template=self.active_template,
            status=TaskStatus.ACTIVE,
            title_snapshot="Already active task",
            description_snapshot=self.active_template.description,
            frequency_snapshot=self.active_template.frequency,
            difficulty_snapshot=self.active_template.difficulty,
        )
        self.client.login(username="assignment_manager", password="strong-pass-123")

        response = self.client.get(self.instance_urls()["list"])

        self.assertContains(response, available_instance.title_snapshot)
        self.assertNotContains(response, active_instance.title_snapshot)

    def test_workspace_detail_shows_available_task_link_only_to_owner_and_manager(self):
        detail_url = reverse("workspace-detail", kwargs={"pk": self.workspace.pk})
        management_url = self.instance_urls()["list"]

        self.client.login(username="assignment_owner", password="strong-pass-123")
        owner_response = self.client.get(detail_url)
        self.client.login(username="assignment_manager", password="strong-pass-123")
        manager_response = self.client.get(detail_url)
        self.client.login(username="assignment_member", password="strong-pass-123")
        member_response = self.client.get(detail_url)

        self.assertContains(owner_response, management_url)
        self.assertContains(manager_response, management_url)
        self.assertNotContains(member_response, management_url)


class MemberSelfSelectionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="selection_owner", password="strong-pass-123")
        self.manager = user_model.objects.create_user(username="selection_manager", password="strong-pass-123")
        self.member = user_model.objects.create_user(username="selection_member", password="strong-pass-123")
        self.second_member = user_model.objects.create_user(
            username="selection_second_member",
            password="strong-pass-123",
        )
        self.outsider = user_model.objects.create_user(username="selection_outsider", password="strong-pass-123")
        self.workspace = Workspace.objects.create(
            name="Selection Workspace",
            workspace_type=WorkspaceType.HOUSEHOLD,
        )
        self.other_workspace = Workspace.objects.create(
            name="Other Selection Workspace",
            workspace_type=WorkspaceType.COMMUNITY,
        )
        self.owner_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=MembershipRole.OWNER,
        )
        self.manager_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.manager,
            role=MembershipRole.MANAGER,
        )
        self.member_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=MembershipRole.MEMBER,
        )
        self.second_member_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.second_member,
            role=MembershipRole.MEMBER,
        )
        self.other_manager_membership = Membership.objects.create(
            workspace=self.other_workspace,
            user=self.manager,
            role=MembershipRole.MANAGER,
        )
        self.task_template = TaskTemplate.objects.create(
            workspace=self.workspace,
            title="Clean kitchen",
            description="Wipe counters and mop the floor.",
            frequency=TaskFrequency.WEEKLY,
            difficulty=TaskDifficulty.MEDIUM,
            created_by=self.owner,
        )
        self.other_task_template = TaskTemplate.objects.create(
            workspace=self.other_workspace,
            title="Other workspace task",
            frequency=TaskFrequency.MONTHLY,
            difficulty=TaskDifficulty.HARD,
            created_by=self.manager,
        )

    def create_available_assignment(self, *, title=None):
        task_template = self.task_template
        if title:
            task_template = TaskTemplate.objects.create(
                workspace=self.workspace,
                title=title,
                description="Task description",
                frequency=TaskFrequency.DAILY,
                difficulty=TaskDifficulty.EASY,
                created_by=self.owner,
            )
        return create_available_task_assignment(
            actor_membership=self.manager_membership,
            task_template=task_template,
        )

    def member_urls(self, task_assignment=None, workspace=None):
        workspace = workspace or self.workspace
        urls = {
            "list": reverse("member-available-task-list", kwargs={"pk": workspace.pk}),
        }
        if task_assignment:
            urls["select"] = reverse(
                "self-select-available-task",
                kwargs={"pk": workspace.pk, "task_assignment_id": task_assignment.pk},
            )
        return urls

    def test_member_can_view_available_tasks_in_their_workspace(self):
        available_assignment = self.create_available_assignment()
        TaskAssignment.objects.create(
            workspace=self.workspace,
            task_template=self.task_template,
            status=TaskStatus.ACTIVE,
            title_snapshot="Already active task",
            description_snapshot="",
            frequency_snapshot=TaskFrequency.DAILY,
            difficulty_snapshot=TaskDifficulty.EASY,
        )
        self.client.login(username="selection_member", password="strong-pass-123")

        response = self.client.get(self.member_urls()["list"])

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, available_assignment.title_snapshot)
        self.assertNotContains(response, "Already active task")

    def test_owner_can_self_select_an_available_task(self):
        task_assignment = self.create_available_assignment()
        self.client.login(username="selection_owner", password="strong-pass-123")

        list_response = self.client.get(self.member_urls()["list"])
        response = self.client.post(self.member_urls(task_assignment)["select"])

        self.assertEqual(list_response.status_code, 200)
        self.assertRedirects(response, self.member_urls()["list"])
        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.assigned_to, self.owner)
        self.assertEqual(task_assignment.status, TaskStatus.ACTIVE)

    def test_manager_can_self_select_an_available_task(self):
        task_assignment = self.create_available_assignment()
        self.client.login(username="selection_manager", password="strong-pass-123")

        list_response = self.client.get(self.member_urls()["list"])
        response = self.client.post(self.member_urls(task_assignment)["select"])

        self.assertEqual(list_response.status_code, 200)
        self.assertRedirects(response, self.member_urls()["list"])
        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.assigned_to, self.manager)
        self.assertEqual(task_assignment.status, TaskStatus.ACTIVE)

    def test_member_self_selection_updates_only_task_eight_fields_and_creates_history(self):
        task_assignment = self.create_available_assignment()
        original_values = {
            "title": task_assignment.title_snapshot,
            "description": task_assignment.description_snapshot,
            "frequency": task_assignment.frequency_snapshot,
            "difficulty": task_assignment.difficulty_snapshot,
            "template_title": self.task_template.title,
            "template_description": self.task_template.description,
            "template_frequency": self.task_template.frequency,
            "template_difficulty": self.task_template.difficulty,
        }
        self.client.login(username="selection_member", password="strong-pass-123")

        response = self.client.post(self.member_urls(task_assignment)["select"])

        self.assertRedirects(response, self.member_urls()["list"])
        task_assignment.refresh_from_db()
        self.task_template.refresh_from_db()
        self.assertEqual(task_assignment.status, TaskStatus.ACTIVE)
        self.assertEqual(task_assignment.assigned_to, self.member)
        self.assertEqual(task_assignment.assignment_type, AssignmentType.SELF_SELECTION)
        self.assertIsNone(task_assignment.assigned_by)
        self.assertIsNotNone(task_assignment.assigned_at)
        self.assertIsNotNone(task_assignment.due_at)
        self.assertIsNone(task_assignment.completion_points_snapshot)
        self.assertIsNone(task_assignment.late_penalty_snapshot)
        self.assertEqual(task_assignment.title_snapshot, original_values["title"])
        self.assertEqual(task_assignment.description_snapshot, original_values["description"])
        self.assertEqual(task_assignment.frequency_snapshot, original_values["frequency"])
        self.assertEqual(task_assignment.difficulty_snapshot, original_values["difficulty"])
        self.assertEqual(self.task_template.title, original_values["template_title"])
        self.assertEqual(self.task_template.description, original_values["template_description"])
        self.assertEqual(self.task_template.frequency, original_values["template_frequency"])
        self.assertEqual(self.task_template.difficulty, original_values["template_difficulty"])
        event = TaskEventHistory.objects.get(task_assignment=task_assignment)
        self.assertEqual(event.event_type, TaskEventType.MEMBER_SELECTED_TASK)
        self.assertEqual(event.workspace, self.workspace)
        self.assertEqual(event.actor, self.member)
        self.assertEqual(event.affected_member, self.member)
        self.assertIsNone(event.score_change)

    def test_member_available_list_is_workspace_scoped(self):
        local_assignment = self.create_available_assignment()
        other_assignment = create_available_task_assignment(
            actor_membership=self.other_manager_membership,
            task_template=self.other_task_template,
        )
        self.client.login(username="selection_manager", password="strong-pass-123")

        response = self.client.get(self.member_urls()["list"])

        self.assertContains(response, local_assignment.title_snapshot)
        self.assertNotContains(response, other_assignment.title_snapshot)

    def test_non_member_cannot_access_member_task_resources(self):
        task_assignment = self.create_available_assignment()
        self.client.login(username="selection_outsider", password="strong-pass-123")

        list_response = self.client.get(self.member_urls()["list"])
        select_response = self.client.post(self.member_urls(task_assignment)["select"])

        self.assertEqual(list_response.status_code, 404)
        self.assertEqual(select_response.status_code, 404)
        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.status, TaskStatus.AVAILABLE)

    def test_anonymous_users_are_redirected_from_member_task_resources(self):
        task_assignment = self.create_available_assignment()
        urls = self.member_urls(task_assignment)

        list_response = self.client.get(urls["list"])
        select_response = self.client.post(urls["select"])

        self.assertRedirects(list_response, f"{reverse('login')}?next={urls['list']}")
        self.assertRedirects(select_response, f"{reverse('login')}?next={urls['select']}")

    def test_cross_workspace_forged_task_id_is_rejected(self):
        other_assignment = create_available_task_assignment(
            actor_membership=self.other_manager_membership,
            task_template=self.other_task_template,
        )
        self.client.login(username="selection_member", password="strong-pass-123")

        response = self.client.post(self.member_urls(other_assignment)["select"])

        self.assertEqual(response.status_code, 404)
        other_assignment.refresh_from_db()
        self.assertEqual(other_assignment.status, TaskStatus.AVAILABLE)
        self.assertEqual(TaskEventHistory.objects.count(), 0)

    def test_service_rejects_cross_workspace_selection(self):
        other_assignment = create_available_task_assignment(
            actor_membership=self.other_manager_membership,
            task_template=self.other_task_template,
        )

        with self.assertRaises(PermissionDenied):
            self_select_available_task(
                actor_membership=self.member_membership,
                task_assignment=other_assignment,
            )

        other_assignment.refresh_from_db()
        self.assertEqual(other_assignment.status, TaskStatus.AVAILABLE)
        self.assertFalse(TaskEventHistory.objects.exists())

    def test_service_rejects_a_user_without_a_workspace_membership(self):
        task_assignment = self.create_available_assignment()
        unpersisted_membership = Membership(
            workspace=self.workspace,
            user=self.outsider,
            role=MembershipRole.MEMBER,
        )

        with self.assertRaises(PermissionDenied):
            self_select_available_task(
                actor_membership=unpersisted_membership,
                task_assignment=task_assignment,
            )

        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.status, TaskStatus.AVAILABLE)
        self.assertFalse(TaskEventHistory.objects.exists())

    def test_repeated_selection_by_same_member_is_rejected_without_extra_history(self):
        task_assignment = self.create_available_assignment()
        self.client.login(username="selection_member", password="strong-pass-123")
        select_url = self.member_urls(task_assignment)["select"]

        first_response = self.client.post(select_url)
        second_response = self.client.post(select_url)

        self.assertRedirects(first_response, self.member_urls()["list"])
        self.assertEqual(second_response.status_code, 409)
        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.assigned_to, self.member)
        self.assertEqual(task_assignment.status, TaskStatus.ACTIVE)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=task_assignment).count(), 1)

    def test_second_member_cannot_take_an_already_selected_task(self):
        task_assignment = self.create_available_assignment()
        self.client.login(username="selection_member", password="strong-pass-123")
        self.client.post(self.member_urls(task_assignment)["select"])
        self.client.login(username="selection_second_member", password="strong-pass-123")

        response = self.client.post(self.member_urls(task_assignment)["select"])

        self.assertEqual(response.status_code, 409)
        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.assigned_to, self.member)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=task_assignment).count(), 1)

    def test_service_conditional_claim_rejects_stale_assignment_without_history(self):
        task_assignment = self.create_available_assignment()
        self_select_available_task(
            actor_membership=self.member_membership,
            task_assignment=task_assignment,
        )

        with self.assertRaises(ValidationError):
            self_select_available_task(
                actor_membership=self.second_member_membership,
                task_assignment=task_assignment,
            )

        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.assigned_to, self.member)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=task_assignment).count(), 1)

    def test_workspace_detail_links_all_members_to_available_tasks(self):
        detail_url = reverse("workspace-detail", kwargs={"pk": self.workspace.pk})
        member_task_url = self.member_urls()["list"]

        for username in ("selection_owner", "selection_manager", "selection_member"):
            self.client.login(username=username, password="strong-pass-123")
            response = self.client.get(detail_url)
            self.assertContains(response, member_task_url)


class AssignmentDeadlineTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="deadline_owner", password="strong-pass-123")
        self.manager = user_model.objects.create_user(username="deadline_manager", password="strong-pass-123")
        self.member = user_model.objects.create_user(username="deadline_member", password="strong-pass-123")
        self.second_member = user_model.objects.create_user(
            username="deadline_second_member",
            password="strong-pass-123",
        )
        self.workspace = Workspace.objects.create(
            name="Deadline Workspace",
            workspace_type=WorkspaceType.HOUSEHOLD,
        )
        self.owner_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=MembershipRole.OWNER,
        )
        self.manager_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.manager,
            role=MembershipRole.MANAGER,
        )
        self.member_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=MembershipRole.MEMBER,
        )
        self.second_member_membership = Membership.objects.create(
            workspace=self.workspace,
            user=self.second_member,
            role=MembershipRole.MEMBER,
        )

    def create_available_assignment(self, frequency):
        task_template = TaskTemplate.objects.create(
            workspace=self.workspace,
            title=f"{frequency} task",
            description="Deadline test task.",
            frequency=frequency,
            difficulty=TaskDifficulty.MEDIUM,
            created_by=self.owner,
        )
        return create_available_task_assignment(
            actor_membership=self.manager_membership,
            task_template=task_template,
        )

    def test_daily_deadline_is_assignment_time_plus_one_day_near_midnight(self):
        assigned_at = datetime(2026, 1, 31, 23, 59, tzinfo=datetime_timezone.utc)

        due_at = calculate_due_at(
            assigned_at=assigned_at,
            frequency_snapshot=TaskFrequency.DAILY,
        )

        self.assertEqual(due_at, datetime(2026, 2, 1, 23, 59, tzinfo=datetime_timezone.utc))
        self.assertTrue(timezone.is_aware(due_at))

    def test_weekly_deadline_is_assignment_time_plus_seven_days_across_week_boundary(self):
        assigned_at = datetime(2026, 12, 28, 8, 30, tzinfo=datetime_timezone.utc)

        due_at = calculate_due_at(
            assigned_at=assigned_at,
            frequency_snapshot=TaskFrequency.WEEKLY,
        )

        self.assertEqual(due_at, datetime(2027, 1, 4, 8, 30, tzinfo=datetime_timezone.utc))
        self.assertTrue(timezone.is_aware(due_at))

    def test_monthly_deadline_is_assignment_time_plus_thirty_days_across_calendar_boundaries(self):
        cases = [
            (
                datetime(2025, 1, 31, 9, 0, tzinfo=datetime_timezone.utc),
                datetime(2025, 3, 2, 9, 0, tzinfo=datetime_timezone.utc),
            ),
            (
                datetime(2024, 1, 31, 9, 0, tzinfo=datetime_timezone.utc),
                datetime(2024, 3, 1, 9, 0, tzinfo=datetime_timezone.utc),
            ),
            (
                datetime(2025, 2, 1, 9, 0, tzinfo=datetime_timezone.utc),
                datetime(2025, 3, 3, 9, 0, tzinfo=datetime_timezone.utc),
            ),
            (
                datetime(2024, 2, 1, 9, 0, tzinfo=datetime_timezone.utc),
                datetime(2024, 3, 2, 9, 0, tzinfo=datetime_timezone.utc),
            ),
        ]

        for assigned_at, expected_due_at in cases:
            with self.subTest(assigned_at=assigned_at):
                self.assertEqual(
                    calculate_due_at(
                        assigned_at=assigned_at,
                        frequency_snapshot=TaskFrequency.MONTHLY,
                    ),
                    expected_due_at,
                )

    def test_deadline_helper_rejects_naive_and_unsupported_frequency_values(self):
        with self.assertRaises(ValidationError):
            calculate_due_at(
                assigned_at=datetime(2026, 1, 1, 12, 0),
                frequency_snapshot=TaskFrequency.DAILY,
            )

        with self.assertRaises(ValidationError):
            calculate_due_at(
                assigned_at=datetime(2026, 1, 1, 12, 0, tzinfo=datetime_timezone.utc),
                frequency_snapshot="YEARLY",
            )

    def test_self_selection_uses_one_authoritative_timestamp_for_assignment_and_deadline(self):
        task_assignment = self.create_available_assignment(TaskFrequency.DAILY)
        assigned_at = datetime(2026, 6, 1, 12, 0, tzinfo=datetime_timezone.utc)

        with patch("tasks.services.timezone.now", return_value=assigned_at):
            self_select_available_task(
                actor_membership=self.member_membership,
                task_assignment=task_assignment,
            )

        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.assigned_at, assigned_at)
        self.assertEqual(task_assignment.due_at, assigned_at + timedelta(days=1))
        self.assertTrue(timezone.is_aware(task_assignment.assigned_at))
        self.assertTrue(timezone.is_aware(task_assignment.due_at))
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=task_assignment).count(), 1)

    def test_self_selection_uses_frequency_snapshot_not_current_template_frequency(self):
        task_assignment = self.create_available_assignment(TaskFrequency.WEEKLY)
        task_assignment.task_template.frequency = TaskFrequency.MONTHLY
        task_assignment.task_template.save(update_fields=["frequency", "updated_at"])
        assigned_at = datetime(2026, 6, 1, 12, 0, tzinfo=datetime_timezone.utc)

        with patch("tasks.services.timezone.now", return_value=assigned_at):
            self_select_available_task(
                actor_membership=self.member_membership,
                task_assignment=task_assignment,
            )

        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.frequency_snapshot, TaskFrequency.WEEKLY)
        self.assertEqual(task_assignment.due_at, assigned_at + timedelta(days=7))

    def test_owner_manager_and_member_self_selection_receive_deadlines(self):
        memberships = [
            self.owner_membership,
            self.manager_membership,
            self.member_membership,
        ]
        assigned_at = datetime(2026, 6, 1, 12, 0, tzinfo=datetime_timezone.utc)

        for membership in memberships:
            task_assignment = self.create_available_assignment(TaskFrequency.MONTHLY)
            with self.subTest(role=membership.role):
                with patch("tasks.services.timezone.now", return_value=assigned_at):
                    self_select_available_task(
                        actor_membership=membership,
                        task_assignment=task_assignment,
                    )

                task_assignment.refresh_from_db()
                self.assertEqual(task_assignment.assigned_to, membership.user)
                self.assertEqual(task_assignment.assigned_at, assigned_at)
                self.assertEqual(task_assignment.due_at, assigned_at + timedelta(days=30))

    def test_invalid_frequency_fails_without_assignment_or_history(self):
        task_assignment = self.create_available_assignment(TaskFrequency.DAILY)
        task_assignment.frequency_snapshot = "YEARLY"
        task_assignment.save(update_fields=["frequency_snapshot", "updated_at"])

        with self.assertRaises(ValidationError):
            self_select_available_task(
                actor_membership=self.member_membership,
                task_assignment=task_assignment,
            )

        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.status, TaskStatus.AVAILABLE)
        self.assertIsNone(task_assignment.assigned_to)
        self.assertIsNone(task_assignment.assigned_at)
        self.assertIsNone(task_assignment.due_at)
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=task_assignment).exists())

    def test_repeated_and_second_member_claims_do_not_change_existing_timestamps(self):
        task_assignment = self.create_available_assignment(TaskFrequency.DAILY)
        first_assigned_at = datetime(2026, 6, 1, 12, 0, tzinfo=datetime_timezone.utc)
        second_attempt_at = datetime(2026, 6, 2, 12, 0, tzinfo=datetime_timezone.utc)

        with patch("tasks.services.timezone.now", return_value=first_assigned_at):
            self_select_available_task(
                actor_membership=self.member_membership,
                task_assignment=task_assignment,
            )

        for membership in (self.member_membership, self.second_member_membership):
            with self.subTest(user=membership.user.username):
                with patch("tasks.services.timezone.now", return_value=second_attempt_at):
                    with self.assertRaises(ValidationError):
                        self_select_available_task(
                            actor_membership=membership,
                            task_assignment=task_assignment,
                        )

        task_assignment.refresh_from_db()
        self.assertEqual(task_assignment.assigned_to, self.member)
        self.assertEqual(task_assignment.assigned_at, first_assigned_at)
        self.assertEqual(task_assignment.due_at, first_assigned_at + timedelta(days=1))
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=task_assignment).count(), 1)

    def test_existing_active_assignment_with_null_timestamps_is_not_backfilled(self):
        legacy_task_assignment = TaskAssignment.objects.create(
            workspace=self.workspace,
            task_template=TaskTemplate.objects.create(
                workspace=self.workspace,
                title="Legacy task",
                frequency=TaskFrequency.DAILY,
                difficulty=TaskDifficulty.EASY,
                created_by=self.owner,
            ),
            assigned_to=self.member,
            assignment_type=AssignmentType.SELF_SELECTION,
            status=TaskStatus.ACTIVE,
            title_snapshot="Legacy task",
            description_snapshot="",
            frequency_snapshot=TaskFrequency.DAILY,
            difficulty_snapshot=TaskDifficulty.EASY,
        )
        task_assignment = self.create_available_assignment(TaskFrequency.DAILY)

        self_select_available_task(
            actor_membership=self.second_member_membership,
            task_assignment=task_assignment,
        )

        legacy_task_assignment.refresh_from_db()
        self.assertIsNone(legacy_task_assignment.assigned_at)
        self.assertIsNone(legacy_task_assignment.due_at)


class ManagerTaskAssignmentTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="assign_owner", password="strong-pass-123")
        self.manager = user_model.objects.create_user(username="assign_manager", password="strong-pass-123")
        self.member = user_model.objects.create_user(username="assign_member", password="strong-pass-123")
        self.second_manager = user_model.objects.create_user(
            username="assign_second_manager", password="strong-pass-123"
        )
        self.outsider = user_model.objects.create_user(username="assign_outsider", password="strong-pass-123")
        self.workspace = Workspace.objects.create(
            name="Assignment Workspace",
            workspace_type=WorkspaceType.BUSINESS,
        )
        self.other_workspace = Workspace.objects.create(
            name="Other Assignment Workspace",
            workspace_type=WorkspaceType.BUSINESS,
        )
        self.owner_membership = Membership.objects.create(
            workspace=self.workspace, user=self.owner, role=MembershipRole.OWNER
        )
        self.manager_membership = Membership.objects.create(
            workspace=self.workspace, user=self.manager, role=MembershipRole.MANAGER
        )
        self.member_membership = Membership.objects.create(
            workspace=self.workspace, user=self.member, role=MembershipRole.MEMBER
        )
        self.second_manager_membership = Membership.objects.create(
            workspace=self.workspace, user=self.second_manager, role=MembershipRole.MANAGER
        )
        Membership.objects.create(
            workspace=self.other_workspace, user=self.outsider, role=MembershipRole.MANAGER
        )

    def create_available_assignment(self, *, workspace=None):
        workspace = workspace or self.workspace
        template = TaskTemplate.objects.create(
            workspace=workspace,
            title="Manager-assigned task",
            description="Pending task description.",
            frequency=TaskFrequency.WEEKLY,
            difficulty=TaskDifficulty.HARD,
            created_by=self.owner if workspace == self.workspace else self.outsider,
        )
        actor = self.manager_membership if workspace == self.workspace else Membership.objects.get(
            workspace=workspace, user=self.outsider
        )
        return create_available_task_assignment(actor_membership=actor, task_template=template)

    def test_manager_assignment_sets_pending_fields_and_history(self):
        assignment = self.create_available_assignment()
        assigned_at = datetime(2026, 7, 1, 10, 0, tzinfo=datetime_timezone.utc)

        with patch("tasks.services.timezone.now", return_value=assigned_at):
            result = assign_task_to_member(
                actor_membership=self.manager_membership,
                task_assignment=assignment,
                target_membership=self.member_membership,
            )

        result.refresh_from_db()
        self.assertEqual(result.status, TaskStatus.PENDING_ACCEPTANCE)
        self.assertEqual(result.assigned_to, self.member)
        self.assertEqual(result.assigned_by, self.manager)
        self.assertEqual(result.assignment_type, AssignmentType.MANAGER_ASSIGNMENT)
        self.assertEqual(result.assigned_at, assigned_at)
        self.assertEqual(result.due_at, assigned_at + timedelta(days=7))
        event = TaskEventHistory.objects.get(task_assignment=result)
        self.assertEqual(event.event_type, TaskEventType.MANAGER_ASSIGNED_TASK)
        self.assertEqual(event.actor, self.manager)
        self.assertEqual(event.affected_member, self.member)
        self.assertEqual(event.workspace, self.workspace)

    def test_owner_can_assign_and_manager_can_assign_to_all_workspace_roles_including_self(self):
        targets = [self.owner_membership, self.manager_membership, self.member_membership]
        for actor_membership in (self.owner_membership, self.manager_membership):
            for target_membership in targets:
                with self.subTest(actor=actor_membership.role, target=target_membership.role):
                    assignment = self.create_available_assignment()
                    assign_task_to_member(
                        actor_membership=actor_membership,
                        task_assignment=assignment,
                        target_membership=target_membership,
                    )
                    assignment.refresh_from_db()
                    self.assertEqual(assignment.status, TaskStatus.PENDING_ACCEPTANCE)
                    self.assertEqual(assignment.assigned_to, target_membership.user)

    def test_member_cannot_use_manager_assignment_service_or_page(self):
        assignment = self.create_available_assignment()
        with self.assertRaises(PermissionDenied):
            assign_task_to_member(
                actor_membership=self.member_membership,
                task_assignment=assignment,
                target_membership=self.member_membership,
            )

        self.client.force_login(self.member)
        response = self.client.get(reverse("manager-task-assignment", args=[self.workspace.pk]))
        self.assertEqual(response.status_code, 403)

    def test_cross_workspace_assignment_and_target_are_rejected(self):
        assignment = self.create_available_assignment()
        other_assignment = self.create_available_assignment(workspace=self.other_workspace)
        other_target = Membership.objects.get(workspace=self.other_workspace, user=self.outsider)

        with self.assertRaises(PermissionDenied):
            assign_task_to_member(
                actor_membership=self.manager_membership,
                task_assignment=other_assignment,
                target_membership=self.member_membership,
            )
        with self.assertRaises(PermissionDenied):
            assign_task_to_member(
                actor_membership=self.manager_membership,
                task_assignment=assignment,
                target_membership=other_target,
            )
        self.assertFalse(TaskEventHistory.objects.filter(event_type=TaskEventType.MANAGER_ASSIGNED_TASK).exists())

    def test_wrong_status_repeated_and_stale_assignments_do_not_change_task_or_history(self):
        assignment = self.create_available_assignment()
        assignment.status = TaskStatus.ACTIVE
        assignment.assigned_to = self.member
        assignment.save(update_fields=["status", "assigned_to", "updated_at"])
        with self.assertRaises(ValidationError):
            assign_task_to_member(
                actor_membership=self.manager_membership,
                task_assignment=assignment,
                target_membership=self.owner_membership,
            )
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=assignment).exists())

        available = self.create_available_assignment()
        assign_task_to_member(
            actor_membership=self.manager_membership,
            task_assignment=available,
            target_membership=self.member_membership,
        )
        assigned_to = TaskAssignment.objects.get(pk=available.pk).assigned_to
        with self.assertRaises(ValidationError):
            assign_task_to_member(
                actor_membership=self.second_manager_membership,
                task_assignment=available,
                target_membership=self.owner_membership,
            )
        available.refresh_from_db()
        self.assertEqual(available.assigned_to, assigned_to)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=available).count(), 1)

    def test_manager_assignment_preserves_snapshots_and_template_and_pending_is_visible_to_target(self):
        assignment = self.create_available_assignment()
        template = assignment.task_template
        snapshots = (
            assignment.title_snapshot,
            assignment.description_snapshot,
            assignment.frequency_snapshot,
            assignment.difficulty_snapshot,
        )
        assign_task_to_member(
            actor_membership=self.manager_membership,
            task_assignment=assignment,
            target_membership=self.member_membership,
        )
        assignment.refresh_from_db()
        self.assertEqual(
            (assignment.title_snapshot, assignment.description_snapshot,
             assignment.frequency_snapshot, assignment.difficulty_snapshot),
            snapshots,
        )
        template.refresh_from_db()
        self.assertEqual(template.title, "Manager-assigned task")
        self.client.force_login(self.member)
        response = self.client.get(reverse("member-available-task-list", args=[self.workspace.pk]))
        self.assertContains(response, "Tasks awaiting your response")
        self.assertContains(response, assignment.title_snapshot)

        self.client.force_login(self.second_manager)
        response = self.client.get(reverse("member-available-task-list", args=[self.workspace.pk]))
        self.assertNotContains(response, assignment.title_snapshot)


class PendingAssignmentResponseTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="response_owner", password="strong-pass-123")
        self.manager = user_model.objects.create_user(username="response_manager", password="strong-pass-123")
        self.member = user_model.objects.create_user(username="response_member", password="strong-pass-123")
        self.other_member = user_model.objects.create_user(
            username="response_other", password="strong-pass-123"
        )
        self.workspace = Workspace.objects.create(
            name="Response Workspace", workspace_type=WorkspaceType.BUSINESS
        )
        self.owner_membership = Membership.objects.create(
            workspace=self.workspace, user=self.owner, role=MembershipRole.OWNER
        )
        self.manager_membership = Membership.objects.create(
            workspace=self.workspace, user=self.manager, role=MembershipRole.MANAGER
        )
        self.member_membership = Membership.objects.create(
            workspace=self.workspace, user=self.member, role=MembershipRole.MEMBER
        )
        self.other_member_membership = Membership.objects.create(
            workspace=self.workspace, user=self.other_member, role=MembershipRole.MEMBER
        )

    def create_pending(self, *, target_membership=None):
        template = TaskTemplate.objects.create(
            workspace=self.workspace,
            title="Pending response task",
            description="Awaiting a decision.",
            frequency=TaskFrequency.DAILY,
            difficulty=TaskDifficulty.EASY,
            created_by=self.owner,
        )
        assignment = create_available_task_assignment(
            actor_membership=self.manager_membership,
            task_template=template,
        )
        return assign_task_to_member(
            actor_membership=self.manager_membership,
            task_assignment=assignment,
            target_membership=target_membership or self.member_membership,
        )

    def test_assigned_member_accepts_and_preserves_assignment_data(self):
        assignment = self.create_pending()
        original = {
            "assigned_to": assignment.assigned_to_id,
            "assigned_by": assignment.assigned_by_id,
            "assigned_at": assignment.assigned_at,
            "due_at": assignment.due_at,
            "frequency_snapshot": assignment.frequency_snapshot,
        }
        accept_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, TaskStatus.ACTIVE)
        self.assertEqual(assignment.assigned_to_id, original["assigned_to"])
        self.assertEqual(assignment.assigned_by_id, original["assigned_by"])
        self.assertEqual(assignment.assigned_at, original["assigned_at"])
        self.assertEqual(assignment.due_at, original["due_at"])
        self.assertEqual(assignment.frequency_snapshot, original["frequency_snapshot"])
        event = TaskEventHistory.objects.get(
            task_assignment=assignment,
            event_type=TaskEventType.MEMBER_ACCEPTED_ASSIGNMENT,
        )
        self.assertEqual(event.event_type, TaskEventType.MEMBER_ACCEPTED_ASSIGNMENT)
        self.assertEqual(event.actor, self.member)
        self.assertEqual(event.affected_member, self.member)

    def test_assigned_member_rejects_and_assignment_can_be_reused(self):
        assignment = self.create_pending()
        snapshots = (
            assignment.title_snapshot, assignment.description_snapshot,
            assignment.frequency_snapshot, assignment.difficulty_snapshot,
        )
        reject_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, TaskStatus.AVAILABLE)
        self.assertIsNone(assignment.assigned_to)
        self.assertIsNone(assignment.assigned_by)
        self.assertIsNone(assignment.assignment_type)
        self.assertIsNone(assignment.assigned_at)
        self.assertIsNone(assignment.due_at)
        self.assertEqual(
            (assignment.title_snapshot, assignment.description_snapshot,
             assignment.frequency_snapshot, assignment.difficulty_snapshot), snapshots
        )
        events = TaskEventHistory.objects.filter(task_assignment=assignment)
        self.assertEqual(events.count(), 2)
        rejection = events.get(event_type=TaskEventType.MEMBER_REJECTED_ASSIGNMENT)
        self.assertEqual(rejection.actor, self.member)
        self.assertEqual(rejection.affected_member, self.member)
        self_select_available_task(
            actor_membership=self.member_membership,
            task_assignment=assignment,
        )
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, TaskStatus.ACTIVE)
        self.assertEqual(assignment.assigned_to, self.member)

    def test_rejected_task_can_be_manager_assigned_again(self):
        assignment = self.create_pending()
        reject_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        assign_task_to_member(
            actor_membership=self.manager_membership,
            task_assignment=assignment,
            target_membership=self.other_member_membership,
        )
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, TaskStatus.PENDING_ACCEPTANCE)
        self.assertEqual(assignment.assigned_to, self.other_member)

    def test_other_member_and_manager_cannot_respond_for_assignee(self):
        assignment = self.create_pending()
        for membership in (self.other_member_membership, self.manager_membership, self.owner_membership):
            with self.subTest(role=membership.role):
                with self.assertRaises(PermissionDenied):
                    accept_pending_task(actor_membership=membership, task_assignment=assignment)
                with self.assertRaises(PermissionDenied):
                    reject_pending_task(actor_membership=membership, task_assignment=assignment)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=assignment).count(), 1)

    def test_owner_and_manager_targets_can_respond_to_their_own_pending_assignments(self):
        owner_assignment = self.create_pending(target_membership=self.owner_membership)
        accept_pending_task(actor_membership=self.owner_membership, task_assignment=owner_assignment)
        self.assertEqual(TaskAssignment.objects.get(pk=owner_assignment.pk).status, TaskStatus.ACTIVE)

        manager_assignment = self.create_pending(target_membership=self.manager_membership)
        reject_pending_task(actor_membership=self.manager_membership, task_assignment=manager_assignment)
        self.assertEqual(TaskAssignment.objects.get(pk=manager_assignment.pk).status, TaskStatus.AVAILABLE)

    def test_pending_assignment_without_manager_origin_is_rejected(self):
        assignment = self.create_pending()
        assignment.assignment_type = AssignmentType.SELF_SELECTION
        assignment.save(update_fields=["assignment_type", "updated_at"])
        with self.assertRaises(PermissionDenied):
            accept_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        with self.assertRaises(PermissionDenied):
            reject_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=assignment).count(), 1)

    def test_self_selected_active_task_cannot_be_accepted_or_rejected(self):
        template = TaskTemplate.objects.create(
            workspace=self.workspace, title="Self task", frequency=TaskFrequency.DAILY,
            difficulty=TaskDifficulty.EASY, created_by=self.owner,
        )
        assignment = create_available_task_assignment(
            actor_membership=self.manager_membership, task_template=template
        )
        self_select_available_task(actor_membership=self.member_membership, task_assignment=assignment)
        with self.assertRaises(ValidationError):
            accept_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        with self.assertRaises(ValidationError):
            reject_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=assignment,
                                                         event_type__in=[
                                                             TaskEventType.MEMBER_ACCEPTED_ASSIGNMENT,
                                                             TaskEventType.MEMBER_REJECTED_ASSIGNMENT,
                                                         ]).exists())

    def test_repeated_response_creates_no_duplicate_event(self):
        assignment = self.create_pending()
        accept_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        with self.assertRaises(ValidationError):
            accept_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        with self.assertRaises(ValidationError):
            reject_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        self.assertEqual(
            TaskEventHistory.objects.filter(
                task_assignment=assignment,
                event_type=TaskEventType.MEMBER_ACCEPTED_ASSIGNMENT,
            ).count(), 1
        )

    def test_pending_response_controls_are_post_only_and_visible_only_to_assignee(self):
        assignment = self.create_pending()
        self.client.force_login(self.member)
        page = self.client.get(reverse("member-available-task-list", args=[self.workspace.pk]))
        self.assertContains(page, reverse("accept-pending-task", args=[self.workspace.pk, assignment.pk]))
        self.assertContains(page, reverse("reject-pending-task", args=[self.workspace.pk, assignment.pk]))
        self.assertEqual(
            self.client.get(reverse("accept-pending-task", args=[self.workspace.pk, assignment.pk])).status_code,
            405,
        )
        self.client.force_login(self.other_member)
        other_page = self.client.get(reverse("member-available-task-list", args=[self.workspace.pk]))
        self.assertNotContains(other_page, "Pending response task")


class TaskCompletionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="complete_owner", password="strong-pass-123")
        self.manager = user_model.objects.create_user(username="complete_manager", password="strong-pass-123")
        self.member = user_model.objects.create_user(username="complete_member", password="strong-pass-123")
        self.other = user_model.objects.create_user(username="complete_other", password="strong-pass-123")
        self.workspace = Workspace.objects.create(name="Completion Workspace", workspace_type=WorkspaceType.BUSINESS)
        self.owner_membership = Membership.objects.create(workspace=self.workspace, user=self.owner, role=MembershipRole.OWNER)
        self.manager_membership = Membership.objects.create(workspace=self.workspace, user=self.manager, role=MembershipRole.MANAGER)
        self.member_membership = Membership.objects.create(workspace=self.workspace, user=self.member, role=MembershipRole.MEMBER)
        self.other_membership = Membership.objects.create(workspace=self.workspace, user=self.other, role=MembershipRole.MEMBER)

    def create_active_self_task(self, *, target_membership=None):
        template = TaskTemplate.objects.create(
            workspace=self.workspace, title="Complete task", description="Complete me.",
            frequency=TaskFrequency.DAILY, difficulty=TaskDifficulty.MEDIUM, created_by=self.owner,
        )
        assignment = create_available_task_assignment(
            actor_membership=self.manager_membership, task_template=template
        )
        if target_membership:
            assignment = assign_task_to_member(
                actor_membership=self.manager_membership,
                task_assignment=assignment,
                target_membership=target_membership,
            )
            accept_pending_task(actor_membership=target_membership, task_assignment=assignment)
        else:
            self_select_available_task(actor_membership=self.member_membership, task_assignment=assignment)
        return assignment

    def test_member_completes_self_selected_task_and_preserves_assignment_data(self):
        assignment = self.create_active_self_task()
        original = {
            "assigned_to": assignment.assigned_to_id, "assigned_at": assignment.assigned_at,
            "due_at": assignment.due_at, "title_snapshot": assignment.title_snapshot,
            "description_snapshot": assignment.description_snapshot, "frequency_snapshot": assignment.frequency_snapshot,
            "difficulty_snapshot": assignment.difficulty_snapshot, "assignment_type": assignment.assignment_type,
        }
        completed_at = datetime(2026, 8, 1, 12, 0, tzinfo=datetime_timezone.utc)
        with patch("tasks.services.timezone.now", return_value=completed_at):
            complete_active_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, TaskStatus.COMPLETED)
        self.assertEqual(assignment.completed_at, completed_at)
        self.assertEqual(assignment.completed_by, self.member)
        for field, value in original.items():
            actual = assignment.assigned_to_id if field == "assigned_to" else getattr(assignment, field)
            self.assertEqual(actual, value)
        event = TaskEventHistory.objects.get(task_assignment=assignment, event_type=TaskEventType.TASK_COMPLETED)
        self.assertEqual(event.actor, self.member)
        self.assertEqual(event.affected_member, self.member)
        self.assertEqual(event.workspace, self.workspace)

    def test_owner_and_manager_can_complete_their_own_accepted_assignments(self):
        for membership in (self.owner_membership, self.manager_membership):
            with self.subTest(role=membership.role):
                assignment = self.create_active_self_task(target_membership=membership)
                complete_active_task(actor_membership=membership, task_assignment=assignment)
                self.assertEqual(TaskAssignment.objects.get(pk=assignment.pk).status, TaskStatus.COMPLETED)

    def test_completion_after_due_at_succeeds_and_preserves_due_at(self):
        assignment = self.create_active_self_task()
        due_at = assignment.due_at
        with patch("tasks.services.timezone.now", return_value=due_at + timedelta(days=2)):
            complete_active_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, TaskStatus.COMPLETED)
        self.assertEqual(assignment.due_at, due_at)

    def test_wrong_user_status_and_repeated_completion_are_rejected_without_duplicate_event(self):
        assignment = self.create_active_self_task()
        with self.assertRaises(PermissionDenied):
            complete_active_task(actor_membership=self.other_membership, task_assignment=assignment)
        available = TaskAssignment.objects.create(
            workspace=self.workspace, task_template=assignment.task_template,
            status=TaskStatus.AVAILABLE, title_snapshot="Available", description_snapshot="",
            frequency_snapshot=TaskFrequency.DAILY, difficulty_snapshot=TaskDifficulty.EASY,
        )
        with self.assertRaises(ValidationError):
            complete_active_task(actor_membership=self.member_membership, task_assignment=available)
        complete_active_task(actor_membership=self.member_membership, task_assignment=assignment)
        completed_at = assignment.completed_at
        with self.assertRaises(ValidationError):
            complete_active_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.completed_at, completed_at)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=assignment, event_type=TaskEventType.TASK_COMPLETED).count(), 1)

    def test_completion_view_is_post_only_and_active_task_is_visible_only_to_assignee(self):
        assignment = self.create_active_self_task()
        self.client.force_login(self.member)
        page = self.client.get(reverse("member-available-task-list", args=[self.workspace.pk]))
        self.assertContains(page, assignment.title_snapshot)
        self.assertContains(page, reverse("complete-active-task", args=[self.workspace.pk, assignment.pk]))
        response = self.client.get(reverse("complete-active-task", args=[self.workspace.pk, assignment.pk]))
        self.assertEqual(response.status_code, 405)
        self.client.force_login(self.other)
        other_page = self.client.get(reverse("member-available-task-list", args=[self.workspace.pk]))
        self.assertNotContains(other_page, assignment.title_snapshot)


class TaskScoringTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="score_owner", password="strong-pass-123")
        self.manager = user_model.objects.create_user(username="score_manager", password="strong-pass-123")
        self.member = user_model.objects.create_user(username="score_member", password="strong-pass-123")
        self.other = user_model.objects.create_user(username="score_other", password="strong-pass-123")
        self.workspace = Workspace.objects.create(
            name="Scoring Workspace", workspace_type=WorkspaceType.BUSINESS, gamification_enabled=True
        )
        self.owner_membership = Membership.objects.create(workspace=self.workspace, user=self.owner, role=MembershipRole.OWNER)
        self.manager_membership = Membership.objects.create(workspace=self.workspace, user=self.manager, role=MembershipRole.MANAGER)
        self.member_membership = Membership.objects.create(workspace=self.workspace, user=self.member, role=MembershipRole.MEMBER)
        self.other_membership = Membership.objects.create(workspace=self.workspace, user=self.other, role=MembershipRole.MEMBER)

    def add_rule(self, *, difficulty, points, penalty=-3, frequency=TaskFrequency.DAILY, workspace=None):
        return ScoringRule.objects.create(
            workspace=workspace or self.workspace,
            frequency=frequency,
            difficulty=difficulty,
            completion_points=points,
            late_penalty=penalty,
        )

    def make_available(self, *, difficulty=TaskDifficulty.EASY, frequency=TaskFrequency.DAILY):
        template = TaskTemplate.objects.create(
            workspace=self.workspace, title="Scored task", description="Score me.",
            frequency=frequency, difficulty=difficulty, created_by=self.owner,
        )
        return create_available_task_assignment(
            actor_membership=self.manager_membership, task_template=template
        )

    def test_active_self_selected_tasks_snapshot_all_difficulty_rules(self):
        values = {
            TaskDifficulty.EASY: (10, -1),
            TaskDifficulty.MEDIUM: (20, -2),
            TaskDifficulty.HARD: (40, -4),
        }
        for difficulty, (points, penalty) in values.items():
            self.add_rule(difficulty=difficulty, points=points, penalty=penalty)
            assignment = self.make_available(difficulty=difficulty)
            self_select_available_task(actor_membership=self.member_membership, task_assignment=assignment)
            assignment.refresh_from_db()
            self.assertEqual(assignment.completion_points_snapshot, points)
            self.assertEqual(assignment.late_penalty_snapshot, penalty)

    def test_manager_acceptance_snapshots_rules_when_task_becomes_active(self):
        self.add_rule(difficulty=TaskDifficulty.MEDIUM, points=77, penalty=-9)
        assignment = self.make_available(difficulty=TaskDifficulty.MEDIUM)
        assign_task_to_member(
            actor_membership=self.manager_membership,
            task_assignment=assignment,
            target_membership=self.member_membership,
        )
        assignment.refresh_from_db()
        self.assertIsNone(assignment.completion_points_snapshot)
        accept_pending_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.completion_points_snapshot, 77)
        self.assertEqual(assignment.late_penalty_snapshot, -9)

    def test_gamified_completion_awards_points_and_records_completion_score(self):
        self.add_rule(difficulty=TaskDifficulty.EASY, points=25)
        assignment = self.make_available()
        self_select_available_task(actor_membership=self.member_membership, task_assignment=assignment)
        complete_active_task(actor_membership=self.member_membership, task_assignment=assignment)
        ledger = MemberScoreLedger.objects.get(task_assignment=assignment)
        self.assertEqual(ledger.workspace, self.workspace)
        self.assertEqual(ledger.member, self.member)
        self.assertEqual(ledger.score_change, 25)
        event = TaskEventHistory.objects.get(task_assignment=assignment, event_type=TaskEventType.TASK_COMPLETED)
        self.assertEqual(event.score_change, 25)

    def test_disabled_gamification_completes_without_score(self):
        self.workspace.gamification_enabled = False
        self.workspace.save(update_fields=["gamification_enabled", "updated_at"])
        assignment = self.make_available()
        self_select_available_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.refresh_from_db()
        self.assertIsNone(assignment.completion_points_snapshot)
        complete_active_task(actor_membership=self.member_membership, task_assignment=assignment)
        self.assertFalse(MemberScoreLedger.objects.filter(task_assignment=assignment).exists())
        event = TaskEventHistory.objects.get(task_assignment=assignment, event_type=TaskEventType.TASK_COMPLETED)
        self.assertIsNone(event.score_change)

    def test_missing_scoring_rule_fails_activation_without_partial_update(self):
        assignment = self.make_available()
        with self.assertRaises(ValidationError):
            self_select_available_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, TaskStatus.AVAILABLE)
        self.assertIsNone(assignment.assigned_to)
        self.assertIsNone(assignment.completion_points_snapshot)
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=assignment).exists())

    def test_missing_scoring_snapshot_fails_completion_without_partial_update(self):
        assignment = self.make_available()
        assignment.status = TaskStatus.ACTIVE
        assignment.assigned_to = self.member
        assignment.assignment_type = AssignmentType.SELF_SELECTION
        assignment.save(update_fields=["status", "assigned_to", "assignment_type", "updated_at"])
        with self.assertRaises(ValidationError):
            complete_active_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, TaskStatus.ACTIVE)
        self.assertIsNone(assignment.completed_at)
        self.assertFalse(MemberScoreLedger.objects.filter(task_assignment=assignment).exists())
        self.assertFalse(TaskEventHistory.objects.filter(task_assignment=assignment, event_type=TaskEventType.TASK_COMPLETED).exists())

    def test_rule_edits_do_not_change_existing_snapshots_or_award(self):
        rule = self.add_rule(difficulty=TaskDifficulty.HARD, points=99)
        assignment = self.make_available(difficulty=TaskDifficulty.HARD)
        self_select_available_task(actor_membership=self.member_membership, task_assignment=assignment)
        rule.completion_points = 1
        rule.save(update_fields=["completion_points", "updated_at"])
        complete_active_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.completion_points_snapshot, 99)
        self.assertEqual(MemberScoreLedger.objects.get(task_assignment=assignment).score_change, 99)

    def test_repeated_completion_cannot_award_points_twice(self):
        self.add_rule(difficulty=TaskDifficulty.EASY, points=12)
        assignment = self.make_available()
        self_select_available_task(actor_membership=self.member_membership, task_assignment=assignment)
        complete_active_task(actor_membership=self.member_membership, task_assignment=assignment)
        with self.assertRaises(ValidationError):
            complete_active_task(actor_membership=self.member_membership, task_assignment=assignment)
        self.assertEqual(MemberScoreLedger.objects.filter(task_assignment=assignment).count(), 1)
        self.assertEqual(TaskEventHistory.objects.filter(task_assignment=assignment, event_type=TaskEventType.TASK_COMPLETED).count(), 1)

    def test_score_configuration_and_assignment_are_workspace_scoped(self):
        other_workspace = Workspace.objects.create(
            name="Other Scoring Workspace", workspace_type=WorkspaceType.BUSINESS, gamification_enabled=True
        )
        other_membership = Membership.objects.create(
            workspace=other_workspace, user=self.other, role=MembershipRole.MEMBER
        )
        self.add_rule(difficulty=TaskDifficulty.EASY, points=30, workspace=other_workspace)
        assignment = self.make_available()
        with self.assertRaises(ValidationError):
            self_select_available_task(actor_membership=self.member_membership, task_assignment=assignment)
        assignment.status = TaskStatus.ACTIVE
        assignment.assigned_to = self.member
        assignment.save(update_fields=["status", "assigned_to", "updated_at"])
        with self.assertRaises(PermissionDenied):
            complete_active_task(actor_membership=other_membership, task_assignment=assignment)
