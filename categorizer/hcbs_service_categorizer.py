"""
HCBS Service Categorization System
Enhanced version with multi-level matching and updated mappings from manual corrections
"""

import pandas as pd
import numpy as np
import re
import logging
from pathlib import Path
from typing import Dict, Tuple, List, Optional
from datetime import datetime
import json

# Import revised mappings from external file
try:
    from .revised_mappings import REVISED_MAPPINGS
except ImportError:
    try:
        from revised_mappings import REVISED_MAPPINGS
    except ImportError:
        REVISED_MAPPINGS = {}
        print("  Warning: revised_mappings.py not found. Revised mappings will not be used.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f'hcbs_categorization_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class HCBSTaxonomy:
    """HCBS Taxonomy classifier with enhanced multi-level matching strategy."""

    TAXONOMY_CATEGORIES = {
        1: "Case Management",
        2: "Round-the-Clock Services",
        3: "Supported Employment",
        4: "Day Services",
        5: "Nursing",
        6: "Home-Delivered Meals",
        7: "Rent and Food for Live-In Caregiver",
        8: "Home-Based Services",
        9: "Caregiver Support",
        10: "Other Mental Health and Behavioral Services",
        11: "Other Health and Therapeutic Services",
        12: "Self-direction and Supporting Services",  # UPDATED NAME
        13: "Participant Training",
        14: "Equipment, Technology, and Modifications",
        15: "Non-Medical Transportation",
        16: "Community Transition Services",
        17: "Other Services",
        99: "Unknown",
    }

    SERVICE_MAPPINGS = [
        # Category 1: Case Management
        (
            1,
            "Case Management",
            [
                "case management",
                "care coordination",
                "service coordination",
                "care management",
                "purchased care management",
                "augmented plan of care",
                "enhanced care management",
                "ecm",
                "case aide",
                "community guide",
                "wraparound technician",
                "enhanced care service",
                "wraparound facilitation",
                "home and community supports",
            ],
            [],
        ),
        # Category 2: Round-the-Clock Services
        (
            2,
            "Group Living - Residential Habilitation",
            ["group living", "residential habilitation", "group home habilitation"],
            [
                "shared",
            ],
        ),
        (
            2,
            "Group Living - Mental Health",
            ["group living", "mental health"],
            [
                "shared",
            ],
        ),
        (
            2,
            "Group Living - Other",
            ["group living", "group home"],
            [
                "habilitation",
                "mental health",
                "shared",
            ],
        ),
        (
            2,
            "Shared Living - Residential Habilitation",
            ["shared living", "shared habilitation"],
            [
                "group",
            ],
        ),
        (
            2,
            "Shared Living - Mental Health",
            ["shared living", "shared", "mental health"],
            [
                "group",
            ],
        ),
        (
            2,
            "Shared Living - Other",
            ["shared living", "shared home", "shared living services"],
            [
                "habilitation",
                "mental health",
                "group",
            ],
        ),
        (2, "In-Home Residential Habilitation", ["residential habilitation"], ["group", "shared"]),
        (
            2,
            "In-Home Round-the-Clock Mental Health",
            ["in home residential", "round the clock", "mental health"],
            ["group", "shared"],
        ),
        (
            2,
            "In-Home Round-the-Clock - Other",
            ["in home habilation", "round the clock", "24 hour", "live in"],
            ["group", "shared", "mental health", "habilitation"],
        ),
        (
            2,
            "Round-the-Clock Services - Unspecified",
            [
                "24 hour",
                "round the clock",
                "residential care",
                "adult family home",
                "adult family living",
                "adult family care",
                # "habilitation services",
                "community living support benefit in licensed settings",
                "community living support benefit in housing sites",
                "comprehensive support provider directed",
                "comprehensive support",
                "goal engagement program",
            ],
            [],
        ),
        # Category 3: Supported Employment
        (3, "Job Development", ["job development", "job coach", "job placement"], []),
        (3, "Ongoing Supported Employment - Individual", ["supported employment", "individual"], ["group"]),
        (3, "Ongoing Supported Employment - Group", ["supported employment", "group"], ["individual"]),
        (3, "Career Planning", ["career planning", "vocational planning"], []),
        (
            3,
            "Supported Employment - Unspecified",
            [
                "supported employment",
                "employment support",
                "vocational support",
                "employment services",
                "employment readiness",
                "Workstation habilitation services",
            ],
            [],
        ),
        # Category 4: Day Services
        (4, "Prevocational Services", ["prevocational", "pre vocational"], []),
        (
            4,
            "Day Habilitation",
            ["day habilitation", "day hab", "habilitative supports", "habilitative intervention"],
            [],
        ),
        (4, "Education Services", ["education service", "educational service"], []),
        (4, "Day Treatment/Partial Hospitalization", ["day treatment", "partial hospitalization"], []),
        (4, "Adult Day Health", ["adult day health", "day health", "day health care"], []),
        (4, "Adult Day Services (Social Model)", ["adult day", "adult day service", "adult day care"], ["health"]),
        (
            4,
            "Community Integration",
            [
                "community integration",
                "community participation",
                "community inclusion",
                "intensive active treatment",
                "abi group day",
                "escort",
                "community life engagement development",
                "community living supports",
                "day training",
            ],
            [],
        ),
        (4, "Medical Day Care for Children", ["medical day care", "children", "pediatric day"], []),
        # Category 5: Nursing
        (
            5,
            "Private Duty Nursing",
            ["private duty nursing", "pdn", "In Home Nursing", "in home nursing", "in Home Nursing"],
            [],
        ),
        (5, "Skilled Nursing", ["skilled nursing", "skilled nurse"], ["private duty"]),
        # Category 6: Home-Delivered Meals
        (
            6,
            "Home-Delivered Meals",
            ["home delivered meal", "home delivered meals", "meal delivery", "meals delivery"],
            [],
        ),
        # Category 7: Rent and Food for Live-In Caregiver
        (7, "Rent and Food for Live-In Caregiver", ["live in caregiver", "caregiver rent", "caregiver food"], []),
        # Category 8: Home-Based Services
        (8, "Home-Based Habilitation", ["home habilitation", "in home habilitation"], ["residential"]),
        (8, "Home Health Aide", ["home health aide", "hha", "supportive home care aide"], []),
        (
            8,
            "Personal Care",
            [
                "personal care",
                "personal assistance",
                "attendant care",
                "personal attendant",
                "personal support services",
            ],
            [],
        ),
        (8, "Companion", ["companion", "companionship"], []),
        (8, "Homemaker", ["homemaker", "homemaking"], []),
        (8, "Chore", ["chore", "housekeeping", "laundry"], []),
        (
            8,
            "Home-Based Services - Other",
            [
                "in home support services",
                "ihss",
                "in home supports",
                "in home support",
                "special medical home care",
                "home delivered services",
                "hds",
                "community living support basic",
                "community living support extended",
                "community access",
                "supported community living",
                "in home service",
                "home telehealth",
                "monitored in home caregiving",
                "grocery shopping and delivery",
                "supported living coaching",
            ],
            [],
        ),
        # Category 9: Caregiver Support
        (9, "Respite - Out-of-Home", ["respite", "out of home"], ["in home"]),
        (9, "Respite - In-Home", ["respite", "in home"], ["out of home"]),
        (9, "Respite - Unspecified", ["respite", "caregiver temporary support"], []),
        (
            9,
            "Caregiver Counseling/Training",
            [
                "caregiver training",
                "caregiver counseling",
                "caregiver education",
                "family training",
                "parenting supports",
                "training and support for unpaid caregivers",
                "parent support and training",
                "professional resource family care",
                "Transportation Costs for Financially Responsible Caregiver",
            ],
            [],
        ),
        # Category 10: Mental Health and Behavioral
        (10, "Mental Health Assessment", ["mental health assessment", "psychiatric assessment"], []),
        (10, "Assertive Community Treatment", ["assertive community treatment", "act"], []),
        (10, "Crisis Intervention", ["crisis intervention", "crisis service"], []),
        (
            10,
            "Behavior Support",
            [
                "behavior support",
                "behavioral support",
                "behavior management",
                "behavior assessment and planning",
                "aba certified clinician",
                "behavior analysis services",
                "behavior programming",
                "creative arts therapies",
                "interdisciplinary training",
            ],
            [],
        ),
        (10, "Peer Specialist", ["peer specialist", "peer support", "peer mentorship"], []),
        (10, "Counseling", ["counseling", "psychotherapy"], ["caregiver"]),
        (10, "Psychosocial Rehabilitation", ["psychosocial rehabilitation", "psychosocial rehab"], []),
        (10, "Clinic Services", ["clinic service", "mental health clinic"], []),
        # Category 11: Health and Therapeutic
        (
            11,
            "Health Monitoring",
            ["health monitoring", "health check", "wellness monitoring", "health maintenance monitoring"],
            [],
        ),
        (11, "Health Assessment", ["health assessment"], ["mental"]),
        (
            11,
            "Medication Assessment/Management",
            [
                "medication assessment",
                "medication management",
                "med management",
                "medication reminder",
                "medication reminder services",
                "pharmacy review",
                "medication review",
                "home delivery of pre packaged medication",
            ],
            [],
        ),
        (
            11,
            "Nutrition Consultation",
            ["nutrition consultation", "dietary consultation", "dietitian services", "dietician services"],
            ["meal"],
        ),
        (11, "Physician Services", ["physician service", "doctor visit", "consultative clinical services"], []),
        (11, "Prescription Drugs", ["prescription drug", "prescribed drugs"], ["assessment", "management", "reminder"]),
        (
            11,
            "Dental Services",
            [
                "dental",
                "dentist",
                "adult dental",
                "adult dental services",
                "adult dental service",
                "oral health services",
            ],
            [],
        ),
        (11, "Occupational Therapy", ["occupational therapy", "ot"], []),
        (11, "Physical Therapy", ["physical therapy", "pt"], ["speech"]),
        (
            11,
            "Speech/Hearing/Language Therapy",
            ["speech therapy", "language therapy", "hearing therapy", "speech language"],
            [],
        ),
        (11, "Respiratory Therapy", ["respiratory therapy", "breathing therapy"], []),
        (
            11,
            "Cognitive Rehabilitative Therapy",
            ["cognitive therapy", "cognitive rehabilitation", "cognitive services"],
            [],
        ),
        (11, "Other Therapies", ["therapy"], ["occupational", "physical", "speech", "respiratory", "cognitive"]),
        (
            11,
            "Other Health Services",
            ["physical risk reduction", "consultation", "interim medical monitoring and treatment", "immt"],
            [],
        ),
        # Category 12: Participant Direction Support
        (
            12,
            "Financial Management Services",
            [
                "financial management service",
                "financial management services",
                "fms",
                "fiscal intermediary",
                "financial management",
            ],
            [],
        ),
        (
            12,
            "Information and Assistance",
            [
                "information and assistance",
                "participant direction support",
                "independent support broker",
                "independant support brokerage service",
                "support broker services",
                "chronic disease self management program",
                "participant directed community support services",
                "self directed community support and employment",
                "comprehensive support self directed",
                "sleep cycle support self directed",
                "participant directed coordination",
            ],
            [],
        ),
        # Category 13: Participant Training
        (
            13,
            "Participant Training",
            ["participant training", "self direction training", "consumer training", "alzheimer dementia coaching"],
            [],
        ),
        # Category 14: Equipment/Technology/Modifications
        (
            14,
            "Personal Emergency Response System",
            [
                "pers",
                "personal emergency response",
                "emergency alert",
                "personal emergency response unit",
                "emergency response services",
                "emergency home response service",
                "medical alert rental",
                "Individual-Directed goods and services",
            ],
            [],
        ),
        (
            14,
            "Home/Vehicle Accessibility Adaptations",
            [
                "accessibility adaptation",
                "home modification",
                "vehicle modification",
                "ramp",
                "environmental modification",
                "environmental modifications",
                "environmental modification assessment",
                "home and environmental modification services",
                "hems",
                "home and environmental modifications services",
            ],
            [],
        ),
        (
            14,
            "Equipment and Technology",
            [
                "equipment",
                "assistive technology",
                "durable medical equipment",
                "dme",
                "automated medication dispenser",
                "amd",
            ],
            ["modification"],
        ),
        (14, "Supplies", ["supplies", "medical supplies"], []),
        # Category 15: Non-Medical Transportation
        (
            15,
            "Non-Medical Transportation",
            [
                "non medical transportation",
                "nonmedical transportation",
                "non medicaltransportation",
                "non medical transporation",
                "Non-Medical Transporation",
                "non medical transporation ",
                "nonmedicaltransporation",
                "transportation",
                "transport",
            ],
            ["medical"],
        ),
        # Category 16: Community Transition
        (
            16,
            "Community Transition Services",
            ["community transition service", "community transition services", "transition assistance"],
            [],
        ),
        # Category 17: Other Services
        (17, "Goods and Services", ["goods and services", "individual directed goods and services", "flex funds"], []),
        (17, "Interpreter", ["interpreter", "translation"], []),
        (17, "Housing Consultation", ["housing consultation", "housing counseling"], []),
        (
            17,
            "Communication Services",
            ["communication", "communication device", "communication translation interpretation"],
            [],
        ),
        (
            17,
            "Other Support Services",
            [
                "life skills coach",
                "blended supports",
                "bill payer",
                "financial risk reduction assessment",
                "financial risk reduction maintenance",
                "financial assessment and risk reduction",
            ],
            [],
        ),
        (17, "Other", ["other"], []),
    ]

    # Note: REVISED_MAPPINGS now imported from revised_mappings.py file
    # This keeps the main code clean and makes it easy to update mappings

    FUZZY_CATEGORY_KEYWORDS = {
        1: ["care management", "management", "coordination", "guide", "aide"],
        2: ["habilitation", "living", "residential", "family home", "family care"],
        3: ["employment", "job", "vocational", "work", "career"],
        4: ["day", "training", "integration", "engagement", "habilitative"],
        5: ["nursing", "nurse", "rn", "lpn"],
        6: ["meal", "meals", "food", "nutrition"],
        8: ["home care", "in home", "assistance", "aide", "helper", "support services", "caregiving", "pest"],
        9: ["respite", "caregiver relief", "caregiver break", "family support", "parent support"],
        10: ["mental health", "behavioral", "counseling", "psychiatric", "behavior", "aba", "peer"],
        11: ["therapy", "therapeutic", "rehabilitation", "treatment", "health", "medication", "dental", "wellness"],
        12: ["broker", "self directed", "participant directed", "financial management"],
        13: ["training", "coaching", "skills"],
        14: [
            "equipment",
            "technology",
            "device",
            "modification",
            "supplies",
            "adaptive",
            "environmental",
            "emergency response",
            "alert",
        ],
        15: ["transport", "transportation", "ride", "transit"],
        16: ["transition", "transitioning", "moving", "relocation"],
        17: ["goods", "services", "communication", "interpreter", "flex", "other"],
    }

    def __init__(self):
        logger.info("Initializing HCBS Taxonomy Classifier with Enhanced Matching")
        self._compile_patterns()
        self._compile_fuzzy_patterns()
        self._compile_revised_mappings()

    def _compile_revised_mappings(self):
        """Compile patterns for revised manual mappings."""
        self.revised_patterns = {}
        for service_name, (code, category) in REVISED_MAPPINGS.items():
            normalized = self.normalize_text(service_name)
            self.revised_patterns[normalized] = (code, category, service_name)

    def _compile_patterns(self):
        self.compiled_mappings = []
        for code, service, keywords, neg_keywords in self.SERVICE_MAPPINGS:
            positive_pattern = re.compile(r"\b(?:" + "|".join(re.escape(kw) for kw in keywords) + r")\b", re.IGNORECASE)
            negative_pattern = None
            if neg_keywords:
                negative_pattern = re.compile(
                    r"\b(?:" + "|".join(re.escape(kw) for kw in neg_keywords) + r")\b", re.IGNORECASE
                )
            self.compiled_mappings.append((code, service, positive_pattern, negative_pattern))

    def _compile_fuzzy_patterns(self):
        self.fuzzy_patterns = {}
        for code, keywords in self.FUZZY_CATEGORY_KEYWORDS.items():
            pattern = re.compile(r"\b(?:" + "|".join(re.escape(kw) for kw in keywords) + r")\b", re.IGNORECASE)
            self.fuzzy_patterns[code] = pattern

    def normalize_text(self, text: str) -> str:
        if pd.isna(text):
            return ""
        text = str(text).lower()
        text = re.sub(r"[/_\-]", " ", text)
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _is_valid_service_name(self, normalized_name: str) -> Tuple[bool, str]:
        if not normalized_name:
            return False, "empty"

        clean = normalized_name.replace(" ", "")

        if clean.isdigit():
            return False, "numeric_only"

        if len(normalized_name) < 3:
            return False, "too_short"

        digit_count = sum(c.isdigit() for c in clean)
        if len(clean) > 0:
            digit_ratio = digit_count / len(clean)
            if digit_ratio > 0.7:
                return False, "mostly_numeric"

        if normalized_name in ["unknown", "tbd", "n a", "na", "none", "null"]:
            return False, "placeholder"

        return True, ""

    def _is_single_keyword_match(self, normalized_text: str, matched_code: int) -> bool:
        high_confidence_singles = [
            "respite",
            "homemaker",
            "companion",
            "chore",
            "dental",
            "interpreter",
            "equipment",
            "supplies",
        ]

        word_count = len(normalized_text.split())

        if word_count <= 1:
            if normalized_text in high_confidence_singles:
                return False
            return True

        if word_count == 2:
            generic_patterns = [
                r"\b(meal|meals)\b",
                r"\b(food|nutrition)\b",
                r"\b(transport|transportation)\b",
                r"\b(job|employment)\b",
                r"\b(transition|transitioning)\b",
                r"\b(integration)\b",
                r"\b(community)\b(?!\s+(transition|integration))",
            ]

            for pattern in generic_patterns:
                if re.search(pattern, normalized_text, re.IGNORECASE):
                    return True

        return False

    def _match_against_taxonomy(self, normalized_text: str) -> Optional[Dict]:
        if not normalized_text:
            return None

        for code, service, pos_pattern, neg_pattern in self.compiled_mappings:
            if pos_pattern.search(normalized_text):
                if neg_pattern and neg_pattern.search(normalized_text):
                    continue

                is_generic = self._is_single_keyword_match(normalized_text, code)

                result = {
                    "taxonomy_code": code,
                    "taxonomy_category": self.TAXONOMY_CATEGORIES[code],
                    "taxonomy_service": service,
                }

                if is_generic:
                    result["_is_generic_match"] = True

                return result

        return None

    def _fuzzy_match_category(self, normalized_text: str) -> Optional[Dict]:
        if not normalized_text:
            return None

        for code, pattern in self.fuzzy_patterns.items():
            if pattern.search(normalized_text):
                category_services = [(c, s, p, n) for c, s, p, n in self.compiled_mappings if c == code]

                for cat_code, service, pos_pattern, neg_pattern in category_services:
                    if pos_pattern.search(normalized_text):
                        if neg_pattern and neg_pattern.search(normalized_text):
                            continue
                        return {
                            "taxonomy_code": code,
                            "taxonomy_category": self.TAXONOMY_CATEGORIES[code],
                            "taxonomy_service": service,
                            "match_quality": "fuzzy_specific",
                        }

                return {
                    "taxonomy_code": code,
                    "taxonomy_category": self.TAXONOMY_CATEGORIES[code],
                    "taxonomy_service": f"{self.TAXONOMY_CATEGORIES[code]} - Unspecified",
                    "match_quality": "fuzzy_general",
                }

        return None

    def categorize_service(
        self, service_name: str, service_description: str = "", additional_context: str = ""
    ) -> Dict:
        """
        Enhanced categorization with multi-level matching strategy.

        Matching levels (UPDATED - NO CONTEXT MATCHING):
        1. Exact taxonomy match on service_name → HIGH confidence
        2. Revised manual mappings on service_name → MEDIUM-HIGH confidence
        3. Fuzzy match on service_name → MEDIUM confidence
        4. No match → UNKNOWN (LOW confidence)

        Note: Context matching removed to prevent false positives.
        """
        # Normalize and validate service name
        normalized_name = self.normalize_text(service_name)
        is_valid_name, invalid_reason = self._is_valid_service_name(normalized_name)

        # Initialize result
        result = {
            "service_name_valid": is_valid_name,
            "service_name_issue": invalid_reason if not is_valid_name else None,
            "needs_manual_review": False,
            "categorization_source": None,
        }

        # LEVEL 1: Exact match on service name (HIGH confidence)
        if is_valid_name and normalized_name:
            exact_match = self._match_against_taxonomy(normalized_name)
            if exact_match:
                is_generic = exact_match.pop("_is_generic_match", False)
                result.update(exact_match)

                if is_generic:
                    result["confidence"] = "medium_high"
                    result["match_type"] = "keyword_name"
                    result["categorization_source"] = "service_name_keyword"
                else:
                    result["confidence"] = "high"
                    result["match_type"] = "exact_name"
                    result["categorization_source"] = "service_name"
                return result

        # LEVEL 2: Revised manual mappings (MEDIUM-HIGH confidence)
        if normalized_name and normalized_name in self.revised_patterns:
            code, category, original_service = self.revised_patterns[normalized_name]
            result.update(
                {
                    "taxonomy_code": code,
                    "taxonomy_category": self.TAXONOMY_CATEGORIES[code],
                    "taxonomy_service": original_service,
                    "confidence": "medium_high",
                    "match_type": "revised_mapping",
                    "categorization_source": "revised_manual_mapping",
                    "needs_manual_review": False if is_valid_name else True,
                }
            )
            return result

        # LEVEL 3: Fuzzy match on service name (MEDIUM confidence)
        if is_valid_name and normalized_name:
            fuzzy_match = self._fuzzy_match_category(normalized_name)
            if fuzzy_match:
                match_quality = fuzzy_match.pop("match_quality", "fuzzy")
                result.update(fuzzy_match)
                result["confidence"] = "medium_high" if match_quality == "fuzzy_specific" else "medium"
                result["match_type"] = f"fuzzy_name_{match_quality}"
                result["categorization_source"] = "service_name_fuzzy"
                result["needs_manual_review"] = True if not is_valid_name else False
                return result

        # LEVEL 4: No match - UNKNOWN
        result.update(
            {
                "taxonomy_code": 99,
                "taxonomy_category": "Unknown",
                "taxonomy_service": "Unknown",
                "confidence": "low",
                "match_type": "no_match",
                "categorization_source": "none",
                "needs_manual_review": True,
            }
        )

        if not is_valid_name:
            result["warning"] = f"Service name is {invalid_reason} and no match found"
        else:
            result["warning"] = "No match found in taxonomy or revised mappings"

        return result


class HCBSServiceCategorizer:
    REQUIRED_COLUMNS = ["service_name"]

    def __init__(self, output_dir: str = "outputs"):
        self.taxonomy = HCBSTaxonomy()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        logger.info(f"Output directory: {self.output_dir}")

    def load_data(self, filepath: str) -> pd.DataFrame:
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        logger.info(f"Loading data from: {filepath}")

        try:
            if filepath.suffix.lower() in [".xlsx", ".xls"]:
                df = pd.read_excel(filepath)
            elif filepath.suffix.lower() == ".csv":
                df = pd.read_csv(filepath, encoding="utf-8")
            else:
                raise ValueError(f"Unsupported file format: {filepath.suffix}")

            logger.info(f"Loaded {len(df)} rows and {len(df.columns)} columns")
            return df
        except Exception as e:
            logger.error(f"Error loading file: {e}")
            raise

    def validate_data(self, df: pd.DataFrame, drop_nulls: bool = True) -> Tuple[bool, List[str]]:
        issues = []
        warnings = []

        missing_required = set(self.REQUIRED_COLUMNS) - set(df.columns)
        if missing_required:
            issues.append(f"Missing required columns: {missing_required}")

        if len(df) == 0:
            issues.append("DataFrame is empty")

        if "service_name" in df.columns:
            null_count = df["service_name"].isna().sum()
            if null_count > 0:
                msg = f"Found {null_count} null values in service_name column"
                if drop_nulls:
                    warnings.append(msg + " (will be removed)")
                    logger.warning(msg + " - these rows will be dropped")
                else:
                    issues.append(msg)

        is_valid = len(issues) == 0

        if is_valid:
            logger.info("Data validation passed")
            if warnings:
                for warning in warnings:
                    logger.warning(warning)
        else:
            logger.warning(f"Data validation issues: {issues}")

        return is_valid, issues

    def process_data(self, df: pd.DataFrame) -> pd.DataFrame:
        logger.info("Starting service categorization with enhanced matching")

        result_df = df.copy()
        result_df["service_name_normalized"] = result_df["service_name"].apply(self.taxonomy.normalize_text)

        context_columns = [
            "renewal_or_new_or_replacement",
            "limits_on_the_service",
        ]

        def build_context(row):
            parts = []
            for col in context_columns:
                if col in row.index and pd.notna(row[col]):
                    parts.append(str(row[col]))
            return " ".join(parts)

        result_df["additional_context"] = result_df.apply(build_context, axis=1)

        categorization_results = []

        for idx, row in result_df.iterrows():
            result = self.taxonomy.categorize_service(
                service_name=row.get("service_name", ""),
                service_description=row.get("additional_context", ""),
                additional_context="",
            )
            categorization_results.append(result)

            if (idx + 1) % 100 == 0:
                logger.info(f"Processed {idx + 1}/{len(result_df)} services")

        cat_df = pd.DataFrame(categorization_results)
        result_df = pd.concat([result_df, cat_df], axis=1)

        logger.info("Categorization complete")

        return result_df

    def generate_summary_statistics(self, df: pd.DataFrame) -> Dict:
        stats = {
            "total_services": len(df),
            "categorized_services": len(df[df["taxonomy_code"] != 99]),
            "unknown_services": len(df[df["taxonomy_code"] == 99]),
            "categorization_rate": len(df[df["taxonomy_code"] != 99]) / len(df) * 100 if len(df) > 0 else 0,
            "categories_distribution": df["taxonomy_category"].value_counts().to_dict(),
            "confidence_distribution": df["confidence"].value_counts().to_dict(),
            "top_services": df["taxonomy_service"].value_counts().head(10).to_dict(),
            "valid_service_names": len(df[df["service_name_valid"] == True]),
            "invalid_service_names": len(df[df["service_name_valid"] == False]),
            "invalid_service_name_rate": (
                len(df[df["service_name_valid"] == False]) / len(df) * 100 if len(df) > 0 else 0
            ),
            "needs_manual_review": len(df[df["needs_manual_review"] == True]),
            "manual_review_rate": len(df[df["needs_manual_review"] == True]) / len(df) * 100 if len(df) > 0 else 0,
            "categorization_source_distribution": (
                df["categorization_source"].value_counts().to_dict() if "categorization_source" in df.columns else {}
            ),
            "match_type_distribution": df["match_type"].value_counts().to_dict(),
        }

        if "service_name_issue" in df.columns:
            invalid_reasons = df[df["service_name_valid"] == False]["service_name_issue"].value_counts().to_dict()
            stats["invalid_name_reasons"] = invalid_reasons

        return stats

    def save_results(self, df: pd.DataFrame, input_filename: str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = Path(input_filename).stem

        output_path = self.output_dir / f"{base_name}_categorized_{timestamp}.csv"
        df.to_csv(output_path, index=False)
        logger.info(f"Saved categorized data to: {output_path}")

        stats = self.generate_summary_statistics(df)
        stats_path = self.output_dir / f"{base_name}_summary_{timestamp}.json"
        with open(stats_path, "w") as f:
            json.dump(stats, f, indent=2)
        logger.info(f"Saved summary statistics to: {stats_path}")

        unknown_df = df[df["taxonomy_code"] == 99][
            [
                "service_name",
                "service_name_normalized",
                "additional_context",
                "service_name_valid",
                "service_name_issue",
                "needs_manual_review",
            ]
        ].drop_duplicates()

        if len(unknown_df) > 0:
            unknown_path = self.output_dir / f"{base_name}_unknown_{timestamp}.csv"
            unknown_df.to_csv(unknown_path, index=False)
            logger.info(f"Saved {len(unknown_df)} unknown services to: {unknown_path}")

        invalid_name_df = df[df["service_name_valid"] == False][
            [
                "document_id" if "document_id" in df.columns else "service_name",
                "service_name",
                "service_name_normalized",
                "service_name_issue",
                "taxonomy_category",
                "taxonomy_service",
                "confidence",
                "match_type",
                "categorization_source",
                "needs_manual_review",
                "additional_context",
            ]
        ].copy()

        if len(invalid_name_df) > 0:
            invalid_path = self.output_dir / f"{base_name}_invalid_names_{timestamp}.csv"
            invalid_name_df.to_csv(invalid_path, index=False)
            logger.info(f"Saved {len(invalid_name_df)} services with invalid names to: {invalid_path}")

        manual_review_df = df[df["needs_manual_review"] == True][
            [
                "document_id" if "document_id" in df.columns else "service_name",
                "service_name",
                "service_name_normalized",
                "service_name_valid",
                "service_name_issue",
                "taxonomy_category",
                "taxonomy_service",
                "confidence",
                "match_type",
                "categorization_source",
                "warning" if "warning" in df.columns else "service_name",
                "additional_context",
            ]
        ].copy()

        if "warning" not in df.columns and "service_name" in manual_review_df.columns:
            manual_review_df = manual_review_df.loc[:, ~manual_review_df.columns.duplicated()]

        if len(manual_review_df) > 0:
            review_path = self.output_dir / f"{base_name}_needs_review_{timestamp}.csv"
            manual_review_df.to_csv(review_path, index=False)
            logger.info(f"Saved {len(manual_review_df)} services needing manual review to: {review_path}")

        print("\n" + "=" * 70)
        print("CATEGORIZATION SUMMARY")
        print("=" * 70)
        print(f"Total Services: {stats['total_services']:,}")
        print(f"Categorized: {stats['categorized_services']:,} ({stats['categorization_rate']:.1f}%)")
        print(f"Unknown: {stats['unknown_services']:,}")
        print("\n" + "-" * 70)
        print("SERVICE NAME QUALITY")
        print("-" * 70)
        print(f"Valid Service Names: {stats['valid_service_names']:,}")
        print(f"Invalid Service Names: {stats['invalid_service_names']:,} ({stats['invalid_service_name_rate']:.1f}%)")

        if "invalid_name_reasons" in stats and stats["invalid_name_reasons"]:
            print("\nInvalid Name Reasons:")
            for reason, count in stats["invalid_name_reasons"].items():
                print(f"  {reason}: {count:,}")

        print("\n" + "-" * 70)
        print("CATEGORIZATION CONFIDENCE")
        print("-" * 70)
        for confidence, count in stats["confidence_distribution"].items():
            print(f"  {confidence.capitalize()}: {count:,}")

        print("\n" + "-" * 70)
        print("MANUAL REVIEW NEEDED")
        print("-" * 70)
        print(f"Services Needing Review: {stats['needs_manual_review']:,} ({stats['manual_review_rate']:.1f}%)")

        print("\n" + "-" * 70)
        print("TOP 5 CATEGORIES")
        print("-" * 70)
        for category, count in list(stats["categories_distribution"].items())[:5]:
            print(f"  {category}: {count:,}")

        print("\n" + "-" * 70)
        print("OUTPUT FILES")
        print("-" * 70)
        print(f"  Main Results (CSV): {base_name}_categorized_{timestamp}.csv")
        print(f"  Main Results (Excel): {base_name}_categorized_{timestamp}.xlsx")
        print(f"  Summary Stats: {base_name}_summary_{timestamp}.json")
        if len(unknown_df) > 0:
            print(f"  Unknown Services: {base_name}_unknown_{timestamp}.csv")
        if len(invalid_name_df) > 0:
            print(f"  Invalid Names: {base_name}_invalid_names_{timestamp}.csv")
        if len(manual_review_df) > 0:
            print(f"  Needs Review: {base_name}_needs_review_{timestamp}.csv")
        print("=" * 70 + "\n")

    def run(self, input_filepath: str):
        try:
            df = self.load_data(input_filepath)

            is_valid, issues = self.validate_data(df)
            if not is_valid:
                logger.error(f"Validation failed: {issues}")
                raise ValueError(f"Data validation failed: {issues}")

            categorized_df = self.process_data(df)

            self.save_results(categorized_df, input_filepath)

            logger.info("Processing completed successfully")

        except Exception as e:
            logger.error(f"Processing failed: {e}", exc_info=True)
            raise


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python hcbs_categorizer.py <input_file.csv|input_file.xlsx> [output_dir]")
        print("\nExample:")
        print("  python hcbs_categorizer.py service_data.csv")
        print("  python hcbs_categorizer.py service_data.xlsx outputs/")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "outputs"

    categorizer = HCBSServiceCategorizer(output_dir=output_dir)
    categorizer.run(input_file)


if __name__ == "__main__":
    main()
