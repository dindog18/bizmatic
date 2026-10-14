"""Format extracted Markdown without permitting embedded HTML or remote images."""

from django import template
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt

register = template.Library()
renderer = MarkdownIt("commonmark", {"html": False}).enable("table").disable("image")


@register.filter
def extraction_markdown(value):
    return mark_safe(renderer.render(str(value or "")))
