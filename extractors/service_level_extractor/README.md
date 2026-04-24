# Service-Level Extractor

Extracts service-level data from 1915(c) waiver documents (Appendix C-1/C-3). Produces **one row per service per document** (multiple rows per document), unlike the waiver-level extractors which produce one row per document.

## Modules

| File | Class | Columns | Description |
|------|-------|---------|-------------|
| `html_service_level_extractor.py` | `HtmServiceLevelExtractor` | 33 | Service-level extraction from HTML/HTM files |
| `text_service_level_extractor.py` | `TxtServiceLevelExtractor` | 33 | Service-level extraction from plain text files |

Both extractors produce identical 33-column output schemas.

## Columns (33)

**Original 20 columns:**
`document_id`, `proposed_effective_date`, `approved_effective_date`, `service_name`, `renewal_or_new_or_replacement`, `limits_on_the_service`, `service_delivery_method`, `where_service_provided`, `provision_of_personal_care`, `provision_of_personal_care_description`, `other_state_policies`, `other_state_policies_description`, `is_statewide`, `geographic_limitations`, `limited_implementation`, `year_1` through `year_5_participants`

**Additional 13 columns (C-1/C-3 Service Specification):**
`service_type`, `service`, `alternate_service_title`, `hcbs_taxonomy_1`, `hcbs_taxonomy_1a`, `hcbs_taxonomy_2`, `hcbs_taxonomy_2a`, `service_definition`, `service_self_directed`, `service_providermanaged`, `serviceprovider_lrp`, `serviceprovider_relative`, `serviceprovider_lg`

## Usage

```python
from extractors.service_level_extractor.html_service_level_extractor import HtmServiceLevelExtractor

extractor = HtmServiceLevelExtractor()
df = extractor.extract_single("path/to/waiver.htm")
df = extractor.extract_folder("path/to/waivers/")
extractor.save_csv("output.csv")
```

```python
from extractors.service_level_extractor.text_service_level_extractor import TxtServiceLevelExtractor

extractor = TxtServiceLevelExtractor()
df = extractor.extract_single("path/to/waiver.txt")
df = extractor.extract_folder("path/to/waivers/")
extractor.save_csv("output.csv")
```

## Run standalone

```bash
python -c "
from extractors.service_level_extractor.html_service_level_extractor import HtmServiceLevelExtractor
ext = HtmServiceLevelExtractor()
df = ext.extract_folder('/path/to/waivers')
ext.save_csv('./output/html_service_level.csv')
"
```

## Merging HTML and Text service-level outputs

See `merge/merge_service_level.py` for the merge script that combines HTML and text service-level extractions with per-column preferred-source selection and service-name matching.
