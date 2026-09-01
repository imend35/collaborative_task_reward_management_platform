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
