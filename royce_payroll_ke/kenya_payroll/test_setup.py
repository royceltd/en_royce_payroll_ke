# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Tests for the generator (setup.py): the components component_specs()
produces, provision()/verify() agreeing with each
other, and — the highest-value test in this whole suite — the guide's own
worked example, run for real against a submitted Salary Slip instead of by
hand. docs/architecture.md calls that worked example "the highest-value
piece of the whole app... run as a real test after every provision and
every regenerate." Before this file existed, that meant a human re-running
the guide's numbers by hand; this is that check, automated."""

from datetime import date, timedelta

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import getdate, rounded, today

from royce_payroll_ke.kenya_payroll.setup import (
	FIXED_KENYA_HOLIDAYS,
	component_specs,
	_easter_sunday,
	_kenya_holidays_for_year,
	ensure_holiday_list,
	ensure_holiday_list_assignment,
	provision,
	regenerate,
	verify,
)
from royce_payroll_ke.kenya_payroll.tests.utils import (
	get_test_company,
	make_test_kenya_payroll_rates,
	make_test_payslip,
)


class TestComponentSpecs(UnitTestCase):
	"""Kenya Payroll's own Salary Components. Since v16.4.0 only the three earnings
	carry formulas; the eight statutory components are filled by the engine
	(engine.py, tested in test_engine.py) and must not depend on payment days, or
	HRMS would pro-rate the engine's figure a second time."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.specs = component_specs()

	def _spec(self, component_name):
		matches = [s for s in self.specs if s["salary_component"] == component_name]
		self.assertEqual(len(matches), 1, f"expected exactly one spec for {component_name!r}")
		return matches[0]

	def test_produces_exactly_11_components(self):
		self.assertEqual(len(self.specs), 11)

	def test_basic_and_allowance_formulas(self):
		self.assertEqual(self._spec("Basic Salary")["formula"], "base")
		self.assertEqual(self._spec("House Allowance")["formula"], "base * 0.15")
		self.assertEqual(self._spec("Transport Allowance")["formula"], "base * 0.10")

	def test_earnings_count_for_every_statutory_charge(self):
		for name in ("Basic Salary", "House Allowance", "Transport Allowance"):
			flags = self._spec(name)["flags"]
			self.assertEqual(flags["is_tax_applicable"], 1, name)
			self.assertEqual(flags["royce_nssf_pensionable"], 1, name)
			self.assertEqual(flags["royce_shif_applicable"], 1, name)
			self.assertEqual(flags["royce_ahl_applicable"], 1, name)

	def test_engine_components_have_no_formula_and_no_proration(self):
		for name in (
			"NSSF Tier I - Employee", "NSSF Tier II - Employee", "SHIF", "Housing Levy", "PAYE",
			"NSSF Employer", "Housing Levy Employer", "NITA",
		):
			spec = self._spec(name)
			self.assertEqual(spec["formula"], "", name)
			self.assertEqual(spec["flags"]["amount_based_on_formula"], 0, name)
			self.assertEqual(spec["flags"]["depends_on_payment_days"], 0, name)
			self.assertEqual(spec["flags"]["variable_based_on_taxable_salary"], 0, name)

	def test_paye_is_the_income_tax_component(self):
		self.assertEqual(self._spec("PAYE")["flags"]["is_income_tax_component"], 1)

	def test_employer_components_stay_out_of_net_pay(self):
		for name in ("NSSF Employer", "Housing Levy Employer", "NITA"):
			self.assertEqual(self._spec(name)["flags"]["do_not_include_in_total"], 1, name)

	def test_return_mappings(self):
		self.assertEqual(self._spec("PAYE")["p9a"], "PAYE Tax")
		self.assertEqual(self._spec("PAYE")["p10a"], "PAYE Tax")
		self.assertEqual(self._spec("SHIF")["p10a"], "SHIF")
		self.assertEqual(self._spec("Housing Levy")["p10a"], "Affordable Housing Levy")


class TestProvisionAndVerify(IntegrationTestCase):
	"""provision() and verify() have to agree with each other — verify() is
	only useful as an onboarding gate if it actually reflects what
	provision() just built. Runs against a dedicated test company (not
	assumed to already exist — a site provisioned purely via
	`bench install-app`, with no Setup Wizard run, has no companies at all,
	confirmed against a genuinely fresh site) whose Chart of Accounts
	template (generic "Standard") already carries the parent account groups
	(Duties and Taxes, Indirect Expenses, Accounts Payable) ensure_accounts()
	depends on.

	Deliberately dated exactly `today` rather than any fixed past date:
	verify() (called here with no `rates` override, on purpose — this is the
	one place testing that default/backward-compatible resolution) resolves
	"the currently effective rates" itself, so this is the only
	effective_from guaranteed to be picked over anything else already
	committed on whatever site these tests run against — nothing can be
	later than today and still be "on or before today"."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates(today())

	def test_provision_then_verify_passes(self):
		result = provision(self.company)
		self.assertEqual(result["rates"], self.rates.name)
		self.assertTrue(frappe.db.exists("Salary Structure", result["salary_structure"]))

		outcome = verify(self.company)
		self.assertEqual(outcome["status"], "PASS")
		self.assertEqual(outcome["rates"], self.rates.name)
		self.assertEqual(outcome["components_checked"], 11)

	def test_provision_is_idempotent(self):
		first = provision(self.company)
		second = provision(self.company)
		self.assertEqual(first["salary_structure"], second["salary_structure"])

	def test_verify_reports_every_problem_at_once(self):
		provision(self.company)
		abbr = frappe.db.get_value("Company", self.company, "abbr")
		account = f"PAYE Payable - {abbr}"
		frappe.db.set_value("Account", account, "account_type", "")
		frappe.db.set_value("Salary Component", "Basic Salary", "formula", "")

		with self.assertRaises(frappe.ValidationError) as ctx:
			verify(self.company)
		message = str(ctx.exception)
		self.assertIn(account, message)
		self.assertIn("Basic Salary", message)


