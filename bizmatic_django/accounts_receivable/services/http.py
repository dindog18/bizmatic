"""Shared JSON actions for the two accounting workspaces."""

import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import assistant, configuration_chat, imports, pages, records
from .catalog import model


def perform(request, mode, action, record_id=None):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValidationError("Expected a JSON object.")
        if action.startswith("setup-"):
            from .setup.actions import perform as setup_action
            return JsonResponse(setup_action(request, mode, action, data, record_id))
        if action in {"configuration-review", "configuration", "submit"}:
            values = data.get("configuration", {})
            setup = values.get("setup_data", {}) if isinstance(values, dict) else {}
            saved = model(mode, "ExtractionConfiguration").objects.filter(pk=record_id).first() if record_id else None
            saved_setup = saved.setup_data if saved else {}
            if (isinstance(setup, dict) and setup.get("version") == 1) or (isinstance(saved_setup, dict) and saved_setup.get("version") == 1):
                from .setup.actions import perform as setup_action
                if action != "configuration-review":
                    data["submit"] = action == "submit"
                return JsonResponse(setup_action(request, mode, "setup-review" if action == "configuration-review" else "setup-save", data, record_id))
        if action in {"parties", "reconciliation"}:
            record = records.save_party(mode, data, record_id) if action == "parties" else records.save_case(mode, data, record_id)
            return JsonResponse({"id": record.pk})
        if action in {"allocations", "matches"} and record_id:
            record = records.save_allocations(mode, record_id, data) if action == "allocations" else records.save_matches(mode, record_id, data)
            return JsonResponse({"id": record.pk})
        if action == "configuration-context":
            return JsonResponse(configuration_chat.setup_context(mode, data, record_id))
        if action == "configuration-reset-context":
            return JsonResponse(configuration_chat.reset_context(mode, data, record_id))
        if action == "configuration-chat":
            return JsonResponse(configuration_chat.chat(mode, data, record_id))
        if action == "configuration-preview":
            return JsonResponse(configuration_chat.preview(mode, data, record_id))
        if action == "configuration-review":
            return JsonResponse(configuration_chat.review(mode, data, record_id, request.user))
        if action in {"configuration", "submit"}:
            data["submit"] = action == "submit"
            with transaction.atomic():
                record = configuration_chat.confirm(mode, data, record_id, request.user)
            return JsonResponse({"record": pages.configuration(record, mode)})
        if action == "assistant" and record_id:
            record = assistant.propose(mode, record_id, data)
            return JsonResponse({"record": pages.configuration(record, mode), "llm_log_no": record.assistant_proposal["llm_log_no"]})
        if action == "import" and record_id:
            run = imports.execute(mode, record_id, data)
            return JsonResponse({"id": run.pk, "status": run.status, "result": run.result})
        if action == "accuracy" and record_id:
            with transaction.atomic():
                log = get_object_or_404(model(mode, "LLMExtractionLog").objects.select_for_update(), pk=record_id)
                if data.get("revision") != log.updated_at.isoformat():
                    raise ValidationError("The attempt changed. Reload before reviewing.", code="conflict")
                if log.status != "completed" or type(data.get("accurate")) is not bool:
                    raise ValidationError("Only a completed attempt can be marked accurate.")
                log.user_selected_accurate = data["accurate"]
                log.reviewed_at = timezone.now()
                log.reviewed_by = request.user if request.user.is_authenticated else None
                log.save(update_fields=["user_selected_accurate", "reviewed_at", "reviewed_by", "updated_at"])
            return JsonResponse({"record": pages.llm_log(log)})
        raise ValidationError("Unsupported accounting action.")
    except (ValidationError, ValueError, TypeError, KeyError, OverflowError) as error:
        message = "; ".join(error.messages) if isinstance(error, ValidationError) else "Invalid request. Check the submitted fields and reload if necessary."
        result = {"message": message}
        if getattr(error, "llm_log_no", None):
            result["llm_log_no"] = error.llm_log_no
        return JsonResponse(result, status=409 if getattr(error, "code", None) == "conflict" else 400)
    except IntegrityError:
        return JsonResponse({"message": "A conflicting record already exists. Reload and check its reference or source."}, status=409)
