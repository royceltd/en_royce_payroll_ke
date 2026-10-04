# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Drop two misleading popups HRMS queues on every Kenya-payroll site.

1. "HR Telemetry Milestone <event> already exists" (title "Duplicate Name").
   hrms.telemetry._claim_milestone() inserts a once-per-site marker on the
   first Salary Structure / Leave Type / Shift Type / Employee / ... during a
   site's first 30 days, and tries again on every later one. The duplicate is
   caught by a savepoint, but Frappe's db_insert() has already msgprint'ed
   "already exists" before raising, so the user sees a red error for a save
   that worked. Present in hrms v16.20.0 and on version-16 as of 2026-10-04.

2. "Added tax components from the Salary Component master as the salary
   structure didn't have any tax component." SalarySlip.add_tax_components()
   shows this on every new slip whose structure has no component flagged
   variable_based_on_taxable_salary, even when the master lookup finds none
   and nothing is added. Kenya Payroll computes PAYE with its own formula and
   keeps that flag off on purpose (setup._PAYE_FINAL_FLAGS), so on our sites
   the alert always fires and is always false.

Both are removed from frappe.local.message_log right after the HRMS code that
queues them has run: (1) by doc_events, which run after hrms's since this app is
installed after it; (2) by a Salary Slip class extension (extend_doctype_class). Nothing in HRMS is patched or copied, so an HRMS upgrade
that fixes either message just makes the matching filter a no-op.
"""

import json

import frappe
from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip

TELEMETRY_DOCTYPE = "HR Telemetry Milestone"
TAX_ALERT = "Added tax components from the Salary Component master"


def _text(entry) -> str:
	"""message_log entries are dicts on current Frappe, JSON strings on older ones."""
	if isinstance(entry, str):
		try:
			entry = json.loads(entry)
		except ValueError:
			return entry
	if isinstance(entry, dict):
		return f"{entry.get('title') or ''} {entry.get('message') or ''}"
	return str(entry)


def _drop(predicate) -> None:
	log = getattr(frappe.local, "message_log", None)
	if not log:
		return
	frappe.local.message_log = [m for m in log if not predicate(_text(m))]


def _is_telemetry_duplicate(text: str) -> bool:
	return TELEMETRY_DOCTYPE in text and "already exists" in text


def drop_telemetry_duplicate(doc, method=None):
	"""after_insert / on_submit on every doctype hrms.telemetry hooks with capture_first()."""
	_drop(_is_telemetry_duplicate)


class KenyaSalarySlip(SalarySlip):
	"""extend_doctype_class extension for Salary Slip (same pattern as ERPNext's
	ERPNextAddress for Address).

	Wraps add_tax_components() itself rather than a doc event, because the form
	reaches it through whitelisted methods (get_emp_and_working_day_details,
	process_salary_based_on_working_days) that never run validate hooks.
	"""

	def add_tax_components(self):
		super().add_tax_components()
		if any(d.variable_based_on_taxable_salary for d in self.get("deductions") or []):
			return  # a tax component really was added: the alert is true, keep it
		_drop(lambda text: TAX_ALERT in text)