class TestPayrollCalculationRegression(IntegrationTestCase):
	"""The automated form of the setup guide's own Section 11 worked
	example — a 150,000 base salary — which docs/architecture.md records as
	independently hand-verified and cross-checked against a real submitted
	Salary Slip three separate times, from three different entry points,
	across two different sites: Gross Pay 187,500, PAYE 44,299, Net Pay
	128,753. That's the oracle for the figures asserted here.

	NSSF, SHIF and NITA are also asserted directly — each is exact regardless
	of rounding mode (no fractional remainder, or one comfortably below the
	.5 boundary), unlike Housing Levy, whose 187,500 * 1.5% lands exactly on
	a rounding tie (2,812.50) and is therefore asserted via frappe.utils.
	rounded() — the same function Frappe itself would apply — rather than a
	hardcoded literal that would flip with the site's configured rounding
	method."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates("1979-01-01")
		cls.period_start, cls.period_end = "1979-06-01", "1979-06-30"

		cls.employee, cls.slip = make_test_payslip(
			cls.company,
			cls.rates,
			"royce.payroll.regression@example.com",
			base=150000,
			posting_date=cls.period_start,
			period_start=cls.period_start,
			period_end=cls.period_end,
		)

	def _amount(self, table, component):
		row = next((r for r in self.slip.get(table) if r.salary_component == component), None)
		self.assertIsNotNone(row, f"{component} not found on the slip's {table} table")
		return row.amount

	def test_gross_pay_matches_the_guides_worked_example(self):
		self.assertEqual(self.slip.gross_pay, 187500)

	def test_paye_and_net_pay_match_the_guides_worked_example(self):
		self.assertEqual(self._amount("deductions", "PAYE"), 44299)
		self.assertEqual(self.slip.net_pay, 128753)

	def test_nssf_split_is_exact(self):
		self.assertEqual(self._amount("deductions", "NSSF Tier I - Employee"), 540)
		self.assertEqual(self._amount("deductions", "NSSF Tier II - Employee"), 5940)

	def test_shif_is_exact(self):
		self.assertEqual(self._amount("deductions", "SHIF"), 5156)

	def test_nita_is_flat_regardless_of_gross(self):
		self.assertEqual(self._amount("earnings", "NITA"), 50)

	def test_housing_levy_matches_frappes_own_rounding(self):
		expected = rounded(187500 * 0.015)
		self.assertEqual(self._amount("deductions", "Housing Levy"), expected)


class TestPermissions(IntegrationTestCase):
	"""provision()/regenerate()/verify() now gate on Kenya Payroll Rates'
	own permission model, not just "logged in" — added alongside the Desk
	buttons that call them, since a visible button makes an unrestricted
	API a lot easier to hit by accident than a bare endpoint does. Verified
	against a real HR User (read-only on Kenya Payroll Rates by its own
	permissions list, no HR Manager/System Manager) rather than assumed."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.rates = make_test_kenya_payroll_rates("1976-01-01")
		cls.company = get_test_company()
		provision(cls.company, rates=cls.rates.name)

		cls.limited_user = "royce.payroll.permtest@example.com"
		if not frappe.db.exists("User", cls.limited_user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.limited_user,
					"first_name": "Perm",
					"send_welcome_email": 0,
					"roles": [{"role": "HR User"}],
				}
			).insert(ignore_permissions=True)

	def test_provision_blocked_for_read_only_user(self):
		frappe.set_user(self.limited_user)
		try:
			with self.assertRaises(frappe.PermissionError):
				provision(self.company, rates=self.rates.name)
		finally:
			frappe.set_user("Administrator")

	def test_regenerate_blocked_for_read_only_user(self):
		frappe.set_user(self.limited_user)
		try:
			with self.assertRaises(frappe.PermissionError):
				regenerate(rates=self.rates.name)
		finally:
			frappe.set_user("Administrator")

	def test_verify_allowed_for_read_only_user(self):
		frappe.set_user(self.limited_user)
		try:
			result = verify(self.company, rates=self.rates.name)
			self.assertEqual(result["status"], "PASS")
		finally:
			frappe.set_user("Administrator")

