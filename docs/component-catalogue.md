# Component catalogue (branch `feat/component-catalogue`, release v16.5.0)

Status: **built, not committed or released** (2026-10-22). 27 unit + 60 integration tests pass on
HRMS 16.51. Builds on v16.4.0 (`taxable-income-engine.md`). Items 12-14 of
`research-2026-10-22.md` §4.

## What changes

1. **Employer contributions on HRMS's native type (accounting fix).** NSSF Employer, Housing Levy
   Employer and NITA were earnings with *Do Not Include in Total* and *Do Not Include in Accounts*
   off. HRMS's Payroll Entry posts such rows as expense **and adds them to Payroll Payable**
   (`payroll_entry.py` `get_salary_components` / `set_payable_amount_against_payroll_payable_account`),
   so after paying salaries Payroll Payable kept the employer share and NSSF / Housing Levy / NITA
   Payable never received it. Now they're *Employer Contribution* components (type exists on HRMS
   16.20.1 and 16.51), each with a liability account; Payroll Entry posts them in a separate
   journal entry (expense Dr, liability Cr). The engine writes them to the slip's
   `employer_contributions` table and drops legacy earnings rows.
   Test: `TestEmployerContributionAccounting` runs a real Payroll Entry and checks the ledger.
   Caveat: with *Process Payroll Accounting Entry based on Employee* on, HRMS puts the employee as
   party on the liability rows; the statutory payables are type *Tax*, so check that before a
   client turns it on.
2. **Allowances per employee.** New structures read House / Transport / Other Allowance from custom
   fields on Salary Structure Assignment (`royce_house_allowance`, `royce_transport_allowance`,
   `royce_other_allowance`; formulas can read assignment fields on 16.20 and 16.51). Existing
   structures keep `base * 0.15` / `base * 0.10`: a pay change must be explicit.
3. **Catalogue.** 22 seeded components (`setup.component_specs()`) with correct tax flags, P9A/P10A
   mapping and accounts: overtime, bonus, commission, leave pay, acting allowance, salary arrears,
   meals (tax-free part), expense reimbursement (untaxed, no statutory charges), car and housing
   benefit (non-cash, not paid or posted), pension, post-retirement medical fund, insurance
   premium, HELB, SACCO, welfare, union dues, staff loan repayment. New optional accounts:
   *Employee Deductions Payable* (under Accounts Payable) and *Staff Loans* (under Loans and
   Advances (Assets)); skipped where the chart lacks the parent group.
4. **Ownership.** `owned` = the eight statutory components, re-applied by provision/regenerate.
   Everything else is created once and never overwritten. Structure rows take their formula from
   the spec, so a new structure on an old site doesn't inherit `base * 0.15` from a seeded master.
5. **Payslip.** Employer box reads the Employer Contributions section; benefits in kind get their
   own box instead of appearing as "paid by your employer".
6. **Patch** `v16_5_component_catalogue`: field sync, type change + liability accounts, catalogue,
   accounts for provisioned companies.

## Not in this branch

- Terminal dues (notice pay, severance, gratuity): statutory treatment to confirm first.
- Salary advances: use HRMS's own Employee Advance (recovered through Additional Salary).
- Moving existing employees off the 15% / 10% structure: a client decision, done with new
  assignments on the new structure.
