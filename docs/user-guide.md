# Kenya Payroll — User Guide

This guide is for whoever is actually running `royce_payroll_ke` against a client — setting up a
new company's payroll, or updating rates after a Finance Act change. For *why* it's built this
way, see `architecture.md` instead; this doc only covers *how to use what exists today*.

**What this app replaces:** the Royce Payroll Setup Guide v2.1's manual sections 3–9 — Chart of
Accounts, 22 Salary Components, the Income Tax Slab placeholder, and the Salary Structure, all
built by hand, in exact order, per client. This app builds the same result from one data record.

**What's not built yet — set expectations before you start:**
- No desk UI button. Every step below that says "run" means typing a command, not clicking one.
- No P9A/P10A/NSSF/SHIF/Housing Levy reports yet — `csf_ke`'s equivalents still work if that app
  happens to be on the site, but nothing in this app produces them itself yet.
- No `royce_provision` orchestration app — this guide runs `royce_payroll_ke` directly against one
  company at a time, not as part of an automated client-onboarding flow.

---

## 1. Prerequisites

Same as the original guide's section 2 — this app doesn't create any of these for you:

| Item | Where to check | Required value |
|---|---|---|
| Company record | Setup → Company | Country: Kenya, a real Abbr |
| Standard Chart of Accounts | Accounting → Chart of Accounts | `Duties and Taxes - {ABBR}`, `Indirect Expenses - {ABBR}`, `Accounts Payable - {ABBR}` must already exist under their usual parents — normal for any Company with Country set to Kenya at creation time |
| `hrms` installed | `bench --site [site] list-apps` | Present |
| Fiscal Year | Accounting → Fiscal Year | Covers the dates you'll run payroll for |

If a standard account is missing, `provision()` (below) fails immediately with a clear error
naming exactly which one — it won't create Chart of Accounts groups for you, only the specific
statutory/expense accounts under them.

---

## 2. Step 1 — Create a Kenya Payroll Rates record

This replaces Appendix A being retyped into 15 components by hand. One record holds every number
KRA publishes; the generator does the retyping.

