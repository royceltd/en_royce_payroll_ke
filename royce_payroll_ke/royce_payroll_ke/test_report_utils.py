# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Tests for statutory_component_report()'s batched query rewrite. Uses two
employees on purpose, not one — a grouping bug in a batched, all-employees-
at-once query (rows from employee A's slip attributed to employee B, or
mixed together) can't be caught by a single-employee test, since there'd be
nothing to accidentally group across. Mirrors the two-employee, two-base-
salary discipline docs/architecture.md records for exactly this reason
("proof the formulas are right, not proof the reports work at the scale a
real payroll run actually has")."""

import frappe
from frappe.tests import IntegrationTestCase

from royce_payroll_ke.royce_payroll_ke.report_utils import statutory_component_report
from royce_payroll_ke.royce_payroll_ke.tests.utils import (
	get_test_company,
	make_test_employee,
	make_test_payroll_rates,
	make_test_payslip,
)


class TestStatutoryComponentReport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_payroll_rates("1978-01-01")
		cls.period_start, cls.period_end = "1978-06-01", "1978-06-30"

		cls.emp_a, cls.slip_a = make_test_payslip(
			cls.company,
			cls.rates,
			"royce.payroll.report.a@example.com",
			base=150000,
			posting_date=cls.period_start,
			period_start=cls.period_start,
			period_end=cls.period_end,
		)
		# Second employee shares the first's holiday list rather than getting its
		# own — same period, no reason to duplicate the fixture.
		holiday_list = frappe.db.get_value("Employee", cls.emp_a, "holiday_list")
		cls.emp_b, cls.slip_b = make_test_payslip(
			cls.company,
			cls.rates,
			"royce.payroll.report.b@example.com",
			base=80000,
			posting_date=cls.period_start,
			period_start=cls.period_start,
			period_end=cls.period_end,
			holiday_list_name=holiday_list,
		)
		# A third employee with no Salary Slip at all — must not appear in any
		# report output, batched or not.
		cls.emp_c = make_test_employee(
			"royce.payroll.report.c@example.com",
			cls.company,
			holiday_list=holiday_list,
		)

	def _row_for(self, data, employee):
		matches = [row for row in data if row["employee"] == employee]
		self.assertEqual(len(matches), 1, f"expected exactly one row for {employee}")
		return matches[0]

	def test_nssf_amounts_are_correct_per_employee_and_unmixed(self):
		filters = {"company": self.company, "from_date": self.period_start, "to_date": self.period_end}
		columns, data = statutory_component_report(
			filters,
			components=["NSSF Tier I - Employee", "NSSF Tier II - Employee"],
			amount_label="NSSF Amount",
		)

		employees_in_report = {row["employee"] for row in data}
		self.assertIn(self.emp_a, employees_in_report)
		self.assertIn(self.emp_b, employees_in_report)
		self.assertNotIn(self.emp_c, employees_in_report)

		row_a = self._row_for(data, self.emp_a)
		self.assertEqual(row_a["gross_pay"], 187500)
		self.assertEqual(row_a["amount"], 6480)  # 540 (Tier I) + 5940 (Tier II)

		row_b = self._row_for(data, self.emp_b)
		self.assertEqual(row_b["gross_pay"], 100000)
		self.assertEqual(row_b["amount"], 6000)  # 540 (Tier I) + 5460 (Tier II)

	def test_employee_with_no_matching_slip_is_excluded(self):
		filters = {"company": self.company, "from_date": self.period_start, "to_date": self.period_end}
		_, data = statutory_component_report(filters, components=["NITA"], amount_label="NITA Amount")
		employees_in_report = {row["employee"] for row in data}
		self.assertNotIn(self.emp_c, employees_in_report)
