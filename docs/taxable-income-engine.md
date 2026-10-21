# Taxable Income Engine (branch `feat/taxable-income-engine`, release v16.4.0)

Status: **built on this branch, not released** (2026-10-22). 21 engine cases and 57
integration tests pass on Frappe/HRMS 16.5x (HRMS 16.51). Covers items 1-7 of the 2026-10-22 improvement list:
flag-driven taxable income, separate statutory bases, capped deductions, reliefs,
employee tax category, and part-month (proration) behaviour.

## 1. Problem

Today `Taxable Income = gross_pay - NSSF_T1 - NSSF_T2 - SHIF - AHL`, a formula string
generated into a Salary Component (`setup.py`). Consequences:

- Every earning is taxed and attracts NSSF, SHIF and Housing Levy, including
  reimbursements and tax-free items. `Is Tax Applicable` is ignored.
- Taxable non-cash benefits (car, housing) are never taxed.
- No pension/provident fund, post-retirement medical fund (PRMF) or mortgage interest
  deduction, no insurance relief, no secondary employment, no disability exemption.
- A client's edit to the formula is overwritten by `regenerate()`, and existing
  Salary Structures keep their own copy of the formula anyway.
- Rates are frozen into each Salary Structure, so a rate change needs a new structure
  and a re-assignment for every employee.

## 2. Decision: calculate statutory amounts in Python, not in generated formulas

**Reverses** "Calculation approach unchanged: band-based PAYE via 22 salary components"
in `architecture.md`. The reason that decision existed (avoid HRMS's annualising Income
Tax Slab engine) still holds: we keep the slab engine off. What changes is *where* our
own monthly calculation runs.

HRMS calls `SalarySlip.apply_regional_deductions()` after earnings and deductions are
computed and before totals and net pay are set. It is overridable per country through
the `regional_overrides` hook (present on HRMS v16.20.1, production today, and v16.51).
Royce registers:

```python
regional_overrides = {
    "Kenya": {
        "hrms.payroll.doctype.salary_slip.salary_slip.apply_regional_deductions":
            "royce_payroll_ke.kenya_payroll.engine.apply_kenya_statutory",
    }
}
```

Why this beats generated formulas:

| | Generated formulas (today) | Python engine |
|---|---|---|
| Client adds an allowance | Must edit TI (and get it right) | Ticks flags; works at once |
| Rate change | New structure + re-assign every employee | New Kenya Payroll Rates record; next slip uses it |
| Caps (`min()`), categories, reliefs | Long, fragile formula strings | Plain, unit-tested code |
| Testing | Needs a real slip | Pure function tested with a table of cases, plus a few real slips |
| Payslip/P9A figures | TI and tax charged are statistical, never saved, so P9A *derives* them | Saved on the slip, reports read them directly |

Region is the site's country (System Settings), so the engine also checks that the slip's
Salary Structure is a Kenya Payroll structure (new check field `royce_kenya_statutory`,
set by the generator and by a patch on existing generated structures). Any other
structure on the site is left alone.

## 3. Calculation, per slip

Inputs: the slip's earning and deduction rows (already prorated by HRMS), flags from each
row's Salary Component, the employee's Kenya tax fields, and the Kenya Payroll Rates
record effective on the slip's **end date** (not the structure's rates version).

1. **Earnings** (skip statistical rows). For each earning row, from its component:
   - taxable cash pay: `Is Tax Applicable`, minus any tax-free allowance (Meals: first
     KES 5,000/month).
   - non-cash benefit (`royce_non_cash_benefit`): collected separately. Taxable in full
     when the month's total is at or above the threshold (KES 5,000/month), otherwise
     not taxable. Must be `Do Not Include in Total` so it never reaches net pay.
   - NSSF base (`royce_nssf_pensionable`), SHIF base (`royce_shif_applicable`),
     Housing Levy base (`royce_ahl_applicable`).
2. **NSSF employee**: Tier I = min(base, LEL) x 6%; Tier II = max(0, min(base, UEL) - LEL) x 6%.
   Limits apply in full in a part month (not prorated).
3. **SHIF** = max(minimum, base x 2.75%) when base > 0. The KES 300 minimum is never prorated.
4. **Housing Levy** = base x 1.5%.
5. **Capped deductions** (each monthly cap from Kenya Payroll Rates):
   - pension pool = NSSF employee + deductions typed *Pension Contribution*, capped at 30,000.
   - PRMF = deductions typed *Post-Retirement Medical Fund*, capped at 15,000.
   - mortgage interest = employee's declared monthly interest + deductions typed
     *Mortgage Interest*, capped at 30,000.
6. **Taxable pay** = taxable cash + taxable non-cash - pension pool - PRMF - mortgage
   - SHIF - Housing Levy, floored at 0. Disability exemption (valid certificate for the
   period): subtract the exempt amount, floored at 0.
7. **Tax charged**:
   - Primary employment: the five monthly bands.
   - Secondary employment: taxable pay x secondary rate, no personal relief.
8. **Reliefs**: personal relief (primary only); insurance relief = min(15% x
   (insurance-premium deductions + declared premiums), 5,000).
