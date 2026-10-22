# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Casual workers paid monthly (v16.6.0): the Kenya Casual Wages structure (daily rate x
Days Worked), the days-worked check, and the rule that Kenya Payroll structures are
Monthly only."""

import frappe
from frappe.tests import IntegrationTestCase

from royce_payroll_ke.kenya_payroll.engine import apply_kenya_statutory, validate_salary_structure
from royce_payroll_ke.kenya_payroll.setup import kenya_structure, provision
from royce_payroll_ke.kenya_payroll.tests.utils import (
	get_test_company,
	make_test_kenya_payroll_rates,
	make_test_payslip,
)


class TestCasualWages(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates("1983-01-01")
		result = provision(cls.company, rates=cls.rates.name)
		cls.structure = result["salary_structure"]
		cls.casual_structure = result["casual_structure"]

	def _casual_slip(self, email, days_worked, month, last_day, submit=True):
		return make_test_payslip(
			self.company,
			self.rates,
			email,
			base=1500,  # the daily rate
			posting_date=f"1983-{month}-{last_day}",
			period_start=f"1983-{month}-01",
			period_end=f"1983-{month}-{last_day}",
			structure_name=self.casual_structure,
			allowances={},
			slip_values={"royce_days_worked": days_worked},
			submit=submit,
		)[1]

	def _amount(self, slip, table, component):
		return sum(r.amount for r in slip.get(table) if r.salary_component == component)

	def test_provision_makes_a_separate_casual_structure(self):
		self.assertNotEqual(self.structure, self.casual_structure)
		self.assertEqual(kenya_structure(self.company), self.structure)
		self.assertEqual(kenya_structure(self.company, casual=True), self.casual_structure)
		again = provision(self.company, rates=self.rates.name)
		self.assertEqual((again["salary_structure"], again["casual_structure"]), (self.structure, self.casual_structure))

	def test_casual_pay_and_statutory_deductions(self):
		# 1,500 a day x 20 days = 30,000. NSSF 6% of 9,000 = 540 + 6% of 21,000 = 1,260;
		# SHIF 2.75% = 825; AHL 1.5% = 450. Taxable 30,000 - 1,800 - 825 - 450 = 26,925;
		# tax 2,400 + 2,925 x 25% = 3,131.25, less relief 2,400 = 731.
		slip = self._casual_slip("royce.casual.pay@example.com", 20, "03", 31)
		self.assertTrue(slip.royce_casual_wages)
		self.assertEqual(self._amount(slip, "earnings", "Casual Wages"), 30000)
		self.assertEqual(slip.gross_pay, 30000)
		self.assertEqual(self._amount(slip, "deductions", "NSSF Tier I - Employee"), 540)
		self.assertEqual(self._amount(slip, "deductions", "NSSF Tier II - Employee"), 1260)
		self.assertEqual(self._amount(slip, "deductions", "SHIF"), 825)
		self.assertEqual(self._amount(slip, "deductions", "Housing Levy"), 450)
		self.assertEqual(self._amount(slip, "deductions", "PAYE"), 731)
		employer = {r.salary_component: r.amount for r in slip.employer_contributions}
		self.assertEqual(employer, {"NSSF Employer": 1800, "Housing Levy Employer": 450, "NITA": 50})

	def test_changing_days_worked_recalculates_the_draft(self):
		slip = self._casual_slip("royce.casual.edit@example.com", 10, "04", 30, submit=False)
		self.assertEqual(slip.gross_pay, 15000)
		slip.royce_days_worked = 20
		slip.save(ignore_permissions=True)
		self.assertEqual(slip.gross_pay, 30000)
		self.assertEqual(self._amount(slip, "deductions", "SHIF"), 825)

	def test_days_worked_must_be_entered_and_fit_the_period(self):
		for email, days in (("royce.casual.none@example.com", 0), ("royce.casual.many@example.com", 32)):
			with self.subTest(days=days):
				slip = self._casual_slip(email, days, "05", 31, submit=False)
				with self.assertRaisesRegex(frappe.ValidationError, "Days Worked"):
					slip.submit()

	def test_kenya_structures_are_monthly_only(self):
		weekly = frappe._dict(name="Weekly", royce_kenya_statutory=1, payroll_frequency="Weekly")
		with self.assertRaisesRegex(frappe.ValidationError, "must be Monthly"):
			validate_salary_structure(weekly)
		validate_salary_structure(frappe._dict(name="Other", royce_kenya_statutory=0, payroll_frequency="Weekly"))

		# A structure made weekly some other way (e.g. before v16.6.0): its slips are refused.
		with self.assertRaisesRegex(frappe.ValidationError, "must be Monthly"):
			apply_kenya_statutory(frappe._dict(salary_structure=self.structure, payroll_frequency="Weekly"))
