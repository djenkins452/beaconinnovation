"""
Management command to generate transactions from recurring templates.

Usage:
    python manage.py generate_recurring
    python manage.py generate_recurring --dry-run
    python manage.py generate_recurring --date 2026-01-15
"""
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from finance.models import RecurringTransaction, Transaction


class Command(BaseCommand):
    help = 'Generate transactions from recurring transaction templates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be generated without creating transactions'
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Process as if today is this date (YYYY-MM-DD format)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Determine the effective date
        if options['date']:
            try:
                effective_date = date.fromisoformat(options['date'])
            except ValueError:
                self.stderr.write(self.style.ERROR(f'Invalid date format: {options["date"]}'))
                return
        else:
            effective_date = date.today()

        self.stdout.write(f'Processing recurring transactions for {effective_date}')

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No transactions will be created'))

        # Get all active recurring transactions that are due
        recurring_templates = RecurringTransaction.objects.filter(
            is_active=True,
            next_due__lte=effective_date
        ).select_related('account', 'category')

        if not recurring_templates.exists():
            self.stdout.write('No recurring transactions due for processing.')
            return

        created_count = 0
        skipped_count = 0

        for template in recurring_templates:
            # Check if end_date has passed
            if template.end_date and template.end_date < effective_date:
                self.stdout.write(
                    f'  Skipping {template.vendor} - end date {template.end_date} has passed'
                )
                skipped_count += 1
                continue

            # Generate transactions for all due periods
            while template.next_due <= effective_date:
                if not dry_run:
                    # Create the transaction
                    transaction = Transaction.objects.create(
                        account=template.account,
                        transaction_type='expense',
                        category=template.category,
                        amount=template.amount,
                        transaction_date=template.next_due,
                        description=template.description,
                        vendor=template.vendor,
                        is_recurring=True,
                        recurring_source=template,
                        notes=f'Auto-generated from recurring template'
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  Created: {template.vendor} - ${template.amount} on {template.next_due}'
                        )
                    )
                else:
                    self.stdout.write(
                        f'  Would create: {template.vendor} - ${template.amount} on {template.next_due}'
                    )

                created_count += 1

                # Calculate next due date
                next_due = self._calculate_next_due(template)

                if not dry_run:
                    template.last_generated = template.next_due
                    template.next_due = next_due
                    template.save(update_fields=['last_generated', 'next_due', 'updated_at'])

                # For dry run, manually advance to prevent infinite loop
                if dry_run:
                    template.next_due = next_due

                # Check if we've passed the end date
                if template.end_date and next_due > template.end_date:
                    if not dry_run:
                        template.is_active = False
                        template.save(update_fields=['is_active', 'updated_at'])
                    self.stdout.write(
                        f'  Deactivating {template.vendor} - end date reached'
                    )
                    break

        self.stdout.write('')
        self.stdout.write(f'Summary:')
        self.stdout.write(f'  Transactions {"would be " if dry_run else ""}created: {created_count}')
        self.stdout.write(f'  Templates skipped: {skipped_count}')

    def _calculate_next_due(self, template):
        """Calculate the next due date based on frequency."""
        current_due = template.next_due

        if template.frequency == 'monthly':
            # Add one month
            next_due = current_due + relativedelta(months=1)
            # Adjust to the specified day of month
            try:
                next_due = next_due.replace(day=template.day_of_month)
            except ValueError:
                # Handle months with fewer days (e.g., Feb 30 -> Feb 28)
                last_day = (next_due.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).day
                next_due = next_due.replace(day=min(template.day_of_month, last_day))

        elif template.frequency == 'quarterly':
            # Add three months
            next_due = current_due + relativedelta(months=3)
            try:
                next_due = next_due.replace(day=template.day_of_month)
            except ValueError:
                last_day = (next_due.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).day
                next_due = next_due.replace(day=min(template.day_of_month, last_day))

        elif template.frequency == 'annually':
            # Add one year
            next_due = current_due + relativedelta(years=1)
            try:
                next_due = next_due.replace(day=template.day_of_month)
            except ValueError:
                # Handle leap year edge case (Feb 29)
                last_day = (next_due.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).day
                next_due = next_due.replace(day=min(template.day_of_month, last_day))

        return next_due
