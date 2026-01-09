"""
Forms for the finance app.
"""
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from .models import Receipt


class ReceiptUploadForm(forms.ModelForm):
    """Form for uploading receipt files."""

    class Meta:
        model = Receipt
        fields = ['file']

    def clean_file(self):
        """Validate uploaded file type and size."""
        file = self.cleaned_data.get('file')

        if not file:
            raise ValidationError('No file was uploaded.')

        # Check file size
        max_size_bytes = settings.FINANCE_RECEIPT_MAX_SIZE_MB * 1024 * 1024
        if file.size > max_size_bytes:
            raise ValidationError(
                f'File too large. Maximum size is {settings.FINANCE_RECEIPT_MAX_SIZE_MB}MB.'
            )

        # Get file extension
        filename = file.name.lower()
        extension = filename.rsplit('.', 1)[-1] if '.' in filename else ''

        # Check file type
        allowed_types = settings.FINANCE_ALLOWED_RECEIPT_TYPES
        if extension not in allowed_types:
            raise ValidationError(
                f'Invalid file type. Allowed types: {", ".join(allowed_types)}'
            )

        return file


def get_file_type(filename: str) -> str:
    """
    Get the file type from a filename.

    Returns 'jpg' for both .jpg and .jpeg extensions.
    """
    extension = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''

    if extension == 'jpeg':
        return 'jpg'

    return extension


def validate_receipt_file(file) -> dict:
    """
    Validate a receipt file and return file info.

    Args:
        file: Uploaded file object

    Returns:
        Dictionary with:
        - valid: bool
        - error: str or None
        - file_type: str (if valid)
        - file_size: int (if valid)
        - original_filename: str (if valid)

    Raises:
        ValidationError if file is invalid
    """
    if not file:
        return {
            'valid': False,
            'error': 'No file was uploaded.',
        }

    # Check file size
    max_size_bytes = settings.FINANCE_RECEIPT_MAX_SIZE_MB * 1024 * 1024
    if file.size > max_size_bytes:
        return {
            'valid': False,
            'error': f'File too large. Maximum size is {settings.FINANCE_RECEIPT_MAX_SIZE_MB}MB.',
        }

    # Get file extension
    filename = file.name
    extension = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''

    # Check file type
    allowed_types = settings.FINANCE_ALLOWED_RECEIPT_TYPES
    if extension not in allowed_types:
        return {
            'valid': False,
            'error': f'Invalid file type. Allowed types: {", ".join(allowed_types)}',
        }

    # Normalize extension
    file_type = 'jpg' if extension == 'jpeg' else extension

    return {
        'valid': True,
        'error': None,
        'file_type': file_type,
        'file_size': file.size,
        'original_filename': filename,
    }
