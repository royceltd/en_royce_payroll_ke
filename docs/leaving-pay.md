# Leaving pay (branch `feat/casual-monthly`, target v16.7.0)

Status: **built and committed, not released** (2026-10-23). Item 9 of
`research-2026-10-22.md` §4. How to use it: `user-guide.md` §7F.

## What changes

1. **Three catalogue components** (seeded: created once, never overwritten), each with its
   default treatment and "confirm with your tax adviser" in its description:

   | Component | Taxed | NSSF | SHIF | Housing Levy | P10A |
   |---|---|---|---|---|---|
   | Notice Pay | yes | yes | yes | yes | Other Allowance |
   | Severance Pay | yes | no | yes | yes | Other Allowance |
   | Gratuity | no | no | yes | yes | (none) |

   Leave paid out uses the existing **Leave Pay**. Defaults charge SHIF and Housing Levy where
   unsettled (the cautious reading). Gratuity untaxed = gratuity earned from 1 July 2025
   (Finance Act 2025, KRA notice 2246); no spread-back for earlier gratuity (user decision).
2. **Gratuity Rule `Kenya Service Gratuity`** (`setup.ensure_gratuity_rule`): Basic Salary,
   one open slab at 0.5 (15 days of a 30-day month per year, Employment Act s.35(5)), "Take
   Exact Completed Years" (HRMS: unrounded, so part years pro rata), minimum 1 year, 365 days.
   HRMS reads Basic's `default_amount` from the last submitted slip. Created once if missing.
3. **Leave encashment** (`setup.link_leave_encashment`): encashable Leave Types with no
   earning component get Leave Pay (HRMS's Leave Encashment can't submit without one).
4. **One-third rule** (`compliance.is_final_slip`): not applied to a slip whose period
   reaches the employee's Relieving Date (final-dues recoveries). HRMS still refuses a
   negative net pay.
5. **Patch** `v16_7_leaving_pay`: components, account mapping, rule, leave types.

Tests: `test_leaving_pay.py` (4 unit, 5 integration), including a real HRMS Gratuity
computed from the rule and paid on the final slip with notice pay. Full suite 35 unit + 81
integration pass on HRMS 16.51 (1 pre-existing skip).

## Open adviser questions (settings, not code)

- Do NSSF, SHIF and Housing Levy apply to notice pay and to severance?
- Is any severance tax-free today, and how much?
- Is notice pay taxed in the month paid (assumed yes)?

## Not done

- Gratuity earned before July 2025 (taxable, spread-back): not supported by decision.
- Sheet C (lump sums) of the KRA simplified return: with the parked exports.
- Recovery of a balance larger than the final slip's pay (net pay can't go negative).
