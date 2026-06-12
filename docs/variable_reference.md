# Variable Reference

Complete list of variables extracted by the pipeline, organized by form section.

## Top Priority Variables (72 fields)

Extracted by `html_top_extractor.py` and `text_top_extractor.py`.

### Request Information (1 of 3) - 5 fields

| Variable | Description | Source Type |
|----------|-------------|-------------|
| `title` | Program title | Textarea |
| `approval_period` | Requested approval period (3 or 5 years) | Radio button (text file returns empty) |
| `replacedwaiver` | Waiver number being replaced | Text input |
| `waiver_type` | Type of waiver (Regular, Model, etc.) | Dropdown |
| `effective_date` | Proposed effective date (mm/dd/yy) | Text input |

### Request Information (2 of 3): Levels of Care - 6 fields

| Variable | Description |
|----------|-------------|
| `hospital_loc`, `hospital_loc_limits` | Hospital LOC checkbox + subcategory limits |
| `nursing_facility_loc`, `nursing_facility_loc_limits` | Nursing facility LOC checkbox + subcategory limits |
| `ifc_loc`, `ifc_loc_limits` | ICF/IID LOC checkbox + subcategory limits |

### Request Information (3 of 3): Concurrent Operations - 7 fields

| Variable | Description |
|----------|-------------|
| `concurrent_1915a`, `concurrent_1915b`, `concurrent_1932a`, `concurrent_1915i`, `concurrent_1915j`, `concurrent_1115` | Concurrent program operations |
| `dual_elg` | Dual eligibility for Medicaid and Medicare |

### Section 4: Waiver(s) Requested - 4 fields

| Variable | Description |
|----------|-------------|
| `waive_1902a` | Income and resources for medically needy (radio) |
| `waive_statewideness` | Statewideness waiver (radio) |
| `waive_geographic_limits` | Geographic limitation description |
| `waive_geographic_lipd` | Limited implementation of participant-direction |

### Appendix B-1: Target Groups - 36 fields

12 group checkboxes — `aged_group`, `physicaldis_group`, `otherdis_group`, `braininjury_group`, `hivaids_group`, `medicallyfrail_group`, `techdep_group`, `autism_group`, `dd_group`, `id_group`, `mi_group`, `sed_group` — each with its own `<group>_min` and `<group>_max` age (e.g. `aged_group_min` / `aged_group_max`). A `<group>_max` reads `"No Maximum Age Limit"` when the group is Included but its Maximum Age cell is empty. (Per-group min/max is currently emitted by the MISC extractor; the text/html extractors still populate the aged group only.)

### Appendix B-2: Individual Cost Limit - 4 fields

`cost_limit_excsinst_costs`, `cost_limit_pcntaboveinstit`, `cost_limit_instit`, `cost_limit_lowerinstit`.

### Appendix B-3: Number of Individuals Served - 13 fields

Years 1-5 counts and max capacity, plus `numberbenes_limited`, `phase_in_out_schedule`, `entrantselection`.

### Appendix B-4: Eligibility Groups - 14 fields

`eligibility_1` through `eligibility_12`, plus `eligibility_5_100` and `eligibility_5_percent` for the FPL option.

### Appendix B-5: Post-Eligibility Treatment - 4 fields

`special_hcbs`, `spousal_impov_a`, `spousal_impov_b`, `spousal_impov_c`.

## Tertiary Priority Variables (60 fields)

Extracted by `html_tertiary_extractor.py` and `text_tertiary_extractor.py`.

### Appendix A Section 7: Distribution of Waiver Functions - 48 fields

Checkboxes for which entity is responsible for each of 12 waiver functions across 4 entity types:

| Variable prefix | Entity |
|-----------------|--------|
| `ma_1` through `ma_12` | Medicaid Agency |
| `osa_1` through `osa_12` | Other State Operating Agency |
| `ce_1` through `ce_12` | Contracted Entity |
| `inse_1` through `inse_12` | Local Non-State Entity |

The 12 functions are:
1. Participant waiver enrollment
2. Waiver enrollment managed against approved limits
3. Waiver expenditures managed against approved levels
4. Level of care evaluation
5. Review of participant service plans
6. Prior authorization of waiver services
7. Utilization management
8. Qualified provider enrollment
9. Execution of Medicaid provider agreements
10. Establishment of statewide rate methodology
11. Rules, policies, procedures, and information development
12. Quality assurance and quality improvement activities

### Brief Waiver Description - 1 field

| Variable | Description |
|----------|-------------|
| `waiver_description` | Program purpose, goals, structure, and delivery methods (free text) |

### Attachment #1: Transition Plans - 10 fields

Checkboxes indicating types of changes included in this waiver submission.

| Variable | Description |
|----------|-------------|
| `transition_plan_1` | Replacing an approved waiver with this waiver |
| `transition_plan_2` | Combining waivers |
| `transition_plan_3` | Splitting one waiver into two waivers |
| `transition_plan_4` | Eliminating a service |
| `transition_plan_5` | Adding or decreasing an individual cost limit pertaining to eligibility |
| `transition_plan_6` | Adding or decreasing limits to a service or set of services (Appendix C) |
| `transition_plan_7` | Reducing the unduplicated count of participants (Factor C) |
| `transition_plan_8` | Adding new, or decreasing, a limitation on the number of participants |
| `transition_plan_9` | Making changes that could result in participants losing eligibility |
| `transition_plan_10` | Making changes that could result in reduced services to participants |

## Column encoding

- **Checkbox fields**: `1` = checked, `0` = unchecked, empty string = element not found
- **Text fields**: value as string, empty string if not found
- **Radio button fields** (text extraction): empty string (no selection indicator in text files)
