from django.db import migrations, models


def mark_existing_completion_scores(apps, schema_editor):
    MemberScoreLedger = apps.get_model("tasks", "MemberScoreLedger")
    MemberScoreLedger.objects.all().update(transaction_type="COMPLETION_SCORE")


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0003_memberscoreledger"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskassignment",
            name="grace_period_ends_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="memberscoreledger",
            name="transaction_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("COMPLETION_SCORE", "Completion score"),
                    ("LATE_PENALTY", "Late penalty"),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(mark_existing_completion_scores, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="memberscoreledger",
            name="transaction_type",
            field=models.CharField(
                choices=[
                    ("COMPLETION_SCORE", "Completion score"),
                    ("LATE_PENALTY", "Late penalty"),
                ],
                max_length=32,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="memberscoreledger",
            name="unique_score_award_per_task_assignment",
        ),
        migrations.AddConstraint(
            model_name="memberscoreledger",
            constraint=models.UniqueConstraint(
                fields=("task_assignment", "transaction_type"),
                name="unique_score_transaction_per_assignment_type",
            ),
        ),
    ]
