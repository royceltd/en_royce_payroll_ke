# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Payroll Register: the month's payroll, one row per employee, with their statutory
numbers, every earning, deduction and employer contribution in its own column, and the
totals. The sheet accountants and auditors ask for; columns follow whatever components
the month's slips actually used."""

import frappe
from frappe import _
from frappe.utils import getdate

from royce_payroll_ke.kenya_payroll.report_utils import component_order, monthly_payroll

TABLE_PREFIX = {"earnings": "e", "deductions": "d", "employer_contributions": "c"}
IDENTITY_FIELDS = {
	"royce_kra_pin": "KRA PIN",
	"royce_national_id": "ID No.",
	"royce_nssf_no": "NSSF No.",
	"royce_shif_no": "SHA No.",
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))
	if not filters.get("month"):
		frappe.throw(_("Month is required"))

	payroll = monthly_payroll(
		filters.company,
		getdate(filters.month),
		bool(int(filters.get("include_draft") or 0)),
		filters.get("department"),
	)
	order = component_order(payroll)
	identity = _identity(list(payroll))

	data = []
	for employee, row in sorted(payroll.items(), key=lambda item: (item[1].employee_name or "", item[0])):
		line = {
			"employee": employee,
			"employee_name": row.employee_name,
			"department": row.department,
			**identity.get(employee, {}),
			"payment_days": row.payment_days,
			"gross_pay": row.gross_pay,
			"total_deduction": row.total_deduction,
			"net_pay": row.net_pay,
			"taxable_pay": row.taxable_pay,
			"employer_total": sum(
				amount for (table, _c), amount in row.components.items() if table == "employer_contributions"
			),
		}
		for table, component in order:
			line[_fieldname(table, component)] = row.components.get((table, component), 0)
		data.append(line)

	return get_columns(order), data


def _identity(employees):
	if not employees:
		return {}
	meta = frappe.get_meta("Employee")
	fields = [f for f in IDENTITY_FIELDS if meta.has_field(f)]
	return {
		e.name: {f: e.get(f) for f in fields}
		for e in frappe.get_all("Employee", filters={"name": ["in", employees]}, fields=["name", *fields])
	}


def _fieldname(table, component):
	return f"{TABLE_PREFIX[table]}_{frappe.scrub(component)}"


def get_columns(order):
	meta = frappe.get_meta("Employee")
	columns = [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 130},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 170},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department",
			"width": 130},
	]
	columns += [
		{"label": _(label), "fieldname": field, "fieldtype": "Data", "width": 120}
		for field, label in IDENTITY_FIELDS.items()
		if meta.has_field(field)
	]
	columns.append({"label": _("Days Paid"), "fieldname": "payment_days", "fieldtype": "Float", "width": 90})

	def money(label, fieldname, width=120):
		return {"label": label, "fieldname": fieldname, "fieldtype": "Currency", "width": width}

	for table, totals in (
		("earnings", [money(_("Gross Pay"), "gross_pay")]),
		("deductions", [money(_("Total Deductions"), "total_deduction"), money(_("Net Pay"), "net_pay")]),
		("employer_contributions", [money(_("Employer Contributions"), "employer_total", 150)]),
	):
		columns += [money(_(c), _fieldname(t, c)) for t, c in order if t == table]
		columns += totals
	columns.append(money(_("Taxable Pay"), "taxable_pay"))
	return columns
