"""Shared collapse logic for split-flag → merged radio variables.

The HTML and text top extractors emit one 0/1 flag per checkbox option
(`cost_limit_instit`, `sd_election_1`, ...). Downstream analysis expects a
single categorical column per radio-button question (`costlimit`,
`sd_election`, ...). This module is the single source of truth for that
mapping.

`collapse_radio_groups` walks each group, looks for the flag that is set to
1, and writes the corresponding option label into the merged column. If no
flag is set the merged column is None. Split flags are removed by default.
"""

from typing import Any, Dict, List, Optional, Tuple


# (merged_name, [(split_flag, option_label), ...])
RADIO_GROUPS: List[Tuple[str, List[Tuple[str, str]]]] = [
    (
        "costlimit",
        [
            ("cost_limit_nolimit", "No Cost Limit"),
            ("cost_limit_excsinst_costs", "Cost Limit in Excess of Institutional Costs"),
            ("cost_limit_instit", "Institutional Cost Limit (100% of level of care)"),
            ("cost_limit_lowerinstit", "Cost Limit Lower Than Institutional Costs"),
        ],
    ),
    (
        "spousal_impov_bc",
        [
            ("spousal_impov_b", "Use spousal post-eligibility rules"),
            ("spousal_impov_c", "Use regular post-eligibility rules"),
        ],
    ),
    (
        "local_eval",
        [
            ("local_eval_a", "Directly by the Medicaid agency"),
            ("local_eval_b", "By the operating agency specified in Appendix A"),
            ("local_eval_c", "By an entity under contract with the Medicaid agency"),
            ("local_eval_d", "Other"),
        ],
    ),
    (
        "local_eval_instrument",
        [
            ("local_eval_instrument_same", "Same instrument used for waiver and institutional level of care"),
            ("local_eval_instrument_diff", "Different instrument used for waiver vs. institutional level of care"),
        ],
    ),
    (
        "sd_election",
        [
            ("sd_election_1", "Waiver supports only individuals who want to direct"),
            ("sd_election_2", "Every participant has opportunity to elect"),
            ("sd_election_3", "Subject to criteria specified by State"),
        ],
    ),
    (
        "sd_authority",
        [
            ("sd_employerauth", "Participant: Employer Authority"),
            ("sd_budgetauth", "Participant: Budget Authority"),
            ("sd_bothauth", "Both Authorities"),
        ],
    ),
]


def collapse_radio_groups(
    data: Dict[str, Any], drop_flags: bool = True
) -> Dict[str, Any]:
    """Return a new dict with split radio flags collapsed into merged columns.

    For each group, the option whose flag == 1 wins. If no flag is set the
    merged column is None. When `drop_flags` is True the per-option flags are
    removed from the output.
    """
    out = dict(data)
    for merged_name, options in RADIO_GROUPS:
        present = [(flag, label) for flag, label in options if flag in out]
        if not present:
            continue
        selected: Optional[str] = None
        for flag, label in present:
            if out.get(flag) == 1:
                selected = label
                break
        out[merged_name] = selected
        if drop_flags:
            for flag, _ in present:
                out.pop(flag, None)
    return out
