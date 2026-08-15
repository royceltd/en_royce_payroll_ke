# Royce Payroll KE — User Guide

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

## 2. Step 1 — Create a Payroll Rates record

This replaces Appendix A being retyped into 15 components by hand. One record holds every number
KRA publishes; the generator does the retyping.

`Ctrl+K → Payroll Rates → New`

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
bench --site [your-site] execute royce_payroll_ke.royce_payroll_ke.setup.provision --kwargs '{"company": "Royce Technologies LTD"}'
```

Leave out `"rates"` and it uses whichever submitted, non-disabled Payroll Rates record has the
latest Effective From on or before today. To target a specific version instead:

```
bench --site [your-site] execute royce_payroll_ke.royce_payroll_ke.setup.provision --kwargs '{"company": "Royce Technologies LTD", "rates": "2026-01-01"}'
```

If you're testing from a browser instead of a terminal (logged into the desk as a System Manager),
the same call works from the browser's dev console:

```js
frappe.call({
  method: "royce_payroll_ke.royce_payroll_ke.setup.provision",
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
| 22 Salary Components | Salary Component list | Global — shared across every company on the site, not just this one |
| `Kenya PAYE Placeholder {year}` | Income Tax Slab list | Empty, submitted — required by HRMS validation, never actually read |
| A Payroll Period covering the calendar year | Payroll Period list | Skipped if one already covers that year for this company |
| `{ABBR} Payroll Structure {rates version}` | Salary Structure list | Submitted, correct row order baked in — named after the exact Payroll Rates record, not just the year (see section 7) |

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

Hand-calculate one payslip independently before trusting a new Payroll Rates version or a new
company's setup — that's not optional. The generator faithfully encodes the formulas it's given;
it can't catch an error in the input data (a mistyped rate, a wrong band boundary) by itself.

---

## 7. When KRA changes a rate

1. Create a **new** Payroll Rates record with the new numbers and the new `Effective From` date.
   Submit it. The old version stays in the system, untouched, for history/audit.
2. Run:
   ```
   bench --site [your-site] execute royce_payroll_ke.royce_payroll_ke.setup.regenerate --kwargs '{"rates": "2027-01-01"}'
   ```
   This re-templates all 22 components' formulas off the new record, **and** builds a fresh Salary
   Structure for every company already provisioned — automatically, no need to name them.
3. For each employee who should move onto the new rates, create a **new** Salary Structure
   Assignment pointing at the new structure, with a From Date on or after the new rates'
   Effective From — same as any other base-salary change (guide section 8). Don't edit or cancel
   their existing assignment; a new dated one takes over automatically.

**Why a new structure instead of updating the old one in place:** Salary Slip reads formulas
straight off the Structure's own rows, not the live Salary Component master — confirmed directly
against the HRMS source, not assumed. An in-place update would leave the Structure's formulas
correct on the master but stale on the row, silently, since the row is only a snapshot taken at
creation time. Naming each Structure after the exact rates version it was built from instead means
there's never a stale copy to worry about: an old Structure keeps meaning exactly what it always
meant, for whoever's still assigned to it, and a new rate always gets its own distinctly-named
Structure rather than mutating one that other people's payslips already depend on.

**What this means in practice:** nothing breaks if you forget to reassign someone after a rate
change — they simply keep running under the old (still internally consistent) structure until you
do. That's the safe failure mode this is designed around, compared to the alternative of an
old assignment silently computing new-rate numbers on stale formulas.

---

## 8. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `provision()` throws "Expected parent account ... not found" | Company's Chart of Accounts doesn't have the standard Kenya group accounts — check Country was set to Kenya when the Company was created |
| `provision()` throws about Payroll Rates not found | No Payroll Rates record is both submitted and has an Effective From on or before today — check status and date |
| A component's amount looks wrong on a slip after a rate change | The employee is probably still on a Salary Structure Assignment pointing at the *old* rates version's structure — check which structure they're assigned to and whether it needs a new, dated assignment per section 7 |
| "A field with the name ... already exists" during install | Another app already owns that exact field name on the same doctype — shouldn't happen with this app's own fields (they're namespaced `royce_p9a_...` / `royce_p10a_...` specifically to avoid this), but worth knowing if it ever shows up from a different app |

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
