"""
Service categorization for 1915(c) waiver data.

Modules:
  - hcbs_service_categorizer: Maps service names to the 18-category CMS HCBS Taxonomy
  - revised_mappings: Curated service-to-category mappings validated through manual review
  - limit_categorizer: Classifies free-text service limit descriptions into 12 categories
"""

from .hcbs_service_categorizer import HCBSTaxonomy
from .limit_categorizer import categorize_limit, categorize_dataframe
