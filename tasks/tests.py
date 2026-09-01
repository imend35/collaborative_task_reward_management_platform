from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import (
    AssignmentType,
    Membership,
    MembershipRole,
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
