# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Payroll Variance and Payroll Register, against two real months of slips:
January and February 1986, four employees:
  steady  - same pay both months
  raise   - base 50,000 -> 60,000 in February
  joiner  - February only
  leaver  - January only
"""

import frappe
from frappe.tests import IntegrationTestCase

from royce_payroll_ke.kenya_payroll.report.kenya_payroll_register import kenya_payroll_register
from royce_payroll_ke.kenya_payroll.report.kenya_payroll_variance import kenya_payroll_variance
from royce_payroll_ke.kenya_payroll.tests.utils import (
	get_test_company,
	make_test_kenya_payroll_rates,
	make_test_payslip,
)

JAN = ("1986-01-01", "1986-01-31")
FEB = ("1986-02-01", "1986-02-28")


class TestPayrollReviewReports(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company("Royce Payroll Review Co", "RPRC")
		rates = make_test_kenya_payroll_rates("1986-01-01")

		def slip(email, base, period):
			employee, _doc = make_test_payslip(
				cls.company, rates, email, base=base,
				posting_date=period[1], period_start=period[0], period_end=period[1],
			)
			return employee

		cls.steady = slip("review.steady@example.com", 40000, JAN)
		slip("review.steady@example.com", 40000, FEB)
		cls.raised = slip("review.raise@example.com", 50000, JAN)
		slip("review.raise@example.com", 60000, FEB)
		cls.leaver = slip("review.leaver@example.com", 30000, JAN)
		cls.joiner = slip("review.joiner@example.com", 35000, FEB)

	def variance(self, **filters):
		columns, data, _message, _chart, summary = kenya_payroll_variance.execute(
			{"company": self.company, "month": FEB[0], **filters}
		)
		return columns, {row["employee"]: row for row in data}, summary

	def test_statuses(self):
		_columns, rows, _summary = self.variance(show_unchanged=1)
		self.assertEqual(rows[self.steady]["status"], "No change")
		self.assertEqual(rows[self.raised]["status"], "Changed")
		self.assertEqual(rows[self.joiner]["status"], "New")
		self.assertEqual(rows[self.leaver]["status"], "Left")

	def test_unchanged_hidden_by_default(self):
		_columns, rows, _summary = self.variance()
		self.assertNotIn(self.steady, rows)
		self.assertEqual(len(rows), 3)

	def test_what_changed_for_a_pay_rise(self):
		_columns, rows, _summary = self.variance()
		row = rows[self.raised]
		# Base 50,000 -> 60,000: Basic +10,000, House (15%) +1,500, Transport (10%) +1,000.
		self.assertEqual(row["gross_change"], 12500)
		self.assertIn("Basic Salary +10,000", row["changes"])
		self.assertIn("House Allowance +1,500", row["changes"])
		self.assertIn("PAYE +", row["changes"])
		self.assertEqual(row["net_change"], row["current_net"] - row["previous_net"])

	def test_summary(self):
		_columns, _rows, summary = self.variance()
		values = {s["label"]: s["value"] for s in summary}
		self.assertEqual(values["Employees paid"], 3)
		self.assertEqual(values["Joined"], 1)
		self.assertEqual(values["Left"], 1)

	def test_compare_with_the_same_month_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.variance(compare_month=FEB[1])

	def test_register(self):
		columns, data = kenya_payroll_register.execute({"company": self.company, "month": FEB[0]})
		fieldnames = [c["fieldname"] for c in columns]
		rows = {r["employee"]: r for r in data}
		self.assertEqual(set(rows), {self.steady, self.raised, self.joiner})

		# Earnings, then gross; deductions, then totals; employer contributions last.
		for later, earlier in (
			("gross_pay", "e_basic_salary"),
			("d_paye", "gross_pay"),
			("net_pay", "d_paye"),
			("c_nssf_employer", "net_pay"),
		):
			self.assertLess(fieldnames.index(earlier), fieldnames.index(later))

		row = rows[self.raised]
		self.assertEqual(row["e_basic_salary"], 60000)
		self.assertEqual(row["gross_pay"], 75000)
		self.assertEqual(
			row["net_pay"],
			row["gross_pay"] - sum(v for k, v in row.items() if k.startswith("d_")),
		)
		self.assertEqual(row["employer_total"], sum(v for k, v in row.items() if k.startswith("c_")))
		self.assertTrue(row["taxable_pay"])
