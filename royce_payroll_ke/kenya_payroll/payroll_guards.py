# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Guards against two payroll mistakes that leave the books wrong without any error.

1. A Salary Slip created by a Payroll Entry, submitted from the slip's own form.
   HRMS posts the accrual Journal Entry (salary expense, PAYE/NSSF/SHIF/Housing
   Levy payables, Payroll Payable) only from the Payroll Entry's "Submit Salary
   Slip" button (hrms submit_salary_slips_for_employees -> make_accrual_jv_entry).
   A slip submitted on its own is marked Submitted but never reaches the accounts,
   and the button can't fix it afterwards because it only picks up draft slips.
   Found on portal.royceerp.com 2026-10-04: July's payroll (79,650) was missing
   from the chart of accounts. So: refuse it, and say what to do instead.

2. A Payroll Entry whose Posting Date is outside its pay period. The accrual is
   dated on the Posting Date, so March's salaries posted on 4 October land in
   October's profit and loss. Warn (don't block: some businesses deliberately
   post on pay day).
"""

import frappe
from frappe import _
from frappe.utils import formatdate, get_link_to_form, getdate


def block_slip_submit_outside_payroll_entry(doc, method=None):
	"""Salary Slip before_submit."""
	if not doc.get("payroll_entry") or frappe.flags.via_payroll_entry or frappe.flags.in_patch:
		return

	frappe.throw(
		_(
			"This salary slip belongs to Payroll Entry {0}. Submit it from the payroll entry with "
			"<b>Submit Salary Slip</b>, so the salary, PAYE, NSSF, SHIF and Housing Levy amounts are "
			"posted to the accounts. Submitting it here would mark it paid without any accounting entry."
		).format(get_link_to_form("Payroll Entry", doc.payroll_entry)),
		title=_("Submit from the Payroll Entry"),
	)


def warn_posting_date_outside_period(doc, method=None):
	"""Payroll Entry validate (drafts only)."""
	if doc.docstatus != 0 or not (doc.posting_date and doc.start_date and doc.end_date):
		return

	posting, start, end = getdate(doc.posting_date), getdate(doc.start_date), getdate(doc.end_date)
	if start <= posting <= end:
		return

	frappe.msgprint(
		_(
			"The Posting Date {0} is outside the pay period {1} to {2}. The salary costs will be "
			"recorded on {0}, so they will show in that month's profit and loss, not the pay period's. "
			"To record them in the pay period, set the Posting Date to {2}."
		).format(formatdate(posting), formatdate(start), formatdate(end)),
		title=_("Posting Date outside the pay period"),
		indicator="orange",
	)
