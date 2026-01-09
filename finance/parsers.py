"""
Parsers for extracting structured data from receipt text.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional


class ReceiptParser:
    """
    Parse extracted receipt text to identify vendor, amount, and date.
    """

    # Amount patterns (most specific first)
    AMOUNT_PATTERNS = [
        # Total patterns
        r'(?:total|grand\s*total|amount\s*due|balance\s*due|amount|due)\s*[:\s]*\$?\s*(\d{1,6}(?:[,]\d{3})*(?:\.\d{2})?)',
        # Dollar sign patterns
        r'\$\s*(\d{1,6}(?:[,]\d{3})*(?:\.\d{2}))',
        # USD patterns
        r'(\d{1,6}(?:[,]\d{3})*(?:\.\d{2}))\s*(?:USD|usd)',
        # Standalone decimal amounts (less reliable)
        r'(?:^|\s)(\d{1,4}\.\d{2})(?:\s|$)',
    ]

    # Date patterns
    DATE_PATTERNS = [
        # MM/DD/YYYY or MM-DD-YYYY
        (r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', 'mdy'),
        # YYYY-MM-DD
        (r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', 'ymd'),
        # Month DD, YYYY (e.g., January 15, 2026)
        (r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s*(\d{4})', 'month_name'),
        # Mon DD, YYYY (e.g., Jan 15, 2026)
        (r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s*(\d{4})', 'month_abbr'),
        # DD Mon YYYY (e.g., 15 Jan 2026)
        (r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})', 'dmy_abbr'),
        # MM/DD/YY
        (r'(\d{1,2})[/-](\d{1,2})[/-](\d{2})(?!\d)', 'mdy_short'),
    ]

    MONTH_NAMES = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4,
        'may': 5, 'june': 6, 'july': 7, 'august': 8,
        'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
        'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9,
        'oct': 10, 'nov': 11, 'dec': 12,
    }

    def parse(self, text: str) -> dict:
        """
        Parse receipt text and extract structured data.

        Args:
            text: Raw text extracted from receipt

        Returns:
            Dictionary with vendor, amount, and date (any may be None)
        """
        return {
            'vendor': self.extract_vendor(text),
            'amount': self.extract_amount(text),
            'date': self.extract_date(text),
        }

    def extract_vendor(self, text: str) -> Optional[str]:
        """
        Extract vendor name from receipt text.

        Strategy:
        1. Look for "Merchant:" pattern
        2. Look for common store name patterns
        3. Use first non-empty line as fallback
        """
        if not text:
            return None

        text_lower = text.lower()
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        if not lines:
            return None

        # Look for explicit merchant label (must have colon or be at start of line)
        merchant_patterns = [
            r'(?:^|\n)\s*merchant\s*:\s*(.+?)(?:\n|$)',
            r'(?:^|\n)\s*store\s*:\s*(.+?)(?:\n|$)',
            r'(?:^|\n)\s*sold\s*by\s*:\s*(.+?)(?:\n|$)',
        ]

        for pattern in merchant_patterns:
            match = re.search(pattern, text_lower)
            if match:
                vendor = match.group(1).strip()
                if vendor and len(vendor) > 2:
                    return self._clean_vendor_name(vendor)

        # Use first line as vendor (common receipt format)
        first_line = lines[0]

        # Skip lines that look like dates, amounts, or common headers
        skip_patterns = [
            r'^\d+[/-]\d+[/-]\d+',  # Date
            r'^\$',  # Amount
            r'^receipt$',
            r'^invoice$',
            r'^order$',
            r'^\d+$',  # Just numbers
        ]

        for i, line in enumerate(lines):
            should_skip = False
            for pattern in skip_patterns:
                if re.match(pattern, line.lower()):
                    should_skip = True
                    break
            if not should_skip:
                first_line = line
                break
        else:
            return None

        # Clean and validate
        vendor = self._clean_vendor_name(first_line)
        if vendor and len(vendor) >= 2:
            return vendor

        return None

    def _clean_vendor_name(self, name: str) -> str:
        """Clean up a vendor name string."""
        # Remove common suffixes/prefixes
        name = re.sub(r'\s*(inc\.?|llc|ltd\.?|corp\.?)$', '', name, flags=re.IGNORECASE)

        # Remove extra whitespace
        name = ' '.join(name.split())

        # Title case
        name = name.title()

        # Truncate if too long
        if len(name) > 200:
            name = name[:200]

        return name

    def extract_amount(self, text: str) -> Optional[Decimal]:
        """
        Extract the total amount from receipt text.

        Returns the most likely total amount found.
        """
        if not text:
            return None

        text_lower = text.lower()
        amounts_found = []

        for pattern in self.AMOUNT_PATTERNS:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                try:
                    amount_str = match.group(1).replace(',', '')
                    amount = Decimal(amount_str)
                    if amount > 0:
                        # Store with priority (earlier patterns are more reliable)
                        amounts_found.append(amount)
                except (InvalidOperation, ValueError):
                    continue

        if not amounts_found:
            return None

        # For "total" patterns, prefer the largest amount found
        # as it's likely the grand total
        # For other patterns, prefer the first match
        if len(amounts_found) > 1:
            # Return the largest reasonable amount (under $100,000)
            reasonable = [a for a in amounts_found if a < Decimal('100000')]
            if reasonable:
                return max(reasonable)

        return amounts_found[0] if amounts_found else None

    def extract_date(self, text: str) -> Optional[date]:
        """
        Extract the transaction date from receipt text.

        Returns the first valid date found.
        """
        if not text:
            return None

        for pattern, format_type in self.DATE_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    parsed_date = self._parse_date_match(match, format_type)
                    if parsed_date and self._is_reasonable_date(parsed_date):
                        return parsed_date
                except (ValueError, TypeError):
                    continue

        return None

    def _parse_date_match(self, match, format_type: str) -> Optional[date]:
        """Parse a regex match into a date based on format type."""
        groups = match.groups()

        if format_type == 'mdy':
            month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
        elif format_type == 'mdy_short':
            month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
            # Convert 2-digit year to 4-digit
            year = 2000 + year if year < 100 else year
        elif format_type == 'ymd':
            year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
        elif format_type == 'month_name':
            month = self.MONTH_NAMES.get(groups[0].lower())
            day, year = int(groups[1]), int(groups[2])
        elif format_type == 'month_abbr':
            month = self.MONTH_NAMES.get(groups[0].lower())
            day, year = int(groups[1]), int(groups[2])
        elif format_type == 'dmy_abbr':
            day = int(groups[0])
            month = self.MONTH_NAMES.get(groups[1].lower())
            year = int(groups[2])
        else:
            return None

        if month is None:
            return None

        return date(year, month, day)

    def _is_reasonable_date(self, d: date) -> bool:
        """Check if a date is reasonable (not too far in past or future)."""
        today = date.today()

        # Allow dates from 5 years ago to 1 year in future
        min_date = date(today.year - 5, 1, 1)
        max_date = date(today.year + 1, 12, 31)

        return min_date <= d <= max_date


def parse_receipt_text(text: str) -> dict:
    """
    Convenience function to parse receipt text.

    Args:
        text: Raw text from receipt

    Returns:
        Dictionary with vendor, amount, and date
    """
    parser = ReceiptParser()
    return parser.parse(text)