9. **PAYE** = max(0, tax charged - reliefs), rounded per the component.
10. **Employer side**: NSSF Employer on the NSSF base (Tier I + II, 6%), Housing Levy
    Employer on the Housing Levy base, NITA flat. Written to the existing employer rows
    (moving them to HRMS's Employer Contribution type is the next branch).

The engine writes the NSSF Tier I/II, SHIF, Housing Levy and PAYE rows with
`update_component_row` (same signature on 16.20 and 16.51), and saves its working on the
slip (read-only "Kenya PAYE" section): taxable pay, pension pool allowed, PRMF allowed,
mortgage interest allowed, disability exemption, tax charged, personal relief, insurance
relief, tax category.

## 4. New fields

**Salary Component** (earnings): `royce_nssf_pensionable`, `royce_shif_applicable`,
`royce_ahl_applicable` (default to the component's `Is Tax Applicable` when created),
`royce_non_cash_benefit`, `royce_tax_free_allowance` (none / Meals).
**Salary Component** (deductions): `royce_kenya_deduction_type` (none / Pension
Contribution / Post-Retirement Medical Fund / Mortgage Interest / Insurance Premium).

**Employee** ("Kenya tax" section): tax category (Primary / Secondary), disability
exemption (check, certificate number, expiry date, exempt amount), declared monthly
mortgage interest, declared monthly insurance premium (paid by the employee directly).

**Kenya Payroll Rates**: pension cap, PRMF cap, mortgage interest cap, insurance relief
rate and cap, non-cash benefit threshold, meals allowance, disability exemption default,
secondary employment rate.

**Salary Slip**: the "Kenya PAYE" read-only fields from section 3.

## 5. What else changes

- **Generator**: drops Taxable Income, the nine band components and Gross PAYE from new
  structures; NSSF/SHIF/AHL/PAYE rows stay (amount filled by the engine); sets the new
  flags on Basic, House and Transport; sets `royce_kenya_statutory` on structures.
  `regenerate()` stops rewriting client components. (Removing the fixed 15%/10%
  allowances is the next branch.)
- **Reports and payslip**: P9A, P10A and the payslip read the saved slip fields instead
  of deriving taxable pay and tax charged. P9A gains the PRMF, mortgage interest and
  insurance relief columns.
- **Patch**: sets the new flags on the generator's earnings, marks existing generated
  structures as Kenya structures, adds the new rates fields to the effective record with
  the 2026 values.
- **Existing structures** keep working: their statistical band rows are ignored and the
  engine fills the statutory rows.

## 6. Tests

- **Engine unit tests** (no database): a table of hand-checked cases. Each band edge
  (24,000 / 32,333 / 500,000 / 800,000), SHIF minimum, NSSF limits, pension above the
  cap, PRMF and mortgage caps, insurance relief cap, non-cash under and over the
  threshold, meals, disability, secondary employment, zero pay, PAYE never negative.
- **Integration**: the guide's worked example (187,550 gross gives PAYE 44,313, unchanged),
  a mid-month joiner (SHIF 300 and NSSF limits not prorated), a tax-free allowance, a
  pension deduction via Additional Salary, an old-style structure.

## 7. Rules still to confirm (configurable, not hard-coded)

| Rule | Value used | Status |
|---|---|---|
| Pension cap 30,000, PRMF 15,000, mortgage 30,000, SHIF/AHL deductible, non-cash 5,000, meals 5,000 | as stated | Confirmed: KRA public notice on the Tax Laws (Amendment) Act 2024 |
| Insurance relief 15%, max 5,000/month | as stated | Income Tax Act s.31; not changed by the 2024 Act as far as found |
| Disability exemption 150,000/month | default, editable per employee | Persons with Disabilities Act 2025 leaves the amount to the exemption granted; confirm |
| Secondary employment rate | defaults to the top band rate (35%), no personal relief | Confirm with KRA / a tax adviser |
| Per diem (10,000/day) | not modelled; treat as a non-taxable reimbursement | Out of scope |

## 8. Notes from building it

- **Part-month bug confirmed in the old design.** HRMS's `update_component_row` re-applies
  payment-days proration to rows that depend on payment days, and the old statutory components
  did. A mid-month joiner's SHIF minimum came out at 150 and a high earner's NSSF was the
  full-month figure halved. The engine writes its rows itself with proration off; tests
  `test_mid_month_joiner_keeps_full_shif_minimum` and `test_high_earner_mid_month_nssf_on_actual_pay`.
- **Personal relief on the slip is the relief used** (capped at the tax charged), so tax charged
  less reliefs always equals PAYE on the payslip. The iTax P10 export (next branch) should declare
  the statutory relief instead if KRA's template expects the full KES 2,400.
- **Production is on HRMS 16.20.1.** The hook exists there with the same signature, but the suite
  has only been run on 16.51. Release this after the 16.5x upgrade, or run the suite on 16.20 first.
- **One structure per company** (`{abbr} Kenya Payroll`) instead of one per rates version; a
  company's pre-v16.4.0 structure is reused.

