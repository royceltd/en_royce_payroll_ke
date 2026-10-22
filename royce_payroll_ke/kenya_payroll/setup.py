# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""The generator: sets a company up for Kenya payroll.

Replaces sections 3-9 of the Royce Payroll Setup Guide v2.1 — Chart of Accounts, the
Salary Components, the Income Tax Slab placeholder, the Payroll Period, and the Salary
Structure. Since v16.4.0 the statutory amounts (NSSF, SHIF, Housing Levy, PAYE) are
calculated by engine.py on each slip, not by formulas generated here.

Three entry points:
  seed_default_rates() - per-SITE bootstrap (each client's site is its own database, so
                          this genuinely runs once per site, not once for the whole
                          business). Called automatically by royce_provision's
                          onboard_client() before provision(), so it's not something
                          onboarding staff need to remember separately. Idempotent either
                          way — no-ops if this site already has an effective record.
  provision(company)  - full company setup, run once per new client.
  regenerate()         - re-applies Kenya Payroll's own component definitions (never a
                          client's own components) and account mappings. A rate change
                          needs no regenerate any more: the engine reads the rates in
                          force for each slip's period.

All three are safe to run more than once: every step checks for what already exists
before creating anything.
"""

from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import flt, getdate

from royce_payroll_ke.kenya_payroll.doctype.kenya_payroll_rates.kenya_payroll_rates import KenyaPayrollRates

# ---------------------------------------------------------------------------
# Chart of Accounts
# ---------------------------------------------------------------------------

STATUTORY_PAYABLE_ACCOUNTS = [
	("PAYE Payable", "Duties and Taxes", "Tax"),
	("NSSF Payable", "Duties and Taxes", "Tax"),
	("SHIF Payable", "Duties and Taxes", "Tax"),
	("Housing Levy Payable", "Duties and Taxes", "Tax"),
	("NITA Payable", "Duties and Taxes", "Tax"),
]

EXPENSE_ACCOUNTS = [
	("Salary Expense", "Indirect Expenses", "Expense Account"),
	("NSSF Employer Expense", "Indirect Expenses", "Expense Account"),
	("AHL Employer Expense", "Indirect Expenses", "Expense Account"),
	("NITA Expense", "Indirect Expenses", "Expense Account"),
]

# For the catalogue's deductions (v16.5.0). Optional: a chart without the parent group
# just doesn't get the account, and map_accounts() skips the components that need it.
# No account type, so Payroll Entry can credit them without a party.
CATALOGUE_ACCOUNTS = [
	("Employee Deductions Payable", "Accounts Payable", ""),  # HELB, SACCO, pension, insurance...
	("Staff Loans", "Loans and Advances (Assets)", ""),  # staff loan repayments reduce this asset
]


def _ensure_account(account_name, parent_name, account_type, company, abbr, optional=False):
	"""Create an account if missing. If it already exists — which happens for
	Payroll Payable specifically, since ERPNext auto-creates it at company setup —
	verify its Account Type is still correct and fix it if not. Existence alone
	isn't enough of a check: an auto-created Payroll Payable account can (and on
	real data, does) come with a blank Account Type, which HRMS's Payroll Entry
	silently refuses to disburse against until it's set."""
	full_name = f"{account_name} - {abbr}"

	if frappe.db.exists("Account", full_name):
		if frappe.db.get_value("Account", full_name, "account_type") != account_type:
			frappe.db.set_value("Account", full_name, "account_type", account_type)
		return

	parent_account = frappe.db.get_value("Account", f"{parent_name} - {abbr}", "name")
	if not parent_account and optional:
		return
	if not parent_account:
		frappe.throw(
			_("Expected parent account {0} not found under {1} — is the Chart of Accounts set up?").format(
				f"{parent_name} - {abbr}", company
			)
		)

	frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"company": company,
			"parent_account": parent_account,
			"account_type": account_type,
			"is_group": 0,
		}
	).insert(ignore_permissions=True)


def ensure_accounts(company):
	"""Create the statutory payable and salary expense accounts, per guide section 4.

	Leaves the Employee Contributions group / Welfare Payable alone — those are only
	created when a client actually has a voluntary-deduction scheme (guide section 6.10),
	which is outside what provisioning a company needs by default.
	"""
	abbr = frappe.db.get_value("Company", company, "abbr")

	for account_name, parent_name, account_type in STATUTORY_PAYABLE_ACCOUNTS + EXPENSE_ACCOUNTS:
		_ensure_account(account_name, parent_name, account_type, company, abbr)

	_ensure_account("Payroll Payable", "Accounts Payable", "Payable", company, abbr)

	for account_name, parent_name, account_type in CATALOGUE_ACCOUNTS:
		_ensure_account(account_name, parent_name, account_type, company, abbr, optional=True)

	# So Payroll Entry pre-fills this instead of making someone pick it by hand every
	# run — one fewer manually-selected account, one fewer chance to pick the wrong one.
	# Only set if currently blank: don't override a deliberate client customisation.
	if not frappe.db.get_value("Company", company, "default_payroll_payable_account"):
		frappe.db.set_value(
			"Company", company, "default_payroll_payable_account", f"Payroll Payable - {abbr}"
		)


