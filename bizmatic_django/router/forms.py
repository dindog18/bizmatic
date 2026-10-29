"""Plain Django validation for human-maintained router configuration."""

from django import forms
from django.apps import apps

from .models import RoutingDestination, RoutingRule
from .services.catalog import destination_catalog


class DestinationForm(forms.ModelForm):
    module_name = forms.ChoiceField()
    target_model = forms.ChoiceField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        catalog = destination_catalog()
        modules = [(module["value"], module["label"]) for module in catalog]
        module_name = self.data.get("module_name", "") if self.is_bound else self.instance.module_name
        targets = next((module["targets"] for module in catalog if module["value"] == module_name), [])
        models = [(target["value"], target["label"]) for target in targets]
        # Keep an existing destination editable if its module is outside today's catalog.
        # New destinations and retargeting still have to use the supported options.
        if self.instance.pk:
            if self.instance.module_name not in dict(modules):
                modules.append((self.instance.module_name, self.instance.module_name))
            if module_name == self.instance.module_name and self.instance.target_model not in dict(models):
                models.append((self.instance.target_model, self.instance.target_model))
        self.fields["module_name"].choices = [("", "Choose a module"), *modules]
        self.fields["target_model"].choices = [("", "Choose a target model"), *models]

    class Meta:
        model = RoutingDestination
        fields = ["name", "module_name", "target_model", "description", "is_active"]

    def clean(self):
        data = super().clean()
        module, target = data.get("module_name"), data.get("target_model")
        if module and target:
            try:
                model = apps.get_model(module, target)
            except LookupError:
                model = None
            if model is None:
                self.add_error("target_model", "Choose a model from an installed Django app.")
            elif model._meta.abstract or model._meta.proxy:
                self.add_error("target_model", "Choose a concrete model.")
            else:
                data["target_model"] = model.__name__
        if self.instance.pk and self.instance.routes.exists():
            original = RoutingDestination.objects.get(pk=self.instance.pk)
            if (module, data.get("target_model")) != (original.module_name, original.target_model):
                raise forms.ValidationError("This destination has routing history. Create a new destination to change its module or model.")
        return data


class RuleForm(forms.ModelForm):
    class Meta:
        model = RoutingRule
        fields = ["name", "destination", "document_type", "instructions", "examples", "is_active"]
