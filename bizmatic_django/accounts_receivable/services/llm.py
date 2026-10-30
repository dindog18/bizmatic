"""Accounting LLM calls; private conversations keep only audit metadata."""

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


def run(mode, configuration, purpose, system, context, route=None, response_schema=None, *, private_context=False):
    # Assistant proposals share one provider; record extraction uses the module provider.
    prefix = "CONFIG_ASSISTANT" if purpose == "configuration" else MODULES[mode].upper()
    provider = get_env(f"{prefix}_LLM_PROVIDER", "ollama").strip().lower()
    name = get_env(f"{prefix}_{provider.upper()}_MODEL", "").strip()
    log = model(mode, "LLMExtractionLog").objects.create(
        configuration=configuration if configuration.pk else None, configuration_revision=configuration.revision,
        configuration_snapshot={} if private_context else snapshot(configuration), target_entity=configuration.target_entity,
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
        # Alibaba's hybrid DeepSeek V4 models default to thinking. Reasoning
        # consumes the same output budget and can leave no JSON to validate.
        # This is a raw HTTP body (not the OpenAI SDK's extra_body wrapper).
        if provider == "alibaba" and name.lower().startswith("deepseek-v4"):
            thinking = get_env(f"{prefix}_ALIBABA_ENABLE_THINKING", "false").strip().lower()
            if thinking not in {"true", "false"}:
                raise ValueError(f"{prefix}_ALIBABA_ENABLE_THINKING must be true or false.")
            body["enable_thinking"] = thinking == "true"
        # Personal setup conversations must not be copied into shared activity.
        # Keep the log object redacted too: callers may save it again after validation.
        redacted = {"content_redacted": True, "reason": "Private setup conversation"}
        log.request_payload = redacted if private_context else body
        log.save(update_fields=["request_payload", "updated_at"])
        if provider not in {"openai", "anthropic", "google", "ollama", "alibaba", "deepseek"} or not name:
            raise ValueError(f"Configure {prefix}_LLM_PROVIDER and its provider model.")
        result = async_to_sync(invoke_with_llm)(provider, body, config_prefix=prefix, timeout=timeout)
        log.response_payload = redacted if private_context else result if isinstance(result, dict) else {"invalid_response": result}
        if not isinstance(result, dict):
            raise ValueError("The accounting provider response must be a JSON object.")
        content_text = response_text(provider, result)
        log.markdown_text = "" if private_context else content_text
        if (result.get("stop_reason") == "max_tokens" or result.get("done_reason") == "length"
                or any(row.get("finish_reason") == "length" for row in result.get("choices", []))
                or any(row.get("finishReason") == "MAX_TOKENS" for row in result.get("candidates", []))):
            raise ValueError(
                f"The accounting response reached its {tokens:,}-token output limit before completing JSON. "
                f"Increase {prefix}_MAX_OUTPUT_TOKENS, restart the application, and retry. "
                "Reasoning tokens also consume the output budget on thinking models."
            )
        raw = content_text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        parsed = json.loads(fenced.group(1) if fenced else raw)
        if not isinstance(parsed, dict):
            raise ValueError("The LLM response must be a JSON object.")
        # The caller completes the attempt only after validating and saving its output.
        log.status = "processing"
    except Exception as error:
        log.status = "failed"
        log.error_message = ("The setup assistant request failed. Check provider settings, input size and timeout, then retry."
                             if private_context else str(error) if isinstance(error, (ValueError, ValidationError))
                             else "The accounting provider request failed. Check the provider settings and retry.")
        parsed = None
    finally:
        for key, value in usage(result).items():
            setattr(log, key, value)
        log.processing_time_ms = round((perf_counter() - started) * 1000)
        log.save()
    return log, parsed
