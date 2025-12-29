# ==============================================================================
# File: 0003_load_initial_data.py
# Project: Beacon Innovations - WLJ Financial Dashboard
# Description: Data migration to load financial projections and service costs
# Owner: Danny Jenkins (dannyjenkins71@gmail.com)
# Created: 2025-12-28
# ==============================================================================

from decimal import Decimal
from django.db import migrations
from django.utils import timezone


def load_financial_projections(apps, schema_editor):
    FinancialProjection = apps.get_model('wlj', 'FinancialProjection')

    # Clear existing projections
    FinancialProjection.objects.all().delete()

    projections = [
        # Conservative Scenario
        {'scenario': 'conservative', 'year': 2026, 'paying_users': 520, 'user_growth_percent': None, 'arpu': Decimal('79'), 'annual_revenue': Decimal('41080'), 'annual_costs': Decimal('12000'), 'net_profit': Decimal('29080'), 'cumulative_profit': Decimal('29080'), 'team_size': Decimal('1')},
        {'scenario': 'conservative', 'year': 2027, 'paying_users': 2000, 'user_growth_percent': Decimal('285'), 'arpu': Decimal('82'), 'annual_revenue': Decimal('164000'), 'annual_costs': Decimal('45000'), 'net_profit': Decimal('119000'), 'cumulative_profit': Decimal('148080'), 'team_size': Decimal('1')},
        {'scenario': 'conservative', 'year': 2028, 'paying_users': 5000, 'user_growth_percent': Decimal('150'), 'arpu': Decimal('85'), 'annual_revenue': Decimal('425000'), 'annual_costs': Decimal('120000'), 'net_profit': Decimal('305000'), 'cumulative_profit': Decimal('453080'), 'team_size': Decimal('2')},
        {'scenario': 'conservative', 'year': 2029, 'paying_users': 10000, 'user_growth_percent': Decimal('100'), 'arpu': Decimal('89'), 'annual_revenue': Decimal('890000'), 'annual_costs': Decimal('200000'), 'net_profit': Decimal('690000'), 'cumulative_profit': Decimal('1143080'), 'team_size': Decimal('3')},
        {'scenario': 'conservative', 'year': 2030, 'paying_users': 15000, 'user_growth_percent': Decimal('50'), 'arpu': Decimal('95'), 'annual_revenue': Decimal('1425000'), 'annual_costs': Decimal('350000'), 'net_profit': Decimal('1075000'), 'cumulative_profit': Decimal('2218080'), 'team_size': Decimal('4')},

        # Base Case Scenario
        {'scenario': 'base_case', 'year': 2026, 'paying_users': 1050, 'user_growth_percent': None, 'arpu': Decimal('79'), 'annual_revenue': Decimal('82950'), 'annual_costs': Decimal('18000'), 'net_profit': Decimal('64950'), 'cumulative_profit': Decimal('64950'), 'team_size': Decimal('1')},
        {'scenario': 'base_case', 'year': 2027, 'paying_users': 4500, 'user_growth_percent': Decimal('329'), 'arpu': Decimal('85'), 'annual_revenue': Decimal('382500'), 'annual_costs': Decimal('85000'), 'net_profit': Decimal('297500'), 'cumulative_profit': Decimal('362450'), 'team_size': Decimal('2')},
        {'scenario': 'base_case', 'year': 2028, 'paying_users': 12000, 'user_growth_percent': Decimal('167'), 'arpu': Decimal('89'), 'annual_revenue': Decimal('1068000'), 'annual_costs': Decimal('280000'), 'net_profit': Decimal('788000'), 'cumulative_profit': Decimal('1150450'), 'team_size': Decimal('4')},
        {'scenario': 'base_case', 'year': 2029, 'paying_users': 25000, 'user_growth_percent': Decimal('108'), 'arpu': Decimal('95'), 'annual_revenue': Decimal('2375000'), 'annual_costs': Decimal('650000'), 'net_profit': Decimal('1725000'), 'cumulative_profit': Decimal('2875450'), 'team_size': Decimal('5')},
        {'scenario': 'base_case', 'year': 2030, 'paying_users': 40000, 'user_growth_percent': Decimal('60'), 'arpu': Decimal('99'), 'annual_revenue': Decimal('3960000'), 'annual_costs': Decimal('1200000'), 'net_profit': Decimal('2760000'), 'cumulative_profit': Decimal('5635450'), 'team_size': Decimal('7')},

        # Aggressive Scenario
        {'scenario': 'aggressive', 'year': 2026, 'paying_users': 2350, 'user_growth_percent': None, 'arpu': Decimal('79'), 'annual_revenue': Decimal('185650'), 'annual_costs': Decimal('36000'), 'net_profit': Decimal('149650'), 'cumulative_profit': Decimal('149650'), 'team_size': Decimal('1')},
        {'scenario': 'aggressive', 'year': 2027, 'paying_users': 12000, 'user_growth_percent': Decimal('411'), 'arpu': Decimal('89'), 'annual_revenue': Decimal('1068000'), 'annual_costs': Decimal('250000'), 'net_profit': Decimal('818000'), 'cumulative_profit': Decimal('967650'), 'team_size': Decimal('4')},
        {'scenario': 'aggressive', 'year': 2028, 'paying_users': 30000, 'user_growth_percent': Decimal('150'), 'arpu': Decimal('95'), 'annual_revenue': Decimal('2850000'), 'annual_costs': Decimal('850000'), 'net_profit': Decimal('2000000'), 'cumulative_profit': Decimal('2967650'), 'team_size': Decimal('8')},
        {'scenario': 'aggressive', 'year': 2029, 'paying_users': 60000, 'user_growth_percent': Decimal('100'), 'arpu': Decimal('99'), 'annual_revenue': Decimal('5940000'), 'annual_costs': Decimal('2000000'), 'net_profit': Decimal('3940000'), 'cumulative_profit': Decimal('6907650'), 'team_size': Decimal('15')},
        {'scenario': 'aggressive', 'year': 2030, 'paying_users': 100000, 'user_growth_percent': Decimal('67'), 'arpu': Decimal('105'), 'annual_revenue': Decimal('10500000'), 'annual_costs': Decimal('4000000'), 'net_profit': Decimal('6500000'), 'cumulative_profit': Decimal('13407650'), 'team_size': Decimal('25')},
    ]

    for proj in projections:
        FinancialProjection.objects.create(**proj)

    print(f'Created {len(projections)} financial projections.')


