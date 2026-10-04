# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Tests for payroll_guards: slips of a Payroll Entry can only be submitted through it,
and a Posting Date outside the pay period is warned about."""

import frappe
from frappe.tests import IntegrationTestCase

from royce_payroll_ke.kenya_payroll.payroll_guards import (
	block_slip_submit_outside_payroll_entry,
	warn_posting_date_outside_period,
)

GUARDS = "royce_payroll_ke.kenya_payroll.payroll_guards."


def _slip(**kw):
	return frappe._dict({"doctype": "Salary Slip", "payroll_entry": None, **kw})


def _entry(posting, start="2026-07-01", end="2026-07-31", docstatus=0):
	return frappe._dict(
		{"doctype": "Payroll Entry", "posting_date": posting, "start_date": start, "end_date": end, "docstatus": docstatus}
	)


def _warned():
	return any(
		"outside the pay period" in str(m.get("message") if isinstance(m, dict) else m)
		for m in frappe.local.message_log or []
	)


class TestSlipSubmitGuard(IntegrationTestCase):
	def tearDown(self):
		frappe.flags.via_payroll_entry = False
		frappe.local.message_log = []

	def test_slip_of_a_payroll_entry_cannot_be_submitted_on_its_own(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			block_slip_submit_outside_payroll_entry(_slip(payroll_entry="HR-PRUN-TEST-00001"))
		self.assertIn("Submit Salary Slip", str(ctx.exception))

	def test_payroll_entry_button_path_is_allowed(self):
		frappe.flags.via_payroll_entry = True  # set by hrms submit_salary_slips_for_employees
		block_slip_submit_outside_payroll_entry(_slip(payroll_entry="HR-PRUN-TEST-00001"))

	def test_standalone_slip_is_allowed(self):
		block_slip_submit_outside_payroll_entry(_slip())


class TestPostingDateWarning(IntegrationTestCase):
	def tearDown(self):
		frappe.local.message_log = []

	def test_posting_date_after_period_warns(self):
		frappe.local.message_log = []
		warn_posting_date_outside_period(_entry("2026-10-04"))
		self.assertTrue(_warned())

	def test_posting_date_before_period_warns(self):
		frappe.local.message_log = []
		warn_posting_date_outside_period(_entry("2026-06-30"))
		self.assertTrue(_warned())

	def test_posting_date_inside_period_is_silent(self):
		frappe.local.message_log = []
		for posting in ("2026-07-01", "2026-07-15", "2026-07-31"):
			warn_posting_date_outside_period(_entry(posting))
		self.assertFalse(_warned())

	def test_submitted_entry_is_silent(self):
		frappe.local.message_log = []
		warn_posting_date_outside_period(_entry("2026-10-04", docstatus=1))
		self.assertFalse(_warned())


class TestGuardThroughRealPayrollEntry(IntegrationTestCase):
	"""The real flow: the slip can't be submitted from its own form, and the Payroll
	Entry's Submit Salary Slip still works and posts the accrual Journal Entry."""

	def test_payroll_entry_flow(self):
		from royce_payroll_ke.kenya_payroll.tests.utils import (
			get_test_company,
			make_test_kenya_payroll_rates,
			make_test_payslip,
		)

		company = get_test_company()
		rates = make_test_kenya_payroll_rates("1980-01-01")
		start, end = "1980-07-01", "1980-07-31"
		employee, standalone = make_test_payslip(
			company, rates, "royce.payroll.guard@example.com", base=60000,
			posting_date=end, period_start=start, period_end=end,
		)
		standalone.cancel()  # free the period for the Payroll Entry

		payable, cost_center = frappe.get_cached_value(
			"Company", company, ["default_payroll_payable_account", "cost_center"]
		)
		if not payable:
			self.skipTest("test company has no default payroll payable account")

		pe = frappe.new_doc("Payroll Entry")
		pe.update(
			{
				"company": company, "posting_date": end, "start_date": start, "end_date": end,
				"payroll_frequency": "Monthly", "currency": "KES", "exchange_rate": 1,
				"payroll_payable_account": payable, "cost_center": cost_center,
			}
		)
		pe.append("employees", {"employee": employee})
		pe.insert(ignore_permissions=True)
		pe.submit()  # creates the draft slip

		slip_name = frappe.db.get_value("Salary Slip", {"payroll_entry": pe.name, "docstatus": 0})
		self.assertTrue(slip_name)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Salary Slip", slip_name).submit()
		self.assertEqual(frappe.db.get_value("Salary Slip", slip_name, "docstatus"), 0)

		frappe.get_doc("Payroll Entry", pe.name).submit_salary_slips()

		docstatus, journal_entry = frappe.db.get_value("Salary Slip", slip_name, ["docstatus", "journal_entry"])
		self.assertEqual(docstatus, 1)
		self.assertTrue(journal_entry)
		self.assertEqual(frappe.db.get_value("Journal Entry", journal_entry, "docstatus"), 1)


class TestGuardHooks(IntegrationTestCase):
	def test_hooks_are_wired(self):
		hooks = frappe.get_hooks("doc_events")
		self.assertIn(
			GUARDS + "block_slip_submit_outside_payroll_entry",
			hooks.get("Salary Slip", {}).get("before_submit", []),
		)
		self.assertIn(
			GUARDS + "warn_posting_date_outside_period",
			hooks.get("Payroll Entry", {}).get("validate", []),
		)