# ---------------------------------------------------------------------------
# Salary Components
# ---------------------------------------------------------------------------
#
# Two kinds of component (v16.5.0):
#   owned  - the eight statutory components the engine (engine.py) fills. Re-applied by
#            provision() and regenerate(): Kenya Payroll is the only source of truth.
#   seeded - pay components and the Kenyan catalogue. Created once if missing, then
#            they're the client's: never overwritten, so a client's edits survive every
#            upgrade and every regenerate().

# The casual structure's one pay row: daily rate (the assignment's Base) x the Days
# Worked entered on the slip. Paid monthly, so the engine's monthly bands and limits
# are right as they are (casuals paid weekly are not supported: docs/research-2026-10-22.md
# §5).
CASUAL_EARNINGS_ORDER = ["Casual Wages"]

# Row order of a new Salary Structure. The engine doesn't depend on row order; this is
# just what reads best on the structure and the slip.
EARNINGS_ORDER = [
	"Basic Salary",
	"House Allowance",
	"Transport Allowance",
	"Other Allowance",
]

DEDUCTIONS_ORDER = [
	"NSSF Tier I - Employee",
	"NSSF Tier II - Employee",
	"SHIF",
	"Housing Levy",
	"PAYE",
]

EMPLOYER_ORDER = [
	"NSSF Employer",
	"Housing Levy Employer",
	"NITA",
]

# Formula components from before v16.4.0 (taxable income, the band cascade, Gross PAYE).
# No longer created or updated; left in place because structures built before v16.4.0
# still list them (the engine ignores them: they are statistical).
RETIRED_COMPONENTS = [
	"Taxable Income",
	"PAYEBand1Max", "PAYEBand1", "PAYEBand2Max", "PAYEBand2", "PAYEBand3Max",
	"PAYEBand3", "PAYEBand4Max", "PAYEBand4", "PAYEBand5", "Gross PAYE",
]


def _num(value):
	"""Format a rate-derived number as a clean literal for a formula string —
	'2400' not '2400.0', '2083.25' not '2083.2500000000002'."""
	value = round(flt(value), 2)
	return str(int(value)) if value == int(value) else str(value)


_NEUTRAL_FLAGS = {
	"statistical_component": 0,
	"variable_based_on_taxable_salary": 0,  # critical — keeps HRMS's slab engine off
	"is_income_tax_component": 0,
	"exempted_from_income_tax": 0,
	"deduct_full_tax_on_selected_payroll_date": 0,
	"do_not_include_in_total": 0,
	"do_not_include_in_accounts": 0,
	"remove_if_zero_valued": 1,
	"round_to_the_nearest_integer": 1,
}

# Pay on the structure (Basic and the fixed monthly allowances): a formula, pro-rated
# for part months, and part of every statutory base.
_MONTHLY_PAY_FLAGS = {
	**_NEUTRAL_FLAGS,
	"amount_based_on_formula": 1,
	"depends_on_payment_days": 1,
	"is_tax_applicable": 1,
	"royce_nssf_pensionable": 1,
	"royce_shif_applicable": 1,
	"royce_ahl_applicable": 1,
	"royce_non_cash_benefit": 0,
	"royce_tax_free_allowance": "",
}

# Casual wages: the days worked are the measure of the month's pay, so no payment-days
# proration on top.
_CASUAL_PAY_FLAGS = {**_MONTHLY_PAY_FLAGS, "depends_on_payment_days": 0}

# Pay entered per month through Additional Salary (overtime, bonus...): the amount is
# what was earned, so it's never pro-rated.
_VARIABLE_PAY_FLAGS = {**_MONTHLY_PAY_FLAGS, "amount_based_on_formula": 0, "depends_on_payment_days": 0}

_REIMBURSEMENT_FLAGS = {
	**_VARIABLE_PAY_FLAGS,
	"is_tax_applicable": 0,
	"royce_nssf_pensionable": 0,
	"royce_shif_applicable": 0,
	"royce_ahl_applicable": 0,
}

# A benefit in kind: taxable past the threshold, never paid in cash, never posted by
# payroll (its cost is booked where it was incurred, e.g. the car's running costs).
_NON_CASH_FLAGS = {
	**_REIMBURSEMENT_FLAGS,
	"is_tax_applicable": 1,
	"royce_non_cash_benefit": 1,
	"do_not_include_in_total": 1,
	"do_not_include_in_accounts": 1,
}

_DEDUCTION_FLAGS = {
	**_NEUTRAL_FLAGS,
	"amount_based_on_formula": 0,
	"depends_on_payment_days": 0,
	"is_tax_applicable": 0,
	"royce_kenya_deduction_type": "",
}

# Amounts written by the engine on the month's actual pay, so no formula and no
# payment-days proration (HRMS would otherwise pro-rate the engine's figure again).
_ENGINE_DEDUCTION_FLAGS = {
	**_NEUTRAL_FLAGS,
	"amount_based_on_formula": 0,
	"depends_on_payment_days": 0,
	"is_tax_applicable": 0,
}

# HRMS's native Employer Contribution type: shown in the slip's own section, posted by
# Payroll Entry as expense against its own liability account (not Payroll Payable).
_ENGINE_EMPLOYER_FLAGS = {
	**_NEUTRAL_FLAGS,
	"amount_based_on_formula": 0,
	"depends_on_payment_days": 0,
	"is_tax_applicable": 0,
	"royce_nssf_pensionable": 0,
	"royce_shif_applicable": 0,
	"royce_ahl_applicable": 0,
	"royce_non_cash_benefit": 0,
}


