# MedicaidWaiverExtraction

Automated extraction pipeline for 1915(c) Home and Community-Based Services (HCBS) Medicaid waiver documents. Converts raw waiver applications (HTML, HTM, TXT, and fillable PDF formats) into structured research datasets.

## What this repo does

- Parses standardized CMS 1915(c) waiver applications across four document formats
- Extracts structured data for approximately 179 variables spanning Request Information, Appendices A through J, and Attachments
- Runs HTML, text, and PDF AcroForm extraction tracks independently
- Merges results post-hoc with field-level conditions to produce a single unified dataset

## Installation

```bash
git clone <repo-url>
cd MedicaidWaiverExtraction
pip install -r requirements.txt
```

Requires Python 3.12.

## Quick start

Test a single file:

```bash
python run/run_extraction.py --test_file /path/to/waiver.htm
python run/run_extraction.py --test_file /path/to/waiver.txt
```

Run full extraction on a directory:

```bash
python run/run_extraction.py --input_dir /path/to/waivers --output_dir ./output
```

Merge HTML and text extractions into a unified dataset:

```bash
python merge/merge_extractions.py \
    --html_csv ./output/html_top_extraction.csv \
    --text_csv ./output/text_top_extraction.csv \
    --output_csv ./output/merged_top.csv
```

## Repository structure

```
MedicaidWaiverExtraction/
├── extractors/
│   ├── html_extractor/          HTML/HTM file parsers
│   ├── text_extractor/          Plain text file parsers
│   └── pdf_acroform_extractor/  Fillable PDF parsers
├── merge/                       Post-hoc merge logic
├── run/                         CLI entry points
└── docs/                        Architecture and methodology
```

Each folder has its own README explaining what's inside and how to use it.

## Priority tiers

Variables are organized into three priority tiers based on stakeholder input:

- **Top priority** (87 fields): Core program characteristics including waiver title, effective dates, levels of care, concurrent programs, target groups, cost limits, eligibility, services. Extracted by `*_top_extractor.py` modules.
- **Secondary priority** (43 fields): Evaluation and reevaluation, self-direction details, rate-setting methods. Not yet modularized.
- **Tertiary priority** (35 fields): Administrative delegation (Appendix A Section 7), financial accountability (Appendix I), transition plans, waiver description. Extracted by `*_tertiary_extractor.py` modules.

## Extraction strategy

The pipeline runs HTML, text, and PDF AcroForm extractors independently across the full corpus, then merges the results based on document ID with field-level conditions. For overlapping document IDs, the merge prefers non-empty values and falls back to the source with the higher fill rate. PDF AcroForm is treated as authoritative for radio button fields since it reads form state directly.

See `docs/extraction_methodology.md` for details.

## Contributing

Work on feature branches and open a pull request to `main`:

- `feature/html-text-extraction` - HTML and text parsers
- `feature/pdf-acroform` - PDF AcroForm extractor
- `feature/merge-pipeline` - merging logic

## License

Internal project. Do not distribute without permission.
