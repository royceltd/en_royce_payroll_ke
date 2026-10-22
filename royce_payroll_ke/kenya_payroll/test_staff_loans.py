# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Staff loans (staff_loans.py, Staff Loan): repayment and interest on the slip, balances
recorded on submit and reversed on cancel, the final slip, write-off, and fringe benefit tax."""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import flt
from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

from royce_payroll_ke.kenya_payroll.report.kenya_fringe_benefit_tax.kenya_fringe_benefit_tax import (
	execute as fbt_report,
)
from royce_payroll_ke.kenya_payroll.staff_loans import INTEREST, REPAYMENT, WRITE_OFF, due, fringe_benefit
from royce_payroll_ke.kenya_payroll.tests.utils import (
	get_test_company,
	make_test_kenya_payroll_rates,
	make_test_payslip,
)


class TestArithmetic(UnitTestCase):
	def test_monthly_repayment_and_interest(self):
		# 12% a year on 20,000 = 200 for the month.
		self.assertEqual(due(20000, 15000, 12), (15000, 200, 0))
		# The last instalment is the balance.
		self.assertEqual(due(5000, 15000, 12), (5000, 50, 0))
		self.assertEqual(due(0, 15000, 12), (0, 0, 0))

	def test_final_slip_and_write_off_take_the_balance(self):
		self.assertEqual(due(40000, 10000, 0, final=True), (40000, 0, 0))
		self.assertEqual(due(40000, 10000, 12, written_off=True), (40000, 0, 40000))

	def test_fringe_benefit(self):
		# 120,000 at 0% against a 15% market rate: 1,500 benefit for the month, 30% tax 450.
		self.assertEqual(fringe_benefit(120000, 0, 15, 30), (1500, 450))
		self.assertEqual(fringe_benefit(120000, 15, 15, 30), (0, 0))
		self.assertEqual(fringe_benefit(0, 0, 15, 30), (0, 0))


class TestStaffLoansOnSlips(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates("1996-01-01")

	def _employee(self, email):
		"""An employee on base 40,000 (gross 50,000) with January 1996 paid."""
		employee, slip = make_test_payslip(
			self.company, self.rates, email, base=40000,
			posting_date="1996-01-31", period_start="1996-01-01", period_end="1996-01-31",
		)
		return employee, slip.salary_structure

	def _loan(self, employee, amount, monthly, start, rate=0, disbursed=None):
		loan = frappe.get_doc(
			{
				"doctype": "Staff Loan", "employee": employee, "loan_amount": amount, "monthly_repayment": monthly,
				"interest_rate": rate, "disbursement_date": disbursed or start, "repayment_start_date": start,
			}
		).insert()
		loan.submit()
		return loan

	def _slip(self, structure, employee, posting_date):
		slip = make_salary_slip(structure, employee=employee, posting_date=posting_date)
		slip.insert()
		return slip

	@staticmethod
	def _row(slip, parentfield, component):
		return sum(flt(r.amount) for r in slip.get(parentfield) if r.salary_component == component)

	def test_repayment_is_recorded_on_submit_and_reversed_on_cancel(self):
		employee, structure = self._employee("loan.basic@example.com")
		loan = self._loan(employee, 30000, 10000, "1996-02-01")
		self.assertEqual((loan.status, flt(loan.outstanding_balance)), ("Active", 30000))

		slip = self._slip(structure, employee, "1996-02-29")
		self.assertEqual(self._row(slip, "deductions", REPAYMENT), 10000)
		self.assertEqual(self._row(slip, "deductions", INTEREST), 0)
		slip.submit()
		loan.reload()
		self.assertEqual((flt(loan.outstanding_balance), flt(loan.total_repaid), len(loan.deductions)), (20000, 10000, 1))

		slip.cancel()
		loan.reload()
		self.assertEqual((flt(loan.outstanding_balance), len(loan.deductions), loan.status), (30000, 0, "Active"))

	def test_interest_and_last_instalment(self):
		employee, structure = self._employee("loan.interest@example.com")
		loan = self._loan(employee, 20000, 15000, "1996-02-01", rate=12)

		february = self._slip(structure, employee, "1996-02-29")
		self.assertEqual((self._row(february, "deductions", REPAYMENT), self._row(february, "deductions", INTEREST)), (15000, 200))
		february.submit()

		march = self._slip(structure, employee, "1996-03-31")
		self.assertEqual((self._row(march, "deductions", REPAYMENT), self._row(march, "deductions", INTEREST)), (5000, 50))
		march.submit()
		loan.reload()
		self.assertEqual((loan.status, flt(loan.outstanding_balance), flt(loan.total_interest)), ("Repaid", 0, 250))

		april = self._slip(structure, employee, "1996-04-30")
		self.assertEqual(self._row(april, "deductions", REPAYMENT), 0)

	def test_final_slip_recovers_what_net_pay_allows(self):
		employee, structure = self._employee("loan.leaver@example.com")
		loan = self._loan(employee, 100000, 5000, "1996-02-01")
		frappe.db.set_value("Employee", employee, "relieving_date", "1996-02-29")

		final = self._slip(structure, employee, "1996-02-29")
		recovered = self._row(final, "deductions", REPAYMENT)
		self.assertGreater(recovered, 5000)
		self.assertLess(recovered, 50000)
		self.assertAlmostEqual(flt(final.net_pay), 0, places=0)
		final.submit()
		loan.reload()
		self.assertEqual(flt(loan.outstanding_balance), flt(100000 - recovered, 2))
		self.assertEqual(loan.status, "Active")

	def test_write_off_is_taxed_and_clears_the_loan(self):
		employee, structure = self._employee("loan.writeoff@example.com")
		loan = self._loan(employee, 30000, 10000, "1996-02-01")
		february = self._slip(structure, employee, "1996-02-29")
		february.submit()

		with self.assertRaises(frappe.ValidationError):
			loan.write_off("1996-02-15")  # inside a period already deducted
		loan.write_off("1996-03-15")

		march = self._slip(structure, employee, "1996-03-31")
		self.assertEqual(self._row(march, "earnings", WRITE_OFF), 20000)
		self.assertEqual(self._row(march, "deductions", REPAYMENT), 20000)
		self.assertEqual(flt(march.gross_pay), 70000)
		self.assertEqual(flt(march.royce_taxable_cash_pay), 70000)
		# Net pay is the salary's, less the tax and levies on the 20,000 benefit.
		self.assertLess(flt(march.net_pay), flt(february.net_pay) + 10000)
		march.submit()
		loan.reload()
		self.assertEqual((loan.status, flt(loan.outstanding_balance)), ("Written Off", 0))

	def test_monthly_repayment_can_be_changed_after_deductions(self):
		employee, structure = self._employee("loan.change@example.com")
		loan = self._loan(employee, 30000, 10000, "1996-02-01")
		self._slip(structure, employee, "1996-02-29").submit()
		loan.reload()
		loan.monthly_repayment = 4000
		loan.save()
		self.assertEqual(self._row(self._slip(structure, employee, "1996-03-31"), "deductions", REPAYMENT), 4000)

	def test_loan_with_deductions_cannot_be_cancelled(self):
		employee, structure = self._employee("loan.cancel@example.com")
		loan = self._loan(employee, 30000, 10000, "1996-02-01")
		self._slip(structure, employee, "1996-02-29").submit()
		loan.reload()
		with self.assertRaises(frappe.ValidationError):
			loan.cancel()

	def test_monthly_repayment_from_months(self):
		employee, _structure = self._employee("loan.months@example.com")
		loan = frappe.get_doc(
			{
				"doctype": "Staff Loan", "employee": employee, "loan_amount": 25000, "repayment_months": 3,
				"disbursement_date": "1996-02-01", "repayment_start_date": "1996-02-01",
			}
		).insert()
		self.assertEqual(flt(loan.monthly_repayment), 8334)
		self.assertEqual(loan.company, self.company)


class TestFringeBenefitTaxReport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates("1997-01-01")

	def test_loans_below_the_market_rate(self):
		employee, _slip = make_test_payslip(
			self.company, self.rates, "loan.fbt@example.com", base=40000,
			posting_date="1997-01-31", period_start="1997-01-01", period_end="1997-01-31",
		)
		for rate in (0, 20):
			frappe.get_doc(
				{
					"doctype": "Staff Loan", "employee": employee, "loan_amount": 120000, "monthly_repayment": 10000,
					"interest_rate": rate, "disbursement_date": "1997-02-01", "repayment_start_date": "1997-03-01",
				}
			).insert().submit()

		filters = {"company": self.company, "month": "1997-02-10"}
		_columns, data, message = fbt_report(filters)
		self.assertEqual(data, [])
		self.assertIn("market interest rate", message)

		frappe.get_doc(
			{
				"doctype": "Kenya FBT Market Rate", "parent": "Kenya Payroll Settings",
				"parenttype": "Kenya Payroll Settings", "parentfield": "fbt_market_rates",
				"from_date": "1997-01-01", "market_rate": 15,
			}
		).db_insert()
		_columns, data = fbt_report(filters)
		self.assertEqual(len(data), 1)  # the 20% loan is above the market rate
		row = data[0]
		self.assertEqual(
			(row["outstanding"], row["loan_rate"], row["market_rate"], row["fringe_benefit"], row["fbt"]),
			(120000, 0, 15, 1500, 450),
		)
		self.assertEqual(row["kra_pin"], "A123456789B")
