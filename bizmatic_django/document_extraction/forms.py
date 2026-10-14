from django import forms
from django.core.files.uploadedfile import UploadedFile
from pathlib import Path

from .models import Document, ReviewStatus


class MultipleFileInput(forms.FileInput):
    """Allow selecting multiple files in one input."""
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None) -> list[UploadedFile]:
        # Validate every upload; missing or empty files raise form errors.
        clean_file = super().clean
        uploads = data if isinstance(data, (list, tuple)) else [data]
        return [clean_file(upload, initial) for upload in (uploads or [None])]


class DocumentUploadForm(forms.Form):
    """Upload files; the view creates and numbers the batch automatically."""
    files = MultipleFileField(label="Documents and images", max_length=255)


class DocumentEditForm(forms.ModelForm):
    revision = forms.CharField(widget=forms.HiddenInput)

    class Meta:
        model = Document
        fields = ("file_name", "document_type", "fk_batch_no", "revision")
        labels = {"fk_batch_no": "Batch"}
        widgets = {"file_name": forms.TextInput(attrs={"class": "form-control"}),
                   "document_type": forms.TextInput(attrs={"class": "form-control"}),
                   "fk_batch_no": forms.Select(attrs={"class": "form-select"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["revision"] = self.instance.updated_at.isoformat()

    def clean_file_name(self):
        name = self.cleaned_data["file_name"]
        if name in (".", "..") or "/" in name or "\\" in name:
            raise forms.ValidationError("Enter a file name without a directory path.")
        if Path(name).suffix.lower() != Path(self.instance.file_name).suffix.lower():
            raise forms.ValidationError("Keep the original file extension.")
        return name


class MarkdownForm(forms.Form):
    markdown_text = forms.CharField(strip=False, label="Markdown source",
                                   widget=forms.Textarea(attrs={"class": "form-control font-monospace", "rows": 18}))
    revision = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_markdown_text(self):
        text = self.cleaned_data["markdown_text"]
        if not text.strip():
            raise forms.ValidationError("Enter Markdown content before saving.")
        return text


class ReviewForm(forms.Form):
    review_status = forms.ChoiceField(choices=ReviewStatus.choices)


class AccuracyForm(forms.Form):
    accurate = forms.TypedChoiceField(choices=(("1", "Accurate"), ("0", "Not accurate")), coerce=lambda value: value == "1")

