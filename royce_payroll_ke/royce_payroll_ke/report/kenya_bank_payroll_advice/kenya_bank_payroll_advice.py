# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Bank-ready payment instructions for a payroll run. Deliberately reads bank
details straight off Employee, not a per-slip snapshot — unlike csf_ke's own
version, which copies bank fields onto the Salary Slip at creation time. This
report is used to generate the payment file for the *current* run, so the
employee's *current* bank details are what's wanted, not whatever was on file
when an older slip happened to be created. Simpler, too: no Salary Slip fields,
no doc_events override to keep them in sync — one less thing that can drift."""

import erpnext
import frappe
from frappe import _
from frappe.utils import flt


def get_columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 140},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 200},
		{"label": _("National ID"), "fieldname": "national_id", "fieldtype": "Data", "width": 110},
		{"label": _("KRA PIN"), "fieldname": "kra_pin", "fieldtype": "Data", "width": 110},
		{"label": _("Bank Name"), "fieldname": "bank_name", "fieldtype": "Data", "width": 170},
		{"label": _("Bank Code"), "fieldname": "bank_code", "fieldtype": "Data", "width": 100},
		{"label": _("Bank Branch"), "fieldname": "bank_branch", "fieldtype": "Data", "width": 150},
		{"label": _("Branch Code"), "fieldname": "branch_code", "fieldtype": "Data", "width": 100},
		{"label": _("Account No"), "fieldname": "bank_account_no", "fieldtype": "Data", "width": 150},
		{"label": _("Net Pay"), "fieldname": "net_pay", "fieldtype": "Currency", "width": 130},
	]


def get_data(filters):
	salary_slip = frappe.qb.DocType("Salary Slip")
	employee = frappe.qb.DocType("Employee")

	query = (
		frappe.qb.from_(salary_slip)
		.inner_join(employee)
		.on(salary_slip.employee == employee.name)
		.select(
			salary_slip.employee,
			employee.employee_name,
			employee.royce_national_id.as_("national_id"),
			employee.royce_kra_pin.as_("kra_pin"),
			employee.bank_name,
			employee.royce_bank_code.as_("bank_code"),
			employee.royce_bank_branch_name.as_("bank_branch"),
			employee.royce_branch_code.as_("branch_code"),
			employee.bank_ac_no.as_("bank_account_no"),
			salary_slip.net_pay,
		)
		.where(
			(salary_slip.docstatus == 1)
			& (salary_slip.company == filters.company)
			& (salary_slip.start_date >= filters.from_date)
			& (salary_slip.end_date <= filters.to_date)
		)
		.orderby(employee.bank_name)
		.orderby(employee.employee_name)
	)

	if filters.get("employee"):
		query = query.where(salary_slip.employee == filters.employee)
	if filters.get("bank_name"):
		query = query.where(employee.bank_name == filters.bank_name)

	return query.run(as_dict=True)


def get_report_summary(data, filters):
	"""One card per receiving bank — a real bank advice file gets split per bank
	before submission, so the per-bank total and headcount is the actual point
	of grouping this way, not decoration."""
	if not data:
		return []

	company_currency = erpnext.get_company_currency(filters.get("company"))

	summary = {}
	grand_total = 0
	for row in data:
		bank = row.get("bank_name") or _("(No Bank on File)")
		net_pay = flt(row.get("net_pay"))
		entry = summary.setdefault(bank, {"count": 0, "total": 0})
		entry["count"] += 1
		entry["total"] += net_pay
		grand_total += net_pay

	report_summary = [
		{
			"label": _("{0} ({1} staff)").format(bank, summary[bank]["count"]),
			"value": summary[bank]["total"],
			"datatype": "Currency",
			"currency": company_currency,
			"indicator": "Blue",
		}
		for bank in sorted(summary)
	]
	report_summary.append(
		{
			"label": _("Total ({0} staff)").format(len(data)),
			"value": grand_total,
			"datatype": "Currency",
			"currency": company_currency,
			"indicator": "Green",
		}
	)
	return report_summary


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))
	if not filters.get("from_date") or not filters.get("to_date"):
		frappe.throw(_("From Date and To Date are required"))

	data = get_data(filters)
	report_summary = get_report_summary(data, filters)

	return get_columns(), data, None, None, report_summary
