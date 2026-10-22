# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Leaving pay (v16.7.0): Notice Pay, Severance Pay and Gratuity components, the Gratuity
Rule, Leave Pay for leave encashment, and the one-third rule on a leaver's final slip."""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import flt
from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

from royce_payroll_ke.kenya_payroll.setup import (
	GRATUITY_RULE,
	component_specs,
	ensure_gratuity_rule,
	link_leave_encashment,
)
from royce_payroll_ke.kenya_payroll.tests.utils import (
	get_test_company,
	make_test_kenya_payroll_rates,
	make_test_payslip,
)


def _flags(name):
	return next(s for s in component_specs() if s["salary_component"] == name)["flags"]


class TestLeavingPayComponents(UnitTestCase):
	def test_notice_pay_is_taxed_like_salary(self):
		flags = _flags("Notice Pay")
		self.assertEqual(
			(flags["is_tax_applicable"], flags["royce_nssf_pensionable"], flags["royce_shif_applicable"],
				flags["royce_ahl_applicable"], flags["depends_on_payment_days"]),
			(1, 1, 1, 1, 0),
		)

	def test_severance_is_taxed_without_nssf(self):
		flags = _flags("Severance Pay")
		self.assertEqual(
			(flags["is_tax_applicable"], flags["royce_nssf_pensionable"], flags["royce_shif_applicable"],
				flags["royce_ahl_applicable"]),
			(1, 0, 1, 1),
		)

	def test_gratuity_is_untaxed_and_off_the_tax_cards(self):
		flags = _flags("Gratuity")
		self.assertEqual(
			(flags["is_tax_applicable"], flags["royce_nssf_pensionable"], flags["royce_shif_applicable"],
				flags["royce_ahl_applicable"]),
			(0, 0, 1, 1),
		)
		spec = next(s for s in component_specs() if s["salary_component"] == "Gratuity")
		self.assertEqual((spec["p9a"], spec["p10a"]), ("", ""))

	def test_defaults_say_to_confirm_with_an_adviser(self):
		for name in ("Notice Pay", "Severance Pay", "Gratuity"):
			spec = next(s for s in component_specs() if s["salary_component"] == name)
			self.assertIn("confirm with your tax adviser", spec["description"], name)


