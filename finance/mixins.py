"""Mixins for the finance app."""
from django.db import models


class AuditLogMixin:
    """
    Mixin to automatically create audit log entries on save/delete.

    To use: have your model inherit from this mixin and call
    save_with_audit() or delete_with_audit() with the request object.
    """

    def _get_field_values(self):
        """Get a dictionary of field values for audit logging."""
        values = {}
        for field in self._meta.fields:
            if field.name in ('created_at', 'updated_at'):
                continue
            value = getattr(self, field.name)
            # Convert non-serializable types
            if hasattr(value, 'pk'):
                value = str(value.pk)
            elif hasattr(value, 'isoformat'):
                value = value.isoformat()
            else:
                value = str(value) if value is not None else None
            values[field.name] = value
        return values

    def save_with_audit(self, request=None, *args, **kwargs):
        """Save the model and create an audit log entry."""
        from finance.models import AuditLog

        is_new = self.pk is None or not self.__class__.objects.filter(pk=self.pk).exists()

        # Get old values for update
        old_values = {}
        if not is_new:
            old_instance = self.__class__.objects.get(pk=self.pk)
            old_values = old_instance._get_field_values()

        # Save the instance
        self.save(*args, **kwargs)

        # Get new values
        new_values = self._get_field_values()

        # Determine what changed
        if is_new:
            changes = {'new': new_values}
            action = 'create'
        else:
            changes = {
                'old': {k: v for k, v in old_values.items() if old_values.get(k) != new_values.get(k)},
                'new': {k: v for k, v in new_values.items() if old_values.get(k) != new_values.get(k)}
            }
            action = 'update'

        # Create audit log
        user = request.user if request and request.user.is_authenticated else None
        ip_address = None
        user_agent = ''

        if request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

        AuditLog.objects.create(
            user=user,
            action=action,
            model_name=self.__class__.__name__,
            object_id=self.pk,
            object_repr=str(self)[:500],
            changes=changes,
            ip_address=ip_address,
            user_agent=user_agent
        )

        return self

    def delete_with_audit(self, request=None, *args, **kwargs):
        """Delete the model and create an audit log entry."""
        from finance.models import AuditLog

        # Get values before deletion
        old_values = self._get_field_values()
        object_id = self.pk
        object_repr = str(self)[:500]

        # Get request info
        user = request.user if request and request.user.is_authenticated else None
        ip_address = None
        user_agent = ''

        if request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

        # Delete the instance
        self.delete(*args, **kwargs)

        # Create audit log
        AuditLog.objects.create(
            user=user,
            action='delete',
            model_name=self.__class__.__name__,
            object_id=object_id,
            object_repr=object_repr,
            changes={'deleted': old_values},
            ip_address=ip_address,
            user_agent=user_agent
        )
