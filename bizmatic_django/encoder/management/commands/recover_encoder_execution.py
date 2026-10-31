"""Recover a durable claim after its worker process has stopped; never retry a tool."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from encoder.models import EncoderExecution, EncoderJob


class Command(BaseCommand):
    help = "Mark an interrupted Encoder execution as unknown after confirming its process stopped."

    def add_arguments(self, parser):
        parser.add_argument("execution_id", type=int)
        parser.add_argument("--confirm-process-stopped", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm_process_stopped"]:
            raise CommandError("Stop/verify the original Django worker first, then pass --confirm-process-stopped.")
        with transaction.atomic():
            initial = EncoderExecution.objects.filter(pk=options["execution_id"]).first()
            if not initial:
                raise CommandError("Execution not found.")
            job = EncoderJob.objects.select_for_update().get(pk=initial.job_id)
            attempt = EncoderExecution.objects.select_for_update().get(pk=initial.pk)
            if attempt.status != "processing" or job.status != "processing":
                raise CommandError("Only an interrupted processing attempt can be recovered.")
            attempt.status = "unknown"
            attempt.error_message = "The Django process stopped before the outcome was saved. Verify the external result before any retry."
            attempt.finished_at = timezone.now()
            attempt.save(update_fields=["status", "error_message", "finished_at"])
            job.status, job.last_error = "failed", attempt.error_message
            job.save(update_fields=["status", "last_error", "updated_at"])
        self.stdout.write("Marked as unknown. No external operation was called. Review and reconcile in Encoder before retrying.")
