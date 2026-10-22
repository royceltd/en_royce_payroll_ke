# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Staff loans through payroll (v16.8.0): the monthly repayment and interest on each slip,
the balance on the Staff Loan, write-off as a taxable benefit, and fringe benefit tax.

A light alternative to Frappe Lending (not adopted: a whole lending app for what an SME
payroll officer does with a spreadsheet). Salary advances stay on HRMS's Employee Advance.

- Each slip from a Kenya Payroll structure deducts, for every active loan of the employee:
  the monthly repayment (capped at the balance), and interest on the balance at the loan's
  rate. A leaver's final slip deducts the whole balance, as far as net pay allows. A slip
  covering the loan's Write Off date clears the balance and adds it back as a taxable
  earning (Staff Loan Write-off), so net pay is unchanged and PAYE is charged on it.
- Amounts are recalculated on every save of a draft slip; a slip's deductions are recorded
  on the loan only when it is submitted, and removed when it is cancelled.
- Fringe benefit tax (Income Tax Act s.12B) is the employer's: fringe_benefit() and the
  Kenya Fringe Benefit Tax report. Nothing is posted.

Two layers, as in engine.py: due() and fringe_benefit() are pure arithmetic; the rest
reads and writes documents.
"""

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate

REPAYMENT = "Staff Loan Repayment"
INTEREST = "Staff Loan Interest"
WRITE_OFF = "Staff Loan Write-off"


@dataclass
class Due:
	loan: str
	principal: float = 0
	interest: float = 0
	write_off: float = 0


def due(balance, monthly_repayment, interest_rate, final=False, written_off=False) -> tuple:
	"""(principal, interest, write_off) for one loan on one slip. Interest is a month's at the
	yearly rate on the balance before this month's repayment, in whole shillings; none is
	charged in the month a loan is written off."""
	balance = flt(balance, 2)
	if balance <= 0:
		return 0.0, 0.0, 0.0
	if written_off:
		return balance, 0.0, balance
	principal = balance if final else min(flt(monthly_repayment, 2), balance)
	interest = flt(round(balance * flt(interest_rate) / 100 / 12))
	return principal, interest, 0.0


def fringe_benefit(balance, loan_rate, market_rate, fbt_rate) -> tuple:
	"""(fringe benefit, fringe benefit tax) for one loan for one month: the interest at the
	market rate the employee didn't pay, and the employer's tax on it."""
	gap = flt(market_rate) - flt(loan_rate)
	if gap <= 0 or flt(balance) <= 0:
		return 0.0, 0.0
	benefit = flt(flt(balance) * gap / 100 / 12, 2)
	return benefit, flt(benefit * flt(fbt_rate) / 100, 2)


# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------


def balance(loan, before_slip=None, before_date=None) -> float:
	"""Outstanding principal from the deductions recorded on the loan (submitted slips),
	leaving out `before_slip`'s own and, with `before_date`, any for a later period."""
	filters = {"parent": loan.name, "parenttype": "Staff Loan"}
	if before_slip:
		filters["salary_slip"] = ["!=", before_slip]
	if before_date:
		filters["period_start"] = ["<", before_date]
	repaid = frappe.get_all("Staff Loan Deduction", filters=filters, pluck="principal")
	return flt(flt(loan.loan_amount) - sum(flt(p) for p in repaid), 2)


def active_loans(employee, on_date):
	"""Submitted, active loans of `employee` whose repayment has started by `on_date`, oldest
	first (repaid in that order when net pay doesn't cover them all)."""
	return frappe.get_all(
		"Staff Loan",
		filters={
			"employee": employee,
			"docstatus": 1,
			"status": "Active",
			"repayment_start_date": ["<=", on_date],
		},
		fields=["name", "loan_amount", "monthly_repayment", "interest_rate", "write_off_date"],
		order_by="disbursement_date asc, creation asc",
	)


def dues(slip) -> list[Due]:
	from royce_payroll_ke.kenya_payroll.compliance import is_final_slip

	final = is_final_slip(slip)
	result = []
	for loan in active_loans(slip.employee, slip.end_date):
		written_off = bool(loan.write_off_date and getdate(loan.write_off_date) <= getdate(slip.end_date))
		principal, interest, write_off = due(
			balance(loan, before_slip=slip.name), loan.monthly_repayment, loan.interest_rate, final, written_off
		)
		if principal or interest:
			result.append(Due(loan.name, principal, interest, write_off))
	return result


def has_loans(employee) -> bool:
	return bool(employee and frappe.db.exists("Staff Loan", {"employee": employee, "docstatus": 1}))


def update_loan(loan_name):
	"""Totals and status from the recorded deductions."""
	loan = frappe.get_doc("Staff Loan", loan_name)
	repaid = sum(flt(d.principal) for d in loan.deductions)
	interest = sum(flt(d.interest) for d in loan.deductions)
	outstanding = flt(flt(loan.loan_amount) - repaid, 2)
	if loan.docstatus == 2:
		status = "Cancelled"
	elif any(d.write_off for d in loan.deductions):
		status = "Written Off"
	elif outstanding <= 0:
		status = "Repaid"
	else:
		status = "Active"
	loan.db_set(
		{"total_repaid": repaid, "total_interest": interest, "outstanding_balance": outstanding, "status": status}
	)


# ---------------------------------------------------------------------------
# Salary Slip
# ---------------------------------------------------------------------------


