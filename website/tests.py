from django.test import TestCase
from django.urls import reverse


class HealthzTests(TestCase):
    def test_healthz_reports_ok_and_context_copy_works(self):
        resp = self.client.get(reverse('healthz'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # On a supported Python the template context-copy path works.
        self.assertTrue(data['context_copy_ok'])
        self.assertEqual(data['status'], 'ok')
        self.assertIn('python', data)
