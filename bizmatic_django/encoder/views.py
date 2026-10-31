"""Server-rendered local workspace; every write/provider call is CSRF-protected POST."""
import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from .forms import ConnectionForm, MappingForm, OperationForm, PayloadForm
from .models import EncoderChatMessage, EncoderExecution, EncoderJob, EncoderMapping, MCPConnection
from .services import chat, discovery, execution, mapping


def context(title, **kwargs):
    return {"page_title": title, "section": "encoder", **kwargs}


def notify_error(request, error):
    messages.error(request, "; ".join(error.messages) if isinstance(error, ValidationError) else "Invalid input. Check the values and try again.")


@require_safe
def dashboard(request):
    jobs = EncoderJob.objects.select_related("route__routing_log__source_document", "connection").prefetch_related("executions")
    if request.GET.get("status") in EncoderJob.Status.values:
        jobs = jobs.filter(status=request.GET["status"])
    return render(request, "encoder/dashboard.html", context("Encoder", page=Paginator(jobs, 30).get_page(request.GET.get("page")), statuses=EncoderJob.Status.choices))


@require_safe
def workspace(request, job_id):
    from .services.presentation import review, message_html
    job = get_object_or_404(EncoderJob.objects.select_related("route__routing_log__source_document", "route__destination", "connection"), pk=job_id)
    show_history = request.GET.get("chat_history") == "1"
    chat_messages = list(job.chat_messages.all() if show_history else job.chat_messages.filter(cycle=job.cycle))
    for answer in chat_messages:
        answer.content_html = message_html(answer.content)
        answer.proposal_json = json.dumps(answer.proposal, indent=2, ensure_ascii=False)
        if isinstance(answer.proposal.get("payload"), dict):
            answer.data_review = review(answer.proposal["payload"], job.tool_schema)
    current_proposal = next((answer for answer in reversed(chat_messages)
                             if answer.cycle == job.cycle and answer.decision in {"accepted", "prepared"}
                             and answer.proposal.get("payload") == job.prepared_payload), None)
    return render(request, "encoder/workspace.html", context(f"Encoder job #{job.pk}", job=job, document=job.document,
        operation_form=OperationForm(job=job, selected_connection=request.GET.get("connection")), payload_form=PayloadForm(job=job), mapping_form=MappingForm(job=job),
        token=execution.review_token(job), payload_json=json.dumps(job.prepared_payload, indent=2, ensure_ascii=False),
        mappings_json=json.dumps(job.field_mappings, indent=2), source_json=json.dumps(mapping.source_data(job), indent=2, ensure_ascii=False),
        show_chat_history=show_history, reset_history=[{"cycle": row.cycle, "created_at": row.created_at, "snapshot": json.dumps(row.snapshot, indent=2, ensure_ascii=False)} for row in job.resets.all()],
        data_review=review(job.prepared_payload, job.tool_schema), review_warnings=current_proposal.proposal.get("issues", []) if current_proposal else [], chat_messages=chat_messages, executions=job.executions.all()))