def load_service_costs(apps, schema_editor):
    ServiceCost = apps.get_model('wlj', 'ServiceCost')

    # Clear existing costs
    ServiceCost.objects.all().delete()

    from datetime import date

    costs = [
        {'category': 'Hosting', 'provider': 'Railway', 'product': 'App Platform', 'purpose': 'Web application hosting', 'cost_1k_low': Decimal('8'), 'cost_1k_high': Decimal('15'), 'cost_10k_low': Decimal('25'), 'cost_10k_high': Decimal('50'), 'cost_50k_low': Decimal('80'), 'cost_50k_high': Decimal('150'), 'current_plan': 'Hobby ($5)', 'recommended_plan': 'Pro ($20)', 'key_limit': '8GB RAM/8vCPU', 'upgrade_trigger': 'Sustained >50% resource usage', 'source_url': 'https://docs.railway.com/reference/pricing', 'date_checked': date(2025, 12, 28)},
        {'category': 'Database', 'provider': 'Railway', 'product': 'PostgreSQL', 'purpose': 'Primary data store', 'cost_1k_low': Decimal('2'), 'cost_1k_high': Decimal('5'), 'cost_10k_low': Decimal('10'), 'cost_10k_high': Decimal('20'), 'cost_50k_low': Decimal('30'), 'cost_50k_high': Decimal('60'), 'current_plan': 'Included', 'recommended_plan': 'Included + volume', 'key_limit': '1GB included', 'upgrade_trigger': '>1GB storage', 'source_url': 'https://docs.railway.com/reference/pricing', 'date_checked': date(2025, 12, 28)},
        {'category': 'AI/LLM', 'provider': 'OpenAI', 'product': 'GPT-4o-mini', 'purpose': 'Dashboard insights/coaching', 'cost_1k_low': Decimal('15'), 'cost_1k_high': Decimal('75'), 'cost_10k_low': Decimal('150'), 'cost_10k_high': Decimal('750'), 'cost_50k_low': Decimal('750'), 'cost_50k_high': Decimal('3750'), 'current_plan': 'Pay-as-you-go', 'recommended_plan': 'Pay-as-you-go', 'key_limit': 'None', 'upgrade_trigger': 'N/A', 'source_url': 'https://platform.openai.com/docs/pricing', 'date_checked': date(2025, 12, 28)},
        {'category': 'AI/LLM', 'provider': 'OpenAI', 'product': 'GPT-4o (Vision)', 'purpose': 'AI Camera scanning', 'cost_1k_low': Decimal('15'), 'cost_1k_high': Decimal('75'), 'cost_10k_low': Decimal('150'), 'cost_10k_high': Decimal('750'), 'cost_50k_low': Decimal('750'), 'cost_50k_high': Decimal('3750'), 'current_plan': 'Pay-as-you-go', 'recommended_plan': 'Pay-as-you-go', 'key_limit': 'None', 'upgrade_trigger': 'N/A', 'source_url': 'https://platform.openai.com/docs/pricing', 'date_checked': date(2025, 12, 28)},
        {'category': 'Media Storage', 'provider': 'Cloudinary', 'product': 'Image/Video CDN', 'purpose': 'Avatars, scans, uploads', 'cost_1k_low': Decimal('0'), 'cost_1k_high': Decimal('0'), 'cost_10k_low': Decimal('89'), 'cost_10k_high': Decimal('150'), 'cost_50k_low': Decimal('400'), 'cost_50k_high': Decimal('600'), 'current_plan': 'Free (25 credits)', 'recommended_plan': 'Plus ($89)', 'key_limit': '25GB total', 'upgrade_trigger': '>25GB storage or bandwidth', 'source_url': 'https://cloudinary.com/pricing', 'date_checked': date(2025, 12, 28)},
        {'category': 'Email', 'provider': 'Resend', 'product': 'Transactional Email', 'purpose': 'Password reset, notifications', 'cost_1k_low': Decimal('0'), 'cost_1k_high': Decimal('20'), 'cost_10k_low': Decimal('20'), 'cost_10k_high': Decimal('90'), 'cost_50k_low': Decimal('90'), 'cost_50k_high': Decimal('200'), 'current_plan': 'Free (3K/mo)', 'recommended_plan': 'Pro ($20)', 'key_limit': '3000 emails/mo', 'upgrade_trigger': '>3000 emails/mo', 'source_url': 'https://resend.com/pricing', 'date_checked': date(2025, 12, 28)},
        {'category': 'Scripture', 'provider': 'API.Bible', 'product': 'Bible API', 'purpose': 'Verse lookups for Faith module', 'cost_1k_low': Decimal('0'), 'cost_1k_high': Decimal('0'), 'cost_10k_low': Decimal('0'), 'cost_10k_high': Decimal('0'), 'cost_50k_low': Decimal('0'), 'cost_50k_high': Decimal('0'), 'current_plan': 'Free', 'recommended_plan': 'Free', 'key_limit': 'Generous', 'upgrade_trigger': 'N/A', 'source_url': 'https://docs.api.bible', 'date_checked': date(2025, 12, 28)},
        {'category': 'Calendar', 'provider': 'Google', 'product': 'Calendar API', 'purpose': 'Task/event sync', 'cost_1k_low': Decimal('0'), 'cost_1k_high': Decimal('0'), 'cost_10k_low': Decimal('0'), 'cost_10k_high': Decimal('0'), 'cost_50k_low': Decimal('0'), 'cost_50k_high': Decimal('0'), 'current_plan': 'Free', 'recommended_plan': 'Free', 'key_limit': 'Standard quotas', 'upgrade_trigger': 'N/A', 'source_url': 'https://developers.google.com', 'date_checked': date(2025, 12, 28)},
        {'category': 'Auth', 'provider': 'W3C', 'product': 'WebAuthn', 'purpose': 'Biometric login', 'cost_1k_low': Decimal('0'), 'cost_1k_high': Decimal('0'), 'cost_10k_low': Decimal('0'), 'cost_10k_high': Decimal('0'), 'cost_50k_low': Decimal('0'), 'cost_50k_high': Decimal('0'), 'current_plan': 'Free (browser)', 'recommended_plan': 'Free (browser)', 'key_limit': 'Browser support', 'upgrade_trigger': 'N/A', 'source_url': '', 'date_checked': date(2025, 12, 28)},
        {'category': 'CDN/JS', 'provider': 'Open Source', 'product': 'HTMX/Chart.js', 'purpose': 'Frontend interactivity', 'cost_1k_low': Decimal('0'), 'cost_1k_high': Decimal('0'), 'cost_10k_low': Decimal('0'), 'cost_10k_high': Decimal('0'), 'cost_50k_low': Decimal('0'), 'cost_50k_high': Decimal('0'), 'current_plan': 'Free (OSS)', 'recommended_plan': 'Free (OSS)', 'key_limit': 'None', 'upgrade_trigger': 'N/A', 'source_url': '', 'date_checked': date(2025, 12, 28)},
        {'category': 'Payments', 'provider': 'Stripe', 'product': 'Payment Processing', 'purpose': 'Subscription billing', 'cost_1k_low': Decimal('0'), 'cost_1k_high': Decimal('0'), 'cost_10k_low': Decimal('0'), 'cost_10k_high': Decimal('0'), 'cost_50k_low': Decimal('0'), 'cost_50k_high': Decimal('0'), 'current_plan': 'Standard (2.9%+30c)', 'recommended_plan': 'Standard', 'key_limit': 'None', 'upgrade_trigger': 'N/A', 'source_url': 'https://stripe.com/pricing', 'date_checked': date(2025, 12, 28)},
        {'category': 'Errors', 'provider': 'Sentry', 'product': 'Error Tracking', 'purpose': 'Bug detection', 'cost_1k_low': Decimal('0'), 'cost_1k_high': Decimal('0'), 'cost_10k_low': Decimal('0'), 'cost_10k_high': Decimal('26'), 'cost_50k_low': Decimal('26'), 'cost_50k_high': Decimal('80'), 'current_plan': 'Developer (Free)', 'recommended_plan': 'Team ($26)', 'key_limit': '5000 errors/mo', 'upgrade_trigger': '>5000 errors/mo', 'source_url': 'https://sentry.io/pricing', 'date_checked': date(2025, 12, 28)},
        {'category': 'Analytics', 'provider': 'PostHog', 'product': 'Product Analytics', 'purpose': 'User behavior tracking', 'cost_1k_low': Decimal('0'), 'cost_1k_high': Decimal('0'), 'cost_10k_low': Decimal('0'), 'cost_10k_high': Decimal('0'), 'cost_50k_low': Decimal('0'), 'cost_50k_high': Decimal('50'), 'current_plan': 'Free (1M events)', 'recommended_plan': 'Free', 'key_limit': '1M events/mo', 'upgrade_trigger': '>1M events/mo', 'source_url': 'https://posthog.com/pricing', 'date_checked': date(2025, 12, 28)},
        {'category': 'Domain', 'provider': 'Cloudflare', 'product': 'DNS + CDN', 'purpose': 'Domain management', 'cost_1k_low': Decimal('1'), 'cost_1k_high': Decimal('1'), 'cost_10k_low': Decimal('1'), 'cost_10k_high': Decimal('1'), 'cost_50k_low': Decimal('2'), 'cost_50k_high': Decimal('20'), 'current_plan': 'Free', 'recommended_plan': 'Pro at scale', 'key_limit': 'N/A', 'upgrade_trigger': 'DDoS protection needs', 'source_url': 'https://cloudflare.com', 'date_checked': date(2025, 12, 28)},
        {'category': 'Email Inbox', 'provider': 'Google', 'product': 'Workspace', 'purpose': 'Support email inbox', 'cost_1k_low': Decimal('0'), 'cost_1k_high': Decimal('6'), 'cost_10k_low': Decimal('6'), 'cost_10k_high': Decimal('6'), 'cost_50k_low': Decimal('6'), 'cost_50k_high': Decimal('6'), 'current_plan': 'None', 'recommended_plan': 'Starter ($6)', 'key_limit': 'N/A', 'upgrade_trigger': 'Professional support needs', 'source_url': 'https://workspace.google.com', 'date_checked': date(2025, 12, 28)},
    ]

    for cost in costs:
        ServiceCost.objects.create(**cost)

    print(f'Created {len(costs)} service cost entries.')


def load_codebase_metrics(apps, schema_editor):
    CodebaseMetric = apps.get_model('wlj', 'CodebaseMetric')

    # Add initial codebase metrics snapshot
    CodebaseMetric.objects.create(
        captured_at=timezone.now(),
        total_tests=1045,
        tests_passing=1045,
        total_python_files=150,
        total_lines_of_code=25000,
        total_models=45,
        total_endpoints=120,
        total_apps=12,
        third_party_services=19,
        metrics_json={
            'django_version': '5.x',
            'python_version': '3.14',
            'test_coverage': '85%',
            'deployment': 'Railway',
            'database': 'PostgreSQL',
        }
    )
    print('Created initial codebase metrics snapshot.')


def reverse_data(apps, schema_editor):
    # Don't delete data on reverse
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('wlj', '0002_create_superuser'),
    ]

    operations = [
        migrations.RunPython(load_financial_projections, reverse_data),
        migrations.RunPython(load_service_costs, reverse_data),
        migrations.RunPython(load_codebase_metrics, reverse_data),
    ]