def _spec(name, abbr, type_, flags, formula="", p9a="", p10a="", account=None, liability=None, owned=False):
	return {
		"salary_component": name,
		"abbr": abbr,
		"type": type_,
		"formula": formula,
		"p9a": p9a,
		"p10a": p10a,
		"flags": flags,
		"account": account,
		"liability": liability,
		"owned": owned,
	}


def component_specs(rates=None):
	"""Every Salary Component Kenya Payroll sets up: the eight it owns and the seeded pay
	components and catalogue. `rates` is accepted for backward compatibility; nothing
	here depends on it (the engine reads the rates in force for each slip's period).

	`account` is the expense or payable account (unsuffixed; " - {abbr}" is appended per
	company); `liability` is an Employer Contribution's liability account."""
	salary, deductions_payable = "Salary Expense", "Employee Deductions Payable"

	def earn(name, abbr, flags, p10a, formula="", p9a="Total Gross Pay"):
		return _spec(name, abbr, "Earning", flags, formula, p9a, p10a, account=salary)

	def ded(name, abbr, kind="", account=deductions_payable):
		return _spec(name, abbr, "Deduction", {**_DEDUCTION_FLAGS, "royce_kenya_deduction_type": kind},
			account=account)

	def owned(name, abbr, p9a, p10a, account, flags=_ENGINE_DEDUCTION_FLAGS):
		return _spec(name, abbr, "Deduction", flags, "", p9a, p10a, account=account, owned=True)

	def employer(name, abbr, expense, liability):
		return _spec(name, abbr, "Employer Contribution", _ENGINE_EMPLOYER_FLAGS,
			account=expense, liability=liability, owned=True)

	return [
		# Pay on the structure. Allowances are per employee, entered on the Salary
		# Structure Assignment (royce_*_allowance), not a fixed share of basic.
		earn("Basic Salary", "Basic", _MONTHLY_PAY_FLAGS, "Basic Salary", "base", p9a="Basic Salary"),
		earn("House Allowance", "House", _MONTHLY_PAY_FLAGS, "Housing Allowance", "royce_house_allowance"),
		earn("Transport Allowance", "Transport", _MONTHLY_PAY_FLAGS, "Transport Allowance",
			"royce_transport_allowance"),
		earn("Other Allowance", "OtherAllowance", _MONTHLY_PAY_FLAGS, "Other Allowance", "royce_other_allowance"),
		# The casual structure's pay. `or 0`: a slip made before days are entered.
		earn("Casual Wages", "CasualWages", _CASUAL_PAY_FLAGS, "Basic Salary", "base * (royce_days_worked or 0)",
			p9a="Basic Salary"),
		# Pay entered per month (Additional Salary).
		earn("Overtime", "Overtime", _VARIABLE_PAY_FLAGS, "Overtime"),
		earn("Bonus", "Bonus", _VARIABLE_PAY_FLAGS, "Other Allowance"),
		earn("Commission", "Commission", _VARIABLE_PAY_FLAGS, "Other Allowance"),
		earn("Leave Pay", "LeavePay", _VARIABLE_PAY_FLAGS, "Leave Pay"),
		earn("Acting Allowance", "Acting", _VARIABLE_PAY_FLAGS, "Other Allowance"),
		earn("Salary Arrears", "SalaryArrears", _VARIABLE_PAY_FLAGS, "Other Allowance"),
		earn("Meals Allowance", "Meals", {**_VARIABLE_PAY_FLAGS, "royce_tax_free_allowance": "Meals"},
			"Other Allowance"),
		earn("Expense Reimbursement", "Reimbursement", _REIMBURSEMENT_FLAGS, ""),
		earn("Car Benefit", "CarBenefit", _NON_CASH_FLAGS, "Value of Car Benefit", p9a="Benefits NonCash"),
		earn("Housing Benefit", "HousingBenefit", _NON_CASH_FLAGS, "Other Non Cash Benefits",
			p9a="Value of Quarters"),
		# Deductions entered per employee (Additional Salary, recurring where needed).
		ded("Pension Contribution", "Pension", "Pension Contribution"),
		ded("Post-Retirement Medical Fund", "PRMF", "Post-Retirement Medical Fund"),
		ded("Insurance Premium", "InsurancePremium", "Insurance Premium"),
		ded("HELB Repayment", "HELB"),
		ded("SACCO Contribution", "SACCO"),
		ded("Staff Welfare", "Welfare"),
		ded("Union Dues", "UnionDues"),
		ded("Staff Loan Repayment", "StaffLoan", account="Staff Loans"),
		# Owned: filled by the engine.
		owned("NSSF Tier I - Employee", "NSSF_T1", "E1 Defined Contribution Retirement Scheme",
			"Actual Contribution", "NSSF Payable"),
		owned("NSSF Tier II - Employee", "NSSF_T2", "E1 Defined Contribution Retirement Scheme",
			"Actual Contribution", "NSSF Payable"),
		owned("SHIF", "SHIF", "SHIF", "SHIF", "SHIF Payable"),
		owned("Housing Levy", "AHL", "Housing Levy", "Affordable Housing Levy", "Housing Levy Payable"),
		# Is Income Tax Component: HRMS's income-tax reports find PAYE by this flag.
		owned("PAYE", "PAYE", "PAYE Tax", "PAYE Tax", "PAYE Payable",
			flags={**_ENGINE_DEDUCTION_FLAGS, "is_income_tax_component": 1}),
		employer("NSSF Employer", "NSSF_ER", "NSSF Employer Expense", "NSSF Payable"),
		employer("Housing Levy Employer", "AHL_ER", "AHL Employer Expense", "Housing Levy Payable"),
		employer("NITA", "NITA", "NITA Expense", "NITA Payable"),
	]


