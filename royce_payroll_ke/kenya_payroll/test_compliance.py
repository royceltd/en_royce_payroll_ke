# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Payroll checks (compliance.py): the one-third rule and statutory details."""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

from royce_payroll_ke.kenya_payroll.compliance import KRA_PIN, one_third_problem, warn_payroll_entry_problems
from royce_payroll_ke.kenya_payroll.tests.utils import (
	get_test_company,
	make_test_kenya_payroll_rates,
	make_test_payslip,
)


class TestRules(UnitTestCase):
	def test_one_third_rule(self):
		# Gross 75,000: deductions up to 50,000 are allowed.
		self.assertIsNone(one_third_problem(75000, 50000))
		self.assertIn("50,000", one_third_problem(75000, 50001))
		self.assertIsNone(one_third_problem(0, 100))

	def test_kra_pin_shape(self):
		self.assertTrue(KRA_PIN.match("A123456789B"))
		for bad in ("A12345678B", "123456789B", "A123456789", "a123456789b"):
			self.assertFalse(KRA_PIN.match(bad), bad)


class TestChecksOnSlips(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates("1987-01-01")

	def tearDown(self):
		for field in ("one_third_rule", "missing_kra_pin", "missing_statutory_numbers"):
			frappe.db.set_single_value("Kenya Payroll Settings", field, None)

	def _slip(self, email, period=("1987-03-01", "1987-03-31"), **employee):
		return make_test_payslip(
			self.company, self.rates, email, base=40000,
			posting_date=period[1], period_start=period[0], period_end=period[1], **employee,
		)

	def test_missing_kra_pin_blocks_submit(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._slip("check.nopin@example.com", royce_kra_pin="")
		self.assertIn("KRA PIN", str(ctx.exception))

	def test_missing_kra_pin_can_be_set_to_warn(self):
		frappe.db.set_single_value("Kenya Payroll Settings", "missing_kra_pin", "Warn")
		_employee, slip = self._slip("check.nopin.warn@example.com", royce_kra_pin="")
		self.assertEqual(slip.docstatus, 1)

	def test_missing_sha_number_warns_but_submits(self):
		_employee, slip = self._slip("check.nosha@example.com", royce_shif_no="")
		self.assertEqual(slip.docstatus, 1)

	def test_deductions_above_two_thirds_block_submit(self):
		# Base 40,000 -> gross 50,000 (with the default 15% / 10% allowances); limit 33,333.
		employee, slip = self._slip("check.third@example.com", period=("1987-04-01", "1987-04-30"))
		slip.cancel()
		frappe.get_doc(
			{
				"doctype": "Additional Salary", "employee": employee, "salary_component": "SACCO Contribution",
				"amount": 30000, "payroll_date": "1987-04-01", "company": self.company, "currency": "KES",
			}
		).insert().submit()
		again = make_salary_slip(slip.salary_structure, employee=employee, posting_date="1987-04-30")
		again.insert()
		self.assertGreater(again.total_deduction, again.gross_pay * 2 / 3)
		with self.assertRaises(frappe.ValidationError) as ctx:
			again.submit()
		self.assertIn("two-thirds", str(ctx.exception))

		frappe.db.set_single_value("Kenya Payroll Settings", "one_third_rule", "Warn")
		again.reload()
		again.submit()
		self.assertEqual(again.docstatus, 1)

	def test_payroll_entry_lists_employees_with_missing_details(self):
		employee, _slip = self._slip("check.entry@example.com", period=("1987-05-01", "1987-05-31"))
		frappe.db.set_value("Employee", employee, "royce_nssf_no", "")
		entry = frappe._dict(docstatus=0, employees=[frappe._dict(employee=employee, employee_name="Check Entry")])
		frappe.local.message_log = []
		warn_payroll_entry_problems(entry)
		messages = " ".join(str(m) for m in frappe.local.message_log)
		self.assertIn("Check Entry", messages)
		self.assertIn("NSSF number", messages)
