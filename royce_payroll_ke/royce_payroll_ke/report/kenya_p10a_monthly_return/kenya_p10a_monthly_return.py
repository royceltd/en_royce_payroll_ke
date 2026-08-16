# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate

from royce_payroll_ke.royce_payroll_ke.doctype.payroll_rates.payroll_rates import PayrollRates
from royce_payroll_ke.royce_payroll_ke.report_utils import card_type_sums

# Guide section 10.2's P10A card-type mapping, grouped the way the actual iTax
# return groups them. Generic against whatever's tagged, not a hardcoded
# component list — a future allowance shows up here automatically as long as
# it's tagged with the right P10A card type on the Salary Component.
CASH_CATEGORIES = [
	"Basic Salary",
	"Housing Allowance",
	"Transport Allowance",
	"Leave Pay",
	"Overtime",
	"Directors Fee",
	"Other Allowance",
]
NON_CASH_CATEGORIES = ["Value of Car Benefit", "Other Non Cash Benefits", "Amount of Benefit"]
OTHER_CASH_CATEGORIES = ["Leave Pay", "Overtime", "Directors Fee", "Other Allowance"]


def get_columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 170},
		{"label": _("KRA PIN"), "fieldname": "kra_pin", "fieldtype": "Data", "width": 110},
		{"label": _("National ID"), "fieldname": "national_id", "fieldtype": "Data", "width": 110},
		{"label": _("Basic Salary"), "fieldname": "basic_salary", "fieldtype": "Currency", "width": 120},
		{"label": _("Housing Allowance"), "fieldname": "housing_allowance", "fieldtype": "Currency", "width": 130},
		{"label": _("Transport Allowance"), "fieldname": "transport_allowance", "fieldtype": "Currency", "width": 140},
		{"label": _("Other Allowance"), "fieldname": "other_allowance", "fieldtype": "Currency", "width": 120},
		{"label": _("Total Cash Pay"), "fieldname": "total_cash_pay", "fieldtype": "Currency", "width": 130},
		{"label": _("Total Non-Cash Pay"), "fieldname": "total_non_cash_pay", "fieldtype": "Currency", "width": 140},
		{"label": _("Global Income"), "fieldname": "global_income", "fieldtype": "Currency", "width": 130},
		{
			"label": _("Actual Contribution (NSSF)"),
			"fieldname": "nssf_actual_contribution",
			"fieldtype": "Currency",
			"width": 170,
		},
		{"label": _("SHIF"), "fieldname": "shif", "fieldtype": "Currency", "width": 110},
		{"label": _("Affordable Housing Levy"), "fieldname": "housing_levy", "fieldtype": "Currency", "width": 160},
		{"label": _("Monthly Personal Relief"), "fieldname": "personal_relief", "fieldtype": "Currency", "width": 150},
		{"label": _("PAYE Tax"), "fieldname": "paye_tax", "fieldtype": "Currency", "width": 110},
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))
	if not filters.get("month"):
		frappe.throw(_("Month is required"))

	month_date = getdate(filters.month)
	month_start, month_end = get_first_day(month_date), get_last_day(month_date)

	employee_filter = {"company": filters.company, "status": "Active"}
	if filters.get("employee"):
		employee_filter = {"name": filters.employee}
	employees = frappe.get_all(
		"Employee",
		filters=employee_filter,
		fields=["name", "employee_name", "royce_kra_pin", "royce_national_id"],
		order_by="employee_name",
	)

	# Personal relief isn't on any component — it's applied as a tax credit
	# inside the PAYE formula, not deducted from taxable income (guide section
	# 6.7) — so the return declares it from Payroll Rates directly, not from a
	# tagged Salary Detail row.
	rates_name = PayrollRates.get_effective(month_end)
	personal_relief = flt(frappe.db.get_value("Payroll Rates", rates_name, "personal_relief")) if rates_name else 0

	data = []
	for emp in employees:
		slips = frappe.get_all(
			"Salary Slip",
			filters={
				"employee": emp.name,
				"company": filters.company,
				"docstatus": 1,
				"start_date": [">=", month_start],
				"end_date": ["<=", month_end],
			},
			pluck="name",
		)
		if not slips:
			continue

		sums = card_type_sums(slips, "royce_p10a_tax_deduction_card_type")
		if not sums:
			continue

		total_cash = sum(flt(sums.get(c)) for c in CASH_CATEGORIES)
		total_non_cash = sum(flt(sums.get(c)) for c in NON_CASH_CATEGORIES)
		other_allowance = sum(flt(sums.get(c)) for c in OTHER_CASH_CATEGORIES)

		data.append(
			{
				"employee": emp.name,
				"employee_name": emp.employee_name,
				"kra_pin": emp.royce_kra_pin,
				"national_id": emp.royce_national_id,
				"basic_salary": flt(sums.get("Basic Salary")),
				"housing_allowance": flt(sums.get("Housing Allowance")),
				"transport_allowance": flt(sums.get("Transport Allowance")),
				"other_allowance": other_allowance,
				"total_cash_pay": total_cash,
				"total_non_cash_pay": total_non_cash,
				"global_income": total_cash + total_non_cash,
				"nssf_actual_contribution": flt(sums.get("Actual Contribution")),
				"shif": flt(sums.get("SHIF")),
				"housing_levy": flt(sums.get("Affordable Housing Levy")),
				"personal_relief": personal_relief,
				"paye_tax": flt(sums.get("PAYE Tax")),
			}
		)

	return get_columns(), data