def _specs_by_name():
	return {spec["salary_component"]: spec for spec in component_specs()}


def upsert_component(spec):
	"""Create or update one Salary Component from a spec dict. Idempotent."""
	if frappe.db.exists("Salary Component", spec["salary_component"]):
		doc = frappe.get_doc("Salary Component", spec["salary_component"])
	else:
		doc = frappe.new_doc("Salary Component")
		doc.salary_component = spec["salary_component"]

	doc.salary_component_abbr = spec["abbr"]
	doc.type = spec["type"]
	doc.condition = spec.get("condition") or ""
	doc.formula = spec["formula"]
	doc.royce_p9a_tax_deduction_card_type = spec.get("p9a") or ""
	doc.royce_p10a_tax_deduction_card_type = spec.get("p10a") or ""

	for fieldname, value in spec["flags"].items():
		doc.set(fieldname, value)

	doc.save(ignore_permissions=True)
	return doc.name


def ensure_components(rates=None):
	"""Re-apply the owned components; create seeded ones only if they don't exist yet.
	A seeded component the client has edited (or deleted and replaced) is left alone."""
	for spec in component_specs(rates):
		if spec["owned"] or not frappe.db.exists("Salary Component", spec["salary_component"]):
			upsert_component(spec)


def map_accounts(company):
	"""Give every component an Accounts row for `company` — guide section 6.9. An existing
	row is kept as the client set it; only an Employer Contribution's missing liability
	account is filled in. A component whose account doesn't exist in this company's
	chart (e.g. no "Loans and Advances (Assets)" group for Staff Loans) is skipped."""
	abbr = frappe.db.get_value("Company", company, "abbr")

	for spec in component_specs():
		if not spec["account"] or not frappe.db.exists("Salary Component", spec["salary_component"]):
			continue
		account = f"{spec['account']} - {abbr}"
		liability = f"{spec['liability']} - {abbr}" if spec["liability"] else None
		if not frappe.db.exists("Account", account) or (liability and not frappe.db.exists("Account", liability)):
			continue

		doc = frappe.get_doc("Salary Component", spec["salary_component"])
		row = next((r for r in doc.accounts if r.company == company), None)
		if row and (not liability or row.get("liability_account")):
			continue
		if not row:
			row = doc.append("accounts", {"company": company, "account": account})
		if liability:
			row.liability_account = liability
		doc.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Income Tax Slab placeholder, Payroll Period, Salary Structure
# ---------------------------------------------------------------------------


