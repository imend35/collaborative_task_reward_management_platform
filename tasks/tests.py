from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import (
    AssignmentType,
    Membership,
    MembershipRole,
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
    create_available_task_assignment,
    seed_default_scoring_rules,
    self_select_available_task,
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
        self.assertIsNone(task_assignment.assigned_at)
        self.assertIsNone(task_assignment.due_at)
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
