# Text Extractor

Extracts structured data from 1915(c) waiver documents in plain text (.txt) format.

## Modules

| File | Class | Columns | Description |
|------|-------|---------|-------------|
| `text_top_extractor.py` | `TextTopExtractor` | 72 | Top-priority variables: Request Info (1-3), B-1 through B-5 |
| `text_tertiary_extractor.py` | `TextTertiaryExtractor` | 60 | Tertiary variables: Appendix A Section 7 + waiver description + transition plans |

## Usage

```python
from extractors.text_extractor import TextTopExtractor, TextTertiaryExtractor

with open("MO0026R0900.txt", "r", encoding="utf-8", errors="replace") as f:
    text = f.read()
text = text.replace("\r\r", "\n").replace("\r", "\n")
lines = text.split("\n")

top_data = TextTopExtractor("MO0026R0900", lines).extract_all()
tertiary_data = TextTertiaryExtractor("MO0026R0900", lines).extract_all()
```

## Extraction approach

Plain text files have no form elements, so the parser works line by line:

- **Checkboxes**: A checked checkbox appears as `Yes` on the line preceding the label; unchecked as `Off`. The parser locates a known section anchor, reads forward, and pairs each label with the Yes/Off value immediately before it.
- **Text inputs**: Value appears on the line following the label, or inline on the same line after a colon.
- **Radio buttons**: Most radio buttons have **no selection indicator** in text files (the same token is repeated for every option). These fields return empty and are extracted from HTML or the PDF AcroForm track instead.
- **Tables**: Column counts auto-detect from the header row or by counting Yes/Off values between the first two row labels.

## Run standalone

```bash
python -m extractors.text_extractor.text_top_extractor /path/to/waiver.txt
python -m extractors.text_extractor.text_tertiary_extractor /path/to/waivers ./output.csv
```

## Variables covered

See `/docs/variable_reference.md` for the full variable list.
