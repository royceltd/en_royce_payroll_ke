# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Payroll Variance: each employee's pay this month against another month (the month
before, by default). What a payroll officer checks before approving a run: who joined,
who left, whose pay changed and why. Draft slips count by default, since the review
happens before the slips are submitted."""

import frappe
from frappe import _
from frappe.utils import add_months, flt, fmt_money, getdate

from royce_payroll_ke.kenya_payroll.report_utils import component_order, month_bounds, monthly_payroll

NEW, LEFT, CHANGED, SAME = "New", "Left", "Changed", "No change"
STATUS_ORDER = {NEW: 0, LEFT: 1, CHANGED: 2, SAME: 3}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))
	if not filters.get("month"):
		frappe.throw(_("Month is required"))

	month = getdate(filters.month)
	compare = getdate(filters.compare_month) if filters.get("compare_month") else add_months(month, -1)
	if month_bounds(compare) == month_bounds(month):
		frappe.throw(_("Compare With must be a different month."))

	include_draft = bool(int(filters.get("include_draft") or 0))
	current = monthly_payroll(filters.company, month, include_draft, filters.get("department"))
	# The month compared with is what was actually paid: submitted slips only.
	previous = monthly_payroll(filters.company, compare, False, filters.get("department"))

	order = component_order(current, previous)
	data = []
	for employee in set(current) | set(previous):
		now, before = current.get(employee), previous.get(employee)
		row = variance_row(employee, now, before, order)
		if row["status"] == SAME and not filters.get("show_unchanged"):
			continue
		data.append(row)

	data.sort(key=lambda r: (STATUS_ORDER[r["status"]], -abs(r["net_change"]), r["employee_name"] or ""))
	return get_columns(month, compare), data, None, None, report_summary(current, previous)


def variance_row(employee, now, before, order):
	empty = frappe._dict(employee_name="", department="", gross_pay=0, net_pay=0, payment_days=0,
		draft=False, components={})
	now_, before_ = now or empty, before or empty
	if not before:
		status = NEW
	elif not now:
		status = LEFT
	else:
		status = CHANGED if describe_changes(before_.components, now_.components, order) or (
			flt(now_.net_pay, 2) != flt(before_.net_pay, 2)
		) else SAME

	net_change = flt(now_.net_pay) - flt(before_.net_pay)
	return {
		"employee": employee,
		"employee_name": now_.employee_name or before_.employee_name,
		"department": now_.department or before_.department,
		"status": status,
		"slip_status": (_("Draft") if now_.draft else _("Submitted")) if now else "",
		"previous_days": flt(before_.payment_days),
		"current_days": flt(now_.payment_days),
		"previous_gross": flt(before_.gross_pay),
		"current_gross": flt(now_.gross_pay),
		"gross_change": flt(now_.gross_pay) - flt(before_.gross_pay),
		"previous_net": flt(before_.net_pay),
		"current_net": flt(now_.net_pay),
		"net_change": net_change,
		"net_change_percent": (net_change / flt(before_.net_pay) * 100) if flt(before_.net_pay) else None,
		"changes": " · ".join(describe_changes(before_.components, now_.components, order))
		if now and before
		else "",
	}


def describe_changes(before, now, order):
	"""Plain-words list of the component amounts that differ, in payslip order."""
	changes = []
	for key in order:
		old, new = flt(before.get(key), 2), flt(now.get(key), 2)
		if old == new:
			continue
		component = _(key[1])
		if not old:
			changes.append(_("{0} new {1}").format(component, _money(new)))
		elif not new:
			changes.append(_("{0} removed (was {1})").format(component, _money(old)))
		else:
			sign = "+" if new > old else "-"
			changes.append(f"{component} {sign}{_money(abs(new - old))}")
	return changes


def _money(value):
	return fmt_money(value, precision=0)


def report_summary(current, previous):
	joiners = len(set(current) - set(previous))
	leavers = len(set(previous) - set(current))
	gross_change = sum(r.gross_pay for r in current.values()) - sum(r.gross_pay for r in previous.values())
	net_change = sum(r.net_pay for r in current.values()) - sum(r.net_pay for r in previous.values())
	return [
		{"label": _("Employees paid"), "value": len(current), "datatype": "Int",
			"indicator": "Blue"},
		{"label": _("Joined"), "value": joiners, "datatype": "Int", "indicator": "Green"},
		{"label": _("Left"), "value": leavers, "datatype": "Int", "indicator": "Red"},
		{"label": _("Change in gross pay"), "value": gross_change, "datatype": "Currency",
			"indicator": "Orange" if gross_change else "Grey"},
		{"label": _("Change in net pay"), "value": net_change, "datatype": "Currency",
			"indicator": "Orange" if net_change else "Grey"},
	]


def get_columns(month, compare):
	this, that = month.strftime("%b %Y"), compare.strftime("%b %Y")
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 130},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 170},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department",
			"width": 130},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Slip"), "fieldname": "slip_status", "fieldtype": "Data", "width": 90},
		{"label": _("Days {0}").format(that), "fieldname": "previous_days", "fieldtype": "Float", "width": 90},
		{"label": _("Days {0}").format(this), "fieldname": "current_days", "fieldtype": "Float", "width": 90},
		{"label": _("Gross {0}").format(that), "fieldname": "previous_gross", "fieldtype": "Currency", "width": 120},
		{"label": _("Gross {0}").format(this), "fieldname": "current_gross", "fieldtype": "Currency", "width": 120},
		{"label": _("Gross Change"), "fieldname": "gross_change", "fieldtype": "Currency", "width": 120},
		{"label": _("Net {0}").format(that), "fieldname": "previous_net", "fieldtype": "Currency", "width": 120},
		{"label": _("Net {0}").format(this), "fieldname": "current_net", "fieldtype": "Currency", "width": 120},
		{"label": _("Net Change"), "fieldname": "net_change", "fieldtype": "Currency", "width": 120},
		{"label": _("Net Change %"), "fieldname": "net_change_percent", "fieldtype": "Percent", "width": 100},
		{"label": _("What Changed"), "fieldname": "changes", "fieldtype": "Data", "width": 420},
	]
