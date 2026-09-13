# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Tests for the generator (setup.py): the formulas component_specs()
produces from a rates record, provision()/verify() agreeing with each
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

from royce_payroll_ke.royce_payroll_ke.setup import (
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
from royce_payroll_ke.royce_payroll_ke.tests.utils import (
	DEFAULT_RATES,
	get_test_company,
	make_test_payroll_rates,
	make_test_payslip,
)


class TestComponentSpecs(UnitTestCase):
	"""Locks in the exact formula/condition strings component_specs()
	produces for the Feb 2026 rates — this is the actual replacement for the
	setup guide's Section 12 manual, per-component, in-exact-order formula
	editing, so a change to the generator that silently drifts from the KRA
	band math should fail here, not get discovered against a real payslip."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.rates = frappe.get_doc({"doctype": "Payroll Rates", "effective_from": "2026-01-01", **DEFAULT_RATES})
		cls.specs = component_specs(cls.rates)

	def _spec(self, component_name):
		matches = [s for s in self.specs if s["salary_component"] == component_name]
		self.assertEqual(len(matches), 1, f"expected exactly one spec for {component_name!r}")
		return matches[0]

	def test_produces_exactly_22_components(self):
		self.assertEqual(len(self.specs), 22)

	def test_basic_and_allowance_formulas(self):
		self.assertEqual(self._spec("Basic Salary")["formula"], "base")
		self.assertEqual(self._spec("House Allowance")["formula"], "base * 0.15")
		self.assertEqual(self._spec("Transport Allowance")["formula"], "base * 0.10")

	def test_nssf_tier_formulas(self):
		t1 = self._spec("NSSF Tier I - Employee")
		self.assertEqual(t1["formula"], "(gross_pay if gross_pay < 9000 else 9000) * 0.06")
		t2 = self._spec("NSSF Tier II - Employee")
		self.assertEqual(
			t2["formula"],
			"((gross_pay if gross_pay < 108000 else 108000) - 9000 if gross_pay > 9000 else 0) * 0.06",
		)

	def test_shif_formula(self):
		self.assertEqual(
			self._spec("SHIF")["formula"], "300 if gross_pay * 0.0275 < 300 else gross_pay * 0.0275"
		)

	def test_housing_levy_formulas(self):
		self.assertEqual(self._spec("Housing Levy")["formula"], "gross_pay * 0.015")
		self.assertEqual(self._spec("Housing Levy Employer")["formula"], "gross_pay * 0.015")

	def test_taxable_income_formula(self):
		self.assertEqual(
			self._spec("Taxable Income")["formula"], "gross_pay - NSSF_T1 - NSSF_T2 - SHIF - AHL"
		)

	def test_paye_bands_follow_the_rate_table(self):
		# Band 1: 0-24,000 @ 10%
		self.assertEqual(self._spec("PAYEBand1Max")["condition"], "TI > 0 and TI <= 24000")
		self.assertEqual(self._spec("PAYEBand1Max")["formula"], "TI * 0.1")
		self.assertEqual(self._spec("PAYEBand1")["condition"], "TI > 24000")
		self.assertEqual(self._spec("PAYEBand1")["formula"], "2400")

		# Band 2: 24,000-32,333 @ 25%
		self.assertEqual(self._spec("PAYEBand2Max")["condition"], "TI > 24000 and TI <= 32333")
		self.assertEqual(self._spec("PAYEBand2Max")["formula"], "(TI - 24000) * 0.25")
		self.assertEqual(self._spec("PAYEBand2")["condition"], "TI > 32333")
		self.assertEqual(self._spec("PAYEBand2")["formula"], "2083.25")

		# Band 3: 32,333-500,000 @ 30%
		self.assertEqual(self._spec("PAYEBand3Max")["condition"], "TI > 32333 and TI <= 500000")
		self.assertEqual(self._spec("PAYEBand3Max")["formula"], "(TI - 32333) * 0.3")
		self.assertEqual(self._spec("PAYEBand3")["condition"], "TI > 500000")
		self.assertEqual(self._spec("PAYEBand3")["formula"], "140300.1")

		# Band 4: 500,000-800,000 @ 32.5%
		self.assertEqual(self._spec("PAYEBand4Max")["condition"], "TI > 500000 and TI <= 800000")
		self.assertEqual(self._spec("PAYEBand4Max")["formula"], "(TI - 500000) * 0.325")
		self.assertEqual(self._spec("PAYEBand4")["condition"], "TI > 800000")
		self.assertEqual(self._spec("PAYEBand4")["formula"], "97500")

		# Band 5: 800,000+ @ 35%, open-ended — no Max variant
		self.assertEqual(self._spec("PAYEBand5")["condition"], "TI > 800000")
		self.assertEqual(self._spec("PAYEBand5")["formula"], "(TI - 800000) * 0.35")

	def test_gross_paye_sums_every_band_component(self):
		spec = self._spec("Gross PAYE")
		self.assertEqual(spec["condition"], "TI > 0")
		self.assertEqual(
			spec["formula"],
			"PAYEBand1Max + PAYEBand1 + PAYEBand2Max + PAYEBand2 + PAYEBand3Max + PAYEBand3"
			" + PAYEBand4Max + PAYEBand4 + PAYEBand5",
		)

	def test_paye_applies_personal_relief_as_a_credit(self):
		spec = self._spec("PAYE")
		self.assertEqual(spec["condition"], "GROSS_PAYE > 2400")
		self.assertEqual(spec["formula"], "GROSS_PAYE - 2400")
		self.assertEqual(spec["p9a"], "PAYE Tax")
		self.assertEqual(spec["p10a"], "PAYE Tax")

	def test_nita_is_a_flat_amount(self):
		spec = self._spec("NITA")
		self.assertEqual(spec["formula"], "50")
		self.assertEqual(spec["flags"]["depends_on_payment_days"], 0)

	def test_nssf_employer_formula(self):
		self.assertEqual(
			self._spec("NSSF Employer")["formula"], "(gross_pay if gross_pay < 108000 else 108000) * 0.06"
		)


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
		cls.rates = make_test_payroll_rates(today())

	def test_provision_then_verify_passes(self):
		result = provision(self.company)
		self.assertEqual(result["rates"], self.rates.name)
		self.assertTrue(frappe.db.exists("Salary Structure", result["salary_structure"]))

		outcome = verify(self.company)
		self.assertEqual(outcome["status"], "PASS")
		self.assertEqual(outcome["rates"], self.rates.name)
		self.assertEqual(outcome["components_checked"], 22)

	def test_provision_is_idempotent(self):
		first = provision(self.company)
		second = provision(self.company)
		self.assertEqual(first["salary_structure"], second["salary_structure"])

	def test_verify_reports_every_problem_at_once(self):
		provision(self.company)
		abbr = frappe.db.get_value("Company", self.company, "abbr")
		account = f"PAYE Payable - {abbr}"
		frappe.db.set_value("Account", account, "account_type", "")
		frappe.db.set_value("Salary Component", "PAYE", "formula", "")

		with self.assertRaises(frappe.ValidationError) as ctx:
			verify(self.company)
		message = str(ctx.exception)
		self.assertIn(account, message)
		self.assertIn("PAYE", message)


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
		cls.rates = make_test_payroll_rates("1979-01-01")
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
	"""provision()/regenerate()/verify() now gate on Payroll Rates'
	own permission model, not just "logged in" — added alongside the Desk
	buttons that call them, since a visible button makes an unrestricted
	API a lot easier to hit by accident than a bare endpoint does. Verified
	against a real HR User (read-only on Payroll Rates by its own
	permissions list, no HR Manager/System Manager) rather than assumed."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.rates = make_test_payroll_rates("1976-01-01")
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
		rates = make_test_payroll_rates("1985-05-05")

		result = provision(company, rates=rates.name)

		current_year = getdate().year
		self.assertIn(current_year, result["holiday_lists"])
		self.assertIn(current_year + 1, result["holiday_lists"])
		for holiday_list in result["holiday_lists"].values():
			self.assertTrue(frappe.db.exists("Holiday List", holiday_list))