class TestKenyaHolidaySeeding(IntegrationTestCase):
	"""Tests for Holiday List / Holiday List Assignment seeding (2026-09-13):
	weekends + Kenya's confidently-known public holidays, wired into
	provision() so every Growth+ tenant gets one without a human doing it by
	hand. See FIXED_KENYA_HOLIDAYS' own comment for what's deliberately NOT
	seeded (Huduma Day, Eid al-Fitr/al-Adha) and why."""

	def test_easter_sunday_matches_known_real_dates(self):
		"""Locks the Meeus/Jones/Butcher algorithm in against two
		independently known real Easter Sundays, not just internal
		self-consistency."""
		self.assertEqual(_easter_sunday(2024), date(2024, 3, 31))
		self.assertEqual(_easter_sunday(2025), date(2025, 4, 20))

	def test_kenya_holidays_for_year_includes_every_fixed_date(self):
		holidays = _kenya_holidays_for_year(2027)
		self.assertEqual(
			holidays[date(2027, 1, 1)], {"description": "New Year's Day", "weekly_off": 0}
		)
		self.assertEqual(
			holidays[date(2027, 12, 25)], {"description": "Christmas Day", "weekly_off": 0}
		)

	def test_kenya_holidays_for_year_includes_computed_easter_dates(self):
		easter = _easter_sunday(2027)
		holidays = _kenya_holidays_for_year(2027)
		self.assertEqual(holidays[easter - timedelta(days=2)]["description"], "Good Friday")
		self.assertEqual(holidays[easter + timedelta(days=1)]["description"], "Easter Monday")

	def test_named_holiday_beats_weekly_off_label_when_they_coincide(self):
		"""A fixed-date public holiday that happens to land on a weekend
		keeps its own name and weekly_off=0, rather than being silently
		relabelled "Weekly Off" -- searches for a real coincidence (via
		Python's own date.weekday(), an oracle independent of the function
		under test) rather than assuming one falls inside a single
		hardcoded year."""
		for year in range(2024, 2040):
			holidays = _kenya_holidays_for_year(year)
			for month, day, description in FIXED_KENYA_HOLIDAYS:
				d = date(year, month, day)
				if d.weekday() in (5, 6):
					self.assertEqual(holidays[d], {"description": description, "weekly_off": 0})
					return
		self.fail("no fixed Kenya holiday landed on a weekend in 2024-2039 -- widen the search range")

	def test_ensure_holiday_list_creates_and_is_idempotent(self):
		company = get_test_company()
		year = 2031  # far from any other test's own dates -- avoids collisions

		first = ensure_holiday_list(company, year)
		second = ensure_holiday_list(company, year)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Holiday List", {"holiday_list_name": first}), 1)

		doc = frappe.get_doc("Holiday List", first)
		self.assertEqual(str(doc.from_date), f"{year}-01-01")
		self.assertEqual(str(doc.to_date), f"{year}-12-31")
		descriptions = {h.description for h in doc.holidays}
		self.assertIn("New Year's Day", descriptions)
		self.assertIn("Good Friday", descriptions)
		self.assertIn("Weekly Off", descriptions)

	def test_ensure_holiday_list_assignment_submits_and_is_idempotent(self):
		company = get_test_company()
		year = 2032
		holiday_list = ensure_holiday_list(company, year)

		first = ensure_holiday_list_assignment(company, holiday_list, f"{year}-01-01")
		second = ensure_holiday_list_assignment(company, holiday_list, f"{year}-01-01")
		self.assertEqual(first, second)
		self.assertEqual(
			frappe.db.count(
				"Holiday List Assignment",
				{"assigned_to": company, "from_date": f"{year}-01-01", "docstatus": 1},
			),
			1,
		)
		self.assertEqual(frappe.db.get_value("Holiday List Assignment", first, "docstatus"), 1)

	def test_provision_seeds_holiday_lists_for_this_and_next_year(self):
		company = get_test_company()
		rates = make_test_kenya_payroll_rates("1985-05-05")

		result = provision(company, rates=rates.name)

		current_year = getdate().year
		self.assertIn(current_year, result["holiday_lists"])
		self.assertIn(current_year + 1, result["holiday_lists"])
		for holiday_list in result["holiday_lists"].values():
			self.assertTrue(frappe.db.exists("Holiday List", holiday_list))
