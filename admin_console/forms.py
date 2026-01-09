import json
from django import forms
from .models import AdminTask


class AdminTaskForm(forms.ModelForm):
    """Form for creating and editing AdminTask instances."""

    # Use a textarea for JSON input with better UX
    description_json = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 12,
            'class': 'form-control font-monospace',
            'placeholder': '''{
    "objective": "What the task should accomplish",
    "inputs": ["Required context (can be empty)"],
    "actions": ["Step 1", "Step 2"],
    "output": "Expected deliverable"
}'''
        }),
        label='Description (JSON)',
        help_text='Enter task description as JSON with keys: objective, inputs, actions, output'
    )

    class Meta:
        model = AdminTask
        fields = ['title', 'priority', 'phase', 'status', 'depends_on', 'notes']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'phase': forms.TextInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'depends_on': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # If editing existing task, populate the JSON field
        if self.instance and self.instance.pk:
            self.fields['description_json'].initial = json.dumps(
                self.instance.description, indent=4
            )

        # Filter depends_on to exclude self and show helpful labels
        if self.instance and self.instance.pk:
            self.fields['depends_on'].queryset = AdminTask.objects.exclude(
                pk=self.instance.pk
            )

    def clean_description_json(self):
        """Validate and parse the JSON description."""
        json_str = self.cleaned_data['description_json']

        try:
            description = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f'Invalid JSON: {str(e)}')

        # Validate required keys
        required_keys = {'objective', 'inputs', 'actions', 'output'}
        if not isinstance(description, dict):
            raise forms.ValidationError('Description must be a JSON object.')

        missing_keys = required_keys - set(description.keys())
        if missing_keys:
            raise forms.ValidationError(
                f'Missing required keys: {", ".join(missing_keys)}'
            )

        # Validate non-empty values
        if not description.get('objective'):
            raise forms.ValidationError('Objective cannot be empty.')
        if not description.get('actions'):
            raise forms.ValidationError('Actions cannot be empty.')
        if not description.get('output'):
            raise forms.ValidationError('Output cannot be empty.')

        # Validate types
        if not isinstance(description.get('inputs', []), list):
            raise forms.ValidationError('Inputs must be a list.')
        if not isinstance(description.get('actions', []), list):
            raise forms.ValidationError('Actions must be a list.')

        return description

    def save(self, commit=True):
        """Save the form and set the description from JSON field."""
        instance = super().save(commit=False)
        instance.description = self.cleaned_data['description_json']

        if commit:
            instance.save()
        return instance


class TaskImportForm(forms.Form):
    """Form for importing tasks from a JSON file."""

    json_file = forms.FileField(
        label='JSON File',
        help_text='Upload a JSON file containing task definitions.',
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.json'})
    )

    def clean_json_file(self):
        """Validate the uploaded file is valid JSON."""
        json_file = self.cleaned_data['json_file']

        # Check file extension
        if not json_file.name.endswith('.json'):
            raise forms.ValidationError('File must have .json extension.')

        # Check file size (max 1MB)
        if json_file.size > 1024 * 1024:
            raise forms.ValidationError('File size must be less than 1MB.')

        return json_file
