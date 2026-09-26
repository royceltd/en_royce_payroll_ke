# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Shared fixtures for royce_payroll_ke's own test suite. Not a test module
itself (no test_ prefix, so `bench run-tests` won't try to collect it) —
just the wiring every other test file needs to avoid re-deriving it.

Every helper here takes an explicit, test-only ``effective_from``/date
rather than ever relying on "whatever's currently effective" — a real site
can have a real, committed Kenya Payroll Rates record (or several) sitting in the
same database these tests run against, and get_effective()'s "most recent
on or before today" resolution would silently pick that up instead of a
test's own fixture if the test didn't pin its own date explicitly. Tests
that must exercise get_effective()'s own resolution do so with far-past,
clearly-test-only dates for exactly this reason.
"""

import frappe
from frappe.utils import getdate
from hrms.payroll.doctype.salary_structure.salary_structure import (
	create_salary_structure_assignment,
	make_salary_slip,
)

from royce_payroll_ke.kenya_payroll.setup import provision

# Deliberately not erpnext.setup.doctype.employee.test_employee.make_employee:
# importing it pulls in erpnext.tests.utils, whose ERPNextTestSuite bootstraps
# erpnext's *entire* legacy global test dataset (items, price lists,
# customers...) as a module-level side effect the moment it's imported — and
# on a real bench (not one erpnext's own `bench run-tests --app erpnext` has
# already primed in the exact order it expects), that bootstrap itself throws
# ("Could not find Customer: _Test Customer"), taking this whole suite down
# with it before a single royce_payroll_ke test even runs. None of that
# machinery is needed here — "_Test Company" already exists on any site
# erpnext is installed on (its own setup wizard/demo data creates it), and an
# Employee only actually requires a handful of fields (verified against
# employee.json's own `reqd` flags, not assumed).

# The Feb 2026 KRA snapshot setup.seed_default_rates() ships — duplicated here
# rather than imported from it, deliberately: these tests are the safety net
# for that snapshot too, and importing it would let a typo in one silently
# hide a matching typo in the other.
DEFAULT_RATES = {
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


def make_test_kenya_payroll_rates(effective_from, submit=True, **overrides):
	"""Build a Kenya Payroll Rates record for tests. Feb 2026 KRA numbers by
	default (see DEFAULT_RATES), overridable per field — including
	``paye_bands`` wholesale, for tests that need a deliberately malformed
	band table.

	Returns a *freshly reloaded* doc (frappe.get_doc(doctype, name), not the
	just-inserted in-memory object) deliberately — setup.py's own functions
	always work with a rates doc fetched this same way
	(_get_rates_doc() -> frappe.get_doc("Kenya Payroll Rates", name)), which is
	what gives fields like `effective_from` their real Date-typed value
	(datetime.date, not a plain string). Returning the in-memory object
	instead would let a test pass here while still not matching what
	production code actually receives.
	"""
	values = {**DEFAULT_RATES, **overrides}
	doc = frappe.get_doc({"doctype": "Kenya Payroll Rates", "effective_from": effective_from, **values})
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return frappe.get_doc("Kenya Payroll Rates", doc.name)


TEST_COMPANY = "Royce Payroll Test Co"


def get_test_company():
	"""A dedicated, KES-denominated test company — deliberately not
	"_Test Company" (INR by default, per erpnext's own company test
	fixture). Retrofitting currency onto a company whose Chart of Accounts
	was already built doesn't work: an already-existing Account (Payroll
	Payable included — ERPNext auto-creates it at company setup) keeps
	whatever `account_currency` it was actually created with; changing
	Company.default_currency afterwards doesn't retroactively fix it, and
	HRMS's Salary Structure Assignment flow needs both to agree (confirmed
	the hard way: `bench run-tests` against a live site, not assumed — see
	docs/architecture.md). A real Kenya client's company is KES from
	creation, so this fixture is built the same way, not patched after the
	fact."""
	if frappe.db.exists("Company", TEST_COMPANY):
		return TEST_COMPANY

	# Company.on_update() (erpnext's own hook, not ours) auto-creates a
	# "Goods In Transit" Warehouse linked to Warehouse Type "Transit" — a
	# master record the Setup Wizard normally seeds, but a site provisioned
	# purely via `bench install-app` (no Setup Wizard) never gets. Confirmed
	# against a genuinely fresh site, not assumed from one with leftover
	# state from something else.
	if not frappe.db.exists("Warehouse Type", "Transit"):
		frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(ignore_permissions=True)

	company = frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": TEST_COMPANY,
			"abbr": "RPTC",
			"default_currency": "KES",
			"country": "Kenya",
			"chart_of_accounts": "Standard",
		}
	)
	company.insert(ignore_permissions=True)
	return company.name


def make_test_employee(user_id, company, **kwargs):
	"""A minimal Employee for tests, without pulling in erpnext's test-utils
	import chain (see the module docstring above for why). Creates the User
	too if it doesn't exist yet, same as erpnext's own helper does.

	Gender is normally seeded by the Setup Wizard, which a site provisioned
	purely via `bench install-app` never runs — confirmed against a
	genuinely fresh site, not assumed from one with leftover state from
	something else (same root cause as the Warehouse Type fix in
	get_test_company())."""
	if not frappe.db.exists("Gender", "Female"):
		frappe.get_doc({"doctype": "Gender", "gender": "Female"}).insert(ignore_permissions=True)

	if not frappe.db.exists("User", user_id):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": user_id,
				"first_name": user_id.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	existing = frappe.db.get_value("Employee", {"user_id": user_id}, "name")
	if existing:
		return existing

	employee = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": user_id.split("@")[0],
			"company": company,
			"user_id": user_id,
			"gender": "Female",
			# Safely before every sentinel effective_from/period date used
			# across this suite (as early as the late 1970s) — date_of_joining
			# is set per-call to match a test's own period, so this only needs
			# to predate the earliest one, not track it exactly.
			"date_of_birth": "1950-01-01",
			"date_of_joining": "2010-01-01",
			"status": "Active",
			**kwargs,
		}
	)
	employee.insert(ignore_permissions=True)
	return employee.name


def make_test_payslip(
	company,
	rates,
	employee_email,
	base,
	posting_date,
	period_start,
	period_end,
	holiday_list_name=None,
	**employee_kwargs,
):
	"""Provision `company` off `rates` (if it isn't already), assign a test
	employee the resulting Salary Structure at `base`, and return
	`(employee, submitted Salary Slip)`.

	`company` must be KES-denominated — use get_test_company(), not
	"_Test Company" (see its own docstring for why).

	Uses a dedicated, zero-holiday Holiday List spanning exactly
	[period_start, period_end] rather than whatever `company`'s own default
	Holiday List happens to cover — that keeps payment-days (and therefore
	every earning figure) deterministic and independent of ambient fixture
	data. Pass `holiday_list_name` to share one across several employees in
	the same test instead of creating a new one per call.
	"""
	abbr = frappe.db.get_value("Company", company, "abbr")
	structure_name = f"{abbr} Payroll Structure {rates.name}"
	if not frappe.db.exists("Salary Structure", structure_name):
		provision(company, rates=rates.name)

	if holiday_list_name:
		holiday_list = holiday_list_name
	else:
		holiday_list = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": f"Kenya Payroll Test Holidays {frappe.generate_hash(length=8)}",
				"from_date": period_start,
				"to_date": period_end,
			}
		).insert(ignore_permissions=True).name

	# Matches HRMS's own test convention: with no holidays and no leave, the
	# ratio is 1.0 either way, but pinning this removes any doubt.
	frappe.db.set_single_value("Payroll Settings", "include_holidays_in_total_working_days", 0)

	# A Fiscal Year covering the test's own period — a fresh company has none
	# by default, and accounting utils validate posting dates against one
	# regardless of how far in the past or future the test period is. Spans
	# the full calendar year (ERPNext requires ~365 days, not just the
	# period itself).
	fy_year = getdate(period_start).year
	fy_start, fy_end = f"{fy_year}-01-01", f"{fy_year}-12-31"
	if not frappe.db.exists("Fiscal Year", {"year_start_date": ["<=", period_start], "year_end_date": [">=", period_end]}):
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": f"Royce Payroll Test FY {fy_year}",
				"year_start_date": fy_start,
				"year_end_date": fy_end,
			}
		).insert(ignore_permissions=True)

	# The assignment must be effective on or before the slip's own period, not
	# some fixed unrelated date — using period_start itself keeps employee and
	# assignment always chronologically consistent with whatever period a
	# given test actually asks for.
	employee = make_test_employee(
		employee_email,
		company,
		holiday_list=holiday_list,
		date_of_joining=period_start,
		**employee_kwargs,
	)

	# The plain Employee.holiday_list field alone isn't what this HRMS version
	# actually resolves a working-days calculation against for a given date —
	# that reads a submitted Holiday List Assignment instead (confirmed
	# against hrms.utils.holiday_list.get_assigned_holiday_list's source, not
	# assumed). Employee.holiday_list is still set above too (a real, still-
	# used field), but this is the record that actually answers "which
	# holiday list applies to this employee on this date."
	if not frappe.db.exists("Holiday List Assignment", {"assigned_to": employee, "holiday_list": holiday_list}):
		frappe.get_doc(
			{
				"doctype": "Holiday List Assignment",
				"applicable_for": "Employee",
				"assigned_to": employee,
				"holiday_list": holiday_list,
				"from_date": period_start,
			}
		).insert(ignore_permissions=True).submit()

	create_salary_structure_assignment(
		employee,
		structure_name,
		company,
		"KES",
		from_date=period_start,
		base=base,
		income_tax_slab=f"Kenya PAYE Placeholder {rates.effective_from.year}",
	)

	slip = make_salary_slip(structure_name, employee=employee, posting_date=posting_date)
	slip.insert(ignore_permissions=True)
	slip.submit()
	return employee, slip