def ensure_income_tax_slab_placeholder(company, rates):
	"""The empty slab HRMS validation requires be linked on every Salary Structure
	Assignment, even though the band approach never reads it. See guide section 5."""
	year = rates.effective_from.year
	name = f"Kenya PAYE Placeholder {year}"
	if frappe.db.exists("Income Tax Slab", name):
		return name

	doc = frappe.get_doc(
		{
			"doctype": "Income Tax Slab",
			"name": name,
			"effective_from": f"{year}-01-01",
			"company": company,
			"currency": "KES",
			"allow_tax_exemption": 0,
			"standard_tax_exemption_amount": 0,
			"tax_relief_limit": 0,
			# The guide says leave this empty — true in spirit (never read, since
			# Variable Based on Taxable Salary stays disabled everywhere), but the
			# `slabs` field is `reqd: 1` and Frappe enforces that server-side even
			# though the desk UI lets it slide. One zero-width, zero-rate row
			# satisfies the constraint while staying a genuine no-op.
			"slabs": [{"from_amount": 0, "to_amount": 0, "percent_deduction": 0}],
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def ensure_payroll_period(company, rates):
	"""One Payroll Period covering the calendar year `rates.effective_from` falls in.
	Skips creation if an existing period for this company already covers that year."""
	year = rates.effective_from.year
	year_start, year_end = f"{year}-01-01", f"{year}-12-31"

	existing = frappe.db.get_value(
		"Payroll Period",
		{"company": company, "start_date": ["<=", year_start], "end_date": [">=", year_end]},
		"name",
	)
	if existing:
		return existing

	doc = frappe.get_doc(
		{
			"doctype": "Payroll Period",
			"name": f"{company} Payroll {year}",
			"company": company,
			"start_date": year_start,
			"end_date": year_end,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def kenya_structure(company, casual=False):
	"""The company's active Kenya Payroll structure (or its casual one), newest first,
	or None."""
	return frappe.db.get_value(
		"Salary Structure",
		{
			"company": company,
			"royce_kenya_statutory": 1,
			"royce_casual_wages": 1 if casual else 0,
			"docstatus": 1,
			"is_active": "Yes",
		},
		"name",
		order_by="creation desc",
	)


def is_casual_structure(salary_structure) -> bool:
	return bool(
		salary_structure and frappe.get_cached_value("Salary Structure", salary_structure, "royce_casual_wages")
	)


def ensure_salary_structure(company, rates=None):
	"""One Kenya Payroll structure per company, reused if it already exists.

	Before v16.4.0 there was one structure per (company, rates version), because each
	structure carried its own copy of the rate-dependent formulas. The engine now reads
	the rates in force for each slip's period, so a rate change no longer needs a new
	structure or a re-assignment of every employee. A pre-v16.4.0 structure (marked by
	the v16_4_kenya_statutory_engine patch) counts as the company's structure."""
	existing = kenya_structure(company)
	if existing:
		return existing
	return _make_structure(company, "Kenya Payroll", EARNINGS_ORDER)


def ensure_casual_structure(company):
	"""One Kenya Casual Wages structure per company, for casual workers paid monthly on
	a daily rate: Base on the assignment is the daily rate, Days Worked is entered on
	each slip. Same statutory rows as the main structure."""
	existing = kenya_structure(company, casual=True)
	if existing:
		return existing
	return _make_structure(company, "Kenya Casual Wages", CASUAL_EARNINGS_ORDER, casual=True)


def _make_structure(company, title, earnings, casual=False):
	abbr = frappe.db.get_value("Company", company, "abbr")
	doc = frappe.new_doc("Salary Structure")
	doc.name = f"{abbr} {title}"
	doc.company = company
	doc.currency = "KES"
	doc.is_active = "Yes"
	# Monthly only: the engine applies monthly bands and limits (validate_salary_structure).
	doc.payroll_frequency = "Monthly"
	doc.salary_slip_based_on_timesheet = 0
	doc.royce_kenya_statutory = 1
	doc.royce_casual_wages = 1 if casual else 0

	for parentfield, components in (
		("earnings", earnings),
		("deductions", DEDUCTIONS_ORDER),
		("employer_contributions", EMPLOYER_ORDER),
	):
		for component in components:
			row = doc.append(parentfield, {})
			_fill_structure_row(row, component)

	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def _fill_structure_row(row, component_name):
	"""Copy the master component's own configuration onto the structure row, rather
	than rely on the row inheriting it implicitly. Salary Detail doesn't carry every
	flag the master does (no round-to-integer / is-income-tax-component fields on the
	row, for instance) — those are read from the master directly at calculation time."""
	master = frappe.get_cached_doc("Salary Component", component_name)
	# The formula comes from Kenya Payroll's spec, not the master: a seeded master is
	# never overwritten, so on a site set up before v16.5.0 House Allowance's master can
	# still say "base * 0.15".
	spec = _specs_by_name().get(component_name)
	row.salary_component = component_name
	row.abbr = master.salary_component_abbr
	row.condition = master.condition
	row.amount_based_on_formula = 1 if spec and spec["formula"] else master.amount_based_on_formula
	row.formula = spec["formula"] if spec and spec["formula"] else master.formula
	row.statistical_component = master.statistical_component
	row.is_tax_applicable = master.is_tax_applicable
	row.variable_based_on_taxable_salary = master.variable_based_on_taxable_salary
	row.depends_on_payment_days = master.depends_on_payment_days
	row.deduct_full_tax_on_selected_payroll_date = master.deduct_full_tax_on_selected_payroll_date
	row.do_not_include_in_total = master.do_not_include_in_total
	row.exempted_from_income_tax = master.exempted_from_income_tax
	row.do_not_include_in_accounts = master.do_not_include_in_accounts


# ---------------------------------------------------------------------------
# Kenya Holiday List (weekends + confidently-known public holidays)
# ---------------------------------------------------------------------------

# Fixed-date Kenya public holidays -- stable for decades, no moving parts.
# Deliberately excludes two real categories rather than guess at them (a
# 2026-09-13 decision, see royce_ip's CLAUDE.md): seed only what we have full
# confidence in, since a wrong "public holiday" a customer trusts blindly is
# worse than an honest gap they fill in themselves.
#   - Huduma Day (Oct 10, formerly Moi Day) -- abolished in 2010, reinstated
#     by a 2017 court order, renamed in 2019. Its legal status has genuinely
#     changed more than once; not something to hardcode confidently.
#   - Eid al-Fitr / Eid al-Adha -- lunar-calendar dates Kenya's government
#     only confirms off an actual moon sighting, typically a day or two
#     beforehand. Any date computed this far in advance is an estimate, not
#     a fact. Left for the customer to add themselves, via the same "Add
#     Local Holidays" tool, once officially gazetted.
FIXED_KENYA_HOLIDAYS = [
	(1, 1, "New Year's Day"),
	(5, 1, "Labour Day"),
	(6, 1, "Madaraka Day"),
	(10, 20, "Mashujaa Day"),
	(12, 12, "Jamhuri Day"),
	(12, 25, "Christmas Day"),
	(12, 26, "Boxing Day"),
]


def _easter_sunday(year: int) -> date:
	"""Easter Sunday for `year`, via the standard Anonymous Gregorian
	algorithm (Meeus/Jones/Butcher). The one moveable date category here
	that's genuinely computable exactly, unlike the fixed list above (no
	moving parts at all) or Eid (fundamentally unknowable this far ahead --
	see FIXED_KENYA_HOLIDAYS' own comment)."""
	a = year % 19
	b = year // 100
	c = year % 100
	d = b // 4
	e = b % 4
	f = (b + 8) // 25
	g = (b - f + 1) // 3
	h = (19 * a + b - d - g + 15) % 30
	i = c // 4
	k = c % 4
	l = (32 + 2 * e + 2 * i - h - k) % 7
	m = (a + 11 * h + 22 * l) // 451
	month = (h + l - 7 * m + 114) // 31
	day = ((h + l - 7 * m + 114) % 31) + 1
	return date(year, month, day)


def _kenya_holidays_for_year(year: int) -> dict:
	"""{date: {"description": ..., "weekly_off": 0/1}} for one calendar year --
	the fixed-date public holidays, the two Easter-relative ones, and every
	Saturday/Sunday not already claimed by one of those. Named holidays take
	priority over the generic "Weekly Off" label when a public holiday lands
	on a weekend (e.g. Christmas on a Saturday), via dict.setdefault ordering
	below -- so the seeded list stays informative instead of silently
	relabelling a named holiday as generic.
	"""
	holidays: dict = {}

	for month, day, description in FIXED_KENYA_HOLIDAYS:
		holidays[date(year, month, day)] = {"description": description, "weekly_off": 0}

	easter = _easter_sunday(year)
	for day_date, description in (
		(easter - timedelta(days=2), "Good Friday"),
		(easter + timedelta(days=1), "Easter Monday"),
	):
		holidays.setdefault(day_date, {"description": description, "weekly_off": 0})

	day = date(year, 1, 1)
	one_day = timedelta(days=1)
	while day.year == year:
		if day.weekday() in (5, 6):  # Saturday, Sunday
			holidays.setdefault(day, {"description": "Weekly Off", "weekly_off": 1})
		day += one_day

	return holidays


def ensure_holiday_list(company: str, year: int) -> str:
	"""Create `year`'s Holiday List for `company` if it doesn't already exist
	-- weekends and Kenya's confidently-known public holidays, per
	_kenya_holidays_for_year(). Fully editable afterward, same as any other
	ERPNext master: a customer who later works half-day Saturdays ticks
	"Is Half Day" on those rows themselves (a real field on Holiday, confirmed
	against the actual Holiday List UI, not assumed), and Eid/any other local
	holiday gets added the same way once it's actually known. One list per
	(company, year) -- next year gets its own, same pattern as
	ensure_payroll_period().
	"""
	name = f"{company} Holidays {year}"
	if frappe.db.exists("Holiday List", name):
		return name

	doc = frappe.new_doc("Holiday List")
	doc.holiday_list_name = name
	doc.from_date = f"{year}-01-01"
	doc.to_date = f"{year}-12-31"
	for day_date, info in sorted(_kenya_holidays_for_year(year).items()):
		doc.append(
			"holidays",
			{
				"holiday_date": day_date,
				"description": info["description"],
				"weekly_off": info["weekly_off"],
				"is_half_day": 0,
			},
		)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_holiday_list_assignment(company: str, holiday_list: str, from_date) -> str:
	"""Submit a Holiday List Assignment linking `company` to `holiday_list` --
	the real v16 wiring payroll/attendance actually resolve against (verified
	against hrms's own v16_0 migration patch, create_holiday_list_assignments.py,
	not assumed -- the older Company.default_holiday_list field is only what
	that patch migrates FROM, not what a fresh v16 site should be wired
	through). No-ops if an assignment for this company and from_date is
	already submitted, matching the doctype's own duplicate check
	(HolidayListAssignment.validate_existing_assignment) -- checked up front
	here instead of caught as a thrown DuplicateAssignment. Doesn't set
	naming_series explicitly -- Frappe fills it in from the doctype's sole
	series option on its own, same as royce_payroll_ke's own
	tests/utils.py's make_test_payslip already relies on for the Employee
	variant of this same doctype.
	"""
	existing = frappe.db.exists(
		"Holiday List Assignment",
		{"assigned_to": company, "from_date": from_date, "docstatus": 1},
	)
	if existing:
		return existing

	doc = frappe.new_doc("Holiday List Assignment")
	doc.applicable_for = "Company"
	doc.assigned_to = company
	doc.holiday_list = holiday_list
	doc.from_date = from_date
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def seed_default_rates():
	"""Create and submit the current Kenya statutory rates, if no effective
	Kenya Payroll Rates record exists yet.

	Per-SITE bootstrap, not per-company — KenyaPayrollRates.get_effective() has no
	company filter, so every company ON THIS SITE shares one record. That is
	NOT the same as "once for the whole business": each client here gets
	their own site (own database, per Model A), so a fresh client's site has
	no rates record regardless of what other clients' sites have. Called
	automatically by royce_provision's onboard_client() before provision(),
	so onboarding stays a single call rather than depending on a separate
	step per site that's easy to forget.

	The numbers below are a known-good snapshot (Feb 2026 KRA rates, per
	docs/user-guide.md section 2) — not a live source of truth that should
	silently drift. A real rate change means creating a new Kenya Payroll Rates
	record by hand with the new effective_from date, same as any other
	Finance Act update; it does not mean editing this function.

	Restricted to System Manager: this creates and submits a submitted
	statutory record that every client's payroll math depends on — not
	something to expose more broadly than onboard_client_cli() itself is."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted — seed_default_rates is restricted to System Managers."), frappe.PermissionError)

	existing = KenyaPayrollRates.get_effective()
	if existing:
		return {"status": "already seeded", "rates": existing}

	doc = frappe.get_doc(
		{
			"doctype": "Kenya Payroll Rates",
			"effective_from": "2026-01-01",
			"paye_bands": [
				{"band_number": 1, "lower_bound": 0, "upper_bound": 24000, "rate": 10},
				{"band_number": 2, "lower_bound": 24000, "upper_bound": 32333, "rate": 25},
				{"band_number": 3, "lower_bound": 32333, "upper_bound": 500000, "rate": 30},
				{"band_number": 4, "lower_bound": 500000, "upper_bound": 800000, "rate": 32.5},
				{"band_number": 5, "lower_bound": 800000, "upper_bound": None, "rate": 35},
			],
			"nssf_tier_i_limit": 9000,
			"nssf_tier_ii_limit": 108000,
			"nssf_employee_rate": 6,
			"nssf_employer_rate": 6,
			"shif_rate": 2.75,
			"shif_minimum": 300,
			"ahl_employee_rate": 1.5,
			"ahl_employer_rate": 1.5,
			"nita_amount": 50,
			"personal_relief": 2400,
			# Tax Laws (Amendment) Act 2024 limits; see docs/taxable-income-engine.md.
			"pension_deduction_limit": 30000,
			"pension_limit_percent_of_basic": 30,
			"prmf_deduction_limit": 15000,
			"mortgage_interest_limit": 30000,
			"disability_exemption_amount": 150000,
			"non_cash_benefit_threshold": 5000,
			"meals_tax_free_limit": 5000,
			"insurance_relief_rate": 15,
			"insurance_relief_limit": 5000,
			"secondary_employment_rate": 35,
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return {"status": "seeded", "rates": doc.name}


def _get_rates_doc(rates):
	rates_name = rates or KenyaPayrollRates.get_effective()
	if not rates_name:
		frappe.throw(_("No effective, submitted Kenya Payroll Rates record found. Create and submit one first."))
	return frappe.get_doc("Kenya Payroll Rates", rates_name)


def _require_payroll_write_permission():
	"""Gate for provision() and regenerate(): both mutate Salary Components,
	the Chart of Accounts, and Salary Structures for every company on the
	site — the same trust level as editing Kenya Payroll Rates itself, not just
	"logged in". Ties to Kenya Payroll Rates' own permission model (System
	Manager / HR Manager have write; HR User is read-only) rather than
	hardcoding role names a second time. Added alongside the Desk buttons
	that call these — without it, the underlying API was already callable
	by any authenticated user (frappe.whitelist() alone doesn't restrict by
	role, and every write inside these functions uses
	ignore_permissions=True); a visible button would only have made that
	gap easier to hit by accident, not created it."""
	if not frappe.has_permission("Kenya Payroll Rates", "write"):
		frappe.throw(_("Not permitted — this requires write access to Kenya Payroll Rates."), frappe.PermissionError)


def _require_payroll_read_permission():
	"""Gate for verify(): read-only, so held to a lower bar than
	provision()/regenerate() — anyone who can at least see Kenya Payroll Rates
	should be able to run a self-check against it."""
	if not frappe.has_permission("Kenya Payroll Rates", "read"):
		frappe.throw(_("Not permitted — this requires read access to Kenya Payroll Rates."), frappe.PermissionError)


def _provisioned_companies():
	"""Companies that have a Kenya Payroll structure."""
	companies = frappe.get_all(
		"Salary Structure",
		filters={"royce_kenya_statutory": 1, "docstatus": 1},
		pluck="company",
		distinct=True,
	)
	return sorted(c for c in companies if c)


def _require_kenya_region():
	"""HRMS only calls the engine where the site's country is Kenya (regional_overrides
	is keyed by System Settings country). Anywhere else the statutory rows would stay
	at zero, silently, so refuse to set payroll up there."""
	from hrms import get_region

	region = get_region()
	if region != "Kenya":
		frappe.throw(
			_("Kenya Payroll needs the site's country to be Kenya (System Settings), not {0}.").format(
				frappe.bold(region or _("blank"))
			),
			title=_("Country is not Kenya"),
		)


@frappe.whitelist()
def provision(company, rates=None):
	"""Full setup for a company: accounts, Kenya Payroll's components, the Income Tax Slab
	placeholder, the Payroll Period, and the two Salary Structures (monthly salary and
	casual wages). Safe to re-run."""
	_require_payroll_write_permission()
	_require_kenya_region()
	rates_doc = _get_rates_doc(rates)

	ensure_accounts(company)
	ensure_components(rates_doc)
	map_accounts(company)
	slab = ensure_income_tax_slab_placeholder(company, rates_doc)
	period = ensure_payroll_period(company, rates_doc)
	structure = ensure_salary_structure(company, rates_doc)
	casual_structure = ensure_casual_structure(company)

	# Attendance/payroll need a Holiday List or every day is treated as a
	# working day -- a wrong-payslip bug, not a crash, so it fails silently
	# rather than loudly (see setup's Kenya Holiday List comment above for
	# why Eid isn't seeded). Both this year and next, matching Fiscal Year's
	# own "current + next" seeding in kenyan_accountant -- a business signing
	# up late in the year shouldn't fall off the edge of its holiday
	# coverage the moment the calendar turns over.
	current_year = getdate().year
	holiday_lists = {}
	for year in (current_year, current_year + 1):
		holiday_list = ensure_holiday_list(company, year)
		ensure_holiday_list_assignment(company, holiday_list, f"{year}-01-01")
		holiday_lists[year] = holiday_list

	return {
		"rates": rates_doc.name,
		"income_tax_slab": slab,
		"payroll_period": period,
		"salary_structure": structure,
		"casual_structure": casual_structure,
		"holiday_lists": holiday_lists,
	}


@frappe.whitelist()
def regenerate(rates=None):
	"""Re-apply Kenya Payroll's own (owned) component definitions, create any missing
	catalogue component or casual wages structure, and complete account mappings for
	every provisioned company.
	A seeded component that already exists is never changed, nor is a client's own.

	A Finance Act rate change does NOT need this any more: submit a new Kenya Payroll
	Rates record with its Effective From date and every slip for a period on or after
	that date uses it. Existing Salary Structure Assignments stay as they are."""
	_require_payroll_write_permission()
	rates_doc = _get_rates_doc(rates)
	ensure_components(rates_doc)

	structures = {}
	for company in _provisioned_companies():
		ensure_accounts(company)
		map_accounts(company)
		ensure_income_tax_slab_placeholder(company, rates_doc)
		ensure_casual_structure(company)
		structures[company] = kenya_structure(company)

	return {"rates": rates_doc.name, "structures": structures}


@frappe.whitelist()
def verify(company, rates=None):
	"""Read-only structural sanity check that provisioning actually produced
	what it should. Deliberately does not create a synthetic employee/payslip
	to test the math end to end — this needs to be safe to run against a real
	client's site, and leaving fake test data in someone's production HR
	system to prove a point is not acceptable. Checks structure instead: the
	site's country, Kenya Payroll's components, the accounts and their types,
	and that the company's Kenya structure carries every statutory row. Raises
	with every problem found, not just the first.

	`rates` defaults to whatever's currently effective, but can be passed
	explicitly, matching provision()'s own pattern."""
	_require_payroll_read_permission()
	from hrms import get_region

	problems = []

	rates_doc = _get_rates_doc(rates)
	rates_name = rates_doc.name

	if get_region() != "Kenya":
		problems.append(_("The site's country (System Settings) is not Kenya, so the statutory engine won't run."))

	# What payroll can't run without: the owned components, and Basic Salary with a
	# formula. Catalogue components are the client's to keep, rename or delete.
	specs = [s for s in component_specs(rates_doc) if s["owned"] or s["salary_component"] == "Basic Salary"]
	for spec in specs:
		name = spec["salary_component"]
		if not frappe.db.exists("Salary Component", name):
			problems.append(_("Salary Component {0} is missing.").format(name))
			continue
		if spec["formula"] and not frappe.db.get_value("Salary Component", name, "formula"):
			problems.append(_("Salary Component {0} has no formula.").format(name))
		if spec["owned"] and frappe.db.get_value("Salary Component", name, "type") != spec["type"]:
			problems.append(_("Salary Component {0} should be of type {1}.").format(name, spec["type"]))

	abbr = frappe.db.get_value("Company", company, "abbr")
	if not abbr:
		frappe.throw(_("Company {0} not found.").format(company))

	for account_name, _parent, account_type in STATUTORY_PAYABLE_ACCOUNTS + EXPENSE_ACCOUNTS:
		full_name = f"{account_name} - {abbr}"
		actual_type = frappe.db.get_value("Account", full_name, "account_type")
		if actual_type != account_type:
			problems.append(
				_("Account {0} has Account Type '{1}', expected '{2}'.").format(
					full_name, actual_type, account_type
				)
			)

	payable_name = f"Payroll Payable - {abbr}"
	if frappe.db.get_value("Account", payable_name, "account_type") != "Payable":
		problems.append(_("Account {0} does not have Account Type 'Payable'.").format(payable_name))

	structure_name = kenya_structure(company)
	if not structure_name:
		problems.append(_("{0} has no active Kenya Payroll Salary Structure.").format(company))
	else:
		structure = frappe.get_doc("Salary Structure", structure_name)
		present = {
			d.salary_component
			for d in structure.earnings + structure.deductions + (structure.get("employer_contributions") or [])
		}
		# Structures from before v16.5.0 have no Other Allowance and carry the employer
		# contributions as earnings; both still work, so only these are required.
		missing = [c for c in ["Basic Salary", *DEDUCTIONS_ORDER, *EMPLOYER_ORDER] if c not in present]
		if missing:
			problems.append(
				_("{0} is missing the rows: {1}.").format(structure_name, ", ".join(missing))
			)

	if not kenya_structure(company, casual=True):
		problems.append(_("{0} has no active Kenya Casual Wages Salary Structure.").format(company))

	if problems:
		frappe.throw(_("Payroll provisioning verification failed for {0}:<br>{1}").format(
			company, "<br>".join(problems)
		))

	return {
		"company": company,
		"rates": rates_name,
		"components_checked": len(specs),
		"structure": structure_name,
		"status": "PASS",
	}
