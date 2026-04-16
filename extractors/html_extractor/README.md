# HTML Extractor

Extracts structured data from 1915(c) waiver documents in HTML/HTM format.

## Modules

| File | Class | Columns | Description |
|------|-------|---------|-------------|
| `html_top_extractor.py` | `HTMLTopExtractor` | 72 | Top-priority variables: Request Info (1-3), B-1 through B-5 |
| `html_tertiary_extractor.py` | `HTMLTertiaryExtractor` | 60 | Tertiary variables: Appendix A Section 7 + waiver description + transition plans |

## Usage

```python
from extractors.html_extractor import HTMLTopExtractor, HTMLTertiaryExtractor
from bs4 import BeautifulSoup

with open("AK0260R0600.htm", "r", encoding="utf-8") as f:
    html = f.read()

doc = BeautifulSoup(html, "html.parser")
top_data = HTMLTopExtractor("AK0260R0600", doc).extract_all()
tertiary_data = HTMLTertiaryExtractor("AK0260R0600", html).extract_all()
```

## Extraction approach

For native HTML documents, extraction relies on element identifiers embedded in the CMS form:

- **Checkboxes**: `<input type="checkbox" id="...">` with known `id` attributes. Read the `checked` attribute.
- **Text inputs**: `<input type="text" id="...">`. Read the `value` attribute.
- **Textareas**: `<textarea id="...">`. Read the element content.
- **Dropdowns**: `<select id="...">` with `<option selected>`. Read the selected option's text.
- **Radio buttons**: `<input type="radio" name="..." id="...:N">` where N is the option index.

For converted HTML documents (PDFs/Word converted to HTML), form elements are stripped. The parser falls back to inferring field values from surrounding text.

## Run standalone

```bash
python -m extractors.html_extractor.html_top_extractor /path/to/waiver.htm
python -m extractors.html_extractor.html_tertiary_extractor /path/to/waivers ./output.csv
```

## Variables covered

See `/docs/variable_reference.md` for the full variable list.
