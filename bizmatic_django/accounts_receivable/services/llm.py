"""One accounting LLM call, with the exact request, response, and failure saved."""

import json
import re
from time import perf_counter
from typing import Any

from asgiref.sync import async_to_sync
from django.core.exceptions import ValidationError

from bizmatic_django.environment import get_env
from document_extraction.services.llm import invoke_with_llm
from router.services.llm import response_text, usage
from .catalog import MODULES, model
from .configuration import snapshot


def run(mode, configuration, purpose, system, context, route=None, response_schema=None):
    # Assistant proposals share one provider; record extraction uses the module provider.
    prefix = "CONFIG_ASSISTANT" if purpose == "configuration" else MODULES[mode].upper()
    provider = get_env(f"{prefix}_LLM_PROVIDER", "ollama").strip().lower()
    name = get_env(f"{prefix}_{provider.upper()}_MODEL", "").strip()
    log = model(mode, "LLMExtractionLog").objects.create(
        configuration=configuration if configuration.pk else None, configuration_revision=configuration.revision,
        configuration_snapshot=snapshot(configuration), target_entity=configuration.target_entity,
        source_type=configuration.source_type, purpose=purpose, provider=provider, model_name=name,
        status="processing", routing_route=route,
        fk_document_no=route.routing_log.source_document if route else None,
        source_llm_log=route.routing_log.source_llm_log if route else None,
    )
    started = perf_counter()
    result = {}
    try:
        content = json.dumps(context, ensure_ascii=False)
        if len(content) > int(get_env(f"{prefix}_MAX_INPUT_CHARACTERS", "150000")):
            raise ValueError("Accounting input is too large. Reduce the source text or instructions.")
        tokens = int(get_env(f"{prefix}_MAX_OUTPUT_TOKENS", "8192"))
        timeout = int(get_env(f"{prefix}_LLM_TIMEOUT_SECONDS", "120"))
        if tokens <= 0 or timeout <= 0:
            raise ValueError("Accounting token and timeout limits must be positive.")
        # JSON mode alone does not tell compatible providers our mapping format.
        # Include the same contract Ollama receives, including on repair requests.
        if response_schema and provider != "ollama":
            system += "\nReturn a JSON object matching this response schema:\n" + json.dumps(response_schema, separators=(",", ":"))
        body: dict[str, Any] = {"model": name, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}], "max_tokens": tokens}
        if provider == "anthropic":
            body["system"] = system
            body["messages"] = [{"role": "user", "content": content}]
        elif provider == "google":
            body = {"model": name, "systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": content}]}], "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": tokens}}
        elif provider == "ollama":
            body.pop("max_tokens")
            body.update(format=response_schema or "json", options={"num_predict": tokens, **({"temperature": 0} if response_schema else {})}, stream=False)
        else:
            body["response_format"] = {"type": "json_object"}
        log.request_payload = body
        log.save(update_fields=["request_payload", "updated_at"])
        if provider not in {"openai", "anthropic", "google", "ollama", "alibaba", "deepseek"} or not name:
            raise ValueError(f"Configure {prefix}_LLM_PROVIDER and its provider model.")
        result = async_to_sync(invoke_with_llm)(provider, body, config_prefix=prefix, timeout=timeout)
        log.response_payload = result if isinstance(result, dict) else {"invalid_response": result}
        if not isinstance(result, dict):
            raise ValueError("The accounting provider response must be a JSON object.")
        log.markdown_text = response_text(provider, result)
        if (result.get("stop_reason") == "max_tokens" or result.get("done_reason") == "length"
                or any(row.get("finish_reason") == "length" for row in result.get("choices", []))
                or any(row.get("finishReason") == "MAX_TOKENS" for row in result.get("candidates", []))):
            raise ValueError("The accounting response was truncated. Increase the output limit and retry.")
        raw = log.markdown_text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        parsed = json.loads(fenced.group(1) if fenced else raw)
        if not isinstance(parsed, dict):
            raise ValueError("The LLM response must be a JSON object.")
        # The caller completes the attempt only after validating and saving its output.
        log.status = "processing"
    except Exception as error:
        log.status = "failed"
        log.error_message = str(error) if isinstance(error, (ValueError, ValidationError)) else "The accounting provider request failed. Check the provider settings and retry."
        parsed = None
    finally:
        for key, value in usage(result).items():
            setattr(log, key, value)
        log.processing_time_ms = round((perf_counter() - started) * 1000)
        log.save()
    return log, parsed