@require_POST
def job_action(request, job_id, action):
    job = get_object_or_404(EncoderJob, pk=job_id)
    try:
        if action == "reset":
            from .services.reset import reset
            reset(job.pk, request.POST.get("revision"), confirmed=request.POST.get("confirmed") == "yes")
            messages.success(request, "Workspace reset. Previous conversations, drafts and execution logs are retained in history.")
        elif action == "select":
            form = OperationForm(request.POST, job=job)
            if not form.is_valid():
                raise ValidationError(form.errors.as_text())
            mapping.select(job.pk, form.cleaned_data["connection"], form.cleaned_data["tool_name"], form.cleaned_data["revision"])
        elif action in {"payload", "mappings"}:
            form = PayloadForm(request.POST, job=job) if action == "payload" else MappingForm(request.POST, job=job)
            if not form.is_valid():
                raise ValidationError(form.errors.as_text())
            kwargs = {"payload": form.payload(job)} if action == "payload" else {"mappings": form.mappings(), "reusable": form.cleaned_data["reusable"]}
            mapping.save(job.pk, form.cleaned_data["revision"], **kwargs)
        elif action == "json":
            mapping.save(job.pk, request.POST.get("revision"), payload=json.loads(request.POST.get("payload", "")))
        elif action == "validate":
            mapping.save(job.pk, request.POST.get("revision"), payload=job.prepared_payload)
        elif action == "execute":
            result = execution.execute(job.pk, request.POST.get("token", ""), confirmed=request.POST.get("confirmed") == "yes", reconciled=request.POST.get("reconciled") == "yes")
            if result.error_message:
                messages.warning(request, result.error_message)
            else:
                messages.success(request, f"Execution #{result.pk}: {result.get_status_display()}.")
        elif action == "chat":
            chat.ask(job.pk, request.POST.get("message", ""))
        elif action in {"accept", "reject"}:
            message = get_object_or_404(EncoderChatMessage, job=job, pk=request.POST.get("message_id"), role="assistant")
            chat.decide(job.pk, message.pk, "accepted" if action == "accept" else "rejected", request.POST.get("revision"))
        else:
            return HttpResponseBadRequest("Unknown Encoder action.")
    except (ValidationError, ValueError, TypeError) as error:
        notify_error(request, error)
    if action in {"chat", "accept", "reject"}:
        from django.urls import reverse
        return redirect(reverse("ENCODER:workspace", args=[job.pk]) + "#encoder-chat")
    return redirect("ENCODER:workspace", job_id=job.pk)


@require_safe
def connections(request):
    return render(request, "encoder/connections.html", context("MCP connections", connections=MCPConnection.objects.all()))


@require_http_methods(["GET", "HEAD", "POST"])
def connection_edit(request, connection_id=None):
    connection = get_object_or_404(MCPConnection, pk=connection_id) if connection_id else None
    form = ConnectionForm(request.POST if request.method == "POST" else None, instance=connection)
    if request.method == "POST" and form.is_valid():
        if request.POST.get("intent") == "test":
            if request.headers.get("Accept") == "application/json":
                return JsonResponse({"message": f"Connection successful. Discovered {len(form.connection_result)} tools. Connection has not been saved."})
            messages.success(request, f"Connection successful. Discovered {len(form.connection_result)} tools. Connection has not been saved.")
        else:
            with transaction.atomic():
                current = MCPConnection.objects.select_for_update().get(pk=connection.pk) if connection else None
                if current and request.POST.get("revision") != current.updated_at.isoformat():
                    form.add_error(None, "Connection changed. Reload before saving.")
                if not form.errors:
                    candidate = form.save(commit=False)
                    same_launch = current and all(getattr(current, field) == getattr(candidate, field) for field in ("transport", "server_url", "bearer_token_env_var", "http_headers", "env_http_headers", "command", "arguments", "working_directory", "environment", "environment_passthrough"))
                    unchanged = {tool["name"] for tool in form.connection_result if current and tool in current.tools}
                    candidate.approved_tools = [name for name in current.approved_tools if name in unchanged] if same_launch else []
                    candidate.launch_profile = ""
                    candidate.tools = form.connection_result
                    candidate.discovery_error = ""
                    candidate.discovered_at = timezone.now()
                    candidate.save()
                    return redirect("ENCODER:connection_detail", connection_id=candidate.pk)
    if request.method == "POST" and request.POST.get("intent") == "test" and request.headers.get("Accept") == "application/json":
        return JsonResponse({"message": "; ".join(message for errors in form.errors.values() for message in errors)}, status=400)
    return render(request, "encoder/connection_form.html", context("Edit MCP connection" if connection else "Add MCP connection", form=form, connection=connection))


