# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Tests for hrms_noise: the two false HRMS popups are dropped, nothing else is."""

import frappe
from frappe.tests import IntegrationTestCase

from royce_payroll_ke.kenya_payroll.hrms_noise import (
	TAX_ALERT,
	TELEMETRY_DOCTYPE,
	KenyaSalarySlip,
	drop_telemetry_duplicate,
)
from royce_payroll_ke.kenya_payroll.tests.utils import (
	get_test_company,
	make_test_kenya_payroll_rates,
	make_test_payslip,
)

TEST_EVENT = "royce_test_duplicate_milestone"


def _messages():
	out = []
	for m in frappe.local.message_log or []:
		out.append(f"{m.get('title') or ''} {m.get('message') or ''}" if isinstance(m, dict) else str(m))
	return out


class TestTelemetryDuplicate(IntegrationTestCase):
	def tearDown(self):
		frappe.db.delete(TELEMETRY_DOCTYPE, {"event": TEST_EVENT})
		frappe.local.message_log = []

	def test_real_duplicate_claim_is_dropped_and_other_messages_kept(self):
		from hrms.telemetry import _claim_milestone

		frappe.local.message_log = []
		frappe.msgprint("keep me")
		self.assertTrue(_claim_milestone(TEST_EVENT))
		# Second claim: hrms swallows the DuplicateEntryError, but Frappe has
		# already queued the "already exists" popup. That's the bug.
		self.assertFalse(_claim_milestone(TEST_EVENT))
		self.assertTrue(any(TELEMETRY_DOCTYPE in m and "already exists" in m for m in _messages()))

		drop_telemetry_duplicate(None)

		msgs = _messages()
		self.assertFalse(any(TELEMETRY_DOCTYPE in m for m in msgs))
		self.assertTrue(any("keep me" in m for m in msgs))

	def test_other_duplicate_name_errors_are_untouched(self):
		frappe.local.message_log = []
		frappe.msgprint("Salary Structure <b>X</b> already exists", title="Duplicate Name")
		drop_telemetry_duplicate(None)
		self.assertEqual(len(_messages()), 1)

	def test_hooks_are_wired(self):
		hooks = frappe.get_hooks("doc_events")
		for dt, event in (("Salary Structure", "after_insert"), ("Salary Slip", "on_submit")):
			self.assertIn(
				"royce_payroll_ke.kenya_payroll.hrms_noise.drop_telemetry_duplicate",
				hooks.get(dt, {}).get(event, []),
			)


class TestFalseTaxAlert(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates("1979-01-01")

	def tearDown(self):
		frappe.local.message_log = []

	def test_salary_slip_uses_extension(self):
		self.assertTrue(issubclass(frappe.get_doc({"doctype": "Salary Slip"}).__class__, KenyaSalarySlip))

	def test_new_kenya_slip_shows_no_false_tax_alert(self):
		frappe.local.message_log = []
		_, slip = make_test_payslip(
			self.company,
			self.rates,
			"royce.payroll.noise@example.com",
			base=90000,
			posting_date="1979-06-01",
			period_start="1979-06-01",
			period_end="1979-06-30",
		)
		if any(d.variable_based_on_taxable_salary for d in slip.deductions):
			self.skipTest("bench has a tax-flagged Salary Component; the alert would be true here")
		self.assertFalse(any(TAX_ALERT in m for m in _messages()))
		# PAYE still computed by Kenya Payroll's own formula component
		paye = set(frappe.get_all("Salary Component", {"is_income_tax_component": 1}, pluck="name"))
		self.assertTrue(any(d.salary_component in paye and d.amount for d in slip.deductions))
