"""AuditEvent must be immutable and free of any ContentType dependency."""
from django.core.exceptions import ValidationError
from django.test import TestCase

from aegis.core import audit
from aegis.core.models import AuditEvent, PlatformUser, Tenant


class AuditEventTests(TestCase):
    databases = {'default', 'platform'}

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(tenant_code='A', name='Tenant A')
        cls.user = PlatformUser.objects.create(email='a@b.c', display_name='Actor')

    def test_record_event_creates_with_tenant_and_actor_attribution(self):
        event = audit.record_event(
            action='membership.granted', tenant=self.tenant, actor=self.user,
            provider='seed', detail={'k': 'v'},
        )
        self.assertIsNotNone(event.pk)
        self.assertEqual(event.tenant_id, self.tenant.id)
        self.assertEqual(event.actor_id, self.user.id)
        self.assertEqual(event.provider, 'seed')
        self.assertEqual(event.detail, {'k': 'v'})

    def test_record_event_derives_object_metadata(self):
        event = audit.record_event(action='tenant.created', tenant=self.tenant, obj=self.tenant)
        self.assertEqual(event.model_name, 'Tenant')
        self.assertEqual(event.object_id, self.tenant.id)

    def test_modification_is_rejected(self):
        event = audit.record_event(action='x', tenant=self.tenant)
        event.action = 'y'
        with self.assertRaises(ValidationError):
            event.save()

    def test_deletion_is_rejected(self):
        event = audit.record_event(action='x', tenant=self.tenant)
        with self.assertRaises(ValidationError):
            event.delete()

    def test_no_contenttype_dependency(self):
        for field in AuditEvent._meta.get_fields():
            related = getattr(field, 'related_model', None)
            if related is not None:
                self.assertNotEqual(
                    related._meta.app_label, 'contenttypes',
                    f'{field.name} must not relate to contenttypes',
                )
        self.assertEqual(
            AuditEvent._meta.get_field('model_name').get_internal_type(), 'CharField'
        )
