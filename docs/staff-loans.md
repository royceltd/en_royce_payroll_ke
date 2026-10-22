# Staff loans (branch `feat/casual-monthly`, target v16.8.0)

Status: **built and committed, not released** (2026-10-23; clicked through on 16.52). How to use it: `user-guide.md` §7G.
Decision (2026-10-22): a light Staff Loan in this app, **not** Frappe Lending. Salary advances
stay on HRMS's Employee Advance (component-catalogue decision).

## What changes

1. **Staff Loan** (submittable, `STL-YYYY-#####`): employee, loan amount, disbursement date,
   yearly interest rate, repayment start, monthly repayment (or months, rounded up). Status
   Draft / Active / Repaid / Written Off / Cancelled; outstanding balance, totals and a read-only
   **Staff Loan Deduction** table (one row per submitted slip). Can't be cancelled once a slip
   has deducted from it. Write Off / Cancel Write Off buttons. Monthly Repayment can be changed after submit.
2. **On the slip** (`staff_loans.py`, called from `engine.apply_kenya_statutory`, Kenya Payroll
   structures only, employees with a Staff Loan only):
   - before the statutory amounts: Staff Loan Repayment = min(monthly, balance) per active loan;
     Staff Loan Interest = balance x rate / 12 (whole shillings); on the slip covering the
     Write Off date, the whole balance as both Staff Loan Write-off (earning) and repayment, no
     interest. Gross pay is re-added because HRMS totals it before the regional hook.
   - final slip (Relieving Date in the period): the whole balance, then `cap_final_recovery`
     reduces it so net pay isn't negative.
   - on submit (`record_slip`): amounts recomputed and checked against the slip's rows (a
     balance changed by another slip in between = "save the slip again"), then one deduction
     row per loan, oldest loan first; on cancel (`reverse_slip`): removed.
3. **Components** (seeded): Staff Loan Interest (deduction, credit **Staff Loan Interest
   Income**, a new optional account under Indirect Income); Staff Loan Write-off (earning:
   taxed, SHIF and Housing Levy, no NSSF, P10A Other Allowance, "confirm with your tax adviser").
   Staff Loan Repayment (v16.5.0) credits Staff Loans.
4. **Fringe benefit tax:** Kenya Payroll Settings gets FBT rate (default 30%) and a table of
   KRA market rates by quarter. Report **Kenya Fringe Benefit Tax** (month): per loan below the
   market rate, Sheet D columns + benefit (balance x (market - loan rate) / 12) + tax. Balance =
   outstanding during the month, before its own repayment (a loan disbursed in the month counts
   in full). Nothing posted.
5. Desk: "Staff Loans" section (sidebar 16.5x and 16.36 formats, workspace card).
6. **Patch** `v16_8_staff_loans`: components, account, mappings.

Tests: `test_staff_loans.py` (3 unit, 8 integration). Full suite 38 unit + 89 integration on
HRMS 16.51 (1 pre-existing skip); `check_names.py` passes.

## Assumptions to confirm with a tax adviser

- FBT charged on the balance outstanding during the month (before that month's repayment).
- Market rate applies from the date entered (KRA publishes one per quarter).
- Write-off taxed in full in the month written off, with SHIF and Housing Levy.

## Not done

- Disbursement entry (done by hand: Payment / Journal Entry to Staff Loans).
- Posting FBT to the ledger; loans to directors (also s.12B) aren't treated differently.
- Changing the interest rate of a submitted loan (the FBT report uses the loan's current rate).
