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

	if not employees:
		return columns, []

	# One query for every matching slip across the whole roster, then one grouped
	# query for the component amounts, instead of two queries per employee —
	# matters once a client's headcount is in the hundreds, not the two employees
	# this was originally verified against. Behaviour is unchanged: an employee
	# with no slip in range, or a zero summed amount, is still dropped from the
	# report the same way the old per-employee loop dropped them.
	slips = frappe.get_all(
		"Salary Slip",
		filters={
			"employee": ["in", [emp.name for emp in employees]],
			"company": filters.company,
			"docstatus": 1,
			"start_date": [">=", filters.from_date],
			"end_date": ["<=", filters.to_date],
		},
		fields=["name", "employee", "gross_pay"],
	)

	slips_by_employee = {}
	for slip in slips:
		slips_by_employee.setdefault(slip.employee, []).append(slip)

	# Gross pay comes from the Salary Slip itself, not summed off a join against
	# Salary Detail — NSSF alone has two rows (Tier I, Tier II) per slip, and
	# joining would fan out and double-count gross_pay per matching row.
	amount_by_slip = {}
	if slips:
		salary_detail = frappe.qb.DocType("Salary Detail")
		result = (
			frappe.qb.from_(salary_detail)
			.select(salary_detail.parent, Sum(salary_detail.amount))
			.where(
				salary_detail.parent.isin([s.name for s in slips])
				& (salary_detail.parenttype == "Salary Slip")
				& salary_detail.salary_component.isin(components)
			)
			.groupby(salary_detail.parent)
		).run()
		amount_by_slip = {parent: flt(amount) for parent, amount in result}

	data = []
	for emp in employees:
		emp_slips = slips_by_employee.get(emp.name)
		if not emp_slips:
			continue

		gross_pay = sum(flt(s.gross_pay) for s in emp_slips)
		amount = sum(amount_by_slip.get(s.name, 0) for s in emp_slips)
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


def card_type_sums_by_employee(slips, fieldname):
	"""Same aggregation as card_type_sums(), batched across many employees'
	slips in one pair of queries instead of one card_type_sums() call per
	employee — what P10A needs, since it reports a whole company's roster for
	one month rather than one employee's whole year the way P9A does.

	`slips` is a list of dicts/rows with at least "name" and "employee" (e.g.
	straight from frappe.get_all). Returns {employee: {category: amount}}."""
	if not slips:
		return {}

	employee_by_slip = {s["name"]: s["employee"] for s in slips}

	salary_detail = frappe.qb.DocType("Salary Detail")
	salary_component = frappe.qb.DocType("Salary Component")
	card_type_field = salary_component[fieldname]

	rows = (
		frappe.qb.from_(salary_detail)
		.inner_join(salary_component)
		.on(salary_detail.salary_component == salary_component.name)
		.select(salary_detail.parent, card_type_field, Sum(salary_detail.amount))
		.where(
			salary_detail.parent.isin(list(employee_by_slip.keys()))
			& (salary_detail.parenttype == "Salary Slip")
			& (card_type_field != "")
		)
		.groupby(salary_detail.parent, card_type_field)
	).run()

	sums_by_employee = {}
	for slip_name, category, amount in rows:
		if not category:
			continue
		employee = employee_by_slip.get(slip_name)
		bucket = sums_by_employee.setdefault(employee, {})
		bucket[category] = bucket.get(category, 0) + flt(amount)

	return sums_by_employee