**This is per-SITE, not per-environment or per-bench** — `KenyaPayrollRates.get_effective()` has no
company filter, which reads as "one record for everything," but a site is its own database, and
that record doesn't cross sites. If you're onboarding through `royce_provision`, you don't need to
do anything here: `onboard_client()`'s payroll branch calls `seed_default_rates()` itself, on this
site, every time, safely (no-ops if it's already there). Run it by hand only if you're working
directly on this app without going through onboarding, or want different values than the shipped
default from the start:

```
bench --site [this-site] execute royce_payroll_ke.kenya_payroll.setup.seed_default_rates
```

It creates and submits exactly the record documented below (the current known values). Use the
manual UI steps below only when the numbers actually change (a real Finance Act update) or you want
different values than the shipped default.

`Ctrl+K → Kenya Payroll Rates → New`

| Field | Example value (Feb 2026 rates) |
|---|---|
| Effective From | `2026-01-01` |
| PAYE Bands (5 rows — see below) | |
| NSSF Tier I Limit | 9,000 |
| NSSF Tier II Limit | 108,000 |
| NSSF Employee Rate | 6% |
| NSSF Employer Rate | 6% |
| SHIF Rate | 2.75% |
| SHIF Minimum | 300 |
| AHL Employee Rate | 1.5% |
| AHL Employer Rate | 1.5% |
| NITA Amount | 50 |
| Personal Relief | 2,400 |

**PAYE Bands table** — exactly 5 rows, contiguous, band 5's Upper Bound left blank:

| Band | Lower Bound | Upper Bound | Rate |
|---|---|---|---|
| 1 | 0 | 24,000 | 10% |
| 2 | 24,000 | 32,333 | 25% |
| 3 | 32,333 | 500,000 | 30% |
| 4 | 500,000 | 800,000 | 32.5% |
| 5 | 800,000 | *(blank)* | 35% |

Save, then **Submit**. If the bands are wrong — wrong count, a gap, band 5 not left open-ended —
you'll get a specific error naming the problem instead of a silently wrong payslip later. That
validation is the whole point of this doctype existing; don't work around it.

---

## 3. Step 2 — Run `provision()`

No button yet, so this is a terminal command:

```
bench --site [your-site] execute royce_payroll_ke.kenya_payroll.setup.provision --kwargs '{"company": "Royce Technologies LTD"}'
```

Leave out `"rates"` and it uses whichever submitted, non-disabled Kenya Payroll Rates record has the
latest Effective From on or before today. To target a specific version instead:

```
bench --site [your-site] execute royce_payroll_ke.kenya_payroll.setup.provision --kwargs '{"company": "Royce Technologies LTD", "rates": "2026-01-01"}'
```

If you're testing from a browser instead of a terminal (logged into the desk as a System Manager),
the same call works from the browser's dev console:

```js
frappe.call({
  method: "royce_payroll_ke.kenya_payroll.setup.provision",
  args: { company: "Royce Technologies LTD" },
  callback: (r) => console.log(r.message),
});
```

**Safe to re-run.** Every step checks what already exists before creating anything — running it
twice against the same company doesn't duplicate accounts, components, or the structure.

---

## 4. What `provision()` actually creates

| Created | Where to look | Notes |
|---|---|---|
| 5 statutory payable accounts | Chart of Accounts, under `Duties and Taxes - {ABBR}` | PAYE, NSSF, SHIF, Housing Levy, NITA Payable |
| 4 expense accounts | Chart of Accounts, under `Indirect Expenses - {ABBR}` | Salary Expense + 3 employer-cost accounts |
| `Payroll Payable - {ABBR}` | Chart of Accounts, under `Accounts Payable - {ABBR}` | Only created if missing — usually already exists |
| 36 Salary Components | Salary Component list | Global — shared across every company on the site, not just this one |
| `Kenya PAYE Placeholder {year}` | Income Tax Slab list | Empty, submitted — required by HRMS validation, never actually read |
| A Payroll Period covering the calendar year | Payroll Period list | Skipped if one already covers that year for this company |
| `{ABBR} Payroll Structure {rates version}` | Salary Structure list | Submitted, correct row order baked in — named after the exact Kenya Payroll Rates record, not just the year (see section 7) |
| `{ABBR} Kenya Casual Wages` | Salary Structure list | For casual workers paid monthly on a daily rate (v16.6.0+, see section 7E) |
| `Kenya Service Gratuity` | Gratuity Rule list | 15 days' basic salary per year of service (v16.7.0+, see section 7F) |

---

## 5. Step 3 — Assign an employee

Standard HRMS step, no automation here (deliberately — this is per-employee, not per-company):

`Ctrl+K → Salary Structure Assignment → New`

| Field | Value |
|---|---|
| Employee | the employee |
| Salary Structure | `{ABBR} Payroll Structure {year}` |
| Company | (auto) |
| From Date | first date the structure applies |
| Base | the employee's monthly basic salary |
| Income Tax Slab | `Kenya PAYE Placeholder {year}` — required, never actually used in the calculation |
| Payroll Cost Centers | at least one row, usually 100% to the employee's main cost center |

Save → Submit.

---

## 6. Step 4 — Run payroll and check the numbers

Bulk (normal monthly run): `Payroll Entry → New` → set the period → **Get Employees** →
**Create Salary Slips** → review at least one before submitting.

Individual (one employee, ad hoc): `Salary Slip → New` → pick the employee and period.

**What to check on the first slip for any new setup**, before trusting it for real payroll:
- Gross Pay = sum of the real earnings only (Basic + allowances) — NSSF Employer, AHL Employer,
  and NITA must **not** appear in it; they're employer-side costs, excluded by design.
- PAYE, NSSF, SHIF, Housing Levy amounts are plausible for the gross pay involved.
- Open the linked Journal Entry after submitting and confirm it balances.

Hand-calculate one payslip independently before trusting a new Kenya Payroll Rates version or a new
company's setup — that's not optional. The generator faithfully encodes the formulas it's given;
it can't catch an error in the input data (a mistyped rate, a wrong band boundary) by itself.

**A faster structural check, before you get that far:** `verify(company)` confirms the 22
components exist with formulas, every account has the correct Account Type, and the current Salary
Structure has the right rows in the right order — without touching any employee data, so it's safe
to run against a real client's site at any time, not just right after provisioning.

```
bench --site [your-site] execute royce_payroll_ke.kenya_payroll.setup.verify --kwargs '{"company": "Royce Technologies LTD"}'
```

Raises with every problem it finds, not just the first, and returns a clean summary if there aren't
any. This checks structure, not arithmetic — it can tell you a component is missing its formula, not
whether the formula computes the right number. Still hand-calculate at least one real payslip; this
is a faster first check, not a replacement for one.

---

## 7. When KRA changes a rate

1. Create a **new** Kenya Payroll Rates record with the new numbers and the new `Effective From` date.
   Submit it. The old version stays in the system, untouched, for history/audit.
2. That's it. Since v16.4.0 every payslip uses the Kenya Payroll Rates record in force on its
   period's end date, so payslips for periods on or after the new date use the new numbers. No
   regenerate, no new Salary Structure, no re-assigning employees. Payslips already submitted keep
   their figures (each records which rates record it used, in its Kenya PAYE section).

`regenerate()` still exists, but only to re-apply Kenya Payroll's own component definitions (for
example after a Kenya Payroll upgrade). It never touches a client's own components.

