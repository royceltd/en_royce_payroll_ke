# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""The generator: turns one Payroll Rates record into a working Kenya payroll setup.

Replaces sections 3-9 of the Royce Payroll Setup Guide v2.1 — Chart of Accounts, the 22
Salary Components (band-based PAYE, per the guide's approach), the Income Tax Slab
placeholder, the Payroll Period, and the Salary Structure with row order enforced here
rather than by whoever happens to be dragging rows in the UI that day.

Three entry points:
  seed_default_rates() - one-time (or once-per-Finance-Act-change) ENVIRONMENT bootstrap,
                          not a per-client step. Creates the single shared Payroll Rates
                          record every client's payroll draws from, if none exists yet.
  provision(company)  - full company setup, run once per new client.
  regenerate()         - re-templates the 22 components' formulas off the currently
                          effective Payroll Rates. Run after a Finance Act rate change.
                          Does not touch accounts or the structure — those don't depend
                          on rates.

All three are safe to run more than once: every step checks for what already exists
before creating anything.
"""

import frappe
from frappe import _
from frappe.utils import flt

from royce_payroll_ke.royce_payroll_ke.doctype.payroll_rates.payroll_rates import PayrollRates

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


def _ensure_account(account_name, parent_name, account_type, company, abbr):
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

# Component -> which expense/payable account (unsuffixed; " - {abbr}" is appended per
# company) its Accounts table row should point to. Components with no entry here
# (Taxable Income, the 9 band components, Gross PAYE) are pure statistical
# intermediates and get no Accounts table row at all — matches guide section 6.9.
ACCOUNT_MAP = {
	"Basic Salary": "Salary Expense",
	"House Allowance": "Salary Expense",
	"Transport Allowance": "Salary Expense",
	"NSSF Tier I - Employee": "NSSF Payable",
	"NSSF Tier II - Employee": "NSSF Payable",
	"SHIF": "SHIF Payable",
	"Housing Levy": "Housing Levy Payable",
	"PAYE": "PAYE Payable",
	"NSSF Employer": "NSSF Employer Expense",
	"Housing Levy Employer": "AHL Employer Expense",
	"NITA": "NITA Expense",
}

# The exact row order the Salary Structure's Earnings / Deductions tables must use.
# Frappe evaluates each table in row order; TI must come after the 4 statutory
# deductions, bands after TI, Gross PAYE after the bands, PAYE last. Reordering this
# breaks the calculation silently — see guide section 7's own warning.
EARNINGS_ORDER = [
	"Basic Salary",
	"House Allowance",
	"Transport Allowance",
	"NSSF Employer",
	"Housing Levy Employer",
	"NITA",
]

DEDUCTIONS_ORDER = [
	"NSSF Tier I - Employee",
	"NSSF Tier II - Employee",
	"SHIF",
	"Housing Levy",
	"Taxable Income",
	"PAYEBand1Max",
	"PAYEBand1",
	"PAYEBand2Max",
	"PAYEBand2",
	"PAYEBand3Max",
	"PAYEBand3",
	"PAYEBand4Max",
	"PAYEBand4",
	"PAYEBand5",
	"Gross PAYE",
	"PAYE",
]


def _num(value):
	"""Format a rate-derived number as a clean literal for a formula string —
	'2400' not '2400.0', '2083.25' not '2083.2500000000002'."""
	value = round(flt(value), 2)
	return str(int(value)) if value == int(value) else str(value)


def _rate(percent_value):
	"""A Percent field (6, 2.75, 32.5, ...) as the fraction a formula needs (0.06, ...)."""
	return flt(percent_value) / 100


# Shared checkbox blocks, named after guide section 6.1's own groupings.
_REAL_EARNING_FLAGS = {
	"depends_on_payment_days": 1,
	"is_tax_applicable": 1,
	"round_to_the_nearest_integer": 1,
	"remove_if_zero_valued": 1,
	"statistical_component": 0,
	"do_not_include_in_total": 0,
	"deduct_full_tax_on_selected_payroll_date": 0,
	"variable_based_on_taxable_salary": 0,
	"is_income_tax_component": 0,
	"exempted_from_income_tax": 0,
	"do_not_include_in_accounts": 0,
}

_STATUTORY_DEDUCTION_FLAGS = {
	"depends_on_payment_days": 1,
	"round_to_the_nearest_integer": 1,
	"remove_if_zero_valued": 1,
	"statistical_component": 0,
	"variable_based_on_taxable_salary": 0,
	"is_income_tax_component": 0,
	"exempted_from_income_tax": 0,
	"is_tax_applicable": 0,
	"do_not_include_in_total": 0,
	"do_not_include_in_accounts": 0,
}

_STATISTICAL_FLAGS = {
	"statistical_component": 1,
	"do_not_include_in_total": 1,
	"round_to_the_nearest_integer": 1,
	"remove_if_zero_valued": 1,
	"amount_based_on_formula": 1,
	"depends_on_payment_days": 0,
	"variable_based_on_taxable_salary": 0,
	"is_income_tax_component": 0,
	"exempted_from_income_tax": 0,
	"is_tax_applicable": 0,
	"do_not_include_in_accounts": 0,
}

_PAYE_FINAL_FLAGS = {
	"is_income_tax_component": 1,
	"round_to_the_nearest_integer": 1,
	"remove_if_zero_valued": 1,
	"amount_based_on_formula": 1,
	"statistical_component": 0,
	"do_not_include_in_total": 0,
	"variable_based_on_taxable_salary": 0,  # critical — keeps the slab engine off
	"depends_on_payment_days": 0,
	"exempted_from_income_tax": 0,
	"is_tax_applicable": 0,
	"do_not_include_in_accounts": 0,
}

_EMPLOYER_EARNING_FLAGS = {
	"statistical_component": 0,
	"do_not_include_in_total": 1,
	"do_not_include_in_accounts": 0,
	"is_tax_applicable": 0,
	"round_to_the_nearest_integer": 1,
	"remove_if_zero_valued": 1,
	"amount_based_on_formula": 1,
	"variable_based_on_taxable_salary": 0,
	"is_income_tax_component": 0,
	"exempted_from_income_tax": 0,
	"deduct_full_tax_on_selected_payroll_date": 0,
}


def component_specs(rates):
	"""Build the full spec for all 22 components from a submitted Payroll Rates doc.

	Returns a list of dicts, each with everything needed to create or update one
	Salary Component and its matching Salary Structure row.
	"""
	bands = sorted(rates.paye_bands, key=lambda row: row.band_number)
	nssf_t1, nssf_t2 = _num(rates.nssf_tier_i_limit), _num(rates.nssf_tier_ii_limit)

	specs = [
		{
			"salary_component": "Basic Salary",
			"abbr": "Basic",
			"type": "Earning",
			"formula": "base",
			"p9a": "Basic Salary",
			"p10a": "Basic Salary",
			"flags": _REAL_EARNING_FLAGS,
		},
		{
			"salary_component": "House Allowance",
			"abbr": "House",
			"type": "Earning",
			"formula": "base * 0.15",
			"p9a": "Total Gross Pay",
			"p10a": "Housing Allowance",
			"flags": _REAL_EARNING_FLAGS,
		},
		{
			"salary_component": "Transport Allowance",
			"abbr": "Transport",
			"type": "Earning",
			"formula": "base * 0.10",
			"p9a": "Total Gross Pay",
			"p10a": "Transport Allowance",
			"flags": _REAL_EARNING_FLAGS,
		},
		{
			"salary_component": "NSSF Tier I - Employee",
			"abbr": "NSSF_T1",
			"type": "Deduction",
			"formula": f"(gross_pay if gross_pay < {nssf_t1} else {nssf_t1}) * {_rate(rates.nssf_employee_rate)}",
			"p9a": "E1 Defined Contribution Retirement Scheme",
			"p10a": "Actual Contribution",
			"flags": _STATUTORY_DEDUCTION_FLAGS,
		},
		{
			"salary_component": "NSSF Tier II - Employee",
			"abbr": "NSSF_T2",
			"type": "Deduction",
			"formula": (
				f"((gross_pay if gross_pay < {nssf_t2} else {nssf_t2}) - {nssf_t1}"
				f" if gross_pay > {nssf_t1} else 0) * {_rate(rates.nssf_employee_rate)}"
			),
			"p9a": "E1 Defined Contribution Retirement Scheme",
			"p10a": "Actual Contribution",
			"flags": _STATUTORY_DEDUCTION_FLAGS,
		},
		{
			"salary_component": "SHIF",
			"abbr": "SHIF",
			"type": "Deduction",
			"formula": (
				f"{_num(rates.shif_minimum)} if gross_pay * {_rate(rates.shif_rate)} < {_num(rates.shif_minimum)}"
				f" else gross_pay * {_rate(rates.shif_rate)}"
			),
			"p9a": "SHIF",
			"p10a": "SHIF",
			"flags": _STATUTORY_DEDUCTION_FLAGS,
		},
		{
			"salary_component": "Housing Levy",
			"abbr": "AHL",
			"type": "Deduction",
			"formula": f"gross_pay * {_rate(rates.ahl_employee_rate)}",
			"p9a": "Housing Levy",
			"p10a": "Affordable Housing Levy",
			"flags": _STATUTORY_DEDUCTION_FLAGS,
		},
		{
			"salary_component": "Taxable Income",
			"abbr": "TI",
			"type": "Deduction",
			"formula": "gross_pay - NSSF_T1 - NSSF_T2 - SHIF - AHL",
			"p9a": "",
			"p10a": "",
			"flags": _STATISTICAL_FLAGS,
		},
	]

	# The 9 band components, generated from the rates' own band table rather than
	# hand-typed — this is the piece that replaces guide section 12's manual cascade.
	previous_upper = 0
	for row in bands:
		is_last = row.band_number == len(bands)
		rate = _rate(row.rate)

		if not is_last:
			specs.append(
				{
					"salary_component": f"PAYEBand{row.band_number}Max",
					"abbr": f"PAYEBand{row.band_number}Max",
					"type": "Deduction",
					"condition": f"TI > {_num(previous_upper)} and TI <= {_num(row.upper_bound)}",
					"formula": f"(TI - {_num(previous_upper)}) * {rate}"
					if previous_upper
					else f"TI * {rate}",
					"p9a": "",
					"p10a": "",
					"flags": _STATISTICAL_FLAGS,
				}
			)
			width = flt(row.upper_bound) - flt(previous_upper)
			specs.append(
				{
					"salary_component": f"PAYEBand{row.band_number}",
					"abbr": f"PAYEBand{row.band_number}",
					"type": "Deduction",
					"condition": f"TI > {_num(row.upper_bound)}",
					"formula": _num(width * rate),
					"p9a": "",
					"p10a": "",
					"flags": _STATISTICAL_FLAGS,
				}
			)
			previous_upper = row.upper_bound
		else:
			# Open-ended top band — no Max variant, no upper bound.
			specs.append(
				{
					"salary_component": f"PAYEBand{row.band_number}",
					"abbr": f"PAYEBand{row.band_number}",
					"type": "Deduction",
					"condition": f"TI > {_num(previous_upper)}",
					"formula": f"(TI - {_num(previous_upper)}) * {rate}",
					"p9a": "",
					"p10a": "",
					"flags": _STATISTICAL_FLAGS,
				}
			)

	band_abbrs = []
	for row in bands:
		if row.band_number != len(bands):
			band_abbrs += [f"PAYEBand{row.band_number}Max", f"PAYEBand{row.band_number}"]
		else:
			band_abbrs += [f"PAYEBand{row.band_number}"]

	specs.append(
		{
			"salary_component": "Gross PAYE",
			"abbr": "GROSS_PAYE",
			"type": "Deduction",
			"condition": "TI > 0",
			"formula": " + ".join(band_abbrs),
			"p9a": "",
			"p10a": "",
			"flags": _STATISTICAL_FLAGS,
		}
	)

	specs.append(
		{
			"salary_component": "PAYE",
			"abbr": "PAYE",
			"type": "Deduction",
			"condition": f"GROSS_PAYE > {_num(rates.personal_relief)}",
			"formula": f"GROSS_PAYE - {_num(rates.personal_relief)}",
			"p9a": "PAYE Tax",
			"p10a": "PAYE Tax",
			"flags": _PAYE_FINAL_FLAGS,
		}
	)

	specs.append(
		{
			"salary_component": "NSSF Employer",
			"abbr": "NSSF_ER",
			"type": "Earning",
			"formula": f"(gross_pay if gross_pay < {nssf_t2} else {nssf_t2}) * {_rate(rates.nssf_employer_rate)}",
			"p9a": "",
			"p10a": "",
			"flags": _EMPLOYER_EARNING_FLAGS,
		}
	)
	specs.append(
		{
			"salary_component": "Housing Levy Employer",
			"abbr": "AHL_ER",
			"type": "Earning",
			"formula": f"gross_pay * {_rate(rates.ahl_employer_rate)}",
			"p9a": "",
			"p10a": "",
			"flags": _EMPLOYER_EARNING_FLAGS,
		}
	)
	specs.append(
		{
			"salary_component": "NITA",
			"abbr": "NITA",
			"type": "Earning",
			"formula": _num(rates.nita_amount),
			"p9a": "",
			"p10a": "",
			# NITA is a flat amount regardless of days worked — the one deliberate
			# override from the shared employer-earning block (guide section 6.8).
			"flags": {**_EMPLOYER_EARNING_FLAGS, "depends_on_payment_days": 0},
		}
	)

	return specs


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
	doc.amount_based_on_formula = 1

	doc.save(ignore_permissions=True)
	return doc.name


def ensure_components(rates):
	for spec in component_specs(rates):
		upsert_component(spec)


def map_accounts(company):
	"""Add a (company, account) row to every component that needs one — guide section 6.9.
	Statistical components (TI, the 9 bands, Gross PAYE) are skipped; they have no
	Accounts table entry by design."""
	abbr = frappe.db.get_value("Company", company, "abbr")

	for component, account in ACCOUNT_MAP.items():
		doc = frappe.get_doc("Salary Component", component)
		already_mapped = any(row.company == company for row in doc.accounts)
		if already_mapped:
			continue
		doc.append("accounts", {"company": company, "account": f"{account} - {abbr}"})
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


def ensure_salary_structure(company, rates):
	"""One structure per (company, rates version) — not per (company, year).

	This is deliberate, not an accident of convenience: Salary Slip reads formulas
	straight off the Structure's own row copies (verified against the HRMS source,
	not assumed — eval_condition_and_formula takes struct_row, never re-reads the
	Salary Component master). A Structure named only by year would go stale the
	moment a rate changes mid-year, with nothing anywhere signalling it. Naming it
	by the exact rates version instead means a new rate always gets a new,
	distinctly-named structure, and an old one is never silently wrong for a rate
	change it predates — it just keeps meaning what it always meant."""
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"{abbr} Payroll Structure {rates.name}"
	if frappe.db.exists("Salary Structure", name):
		return name

	doc = frappe.new_doc("Salary Structure")
	doc.name = name
	doc.company = company
	doc.currency = "KES"
	doc.is_active = "Yes"
	doc.payroll_frequency = "Monthly"
	doc.salary_slip_based_on_timesheet = 0

	for component in EARNINGS_ORDER:
		row = doc.append("earnings", {})
		_fill_structure_row(row, component)

	for component in DEDUCTIONS_ORDER:
		row = doc.append("deductions", {})
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
	row.salary_component = component_name
	row.abbr = master.salary_component_abbr
	row.condition = master.condition
	row.amount_based_on_formula = master.amount_based_on_formula
	row.formula = master.formula
	row.statistical_component = master.statistical_component
	row.is_tax_applicable = master.is_tax_applicable
	row.variable_based_on_taxable_salary = master.variable_based_on_taxable_salary
	row.depends_on_payment_days = master.depends_on_payment_days
	row.deduct_full_tax_on_selected_payroll_date = master.deduct_full_tax_on_selected_payroll_date
	row.do_not_include_in_total = master.do_not_include_in_total
	row.exempted_from_income_tax = master.exempted_from_income_tax
	row.do_not_include_in_accounts = master.do_not_include_in_accounts


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def seed_default_rates():
	"""Create and submit the current Kenya statutory rates, if no effective
	Payroll Rates record exists yet.

	One-time (or once-per-Finance-Act-change) ENVIRONMENT bootstrap — not a
	per-client onboarding step. PayrollRates.get_effective() has no company
	filter: every client's payroll draws from whichever single record is
	submitted and effective as of today, so this only ever needs running
	once per bench, not once per client.

	The numbers below are a known-good snapshot (Feb 2026 KRA rates, per
	docs/user-guide.md section 2) — not a live source of truth that should
	silently drift. A real rate change means creating a new Payroll Rates
	record by hand with the new effective_from date, same as any other
	Finance Act update; it does not mean editing this function.

	Restricted to System Manager: this creates and submits a submitted
	statutory record that every client's payroll math depends on — not
	something to expose more broadly than onboard_client_cli() itself is."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted — seed_default_rates is restricted to System Managers."), frappe.PermissionError)

	existing = PayrollRates.get_effective()
	if existing:
		return {"status": "already seeded", "rates": existing}

	doc = frappe.get_doc(
		{
			"doctype": "Payroll Rates",
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
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return {"status": "seeded", "rates": doc.name}


def _get_rates_doc(rates):
	rates_name = rates or PayrollRates.get_effective()
	if not rates_name:
		frappe.throw(_("No effective, submitted Payroll Rates record found. Create and submit one first."))
	return frappe.get_doc("Payroll Rates", rates_name)


def _provisioned_companies():
	"""Companies that already have a Kenya payroll structure. Detected via the
	'Taxable Income' component rather than a naming convention — it's a marker
	unique to this app's band engine, so it identifies our structures correctly
	even if someone renames one."""
	structure_names = frappe.get_all(
		"Salary Detail",
		filters={"salary_component": "Taxable Income", "parenttype": "Salary Structure"},
		pluck="parent",
	)
	companies = {frappe.db.get_value("Salary Structure", name, "company") for name in structure_names}
	return sorted(c for c in companies if c)


@frappe.whitelist()
def provision(company, rates=None):
	"""Full setup for a company: accounts, the 22 components, the Income Tax Slab
	placeholder, the Payroll Period, and the Salary Structure. Safe to re-run."""
	rates_doc = _get_rates_doc(rates)

	ensure_accounts(company)
	ensure_components(rates_doc)
	map_accounts(company)
	slab = ensure_income_tax_slab_placeholder(company, rates_doc)
	period = ensure_payroll_period(company, rates_doc)
	structure = ensure_salary_structure(company, rates_doc)

	return {
		"rates": rates_doc.name,
		"income_tax_slab": slab,
		"payroll_period": period,
		"salary_structure": structure,
	}


@frappe.whitelist()
def regenerate(rates=None):
	"""Re-template the 22 components' formulas off the given (or currently effective)
	Payroll Rates record, and give every already-provisioned company a fresh Salary
	Structure for this rates version. Run after a Finance Act rate change — replaces
	guide section 12's manual, per-component, in-exact-order hand edits.

	Does not touch any existing Salary Structure Assignment. Employees keep using
	whatever structure they're currently assigned to — including one built off an
	older rates version — until someone explicitly reassigns them with a From Date
	on or after the new rates' effective date, same as any other base-salary change
	per guide section 8. That's a deliberate choice: it would be worse to silently
	migrate a live assignment onto new formulas mid-flight than to leave the old
	assignment as it was and require an explicit, dated, reviewable change."""
	rates_doc = _get_rates_doc(rates)
	ensure_components(rates_doc)

	structures = {}
	for company in _provisioned_companies():
		map_accounts(company)
		ensure_income_tax_slab_placeholder(company, rates_doc)
		structures[company] = ensure_salary_structure(company, rates_doc)

	return {"rates": rates_doc.name, "structures": structures}


@frappe.whitelist()
def verify(company):
	"""Read-only structural sanity check that provisioning actually produced
	what it should. Deliberately does not create a synthetic employee/payslip
	to test the math end to end — this needs to be safe to run against a real
	client's site, and leaving fake test data in someone's production HR
	system to prove a point is not acceptable. Checks structure instead: do
	the 22 components exist with formulas, do the accounts exist with the
	right Account Type, does the current Salary Structure have the right rows
	in the right order. Raises with every problem found, not just the first —
	whoever's onboarding a client wants the whole list at once, not one
	failure per retry."""
	problems = []

	rates_name = PayrollRates.get_effective()
	if not rates_name:
		frappe.throw(_("No effective, submitted Payroll Rates record found."))
	rates_doc = frappe.get_doc("Payroll Rates", rates_name)

	expected_components = [spec["salary_component"] for spec in component_specs(rates_doc)]
	for name in expected_components:
		if not frappe.db.exists("Salary Component", name):
			problems.append(_("Salary Component {0} is missing.").format(name))
			continue
		if not frappe.db.get_value("Salary Component", name, "formula"):
			problems.append(_("Salary Component {0} has no formula.").format(name))

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

	structure_name = f"{abbr} Payroll Structure {rates_name}"
	if not frappe.db.exists("Salary Structure", structure_name):
		problems.append(_("Salary Structure {0} is missing.").format(structure_name))
	else:
		structure = frappe.get_doc("Salary Structure", structure_name)
		actual_earnings = [d.salary_component for d in structure.earnings]
		actual_deductions = [d.salary_component for d in structure.deductions]
		if actual_earnings != EARNINGS_ORDER:
			problems.append(
				_("{0}'s earnings row order is wrong — got {1}, expected {2}.").format(
					structure_name, actual_earnings, EARNINGS_ORDER
				)
			)
		if actual_deductions != DEDUCTIONS_ORDER:
			problems.append(
				_("{0}'s deductions row order is wrong — got {1}, expected {2}.").format(
					structure_name, actual_deductions, DEDUCTIONS_ORDER
				)
			)

	if problems:
		frappe.throw(_("Payroll provisioning verification failed for {0}:<br>{1}").format(
			company, "<br>".join(problems)
		))

	return {
		"company": company,
		"rates": rates_name,
		"components_checked": len(expected_components),
		"structure": structure_name,
		"status": "PASS",
	}