class TestLeavingPaySetup(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates("1994-01-01")
		from royce_payroll_ke.kenya_payroll.setup import provision

		provision(cls.company, rates=cls.rates.name)

	def test_gratuity_rule_is_15_days_basic_per_year(self):
		rule = frappe.get_doc("Gratuity Rule", GRATUITY_RULE)
		self.assertEqual([r.salary_component for r in rule.applicable_earnings_component], ["Basic Salary"])
		self.assertEqual(len(rule.gratuity_rule_slabs), 1)
		slab = rule.gratuity_rule_slabs[0]
		self.assertEqual((slab.from_year, slab.to_year, flt(slab.fraction_of_applicable_earnings)), (0, 0, 0.5))
		self.assertEqual(rule.minimum_year_for_gratuity, 1)

	def test_gratuity_rule_edits_are_kept(self):
		slab = {"parent": GRATUITY_RULE}
		frappe.db.set_value("Gratuity Rule Slab", slab, "fraction_of_applicable_earnings", 0.6)
		try:
			ensure_gratuity_rule()
			self.assertEqual(flt(frappe.db.get_value("Gratuity Rule Slab", slab, "fraction_of_applicable_earnings")), 0.6)
		finally:
			frappe.db.set_value("Gratuity Rule Slab", slab, "fraction_of_applicable_earnings", 0.5)

	def test_encashable_leave_types_pay_through_leave_pay(self):
		def leave_type(name, **values):
			if not frappe.db.exists("Leave Type", name):
				frappe.get_doc({"doctype": "Leave Type", "leave_type_name": name, **values}).insert()
			return name

		blank = leave_type("Kenya Test Annual Leave", allow_encashment=1)
		chosen = leave_type("Kenya Test Encash Bonus", allow_encashment=1, earning_component="Bonus")
		not_encashable = leave_type("Kenya Test Sick Leave", allow_encashment=0)
		link_leave_encashment()
		self.assertEqual(frappe.db.get_value("Leave Type", blank, "earning_component"), "Leave Pay")
		self.assertEqual(frappe.db.get_value("Leave Type", chosen, "earning_component"), "Bonus")
		self.assertFalse(frappe.db.get_value("Leave Type", not_encashable, "earning_component"))


class TestFinalSlip(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates("1995-01-01")

	def _additional_salary(self, employee, component, amount, payroll_date):
		frappe.get_doc(
			{
				"doctype": "Additional Salary", "employee": employee, "salary_component": component,
				"amount": amount, "payroll_date": payroll_date, "company": self.company, "currency": "KES",
			}
		).insert().submit()

	def test_final_dues_recoveries_are_exempt_from_the_one_third_rule(self):
		# Base 40,000 -> gross 50,000; a 36,000 recovery plus statutory deductions breaks the
		# two-thirds limit (33,333) with net pay still positive.
		employee, slip = make_test_payslip(
			self.company, self.rates, "leaver.third@example.com", base=40000,
			posting_date="1995-03-31", period_start="1995-03-01", period_end="1995-03-31",
		)
		self._additional_salary(employee, "SACCO Contribution", 36000, "1995-04-01")
		frappe.db.set_value("Employee", employee, "relieving_date", "1995-04-30")

		final = make_salary_slip(slip.salary_structure, employee=employee, posting_date="1995-04-30")
		final.insert()
		self.assertGreater(final.total_deduction, final.gross_pay * 2 / 3)
		final.submit()
		self.assertEqual(final.docstatus, 1)

	def test_leaving_dues_on_the_final_slip(self):
		"""Gratuity from HRMS's Gratuity with the seeded rule, plus notice pay, on the last
		slip: notice pay is taxed, gratuity is not, and both count for SHIF and Housing Levy."""
		employee, slip = make_test_payslip(
			self.company, self.rates, "leaver.dues@example.com", base=40000,
			posting_date="1995-05-31", period_start="1995-05-01", period_end="1995-05-31",
		)
		frappe.db.set_value("Employee", employee, {"date_of_joining": "1991-06-01", "relieving_date": "1995-06-30"})

		gratuity = frappe.get_doc(
			{
				"doctype": "Gratuity", "employee": employee, "company": self.company, "posting_date": "1995-06-30",
				"gratuity_rule": GRATUITY_RULE, "pay_via_salary_slip": 1, "payroll_date": "1995-06-01",
				"salary_component": "Gratuity",
			}
		).insert()
		# 1,490 days / 365 = 4.08 years x 40,000 basic x 0.5 (15 days of 30).
		self.assertAlmostEqual(flt(gratuity.current_work_experience), 4.08, places=2)
		self.assertAlmostEqual(gratuity.amount, 40000 * 0.5 * flt(gratuity.current_work_experience), places=0)
		gratuity.submit()
		self._additional_salary(employee, "Notice Pay", 40000, "1995-06-01")

		final = make_salary_slip(slip.salary_structure, employee=employee, posting_date="1995-06-30")
		final.insert()
		rows = {d.salary_component: flt(d.amount) for d in final.earnings}
		self.assertAlmostEqual(rows["Gratuity"], gratuity.amount, places=0)
		self.assertEqual(rows["Notice Pay"], 40000)

		# 50,000 salary + 40,000 notice pay taxed; gratuity not.
		self.assertEqual(flt(final.royce_taxable_cash_pay), 90000)
		shif = next(d.amount for d in final.deductions if d.salary_component == "SHIF")
		self.assertEqual(flt(shif), round((90000 + rows["Gratuity"]) * 0.0275))
