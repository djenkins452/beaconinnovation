import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError


class AdminTask(models.Model):
    """Task model for Claude Code task management."""

    STATUS_CHOICES = [
        ('ready', 'Ready'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('blocked', 'Blocked'),
    ]

    PRIORITY_CHOICES = [
        (1, 'Low'),
        (2, 'Medium'),
        (3, 'High'),
        (4, 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.JSONField(
        help_text='JSON with keys: objective, inputs, actions, output'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ready')
    priority = models.IntegerField(choices=PRIORITY_CHOICES, default=2)

    # Tracking fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_tasks'
    )

    # Progress tracking
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Optional grouping
    phase = models.CharField(max_length=100, blank=True, default='')
    depends_on = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dependent_tasks'
    )

    # Notes for blocked tasks or additional context
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-priority', 'created_at']
        verbose_name = 'Admin Task'
        verbose_name_plural = 'Admin Tasks'

    def __str__(self):
        return f"[{self.get_status_display()}] {self.title}"

    def clean(self):
        """Validate the JSON description format."""
        super().clean()
        required_keys = {'objective', 'inputs', 'actions', 'output'}

        if not isinstance(self.description, dict):
            raise ValidationError({'description': 'Description must be a JSON object.'})

        missing_keys = required_keys - set(self.description.keys())
        if missing_keys:
            raise ValidationError({
                'description': f'Missing required keys: {", ".join(missing_keys)}'
            })

        # Validate non-empty values
        if not self.description.get('objective'):
            raise ValidationError({'description': 'Objective cannot be empty.'})
        if not self.description.get('actions'):
            raise ValidationError({'description': 'Actions cannot be empty.'})
        if not self.description.get('output'):
            raise ValidationError({'description': 'Output cannot be empty.'})

        # Validate types
        if not isinstance(self.description.get('inputs', []), list):
            raise ValidationError({'description': 'Inputs must be a list.'})
        if not isinstance(self.description.get('actions', []), list):
            raise ValidationError({'description': 'Actions must be a list.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_ready(self):
        """Check if task is ready to be worked on."""
        if self.status != 'ready':
            return False
        if self.depends_on and self.depends_on.status != 'done':
            return False
        return True

    def to_api_dict(self):
        """Return dictionary for API response."""
        return {
            'id': str(self.id),
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'priority': self.priority,
            'phase': self.phase,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
        }
