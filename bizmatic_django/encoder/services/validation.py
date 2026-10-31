"""Full JSON Schema validation including formats; external references are forbidden."""
import json

from django.core.exceptions import ValidationError
from jsonschema import FormatChecker, validators
from jsonschema.exceptions import SchemaError


def check_schema(schema):
    if not isinstance(schema, dict):
        raise ValidationError("The MCP tool must declare an object input schema.")
    def inspect(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (not isinstance(value, str) or not value.startswith("#")):
                    raise ValidationError("External schema references are unsupported. The MCP server must supply a self-contained schema.")
                inspect(value)
        elif isinstance(node, list):
            for value in node:
                inspect(value)
    inspect(schema)
    try:
        validators.validator_for(schema).check_schema(schema)
    except SchemaError:
        raise ValidationError("The MCP server returned an invalid input schema.") from None


def errors(payload, schema):
    check_schema(schema)
    if not isinstance(payload, dict):
        return [{"field": "$", "message": "The prepared payload must be a JSON object."}]
    try:
        json.dumps(payload, allow_nan=False)
    except (ValueError, TypeError):
        return [{"field": "$", "message": "Payload values must be valid JSON with finite numbers."}]
    try:
        validator = validators.validator_for(schema)(schema, format_checker=FormatChecker())
        return [{"field": ".".join(map(str, error.absolute_path)) or "$", "message": error.message}
                for error in sorted(validator.iter_errors(payload), key=lambda error: str(list(error.absolute_path)))][:100]
    except Exception:
        raise ValidationError("This schema cannot be resolved locally. Ask the MCP server administrator for a self-contained supported schema.") from None
