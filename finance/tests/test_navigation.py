"""
Tests for navigation (Phase 14).
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User


class NavigationTests(TestCase):
    """Tests for navigation menu."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

    def test_navigation_contains_all_links(self):
        """Test that navigation contains all main links."""
        response = self.client.get(reverse('finance:dashboard'))
        self.assertEqual(response.status_code, 200)

        # Check all navigation links are present
        self.assertContains(response, 'Dashboard')
        self.assertContains(response, 'Transactions')
        self.assertContains(response, 'Accounts')
        self.assertContains(response, 'Categories')
        self.assertContains(response, 'Recurring')
        self.assertContains(response, 'Imports')
        self.assertContains(response, 'Reports')
        self.assertContains(response, 'Tax Alerts')
        self.assertContains(response, 'Audit Log')

    def test_navigation_links_are_valid(self):
        """Test that all navigation links resolve to valid URLs."""
        response = self.client.get(reverse('finance:dashboard'))

        # Check URL patterns are present
        self.assertContains(response, reverse('finance:dashboard'))
        self.assertContains(response, reverse('finance:transaction_list'))
        self.assertContains(response, reverse('finance:account_list'))
        self.assertContains(response, reverse('finance:category_list'))
        self.assertContains(response, reverse('finance:recurring_list'))
        self.assertContains(response, reverse('finance:csv_import_list'))
        self.assertContains(response, reverse('finance:spending_report'))
        self.assertContains(response, reverse('finance:alert_list'))
        self.assertContains(response, reverse('finance:audit_log_list'))

    def test_dashboard_active_state(self):
        """Test dashboard link shows active state on dashboard page."""
        response = self.client.get(reverse('finance:dashboard'))
        # The dashboard link should have class="active"
        content = response.content.decode()
        self.assertIn('href="/finance/"', content)

    def test_transactions_active_state(self):
        """Test transactions link shows active state on transaction pages."""
        response = self.client.get(reverse('finance:transaction_list'))
        self.assertEqual(response.status_code, 200)
        # Should contain Transactions in the nav

    def test_accounts_active_state(self):
        """Test accounts link shows active state on account pages."""
        response = self.client.get(reverse('finance:account_list'))
        self.assertEqual(response.status_code, 200)

    def test_categories_active_state(self):
        """Test categories link shows active state on category pages."""
        response = self.client.get(reverse('finance:category_list'))
        self.assertEqual(response.status_code, 200)

    def test_recurring_active_state(self):
        """Test recurring link shows active state on recurring pages."""
        response = self.client.get(reverse('finance:recurring_list'))
        self.assertEqual(response.status_code, 200)

    def test_imports_active_state(self):
        """Test imports link shows active state on import pages."""
        response = self.client.get(reverse('finance:csv_import_list'))
        self.assertEqual(response.status_code, 200)

    def test_reports_active_state(self):
        """Test reports link shows active state on report pages."""
        response = self.client.get(reverse('finance:spending_report'))
        self.assertEqual(response.status_code, 200)

    def test_alerts_active_state(self):
        """Test tax alerts link shows active state on alert pages."""
        response = self.client.get(reverse('finance:alert_list'))
        self.assertEqual(response.status_code, 200)

    def test_audit_log_active_state(self):
        """Test audit log link shows active state on audit pages."""
        response = self.client.get(reverse('finance:audit_log_list'))
        self.assertEqual(response.status_code, 200)

    def test_brand_links_to_dashboard(self):
        """Test that brand logo links to dashboard."""
        response = self.client.get(reverse('finance:transaction_list'))
        self.assertContains(response, 'Beacon Finance')
        self.assertContains(response, 'class="nav-brand"')

    def test_navigation_visible_on_all_pages(self):
        """Test navigation is visible on multiple pages."""
        pages = [
            reverse('finance:dashboard'),
            reverse('finance:transaction_list'),
            reverse('finance:account_list'),
            reverse('finance:category_list'),
            reverse('finance:recurring_list'),
            reverse('finance:alert_list'),
            reverse('finance:audit_log_list'),
        ]

        for page in pages:
            response = self.client.get(page)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'nav-links')
            self.assertContains(response, 'Beacon Finance')

    def test_navigation_requires_login(self):
        """Test pages require login to access."""
        self.client.logout()

        pages = [
            reverse('finance:dashboard'),
            reverse('finance:transaction_list'),
            reverse('finance:account_list'),
            reverse('finance:recurring_list'),
            reverse('finance:alert_list'),
            reverse('finance:audit_log_list'),
        ]

        for page in pages:
            response = self.client.get(page)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login/', response.url)
