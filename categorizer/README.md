# Categorizer

Post-extraction classification of service-level data. Maps extracted service names and limits to standardized categories for cross-state comparison.

## Files

| File | Description |
|------|-------------|
| `hcbs_service_categorizer.py` | Maps service names to 18-category CMS HCBS Taxonomy |
| `revised_mappings.py` | Curated service-to-category mappings (data file) |
| `limit_categorizer.py` | Classifies service limit descriptions into 12 categories |

## Service Name Categorizer

Classifies each service name into one of the 18 CMS HCBS Taxonomy categories using hierarchical matching: exact match, revised mappings (LLM-assisted and manually validated), then fuzzy keyword match. Unmatched services are flagged as Unknown.

```bash
python categorizer/hcbs_service_categorizer.py service_data.csv
python categorizer/hcbs_service_categorizer.py service_data.xlsx outputs/
```

```python
from categorizer import HCBSTaxonomy
categorizer = HCBSTaxonomy()
result = categorizer.categorize("Personal Care Services")
```

## Limit Categorizer

Classifies free-text service limit descriptions into 12 categories using regex patterns with priority-based assignment. Each limit gets all matching categories plus a single primary category (highest priority match).

```bash
python categorizer/limit_categorizer.py service_data.csv --limit_col limits_on_the_service
```

```python
from categorizer import categorize_dataframe
df = categorize_dataframe(df, limit_col="limits_on_the_service")
# Adds: limit_categories (all matches), limit_type_primary (highest priority)
```

## Data dependencies

`revised_mappings.py` is imported by `hcbs_service_categorizer.py`. Both files must be in the same directory.
