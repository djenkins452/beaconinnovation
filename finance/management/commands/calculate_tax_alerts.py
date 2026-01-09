"""
Management command to calculate quarterly tax alerts.

Usage:
    python manage.py calculate_tax_alerts
    python manage.py calculate_tax_alerts --quarter 1 --year 2026
    python manage.py calculate_tax_alerts --threshold 1500
"""
from datetime import date
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone
from django.conf import settings
from finance.models import Transaction, TaxAlert


class Command(BaseCommand):
    help = 'Calculate quarterly net profit and create/update tax alerts'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quarter',
            type=int,
            choices=[1, 2, 3, 4],
            help='Specific quarter to calculate (1-4)'
        )
        parser.add_argument(
            '--year',
            type=int,
            help='Specific year to calculate'
        )
        parser.add_argument(
            '--threshold',
            type=Decimal,
            help='Custom threshold amount (default from settings or $1000)'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Recalculate all quarters with transactions'
        )

    def handle(self, *args, **options):
        # Determine threshold
        default_threshold = Decimal(
            getattr(settings, 'FINANCE_TAX_ALERT_THRESHOLD', '1000')
        )
        threshold = options['threshold'] or default_threshold

        self.stdout.write(f'Tax alert threshold: ${threshold}')
        self.stdout.write('')

        if options['all']:
            # Calculate all quarters that have transactions
            self._calculate_all_quarters(threshold)
        elif options['quarter'] and options['year']:
            # Calculate specific quarter
            self._calculate_quarter(options['quarter'], options['year'], threshold)
        else:
            # Calculate current quarter
            today = date.today()
            current_quarter = (today.month - 1) // 3 + 1
            current_year = today.year
            self._calculate_quarter(current_quarter, current_year, threshold)

    def _get_quarter_dates(self, quarter, year):
        """Get start and end dates for a quarter."""
        quarter_starts = {
            1: date(year, 1, 1),
            2: date(year, 4, 1),
            3: date(year, 7, 1),
            4: date(year, 10, 1),
        }
        quarter_ends = {
            1: date(year, 3, 31),
            2: date(year, 6, 30),
            3: date(year, 9, 30),
            4: date(year, 12, 31),
        }
        return quarter_starts[quarter], quarter_ends[quarter]

    def _calculate_quarter(self, quarter, year, threshold):
        """Calculate tax alert for a specific quarter."""
        start_date, end_date = self._get_quarter_dates(quarter, year)

        self.stdout.write(f'Calculating Q{quarter} {year} ({start_date} to {end_date})')

        # Calculate total income
        total_income = Transaction.objects.filter(
            transaction_type='income',
            transaction_date__gte=start_date,
            transaction_date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Calculate total expenses
        total_expenses = Transaction.objects.filter(
            transaction_type='expense',
            transaction_date__gte=start_date,
            transaction_date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Calculate net profit
        net_profit = total_income - total_expenses

        self.stdout.write(f'  Total Income: ${total_income}')
        self.stdout.write(f'  Total Expenses: ${total_expenses}')
        self.stdout.write(f'  Net Profit: ${net_profit}')

        # Determine if alert should be triggered
        alert_triggered = net_profit >= threshold

        # Get or create the tax alert
        alert, created = TaxAlert.objects.get_or_create(
            quarter=quarter,
            year=year,
            defaults={
                'threshold_amount': threshold,
                'actual_net_profit': net_profit,
                'alert_triggered': alert_triggered,
                'alert_date': timezone.now() if alert_triggered else None,
            }
        )

        if not created:
            # Update existing alert
            old_triggered = alert.alert_triggered
            alert.threshold_amount = threshold
            alert.actual_net_profit = net_profit
            alert.alert_triggered = alert_triggered

            # Set alert_date if newly triggered
            if alert_triggered and not old_triggered:
                alert.alert_date = timezone.now()

            alert.save()

        # Output result
        if alert_triggered:
            self.stdout.write(
                self.style.WARNING(
                    f'  ⚠️  ALERT: Net profit ${net_profit} exceeds threshold ${threshold}'
                )
            )
            self._show_estimated_tax_due(quarter, year)
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'  ✓ Net profit ${net_profit} is below threshold ${threshold}'
                )
            )

        return alert

    def _calculate_all_quarters(self, threshold):
        """Calculate tax alerts for all quarters with transactions."""
        # Find the date range of all transactions
        first_transaction = Transaction.objects.order_by('transaction_date').first()
        last_transaction = Transaction.objects.order_by('-transaction_date').first()

        if not first_transaction or not last_transaction:
            self.stdout.write('No transactions found.')
            return

        start_date = first_transaction.transaction_date
        end_date = last_transaction.transaction_date

        # Iterate through all quarters in range
        current_year = start_date.year
        current_quarter = (start_date.month - 1) // 3 + 1

        while (current_year < end_date.year or
               (current_year == end_date.year and
                current_quarter <= (end_date.month - 1) // 3 + 1)):

            self._calculate_quarter(current_quarter, current_year, threshold)
            self.stdout.write('')

            # Move to next quarter
            current_quarter += 1
            if current_quarter > 4:
                current_quarter = 1
                current_year += 1

    def _show_estimated_tax_due(self, quarter, year):
        """Show estimated tax payment due date."""
        # IRS estimated tax due dates
        due_dates = {
            1: f'April 15, {year}',
            2: f'June 15, {year}',
            3: f'September 15, {year}',
            4: f'January 15, {year + 1}',
        }
        self.stdout.write(
            f'  📅 Estimated tax payment due: {due_dates[quarter]}'
        )
