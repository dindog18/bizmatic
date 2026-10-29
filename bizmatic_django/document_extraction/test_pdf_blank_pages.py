from pathlib import Path
from tempfile import TemporaryDirectory

import pymupdf
from django.test import SimpleTestCase

from document_extraction.services.documents import extract_pdf_to_markdown


class PDFBlankPagesTests(SimpleTestCase):
    def test_blank_separator_and_trailing_pages_preserve_text_and_page_numbers(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'invoice.pdf'
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((72, 72), 'Invoice 100')
                pdf.new_page()
                pdf.new_page().insert_text((72, 72), 'Invoice continued')
                pdf.new_page()
                pdf.save(path)
            result = extract_pdf_to_markdown(path)
            self.assertIn('## Page 1\n\nInvoice 100', result)
            self.assertIn('## Page 3\n\nInvoice continued', result)
            self.assertNotIn('## Page 2', result)

    def test_visible_image_only_page_still_requires_ocr(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'scan.pdf'
            image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
            image.clear_with(0)
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((72, 72), 'Invoice 100')
                pdf.new_page().insert_image(pymupdf.Rect(72, 72, 92, 92), stream=image.tobytes('png'))
                pdf.save(path)
            with self.assertRaisesMessage(ValueError, 'Page 2 has no extractable text'):
                extract_pdf_to_markdown(path)

    def test_oversized_blank_page_is_skipped_with_bounded_rendering(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'large-page.pdf'
            with pymupdf.open() as pdf:
                pdf.new_page().insert_text((72, 72), 'Invoice 100')
                pdf.new_page(width=14400, height=14400)
                pdf.save(path)
            self.assertIn('Invoice 100', extract_pdf_to_markdown(path))