def apply_to_slip(slip, set_row):
	"""Called by engine.apply_kenya_statutory before the statutory amounts, so a write-off
	is taxed. `set_row` is the engine's row writer. Employees without a Staff Loan are left
	alone (a client may still deduct loans through Additional Salary)."""
	if not has_loans(slip.employee):
		return
	items = dues(slip)
	set_row(slip, "deductions", REPAYMENT, flt(sum(d.principal for d in items), 2))
	set_row(slip, "deductions", INTEREST, flt(sum(d.interest for d in items), 2))
	write_off = flt(sum(d.write_off for d in items), 2)
	had_write_off = any(r.salary_component == WRITE_OFF and not r.get("additional_salary") for r in slip.earnings)
	set_row(slip, "earnings", WRITE_OFF, write_off)
	if write_off or had_write_off:
		# HRMS added up gross pay before the regional hook; the write-off is pay too.
		slip.gross_pay = slip.get_component_totals("earnings", depends_on_payment_days=1)
		slip.base_gross_pay = flt(flt(slip.gross_pay) * flt(slip.exchange_rate), slip.precision("base_gross_pay"))


def cap_final_recovery(slip):
	"""On a leaver's final slip the whole balance is deducted, but net pay can't go below
	zero (HRMS refuses the slip). Reduce the repayment to what the pay covers; the rest
	stays on the loan to recover another way. Called after the statutory amounts."""
	from royce_payroll_ke.kenya_payroll.compliance import is_final_slip

	if not has_loans(slip.employee) or not is_final_slip(slip):
		return
	row = next(
		(r for r in slip.deductions if r.salary_component == REPAYMENT and not r.get("additional_salary")), None
	)
	if not row:
		return
	deductions = sum(flt(r.amount) for r in slip.deductions if not r.do_not_include_in_total)
	shortfall = deductions + flt(slip.get("total_loan_repayment")) - flt(slip.gross_pay)
	if shortfall > 0:
		write_off = sum(d.write_off for d in dues(slip))
		amount = max(flt(write_off, 2), flt(flt(row.amount) - shortfall, 2))
		row.amount = row.default_amount = amount


def _slip_amount(slip, parentfield, component):
	return flt(
		sum(
			flt(r.amount)
			for r in slip.get(parentfield) or []
			if r.salary_component == component and not r.get("additional_salary")
		),
		2,
	)


def record_slip(doc, method=None):
	"""Salary Slip on_submit: record what the slip deducted on each loan. The amounts are
	worked out again and must match the slip's rows; if another slip changed a balance in
	between, the slip has to be recalculated (saved again) first."""
	if not has_loans(doc.employee):
		return
	from royce_payroll_ke.kenya_payroll.engine import is_kenya_structure

	if not is_kenya_structure(doc.salary_structure):
		return

	items = dues(doc)
	principal = _slip_amount(doc, "deductions", REPAYMENT)
	interest = _slip_amount(doc, "deductions", INTEREST)
	write_off = _slip_amount(doc, "earnings", WRITE_OFF)
	expected_write_off = flt(sum(d.write_off for d in items), 2)
	if (
		abs(interest - flt(sum(d.interest for d in items), 2)) > 0.01
		or abs(write_off - expected_write_off) > 0.01
		or principal - flt(sum(d.principal for d in items), 2) > 0.01
		or principal < expected_write_off - 0.01
	):
		frappe.throw(
			_("The staff loan balances for {0} changed after this slip was calculated. Save the slip again, then submit it.").format(
				frappe.bold(doc.employee_name or doc.employee)
			),
			title=_("Staff loan changed"),
		)

	# Written-off loans are cleared in full; what's left of the repayment goes to the other
	# loans oldest first (less than due only on a final slip capped at net pay).
	remaining = flt(principal - expected_write_off, 2)
	for item in items:
		if item.write_off:
			paid = item.principal
		else:
			paid = min(item.principal, remaining)
			remaining = flt(remaining - paid, 2)
		if not paid and not item.interest:
			continue
		frappe.get_doc(
			{
				"doctype": "Staff Loan Deduction",
				"parent": item.loan,
				"parenttype": "Staff Loan",
				"parentfield": "deductions",
				"docstatus": 1,
				"idx": frappe.db.count("Staff Loan Deduction", {"parent": item.loan}) + 1,
				"salary_slip": doc.name,
				"period_start": doc.start_date,
				"period_end": doc.end_date,
				"principal": paid,
				"interest": item.interest,
				"write_off": 1 if item.write_off else 0,
			}
		).db_insert()
		update_loan(item.loan)


def reverse_slip(doc, method=None):
	"""Salary Slip on_cancel: take the slip's deductions off its loans."""
	loans = frappe.get_all(
		"Staff Loan Deduction", filters={"salary_slip": doc.name, "parenttype": "Staff Loan"}, pluck="parent"
	)
	if not loans:
		return
	frappe.db.delete("Staff Loan Deduction", {"salary_slip": doc.name, "parenttype": "Staff Loan"})
	for loan in set(loans):
		update_loan(loan)


# ---------------------------------------------------------------------------
# Fringe benefit tax
# ---------------------------------------------------------------------------


def market_rate(on_date):
	"""KRA's market interest rate in force on `on_date` (Kenya Payroll Settings), or None."""
	rows = frappe.get_all(
		"Kenya FBT Market Rate",
		filters={"parent": "Kenya Payroll Settings", "from_date": ["<=", on_date]},
		fields=["market_rate"],
		order_by="from_date desc",
		limit=1,
	)
	return flt(rows[0].market_rate) if rows else None


def fbt_rate():
	"""The settings' rate, or 30% (corporation tax) when it was never saved: a Single
	returns 0 for an unsaved Percent, and FBT is never charged at 0%."""
	return flt(frappe.db.get_single_value("Kenya Payroll Settings", "fbt_rate")) or 30.0


def month_balance(loan, month_start):
	"""The balance the month's fringe benefit is charged on: the principal outstanding
	during the month, before the month's own repayment (deductions for earlier periods
	only). A loan disbursed in the month counts in full."""
	return balance(loan, before_date=get_first_day(month_start))
