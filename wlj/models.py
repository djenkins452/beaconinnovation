# ==============================================================================
# File: models.py
# Project: Beacon Innovations - WLJ Financial Dashboard
# Description: Models for storing WLJ financial projections, service costs,
#              and business metrics. Data imported from WLJ codebase exports.
# Owner: Danny Jenkins (dannyjenkins71@gmail.com)
# Company: Beacon Innovations LLC
# Created: 2025-12-28
# Last Updated: 2025-12-28
# ==============================================================================

from django.db import models
from django.contrib.auth.models import User


class ServiceCost(models.Model):
    """
    Third-party service costs at different growth stages.
    Imported from WLJ docs/business/exports/services_costs.csv
    """
    category = models.CharField(max_length=50)
    provider = models.CharField(max_length=100)
    product = models.CharField(max_length=100)
    purpose = models.CharField(max_length=200)

    cost_1k_low = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_1k_high = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_10k_low = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_10k_high = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_50k_low = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_50k_high = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    current_plan = models.CharField(max_length=100, blank=True)
    recommended_plan = models.CharField(max_length=100, blank=True)
    key_limit = models.CharField(max_length=200, blank=True)
    upgrade_trigger = models.CharField(max_length=200, blank=True)
    source_url = models.URLField(blank=True)
    date_checked = models.DateField(null=True, blank=True)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'provider']
        verbose_name = 'Service Cost'
        verbose_name_plural = 'Service Costs'

    def __str__(self):
        return f"{self.provider} - {self.product}"


class FinancialProjection(models.Model):
    """Multi-year financial projections for different scenarios."""
    SCENARIO_CHOICES = [
        ('conservative', 'Conservative'),
        ('base_case', 'Base Case'),
        ('aggressive', 'Aggressive'),
    ]

    scenario = models.CharField(max_length=20, choices=SCENARIO_CHOICES)
    year = models.IntegerField()
    paying_users = models.IntegerField()
    user_growth_percent = models.DecimalField(max_digits=5, decimal_places=1, null=True)
    arpu = models.DecimalField(max_digits=10, decimal_places=2)
    annual_revenue = models.DecimalField(max_digits=12, decimal_places=2)
    annual_costs = models.DecimalField(max_digits=12, decimal_places=2)
    net_profit = models.DecimalField(max_digits=12, decimal_places=2)
    cumulative_profit = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    team_size = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scenario', 'year']
        unique_together = ['scenario', 'year']
        verbose_name = 'Financial Projection'
        verbose_name_plural = 'Financial Projections'

    def __str__(self):
        return f"{self.get_scenario_display()} - Year {self.year}"


class CodebaseMetric(models.Model):
    """Codebase health and size metrics."""
    captured_at = models.DateTimeField()
    total_tests = models.IntegerField()
    tests_passing = models.IntegerField(null=True)
    total_python_files = models.IntegerField()
    total_lines_of_code = models.IntegerField(null=True)
    total_models = models.IntegerField()
    total_endpoints = models.IntegerField()
    total_apps = models.IntegerField()
    third_party_services = models.IntegerField()
    metrics_json = models.JSONField(default=dict)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-captured_at']
        verbose_name = 'Codebase Metric'
        verbose_name_plural = 'Codebase Metrics'

    def __str__(self):
        return f"Metrics from {self.captured_at.strftime('%Y-%m-%d')}"


class Document(models.Model):
    """Investor documents available for download."""
    DOCUMENT_TYPES = [
        ('executive_summary', 'Executive Summary'),
        ('pitch_deck', 'Pitch Deck'),
        ('financial_model', 'Financial Model'),
        ('cost_analysis', 'Cost Analysis'),
        ('strategic_plan', 'Strategic Plan'),
        ('tech_architecture', 'Technical Architecture'),
        ('other', 'Other'),
    ]

    title = models.CharField(max_length=200)
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPES)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to='wlj/documents/')
    version = models.CharField(max_length=20, default='1.0')
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    download_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['document_type', '-created_at']
        verbose_name = 'Document'
        verbose_name_plural = 'Documents'

    def __str__(self):
        return f"{self.title} (v{self.version})"


class DocumentDownload(models.Model):
    """Track document downloads by user."""
    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    downloaded_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-downloaded_at']

    def __str__(self):
        return f"{self.user.username} downloaded {self.document.title}"