@require_http_methods(["GET", "HEAD", "POST"])
def connection_detail(request, connection_id):
    connection = get_object_or_404(MCPConnection, pk=connection_id)
    if request.method == "POST":
        try:
            if request.POST.get("intent") == "discover":
                discovery.discover(connection)
                messages.success(request, "Connection tested and tools discovered. Choose permitted operations below.")
            else:
                with transaction.atomic():
                    connection = MCPConnection.objects.select_for_update().get(pk=connection_id)
                    if request.POST.get("revision") != connection.updated_at.isoformat():
                        raise ValidationError("The connection changed. Reload before approving operations.")
                    names = request.POST.getlist("approved_tools")
                    if set(names) - {row["name"] for row in connection.tools}:
                        raise ValidationError("Only discovered tools can be permitted.")
                    connection.approved_tools = names
                    connection.save()
                    messages.success(request, "Permitted operations saved.")
        except ValidationError as error:
            notify_error(request, error)
        return redirect("ENCODER:connection_detail", connection_id=connection.pk)
    tools = [{**row, "schema_json": json.dumps(row.get("inputSchema", {}), indent=2), "approved": row["name"] in connection.approved_tools} for row in connection.tools]
    return render(request, "encoder/connection_detail.html", context(connection.name, connection=connection, tools=tools))


@require_http_methods(["GET", "HEAD", "POST"])
def mapping_edit(request, connection_id, tool_name):
    connection = get_object_or_404(MCPConnection, pk=connection_id)
    row = discovery.tool(connection, tool_name)
    profile = EncoderMapping.objects.filter(connection=connection, tool_name=tool_name).first()
    error = ""
    if request.method == "POST":
        try:
            mappings = json.loads(request.POST.get("mappings", "{}"))
            mapping.check_mappings(mappings)
            field = request.POST.get("idempotency_field", "").strip()
            if field and row["inputSchema"].get("properties", {}).get(field, {}).get("type") != "string":
                raise ValidationError("Idempotency parameter must be a declared string field.")
            with transaction.atomic():
                MCPConnection.objects.select_for_update().get(pk=connection.pk)
                current = EncoderMapping.objects.filter(connection=connection, tool_name=tool_name).first()
                if request.POST.get("revision", "") != (current.updated_at.isoformat() if current else ""):
                    raise ValidationError("Mapping changed. Reload before saving.")
                EncoderMapping.objects.update_or_create(connection=connection, tool_name=tool_name, defaults={"field_mappings": mappings, "idempotency_field": field})
            return redirect("ENCODER:connection_detail", connection_id=connection.pk)
        except (ValidationError, ValueError) as exc:
            error = "; ".join(exc.messages) if isinstance(exc, ValidationError) else "Enter valid JSON mappings."
    return render(request, "encoder/mapping_form.html", context("Reusable mapping", connection=connection, tool_name=tool_name,
        mappings_json=request.POST.get("mappings") if request.method == "POST" else json.dumps(profile.field_mappings if profile else {}, indent=2),
        profile=profile, schema_properties=row["inputSchema"].get("properties", {}), schema_json=json.dumps(row["inputSchema"], indent=2), action_error=error))


@require_safe
def history(request):
    rows = EncoderExecution.objects.select_related("job__route__routing_log__source_document", "connection")
    return render(request, "encoder/history.html", context("Encoder execution history", page=Paginator(rows, 30).get_page(request.GET.get("page"))))


@require_safe
def execution_detail(request, execution_id):
    row = get_object_or_404(EncoderExecution.objects.select_related("job__route__routing_log__source_document", "connection"), pk=execution_id)
    return render(request, "encoder/execution_detail.html", context(f"Execution #{row.pk}", execution=row,
        payload_json=json.dumps(row.payload, indent=2), response_json=json.dumps(row.response, indent=2), schema_json=json.dumps(row.tool_schema, indent=2)))


@require_safe
def llm_logs(request):
    rows = EncoderChatMessage.objects.filter(role="assistant").select_related("job__route__routing_log__source_document").order_by("-pk")
    if request.GET.get("status") in {"completed", "failed", "processing"}:
        rows = rows.filter(status=request.GET["status"])
    return render(request, "encoder/llm_logs.html", context("Encoder LLM activity", page=Paginator(rows, 30).get_page(request.GET.get("page"))))


@require_safe
def llm_log_detail(request, message_id):
    row = get_object_or_404(EncoderChatMessage.objects.select_related("job__route__routing_log__source_document"), pk=message_id, role="assistant")
    return render(request, "encoder/llm_log_detail.html", context(f"Encoder LLM attempt #{row.pk}", attempt=row,
        request_json=json.dumps(row.request_payload, indent=2, ensure_ascii=False), response_json=json.dumps(row.response_payload, indent=2, ensure_ascii=False)))
