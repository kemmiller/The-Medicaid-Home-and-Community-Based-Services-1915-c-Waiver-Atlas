"""
Appendix I Extractor - Rates and Enhanced Payments Only

Extracts only 2 variables:
1. provider_rate_methods - I-2 (1 of 3): Rate Determination Methods (textarea)
2. enhanced_payments_yes - I-3 (3 of 7): Supplemental or Enhanced Payments (0=No, 1=Yes)

Supports:
- Native HTML forms (element IDs)
- Converted PDFs (text pattern matching)
- TXT fallback for missing values
"""

import re
from pathlib import Path
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup
import pandas as pd


class AppendixIRatesExtractor:
    """Extracts Rate Methods and Enhanced Payments from Appendix I."""

    def __init__(self, document_id: str, document: BeautifulSoup):
        self.document_id = document_id
        self.document = document
        self._full_text = document.get_text()

    # =========================================================================
    # VARIABLE 1: provider_rate_methods (I-2, 1 of 3)
    # =========================================================================

    @property
    def provider_rate_methods(self) -> str:
        """
        I-2-a: Rate Determination Methods.
        Describes methods employed to establish provider payment rates.
        """
        # Method 1: Native HTML form - textarea by ID
        textarea = self.document.find("textarea", {"id": "svapdxI2_1:fnaRatDetMth"})
        if textarea:
            text = textarea.get_text().strip()
            if text and len(text) > 50:
                return self._clean_text(text)

        # Method 2: Converted PDF - find section by markers
        # Skip the instruction text and find the actual content
        text = self._extract_section_text(
            start_markers=[
                "available upon request to CMS through the Medicaid agency",  # End of instructions
                "operating agency (if applicable).",  # End of instructions variant
            ],
            end_markers=[
                "Flow of Billings",
                "b. Flow of Billings",
                "Describe the flow of billings",
            ],
        )
        if text and len(text) > 50:
            return self._clean_text(text)

        # Fallback: try to find content after "Rate Determination Methods" header
        text = self._extract_section_text(
            start_markers=[
                "Rate Determination Methods",
            ],
            end_markers=[
                "Flow of Billings",
                "b. Flow of Billings",
            ],
        )
        # Skip instruction text if present
        if text:
            # Remove common instruction patterns
            text = re.sub(
                r".*?(?:available upon request to CMS|operating agency \(if applicable\))\.?\s*",
                "",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if len(text.strip()) > 50:
                return self._clean_text(text)

        return ""

    # =========================================================================
    # VARIABLE 2: enhanced_payments_yes (I-3, 3 of 7)
    # =========================================================================

    @property
    def enhanced_payments_yes(self) -> Optional[int]:
        """
        I-3-c: Supplemental or Enhanced Payments.
        0 = No. The State does not make supplemental or enhanced payments.
        1 = Yes. The State makes supplemental or enhanced payments.
        """
        # Method 1: Native HTML form - radio button by name
        radios = self.document.find_all("input", {"name": "svapdxI3_3:fnaPymtSppl"})
        for radio in radios:
            if "checked" in radio.attrs:
                try:
                    value = int(radio.get("value", -1))
                    if value in (0, 1):
                        return value
                except ValueError:
                    pass

        # Method 2: Converted PDF - pattern matching in text
        # Look for the selected option marker
        patterns = [
            (r"No\.?\s*The\s+[Ss]tate\s+does\s+not\s+make\s+supplemental", 0),
            (r"Yes\.?\s*The\s+[Ss]tate\s+makes\s+supplemental", 1),
        ]

        # Find the Supplemental Payments section
        section_match = re.search(
            r"Supplemental or Enhanced Payments.*?(?=Payments to State|d\.\s*Payments to|I-3:.*?\(4 of 7\))",
            self._full_text,
            re.IGNORECASE | re.DOTALL,
        )

        if section_match:
            section_text = section_match.group(0)
            for pattern, value in patterns:
                if re.search(pattern, section_text, re.IGNORECASE):
                    return value

        return None

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _extract_section_text(
        self, start_markers: list, end_markers: list, max_length: int = 12000
    ) -> str:
        """Extract text between start and end markers."""
        text = self._full_text

        # Find start position
        start_pos = -1
        for marker in start_markers:
            match = re.search(re.escape(marker), text, re.IGNORECASE)
            if match:
                start_pos = match.end()
                break

        if start_pos == -1:
            return ""

        # Find end position
        end_pos = len(text)
        for marker in end_markers:
            match = re.search(re.escape(marker), text[start_pos:], re.IGNORECASE)
            if match:
                end_pos = start_pos + match.start()
                break

        # Extract and clean
        extracted = text[start_pos:end_pos]
        if len(extracted) > max_length:
            extracted = extracted[:max_length]

        return extracted.strip()

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text)
        # Remove common artifacts
        text = re.sub(r"Character Count:.*?out of \d+", "", text)
        # Remove leftover instruction fragments
        text = re.sub(r"^.*?operating agency \(if applicable\)\.?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^.*?through the Medicaid agency\.?\s*", "", text, flags=re.IGNORECASE)
        return text.strip()

    # =========================================================================
    # MAIN EXTRACTION
    # =========================================================================

    def extract_all(self) -> Dict[str, Any]:
        """Extract the 2 required variables."""
        return {
            "document_id": self.document_id,
            "provider_rate_methods": self.provider_rate_methods,
            "enhanced_payments_yes": self.enhanced_payments_yes,
        }


