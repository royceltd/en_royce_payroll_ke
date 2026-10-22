# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Payroll checks that stop a slip breaking Kenyan law or failing at filing time.

- One-third rule: the Employment Act 2007, s.19(3), caps an employee's total deductions at
  two-thirds of their wages. Stacked loans, SACCO and HELB deductions are how it gets
  broken.
- Statutory details: KRA's PAYE return lists employees by KRA PIN; the NSSF, SHA and KRA
  returns need the ID, NSSF and SHA numbers; a bank payment needs an account number.
- Days worked (casual wages structure): pay is daily rate x days worked, so a slip with no
  days, or more days than the period has, is a data-entry mistake. Always Block.

Each check except days worked is Block, Warn or Off in Kenya Payroll Settings. They run on slips from a
Kenya Payroll structure only:
- Payroll Entry (draft) validate: one list of every employee with missing details,
  before the slips are made.
- Salary Slip validate (saved by hand): the slip's own problems as a warning.
- Salary Slip before_submit: Block-level problems stop that slip. When a Payroll Entry
  submits its slips, HRMS leaves a blocked slip unsubmitted and goes on with the rest.
"""

import re

import frappe
from frappe import _
from frappe.utils import date_diff, flt, fmt_money, get_link_to_form

from royce_payroll_ke.kenya_payroll.engine import is_kenya_structure
from royce_payroll_ke.kenya_payroll.setup import is_casual_structure

BLOCK, WARN, OFF = "Block", "Warn", "Off"
DEFAULTS = {
	"one_third_rule": BLOCK,
	"missing_kra_pin": BLOCK,
	"missing_statutory_numbers": WARN,
	"missing_bank_details": WARN,
}

# Not in Kenya Payroll Settings: there's no case for letting these through.
FIXED = {"days_worked": BLOCK}

# Letter, nine digits, letter (individuals' PINs start with A). Checked for shape only.
KRA_PIN = re.compile(r"^[A-Z]\d{9}[A-Z]$")


def level(check):
	if check in FIXED:
		return FIXED[check]
	value = frappe.db.get_single_value("Kenya Payroll Settings", check)
	return value or DEFAULTS[check]


def one_third_problem(gross_pay, total_deductions):
	"""The one-third rule's message, or None. Deductions may not exceed two-thirds of gross
	pay, so the employee keeps at least a third."""
	gross_pay, total_deductions = flt(gross_pay), flt(total_deductions)
	if gross_pay <= 0:
		return None
	limit = flt(gross_pay * 2 / 3, 2)
	if flt(total_deductions, 2) <= limit:
		return None
	return _(
		"Deductions of {0} are more than two-thirds of pay of {1} (limit {2}). The Employment Act "
		"(s.19(3)) requires the employee to receive at least a third of their wages: reduce loan, "
		"SACCO or other deductions."
	).format(_money(total_deductions), _money(gross_pay), _money(limit))


def employee_problems(employee):
	"""[(check, message)] for missing or invalid statutory and bank details."""
	values = frappe.db.get_value(
		"Employee",
		employee,
		["royce_kra_pin", "royce_national_id", "royce_nssf_no", "royce_shif_no", "salary_mode", "bank_ac_no"],
		as_dict=True,
	) or frappe._dict()
	problems = []

	pin = (values.royce_kra_pin or "").strip().upper()
	if not pin:
		problems.append(("missing_kra_pin", _("no KRA PIN")))
	elif not KRA_PIN.match(pin):
		problems.append(("missing_kra_pin", _("KRA PIN {0} is not in the format A123456789B").format(pin)))

	missing = [
		label
		for field, label in (
			("royce_national_id", _("ID number")),
			("royce_nssf_no", _("NSSF number")),
			("royce_shif_no", _("SHA number")),
		)
		if not (values.get(field) or "").strip()
	]
	if missing:
		problems.append(("missing_statutory_numbers", _("no {0}").format(", ".join(missing))))

	if values.salary_mode == "Bank" and not (values.bank_ac_no or "").strip():
		problems.append(("missing_bank_details", _("paid by bank but no bank account number")))

	return [(check, message) for check, message in problems if level(check) != OFF]


def days_worked_problem(days_worked, start_date, end_date):
	"""The days-worked message for a casual wages slip, or None."""
	days_worked = flt(days_worked)
	if days_worked <= 0:
		return _("no Days Worked entered (pay is the daily rate x days worked)")
	period_days = date_diff(end_date, start_date) + 1 if start_date and end_date else None
	if period_days and days_worked > period_days:
		return _("Days Worked is {0}, more than the {1} days in the pay period").format(
			frappe.format(days_worked, {"fieldtype": "Float"}), period_days
		)
	return None


def slip_problems(slip):
	"""[(check, message)] for one salary slip."""
	problems = list(employee_problems(slip.employee)) if slip.employee else []
	if is_casual_structure(slip.salary_structure):
		message = days_worked_problem(slip.get("royce_days_worked"), slip.start_date, slip.end_date)
		if message:
			problems.append(("days_worked", message))
	if level("one_third_rule") != OFF:
		deductions = flt(slip.total_deduction) + flt(slip.get("total_loan_repayment"))
		message = one_third_problem(slip.gross_pay, deductions)
		if message:
			problems.append(("one_third_rule", message))
	return problems


def _money(value):
	return fmt_money(value, precision=0, currency="KES")


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


def block_slip_problems(doc, method=None):
	"""Salary Slip before_submit."""
	if not is_kenya_structure(doc.salary_structure):
		return
	blocking = [message for check, message in slip_problems(doc) if level(check) == BLOCK]
	if blocking:
		frappe.throw(
			_("Salary slip for {0} can't be submitted:").format(frappe.bold(doc.employee_name or doc.employee))
			+ "<ul>"
			+ "".join(f"<li>{m}</li>" for m in blocking)
			+ "</ul>"
			+ _("Fix these, or change the check in {0}.").format(
				get_link_to_form("Kenya Payroll Settings", "Kenya Payroll Settings")
			),
			title=_("Payroll check failed"),
		)


def warn_slip_problems(doc, method=None):
	"""Salary Slip validate, when saved by hand (a Payroll Entry making or submitting its
	slips reports through the Payroll Entry instead)."""
	if doc.docstatus != 0 or frappe.flags.via_payroll_entry or not is_kenya_structure(doc.salary_structure):
		return
	problems = slip_problems(doc)
	if problems:
		frappe.msgprint(
			"<ul>" + "".join(f"<li>{m}</li>" for _c, m in problems) + "</ul>",
			title=_("Check before submitting"),
			indicator="red" if any(level(c) == BLOCK for c, _m in problems) else "orange",
		)


def warn_payroll_entry_problems(doc, method=None):
	"""Payroll Entry validate (drafts): every employee with missing details, in one message."""
	if doc.docstatus != 0 or not doc.get("employees"):
		return
	lines, blocking = [], False
	for row in doc.employees:
		problems = employee_problems(row.employee)
		if problems:
			blocking = blocking or any(level(c) == BLOCK for c, _m in problems)
			lines.append(
				f"<li>{frappe.bold(row.employee_name or row.employee)}: {'; '.join(m for _c, m in problems)}</li>"
			)
	if lines:
		frappe.msgprint(
			_("Fix these before submitting the salary slips{0}:").format(
				_(" (marked Block in Kenya Payroll Settings, those slips won't submit)") if blocking else ""
			)
			+ "<ul>"
			+ "".join(lines)
			+ "</ul>",
			title=_("Employee details missing"),
			indicator="red" if blocking else "orange",
		)
