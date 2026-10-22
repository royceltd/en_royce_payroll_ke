# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Fringe benefit tax on staff loans for one month (Income Tax Act s.12B): one row per loan
at a rate below KRA's market interest rate, with the columns of Sheet D of KRA's simplified
PAYE return (PIN, loan account, loan amount, outstanding, loan rate, market rate) and the
benefit and tax. The employer pays the tax with the month's PAYE, by the 9th."""

import frappe
from frappe import _
from frappe.utils import get_first_day, get_last_day, getdate

from royce_payroll_ke.kenya_payroll.staff_loans import fbt_rate, fringe_benefit, market_rate, month_balance


def get_columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 130},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 170},
		{"label": _("KRA PIN"), "fieldname": "kra_pin", "fieldtype": "Data", "width": 120},
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Staff Loan", "width": 140},
		{"label": _("Loan Amount"), "fieldname": "loan_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Currency", "width": 120},
		{"label": _("Loan Rate %"), "fieldname": "loan_rate", "fieldtype": "Percent", "width": 100},
		{"label": _("Market Rate %"), "fieldname": "market_rate", "fieldtype": "Percent", "width": 110},
		{"label": _("Fringe Benefit"), "fieldname": "fringe_benefit", "fieldtype": "Currency", "width": 120},
		{"label": _("Fringe Benefit Tax"), "fieldname": "fbt", "fieldtype": "Currency", "width": 130},
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))
	if not filters.get("month"):
		frappe.throw(_("Month is required"))

	month = getdate(filters.month)
	start, end = get_first_day(month), get_last_day(month)
	rate = market_rate(start)
	if rate is None:
		return get_columns(), [], _(
			"No KRA market interest rate for {0} in Kenya Payroll Settings. Add the rate for the quarter first."
		).format(frappe.format(start, "Date"))

	tax_rate = fbt_rate()
	loans = frappe.get_all(
		"Staff Loan",
		filters={"company": filters.company, "docstatus": 1, "disbursement_date": ["<=", end]},
		fields=["name", "employee", "employee_name", "loan_amount", "interest_rate"],
		order_by="employee_name asc, disbursement_date asc",
	)
	pins = dict(
		frappe.get_all(
			"Employee", filters={"name": ["in", list({loan.employee for loan in loans}) or [""]]},
			fields=["name", "royce_kra_pin"], as_list=True,
		)
	)

	data = []
	for loan in loans:
		outstanding = month_balance(loan, start)
		benefit, tax = fringe_benefit(outstanding, loan.interest_rate, rate, tax_rate)
		if not benefit:
			continue
		data.append(
			{
				"employee": loan.employee,
				"employee_name": loan.employee_name,
				"kra_pin": pins.get(loan.employee),
				"loan": loan.name,
				"loan_amount": loan.loan_amount,
				"outstanding": outstanding,
				"loan_rate": loan.interest_rate,
				"market_rate": rate,
				"fringe_benefit": benefit,
				"fbt": tax,
			}
		)
	return get_columns(), data
