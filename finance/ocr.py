"""
OCR processing module for receipt text extraction using Tesseract.
"""
import io
import logging
from decimal import Decimal
from typing import Optional

try:
    import pytesseract
    from PIL import Image, ImageOps, ImageFilter, ImageEnhance
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

from .parsers import ReceiptParser

logger = logging.getLogger(__name__)


class OCRProcessor:
    """Process images using Tesseract OCR with preprocessing."""

    def __init__(self):
        if not TESSERACT_AVAILABLE:
            raise ImportError(
                "pytesseract and Pillow are required for OCR. "
                "Install with: pip install pytesseract Pillow"
            )

    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Apply preprocessing to improve OCR accuracy.

        Steps:
        1. Convert to grayscale
        2. Enhance contrast
        3. Apply slight sharpening
        4. Deskew if needed (simple approach)
        """
        # Convert to grayscale
        if image.mode != 'L':
            image = image.convert('L')

        # Enhance contrast
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.5)

        # Enhance sharpness
        enhancer = ImageEnhance.Sharpness(image)
        image = enhancer.enhance(1.5)

        # Apply slight threshold to clean up
        # This helps with low-quality scans
        image = image.point(lambda x: 0 if x < 140 else 255)

        return image

    def extract_text(self, image_file) -> tuple[str, float]:
        """
        Extract text from an image file.

        Args:
            image_file: File-like object or path to image

        Returns:
            Tuple of (extracted_text, confidence_score)
        """
        try:
            # Open the image
            if hasattr(image_file, 'read'):
                image = Image.open(image_file)
            else:
                image = Image.open(image_file)

            # Preprocess
            processed = self.preprocess_image(image)

            # Extract text with detailed data for confidence
            data = pytesseract.image_to_data(
                processed,
                lang='eng',
                output_type=pytesseract.Output.DICT
            )

            # Build text from words
            words = []
            confidences = []
            for i, word in enumerate(data['text']):
                if word.strip():
                    words.append(word)
                    conf = data['conf'][i]
                    if conf != -1:  # -1 means no confidence available
                        confidences.append(conf)

            text = ' '.join(words)

            # Calculate average confidence (0-100 from tesseract, convert to 0-1)
            if confidences:
                avg_confidence = sum(confidences) / len(confidences) / 100.0
            else:
                avg_confidence = 0.0

            return text, avg_confidence

        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            raise OCRError(f"Failed to extract text: {e}")

    def extract_text_simple(self, image_file) -> str:
        """
        Simple text extraction without confidence scoring.

        Args:
            image_file: File-like object or path to image

        Returns:
            Extracted text string
        """
        try:
            if hasattr(image_file, 'read'):
                image = Image.open(image_file)
            else:
                image = Image.open(image_file)

            processed = self.preprocess_image(image)
            text = pytesseract.image_to_string(processed, lang='eng')
            return text.strip()

        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            raise OCRError(f"Failed to extract text: {e}")


class OCRError(Exception):
    """Exception raised for OCR processing errors."""
    pass


class ReceiptOCR:
    """
    High-level receipt OCR processing that combines
    text extraction and parsing.
    """

    def __init__(self):
        self.processor = OCRProcessor()
        self.parser = ReceiptParser()

    def process_receipt(self, image_file) -> dict:
        """
        Process a receipt image and extract structured data.

        Args:
            image_file: File-like object or path to image

        Returns:
            Dictionary with:
            - raw_text: Full extracted text
            - vendor: Suggested vendor name (or None)
            - amount: Suggested amount as Decimal (or None)
            - date: Suggested date as date object (or None)
            - confidence: OCR confidence score (0.0-1.0)
        """
        # Extract text with confidence
        raw_text, confidence = self.processor.extract_text(image_file)

        # Parse the extracted text
        parsed = self.parser.parse(raw_text)

        return {
            'raw_text': raw_text,
            'vendor': parsed.get('vendor'),
            'amount': parsed.get('amount'),
            'date': parsed.get('date'),
            'confidence': Decimal(str(round(confidence, 2))),
        }


def process_receipt_image(image_file) -> dict:
    """
    Convenience function to process a receipt image.

    Args:
        image_file: File-like object or path to image

    Returns:
        Dictionary with extracted receipt data
    """
    ocr = ReceiptOCR()
    return ocr.process_receipt(image_file)


def is_tesseract_available() -> bool:
    """Check if Tesseract is available on the system."""
    if not TESSERACT_AVAILABLE:
        return False

    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