# =========================================================================
# TXT FALLBACK
# =========================================================================


class TxtFallbackRates:
    """TXT fallback for the 2 Appendix I variables."""

    def __init__(self, txt_path: str):
        self._content = ""
        try:
            with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
                self._content = f.read()
        except:
            pass

    def get_provider_rate_methods(self) -> Optional[str]:
        """Extract rate determination methods from TXT."""
        if not self._content:
            return None

        # Try to find the section
        patterns = [
            r"Rate Determination Methods.*?In two pages or less.*?describe.*?(\w.{200,8000}?)(?=b\.\s*Flow of Billings|Flow of Billings|Describe the flow)",
            r"(DMMA has delegated.*?)(?=Flow of Billings|Describe the flow)",
            r"(Rates for.*?services are established.*?)(?=Flow of Billings|Describe the flow)",
        ]

        for pattern in patterns:
            match = re.search(pattern, self._content, re.IGNORECASE | re.DOTALL)
            if match:
                text = match.group(1).strip()
                if len(text) > 100:
                    return re.sub(r"\s+", " ", text)

        return None

    def get_enhanced_payments(self) -> Optional[int]:
        """Extract supplemental payments selection from TXT."""
        if not self._content:
            return None

        # Look for the Yes/No selection
        if re.search(
            r"No\.?\s*The\s+[Ss]tate\s+does\s+not\s+make\s+supplemental",
            self._content,
            re.IGNORECASE,
        ):
            return 0
        if re.search(
            r"Yes\.?\s*The\s+[Ss]tate\s+makes\s+supplemental",
            self._content,
            re.IGNORECASE,
        ):
            return 1

        return None


def is_missing_or_weak(value) -> bool:
    """Check if value needs fallback."""
    if value is None:
        return True
    if isinstance(value, str) and len(value.strip()) < 50:
        return True
    return False


def find_sibling_txt(html_path: str) -> str:
    """Find sibling .txt file."""
    path = Path(html_path)
    txt_path = path.with_suffix(".txt")
    if txt_path.exists():
        return str(txt_path)
    return ""


# =========================================================================
# FILE PROCESSING
# =========================================================================


def load_html(file_path: str) -> BeautifulSoup:
    """Load HTML file."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return BeautifulSoup(f.read(), "html.parser")


def process_single_file(file_path: str) -> Dict[str, Any]:
    """Process single HTML file with TXT fallback."""
    doc_id = Path(file_path).stem
    document = load_html(file_path)
    extractor = AppendixIRatesExtractor(doc_id, document)
    result = extractor.extract_all()

    # TXT fallback
    txt_path = find_sibling_txt(file_path)
    if txt_path:
        fallback = TxtFallbackRates(txt_path)

        if is_missing_or_weak(result["provider_rate_methods"]):
            txt_value = fallback.get_provider_rate_methods()
            if txt_value:
                result["provider_rate_methods"] = txt_value

        if result["enhanced_payments_yes"] is None:
            txt_value = fallback.get_enhanced_payments()
            if txt_value is not None:
                result["enhanced_payments_yes"] = txt_value

    return result


def process_directory(input_dir: str, output_csv: str = None) -> pd.DataFrame:
    """Process all HTML/HTM files in directory."""
    htm_files = list(Path(input_dir).glob("**/*.htm")) + list(
        Path(input_dir).glob("**/*.html")
    )
    print(f"Found {len(htm_files)} .htm/.html files in {input_dir}")

    results = []
    errors = []

    for file_path in htm_files:
        try:
            data = process_single_file(str(file_path))
            results.append(data)
            print(f"  ✓ {data['document_id']}")
        except Exception as e:
            errors.append({"file": str(file_path), "error": str(e)})
            print(f"  ✗ {file_path}: {e}")

    df = pd.DataFrame(results)

    if output_csv:
        df.to_csv(output_csv, index=False)
        print(f"\nSaved to {output_csv}")

    print(f"\nProcessed: {len(results)} files, {len(errors)} errors")
    return df


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python html_appendix_i_rates_extractor.py <input_dir> [output_csv]")
        sys.exit(1)

    input_dir = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else None
    df = process_directory(input_dir, output_csv)

    print("\nResults:")
    print(df.to_string())
