# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Shared query logic for the single-component statutory reports (NSSF, SHIF,
Housing Levy) — structurally identical: sum one or two components per employee
over a period, with the employee's identifying numbers alongside. Written once
here rather than three times per report, so there's one place to get it right."""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt


def statutory_component_report(filters, components, amount_label, id_fieldname=None, id_label=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required"))

	employee_filter = {"company": filters.company, "status": "Active"}
	if filters.get("employee"):
		employee_filter = {"name": filters.employee}

	employee_fields = ["name", "employee_name", "royce_national_id", "royce_kra_pin"]
	if id_fieldname:
		employee_fields.append(id_fieldname)
	employees = frappe.get_all(
		"Employee", filters=employee_filter, fields=employee_fields, order_by="employee_name"
	)

	columns = [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("National ID"), "fieldname": "national_id", "fieldtype": "Data", "width": 120},
		{"label": _("KRA PIN"), "fieldname": "kra_pin", "fieldtype": "Data", "width": 120},
	]
	if id_fieldname:
		columns.append({"label": _(id_label), "fieldname": "id_no", "fieldtype": "Data", "width": 120})
	columns += [
		{"label": _("Gross Pay"), "fieldname": "gross_pay", "fieldtype": "Currency", "width": 130},
		{"label": _(amount_label), "fieldname": "amount", "fieldtype": "Currency", "width": 130},
	]

	data = []
	for emp in employees:
		slips = frappe.get_all(
			"Salary Slip",
			filters={
				"employee": emp.name,
				"company": filters.company,
				"docstatus": 1,
				"start_date": [">=", filters.from_date],
				"end_date": ["<=", filters.to_date],
			},
			fields=["name", "gross_pay"],
		)
		if not slips:
			continue

		# Gross pay comes from the Salary Slip itself, not summed off a join against
		# Salary Detail — NSSF alone has two rows (Tier I, Tier II) per slip, and
		# joining would fan out and double-count gross_pay per matching row.
		gross_pay = sum(flt(s.gross_pay) for s in slips)

		salary_detail = frappe.qb.DocType("Salary Detail")
		slip_names = [s.name for s in slips]
		result = (
			frappe.qb.from_(salary_detail)
			.select(Sum(salary_detail.amount))
			.where(
				salary_detail.parent.isin(slip_names)
				& (salary_detail.parenttype == "Salary Slip")
				& salary_detail.salary_component.isin(components)
			)
		).run()
		amount = flt(result[0][0]) if result and result[0][0] else 0
		if not amount:
			continue

		row = {
			"employee": emp.name,
			"employee_name": emp.employee_name,
			"national_id": emp.royce_national_id,
			"kra_pin": emp.royce_kra_pin,
			"gross_pay": gross_pay,
			"amount": amount,
		}
		if id_fieldname:
			row["id_no"] = emp.get(id_fieldname)
		data.append(row)

	return columns, data


def card_type_sums(slip_names, fieldname):
	"""Sum Salary Detail amounts per classification category across one or more
	Salary Slips. `fieldname` is 'royce_p9a_tax_deduction_card_type' or
	'royce_p10a_tax_deduction_card_type' — whichever KRA return this is for.
	Returns {category: amount}, generic over whatever's actually tagged rather
	than a hardcoded component list, so a future component (a new allowance, a
	benefit-in-kind) shows up correctly without the report itself changing —
	same pattern proven compatible against csf_ke's own P9A implementation."""
	if not slip_names:
		return {}

	salary_detail = frappe.qb.DocType("Salary Detail")
	salary_component = frappe.qb.DocType("Salary Component")
	card_type_field = salary_component[fieldname]

	rows = (
		frappe.qb.from_(salary_detail)
		.inner_join(salary_component)
		.on(salary_detail.salary_component == salary_component.name)
		.select(card_type_field, Sum(salary_detail.amount))
		.where(
			salary_detail.parent.isin(slip_names)
			& (salary_detail.parenttype == "Salary Slip")
			& (card_type_field != "")
		)
		.groupby(card_type_field)
	).run()

	return {row[0]: flt(row[1]) for row in rows if row[0]}
