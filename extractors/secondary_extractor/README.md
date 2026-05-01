# Secondary Extractor

Secondary-priority variables from 1915(c) waiver documents, covering Appendix E (Participant Direction) and Appendix I (Rates and Enhanced Payments).

## Modules

| File | Description |
|------|-------------|
| `html_appendix_e_extractor.py` | Appendix E: Participant Direction of Services (self-direction, employer/budget authority, living arrangements, FMS, enrollment goals) |
| `html_appendix_i_rates_extractor.py` | Appendix I: Rate determination methods (textarea) and supplemental/enhanced payments (radio button) |
| `run_all_extractions.py` | Unified runner that processes all state directories with resume capability and extraction logging |
| `combine_state_csvs.py` | Combines per-state CSVs into master CSVs for each appendix |

## Extraction approach

Both extractors support three extraction methods with automatic fallback:
1. **Native HTML forms** - reads element IDs and form states directly
2. **Converted PDFs** - text pattern matching for documents converted to HTML
3. **TXT fallback** - searches sibling .txt files when HTML extraction yields weak or missing results

## Usage

### Run all secondary extractions across states

```bash
python extractors/secondary_extractor/run_all_extractions.py \
    --input /path/to/waivers \
    --output ./outputs

# Resume from where it stopped
python extractors/secondary_extractor/run_all_extractions.py \
    --input /path/to/waivers \
    --output ./outputs \
    --resume
```

### Run individual extractors

```bash
# Appendix E
python extractors/secondary_extractor/html_appendix_e_extractor.py /path/to/state_dir output.csv

# Appendix I rates
python extractors/secondary_extractor/html_appendix_i_rates_extractor.py /path/to/state_dir output.csv
```

### Combine per-state CSVs after extraction

```bash
python extractors/secondary_extractor/combine_state_csvs.py --input ./outputs --output ./outputs
```

This produces master CSVs (e.g., `master_appendix_e.csv`, `master_appendix_i_rates.csv`) combining all state-level results.

## Output

Produces per-state CSVs in subdirectories (`outputs/appendix_e/appendix_e_AL.csv`, etc.) and combined master CSVs. The runner includes extraction logging with error tracking and fill-rate statistics.
