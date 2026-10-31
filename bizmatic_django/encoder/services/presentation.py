"""Read-only, schema-driven summaries. Presence never implies verified extraction."""
import json
from markdown_it import MarkdownIt
from django.utils.safestring import mark_safe

from jsonschema import FormatChecker, validators


def message_html(text):
    # Formatting only: no raw HTML, clickable links or remote image requests.
    renderer = MarkdownIt("commonmark", {"html": False}).disable(["image", "link", "autolink"])
    return mark_safe(renderer.render(text or ""))


def review(payload, schema):
    values, missing, invalid = [], [], []

    def label(path):
        return " › ".join(str(part + 1) if isinstance(part, int) else str(part).replace("_", " ").capitalize() for part in path)

    def walk(value, path=()):
        if not path and value == {}:
            return
        if len(values) >= 100:
            return
        if isinstance(value, dict) and value:
            for key, child in value.items():
                walk(child, (*path, key))
        elif isinstance(value, list) and value:
            for index, child in enumerate(value):
                walk(child, (*path, index))
        else:
            values.append({"label": label(path) or "Payload", "path": ".".join(map(str, path)),
                           "value": "Not supplied" if value is None or value == "" else ("Yes" if value is True else "No" if value is False else json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value))})

    walk(payload)
    try:
        validator = validators.validator_for(schema)(schema, format_checker=FormatChecker())
        for error in validator.iter_errors(payload):
            if error.validator == "required" and isinstance(error.instance, dict):
                for key in error.validator_value:
                    if key not in error.instance:
                        path = (*error.absolute_path, key)
                        field = error.schema.get("properties", {}).get(key, {})
                        entry = {"label": label(path), "path": ".".join(map(str, path))}
                        if field.get("description"):
                            entry["description"] = field["description"]
                        if field.get("type"):
                            entry["expected"] = str(field["type"])
                        if field.get("enum"):
                            entry["choices"] = ", ".join(str(value) for value in field["enum"])
                        if entry not in missing:
                            missing.append(entry)
            else:
                invalid.append({"label": label(error.absolute_path) or "Payload", "message": error.message})
    except Exception:
        invalid.append({"label": "Schema", "message": "Review validation results; this schema could not be summarized."})
    return {"values": values, "missing": missing[:100], "invalid": invalid[:100]}
