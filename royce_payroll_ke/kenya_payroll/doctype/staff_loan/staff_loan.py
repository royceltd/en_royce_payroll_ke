# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""A loan to an employee, repaid through payroll. The arithmetic and the slip side are in
kenya_payroll/staff_loans.py."""

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_first_day, getdate

from royce_payroll_ke.kenya_payroll.staff_loans import update_loan


class StaffLoan(Document):
	def validate(self):
		if flt(self.loan_amount) <= 0:
			frappe.throw(_("Loan Amount must be more than zero."))
		if flt(self.interest_rate) < 0 or flt(self.interest_rate) > 100:
			frappe.throw(_("Interest Rate must be between 0 and 100% a year."))
		if not flt(self.monthly_repayment) and self.repayment_months:
			if self.repayment_months < 1:
				frappe.throw(_("Repayment Months must be at least 1."))
			self.monthly_repayment = math.ceil(flt(self.loan_amount) / self.repayment_months)
		if flt(self.monthly_repayment) <= 0:
			frappe.throw(_("Enter the Monthly Repayment, or the Repayment Months to work it out."))
		if flt(self.monthly_repayment) > flt(self.loan_amount):
			self.monthly_repayment = self.loan_amount
		if getdate(self.repayment_start_date) < get_first_day(self.disbursement_date):
			frappe.throw(_("Repayment can't start before the month the loan is disbursed."))
		self.outstanding_balance = self.loan_amount
		self.status = "Draft"

	def before_update_after_submit(self):
		if flt(self.monthly_repayment) <= 0:
			frappe.throw(_("Monthly Repayment must be more than zero."))

	def on_submit(self):
		self.db_set({"status": "Active", "outstanding_balance": self.loan_amount})

	def before_cancel(self):
		if self.deductions:
			frappe.throw(
				_("Salary slips have already deducted repayments on this loan. Cancel those slips first: {0}").format(
					", ".join(sorted({d.salary_slip for d in self.deductions}))
				)
			)

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	@frappe.whitelist()
	def write_off(self, write_off_date):
		"""Mark the loan to be written off: the salary slip covering `write_off_date` clears
		the balance and pays it as a taxable benefit."""
		self.check_permission("submit")
		if self.docstatus != 1 or self.status != "Active":
			frappe.throw(_("Only an active loan can be written off."))
		# From the database: slips record their deductions directly, not through this doc.
		ends = frappe.get_all("Staff Loan Deduction", filters={"parent": self.name}, pluck="period_end")
		last = max((getdate(d) for d in ends), default=None)
		if last and getdate(write_off_date) <= last:
			frappe.throw(
				_("Choose a date after the last salary slip that deducted a repayment ({0}).").format(
					frappe.format(last, "Date")
				)
			)
		self.db_set("write_off_date", write_off_date)
		self.add_comment("Info", _("To be written off on {0}").format(frappe.format(getdate(write_off_date), "Date")))

	@frappe.whitelist()
	def cancel_write_off(self):
		self.check_permission("submit")
		if self.status != "Active":
			frappe.throw(_("The write-off has already been made by a salary slip. Cancel that slip to undo it."))
		self.db_set("write_off_date", None)
		update_loan(self.name)