---

## 7B. Telling Kenya Payroll how each component is taxed (v16.4.0+)

NSSF, SHIF, Housing Levy and PAYE are calculated by Kenya Payroll on each payslip, from flags on
each Salary Component and the employee's Kenya Tax details. Nothing is hard-coded per component.

**Earnings** (Salary Component, Kenya Payroll section):
- **Is Tax Applicable** (HRMS's own field): part of taxable pay. Untick for reimbursements.
- **Counts for NSSF / SHIF / Housing Levy**: which statutory charges apply. A new earning starts
  with all three ticked; untick them for reimbursements and other non-salary payments.
- **Non-Cash Benefit**: a benefit in kind (car, housing). Also tick Do Not Include in Total.
  Taxable once the month's benefits reach the threshold in Kenya Payroll Rates (KES 5,000).
- **Tax-Free Allowance = Meals**: the first KES 5,000 a month is tax-free.

**Deductions** (Kenya Tax Treatment):
- **Pension Contribution**: added to NSSF; together allowed up to KES 30,000 a month.
- **Post-Retirement Medical Fund**: allowed up to KES 15,000 a month.
- **Mortgage Interest**: allowed up to KES 30,000 a month.
- **Insurance Premium**: gives insurance relief (15%, up to KES 5,000 a month).
- Blank: an ordinary after-tax deduction (loans, SACCO, HELB, welfare).

**Allowances per employee (v16.5.0+):** House, Transport and Other Allowance are monthly
amounts on each employee's **Salary Structure Assignment**, next to Base, not a fixed share of
basic. Leave them at 0 for a consolidated salary. A change of allowance is a new assignment with a
From Date, like a pay rise. Structures set up before v16.5.0 keep their old 15% / 10% formulas
until you move employees to a new structure.

**Pay that changes month to month** (overtime, bonus, commission, leave pay, acting allowance,
arrears, meals, reimbursements, car or housing benefit) and **deductions** (pension, medical fund,
insurance premium, HELB, SACCO, welfare, union dues, staff loan) go in through **Additional
Salary**, ticking *Is Recurring* with From/To dates for a standing monthly deduction. Kenya Payroll
creates all of these components with the right tax flags and accounts; you can edit them, and
upgrades never overwrite your edits (only the eight statutory components are Kenya Payroll's).

**Employer contributions** (NSSF, Housing Levy, NITA) appear in the slip's Employer Contributions
section and post to their own expense and liability accounts (NSSF / Housing Levy / NITA Payable)
in a separate journal entry when the Payroll Entry is submitted.

**Employee** (Kenya Tax section): tax category (Primary or Secondary Employment), mortgage interest
(monthly, from the lender's certificate), and a disability exemption with its certificate number and
expiry date. Insurance relief only applies to premiums deducted through payroll (the Insurance
Premium deduction); premiums an employee pays directly are claimed in their own annual return.

Every limit above lives on Kenya Payroll Rates and changes with a new rates record. Each payslip's
**Kenya PAYE** section shows the full working: taxable pay, what was allowed, tax charged, reliefs.

---

## 7C. Reviewing a payroll run (Payroll Review)

Before submitting a month's slips, open **Payroll Variance** (Kenya Payroll → Payroll Review):
pick the company and the month. Draft slips are included, so you can review the run before
approving it. Every employee is compared with the month before (or the month in *Compare
With*): **New** (joined), **Left** (paid last month, not this month), **Changed**, with gross
and net before and after and a plain list of what changed ("Basic Salary +10,000 · Overtime new
3,000 · PAYE +2,400"). Unchanged employees are hidden unless you tick *Show Unchanged*. The
summary at the top shows headcount, joiners, leavers and the change in total gross and net.

**Payroll Register** is the month's payroll on one sheet: each employee's KRA PIN, ID, NSSF and
SHA numbers, days paid, every earning, deduction and employer contribution in its own column,
gross, total deductions, net pay and taxable pay, with a totals row. Export it to Excel for the
accountant or the auditor. It shows submitted slips unless you tick *Include Draft Slips*.

---

## 7D. Payroll checks (Kenya Payroll Settings)

Kenya Payroll checks every salary slip before it is submitted:

| Check | Default | Why |
|---|---|---|
| Deductions above two-thirds of gross pay (loan repayments included) | Block | Employment Act 2007, s.19(3) |
| Missing or badly formatted KRA PIN (letter, 9 digits, letter) | Block | KRA's PAYE return lists employees by PIN |
| Missing ID, NSSF or SHA number | Warn | Needed for the NSSF, SHA and KRA returns |
| Missing bank account number when Salary Mode is Bank | Warn | The payment would fail |

When you save a Payroll Entry you get one list of every employee with missing details. When the
Payroll Entry submits its slips, a slip that fails a **Block** check stays in draft (the rest go
through) and is listed as not submitted; fix it and submit again. Change any check to Block,
Warn or Off in **Kenya Payroll Settings** (Kenya Payroll → Setup).

---

## 7E. Casual workers (paid monthly on a daily rate)

For workers on a daily rate who are paid at the end of the month (v16.6.0+). Every company
set up for Kenya Payroll has a second structure, `{ABBR} Kenya Casual Wages`, with one pay
row: **Casual Wages = daily rate × Days Worked**. NSSF, SHIF, Housing Levy, PAYE and the
employer contributions are worked out exactly as for salaried staff, on the month's wages.

1. **Assign the structure.** Salary Structure Assignment as in section 5, with Salary
   Structure `{ABBR} Kenya Casual Wages` and **Base = the daily rate** (e.g. 1,500). Leave the
   House/Transport/Other Allowance fields empty: this structure doesn't use them.
2. **Run payroll as usual** (Payroll Entry → Create Salary Slips).
3. **Enter the days.** Open each casual worker's draft slip, type **Days Worked** (next to
   Payment Days) and save: the wages and every deduction are recalculated. For many workers,
   use Data Import (Update Existing Records) on Salary Slip with the Days Worked column.
4. **Submit** from the Payroll Entry. A casual slip with no Days Worked, or more days than the
   month has, is not submitted (it stays in draft, listed on the Payroll Entry).

Overtime and other one-off pay go through Additional Salary, the same as for salaried staff.

**Worked example:** 1,500 a day × 20 days = 30,000. NSSF 540 + 1,260, SHIF 825, Housing Levy
450, PAYE 731, net pay 26,194.

**Kenya Payroll structures are Monthly only.** All the bands, reliefs, limits and minimums
are monthly, and KRA taxes weekly or daily pay on the month's total. A Kenya Payroll structure
set to Weekly, Fortnightly or Daily can't be saved, and its slips are refused. Weekly pay is
not supported yet; see `docs/research-2026-10-22.md` §5.

**Casual for a long time?** Under the Employment Act (s.37), a casual worker kept on
continuously for more than a month, or doing work that adds up to three months or more, is
treated as on a monthly contract. Kenya Payroll doesn't check this; review it with the
employer.

---

## 7F. Paying a leaver (v16.7.0+)

Everything a leaver is owed goes on their **last salary slip**, so PAYE, NSSF, SHIF and
Housing Levy are worked out on it in the normal way.

1. **Set the Relieving Date** on the Employee. The last slip pays up to that date.
2. **Add what they're owed** for that month:

| Owed | How | Default treatment |
|---|---|---|
| Notice pay (in lieu of notice) | Additional Salary, component **Notice Pay** | Taxed; NSSF, SHIF, Housing Levy |
| Untaken leave | Leave Encashment (paid through Leave Pay), or Additional Salary with **Leave Pay** | Taxed; NSSF, SHIF, Housing Levy |
| Severance (redundancy, at least 15 days' pay per completed year, s.40) | Additional Salary, component **Severance Pay** | Taxed; SHIF, Housing Levy; no NSSF |
| Gratuity / service pay | HRMS **Gratuity** with rule `Kenya Service Gratuity`, Pay via Salary Slip, component **Gratuity** | Not taxed (earned from 1 July 2025); SHIF, Housing Levy; no NSSF |
| Loan or advance still owed | Additional Salary with the deduction (e.g. Staff Loan Repayment) | Not limited by the one-third rule on the last slip |

3. **Run payroll** as usual.

**Confirm the defaults with your tax adviser.** Whether NSSF, SHIF and Housing Levy apply to
notice pay and severance, and whether any severance is tax-free, are not settled. The defaults
charge them where unsure. Each component's description says what it does; change the ticks
in its Kenya section (Salary Component) if your adviser says otherwise. Gratuity earned before
July 2025 may be taxable and isn't handled here.

**Gratuity Rule.** `Kenya Service Gratuity` pays half a month's Basic Salary (15 days of 30)
per year of service, part years pro rata, from one year of service. Basic is read from the
employee's last submitted slip. Edit the rule if a contract pays more or counts 26 working
days; Kenya Payroll never overwrites it. Statutory service pay (s.35(5)) isn't owed to
employees who are in NSSF or a pension scheme; gratuity for them is whatever the contract says.

**One-third rule.** On the slip that reaches the Relieving Date, deductions may exceed
two-thirds of pay (recovering final dues). Net pay still can't be negative: HRMS refuses
such a slip, so a larger balance is recovered another way.

**Full and Final Statement.** If you also use one (for the asset return and the record), leave
its Gratuity and Leave Encashment rows out when the salary slip paid them: its journal entry
would pay them a second time.

---

## 7G. Staff loans (v16.8.0+)

For loans to employees repaid through payroll. (Salary advances: use HRMS's **Employee
Advance**.) Open **Kenya Payroll → Staff Loans → Staff Loan**.

1. **Create the loan:** employee, Loan Amount, Disbursement Date, Repayment Starts (any date in
   the first month to deduct), and either Monthly Repayment or Repayment Months. Interest Rate
   is a yearly rate charged on the balance each month (0 for an interest-free loan). Submit.
2. **Pay it out** with a Payment Entry or Journal Entry: debit **Staff Loans**, credit the bank.
3. **Run payroll as usual.** Each slip deducts **Staff Loan Repayment** (the monthly amount, or
   the balance if less) and **Staff Loan Interest**. The loan's balance and deductions table
   update when the slip is submitted, and go back if the slip is cancelled. The loan shows
   **Repaid** when the balance reaches zero.

**Leavers.** The slip that reaches the employee's Relieving Date deducts the whole balance, as far
as their pay covers it (net pay can't go below zero). The one-third rule doesn't apply to that
slip. Any balance left stays on the loan; recover it another way.

**Writing a loan off.** On the loan, **Write Off** and pick a date. The slip covering that date
clears the balance and adds the same amount to pay as **Staff Loan Write-off**, so net pay is
unchanged but PAYE (and, by default, SHIF and Housing Levy) is charged on it: a forgiven loan is
a taxable benefit. Confirm the levies with your tax adviser. **Cancel Write Off** undoes it
until that slip is submitted.

**Fringe benefit tax.** A loan at a rate below KRA's market interest rate means fringe benefit
tax for the employer (Income Tax Act s.12B): 30% of the interest the employee didn't pay,
paid with the month's PAYE by the 9th. Enter KRA's market rate for each quarter in **Kenya
Payroll Settings → Fringe Benefit Tax**, then run **Fringe Benefit Tax** (Kenya Payroll → Staff
Loans) for the month: one row per loan with the PAYE return's Sheet D columns, the benefit and
the tax. The tax is not posted to the accounts; post it with the PAYE payment.

Loans already deducted through Additional Salary keep working. An employee is handled by
Staff Loan only once they have one; don't use both for the same employee.

---

## 7H. Payslips by SMS (v16.9.0+)

Texts each employee a short pay summary, through the **Bulk SMS** app (it must be installed,
enabled and have an API key and an approved Sender ID: see its own guide). The number used is
the **Mobile** (cell number) on the Employee.

- **Whole payroll run:** open the submitted Payroll Entry → **Send Payslips by SMS**. A preview
  shows how many will be sent, who is skipped (no mobile number, or already sent), an example
  message and the estimated cost. **Send** sends in the background; the result appears as a
  message and as a comment on the Payroll Entry. Tick **Also resend to those already sent** to
  send again to everyone.
- **One employee:** open their submitted Salary Slip → **Send by SMS** (always sends).
- Every message is in **Bulk SMS Log**, linked to its salary slip, with status and cost.

The default message is about one SMS (160 characters):

> Jane Wanjiku, Oct 2026 pay: gross 50,000, deductions 11,018, net KES 38,982. Test Hardware Ltd

Change it in **Kenya Payroll Settings → Payslip SMS Template** (Jinja: `{{ employee_name }}`,
`{{ first_name }}`, `{{ month }}`, `{{ gross }}`, `{{ deductions }}`, `{{ net }}`, `{{ paye }}`,
`{{ company }}`, `{{ doc }}`). Anyone holding the phone can read an SMS, so keep it a summary:
no KRA PIN, loans or other personal details. Nothing is sent automatically when slips are
submitted.

Pay data goes to the SMS provider (RoyceTalk); include that in your data protection records.

---

## 7A. Running the statutory reports

Seven reports exist once submitted Salary Slips do: **Kenya NSSF Contributions**, **Kenya SHIF
Contributions**, **Kenya Housing Levy Contributions**, **Kenya NITA Contributions**, **Kenya P10A
Monthly Return**, **Kenya P9A Tax Deduction Card**, and **Kenya Bank Payroll Advice**. `Ctrl+K`,
type the name, find them via `/app/query-report/<name>`, or open the **Kenya Payroll** workspace
from the app switcher — all seven are listed there under Statutory Reports.

- **Bank Payroll Advice** — filter by Company and a From/To Date range; optionally narrow to one
  **Bank Name** if you need a separate file per receiving bank, which is normal practice before
  submission. Reads bank details **live off the Employee record**, not a snapshot on the slip — it
  always reflects the employee's current bank details, which is what a payment run actually needs.
  Requires **Bank Name** and **Account No** (both core ERPNext fields) plus **Bank Code**,
  **Bank Branch**, and **Branch Code** (`royce_bank_code`, `royce_bank_branch_name`,
  `royce_branch_code` — blank until filled in on the Employee).

- **NSSF / SHIF / Housing Levy / NITA** — filter by Company and a From/To Date range. Housing Levy
  deliberately shows *both* employee and employer contributions summed, since that's what
  `Housing Levy Payable` actually accumulates and a report showing only the employee side wouldn't
  reconcile against it. NITA is employer-only — flat 50 per employee per month, regardless of
  gross pay — so its report is purely an employer-cost view, not a "what did we withhold" one.
- **P10A** — filter by Company and any date within the return month (only the month/year is used).
  One row per employee for that month, shaped to match what iTax expects.
- **P9A** — filter by Company, Fiscal Year, and **one specific Employee** — this is a
  per-employee annual certificate, not a company-wide list. Twelve rows, one per calendar month,
  zeros for months with no submitted slip. **For the actual PDF to hand to the employee**, don't
  use the on-screen report's own export — call
  `royce_payroll_ke.kenya_payroll.report.kenya_p9a_tax_deduction_card.kenya_p9a_tax_deduction_card.download_certificate`
  with `company`, `fiscal_year`, and `employee`, e.g.:
  ```
  bench --site [your-site] execute royce_payroll_ke.kenya_payroll.report.kenya_p9a_tax_deduction_card.kenya_p9a_tax_deduction_card.download_certificate --kwargs '{"company": "Royce Technologies LTD", "fiscal_year": "2026", "employee": "HR-EMP-00001"}'
  ```
  (This is a whitelisted method — reachable over the API too, not only `bench execute`; a proper
  "Download PDF" button on the report is on the list, not built yet.)

**Both P9A and P10A read National ID and KRA PIN from the Employee record** (`royce_national_id`,
`royce_kra_pin`) — blank on an employee until someone fills them in, same fields used by the NSSF
and SHIF reports. **`download_certificate()` refuses to generate a P9A if the employee has no KRA
PIN on file** — a certificate missing a legally required field isn't a compliant filing, so this
is a hard block, not a warning. Fill in the PIN and try again.

**A caution on running payroll twice for the same period:** if a `Payroll Entry` run is ever
interrupted before its slips are submitted, the resulting Draft slips don't protect against a
second `Payroll Entry` picking up the same employees again — HRMS's own duplicate check only
excludes employees who already have a **Submitted** slip for that exact period, not a Draft one.
Before creating a new `Payroll Entry` for a period you're not sure was completed, check the Salary
Slip list for that date range first — clean up or submit any stray Drafts rather than starting
fresh and risking duplicates.

---

## 8. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `provision()` throws "Expected parent account ... not found" | Company's Chart of Accounts doesn't have the standard Kenya group accounts — check Country was set to Kenya when the Company was created |
| `provision()` throws about Kenya Payroll Rates not found | No Kenya Payroll Rates record is both submitted and has an Effective From on or before today — check status and date |
| A component's amount looks wrong on a slip after a rate change | The employee is probably still on a Salary Structure Assignment pointing at the *old* rates version's structure — check which structure they're assigned to and whether it needs a new, dated assignment per section 7 |
| "A field with the name ... already exists" during install | Another app already owns that exact field name on the same doctype — shouldn't happen with this app's own fields (they're namespaced `royce_p9a_...` / `royce_p10a_...` specifically to avoid this), but worth knowing if it ever shows up from a different app |
| P9A/P10A show 0 for a column that should have a value | Check the Employee record has `royce_national_id`/`royce_kra_pin` filled in for identity columns; for amount columns, check the Salary Component actually has the right P9A/P10A card type set — blank means excluded on purpose |
| P9A's "Tax Charged" looks slightly off for a very low earner | Expected, not a bug, for the specific case where Gross PAYE fell below the personal relief threshold — PAYE never gets created on that slip at all (its own Condition prevents it), so there's no persisted trace of the true pre-relief figure to derive from. See architecture.md's sixth finding. |

---

## Appendix — rates used in this guide's examples

Current as at February 2026 (NSSF Year 4). These will go stale — check KRA/NSSF/SHA before using
them for a real client, and see `architecture.md` if you're the one updating this document.

| | |
|---|---|
| PAYE personal relief | 2,400/month |
| NSSF Tier I / II limits | 9,000 / 108,000, both at 6% |
| SHIF | 2.75%, 300 minimum |
| Affordable Housing Levy | 1.5% employee, 1.5% employer |
| NITA | 50/month, employer-paid flat |
