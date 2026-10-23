# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Payslips by SMS (payslip_sms.py). The SMS provider is never called: royce_talk's
send_single_sms is replaced by a mock. Skipped where the Bulk SMS app isn't installed."""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from royce_payroll_ke.kenya_payroll import payslip_sms
from royce_payroll_ke.kenya_payroll.tests.utils import (
	get_test_company,
	make_test_kenya_payroll_rates,
	make_test_payslip,
)

SEND = "royce_talk.bulk_sms.utils.send_single_sms"


@unittest.skipUnless("royce_talk" in frappe.get_installed_apps(), "Bulk SMS app not installed")
class TestPayslipSms(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates("1998-01-01")

	def tearDown(self):
		frappe.db.set_single_value("Kenya Payroll Settings", "payslip_sms_template", None)

	def _slip(self, email, phone="0712345678"):
		_employee, slip = make_test_payslip(
			self.company, self.rates, email, base=40000,
			posting_date="1998-01-31", period_start="1998-01-01", period_end="1998-01-31",
			cell_number=phone,
		)
		return slip

	def test_default_message_is_a_short_summary(self):
		slip = self._slip("sms.message@example.com")
		text = payslip_sms.message(slip)
		self.assertTrue(text.startswith(f"{slip.employee_name}, Jan 1998 pay: gross 50,000, deductions "), text)
		self.assertIn(f"net KES {flt(slip.net_pay):,.0f}. {self.company}", text)
		self.assertLessEqual(len(text), 160)

	def test_template_from_settings(self):
		slip = self._slip("sms.template@example.com")
		frappe.db.set_single_value(
			"Kenya Payroll Settings", "payslip_sms_template", "Hi {{ first_name }}, PAYE {{ paye }}, net {{ net }}"
		)
		paye = next(d.amount for d in slip.deductions if d.salary_component == "PAYE")
		self.assertEqual(
			payslip_sms.message(slip), f"Hi {slip.employee_name}, PAYE {flt(paye):,.0f}, net {flt(slip.net_pay):,.0f}"
		)

	def test_plan_skips_missing_phones_and_already_sent(self):
		with_phone = self._slip("sms.plan.a@example.com")
		without_phone = self._slip("sms.plan.b@example.com", phone="")
		sent = self._slip("sms.plan.c@example.com")
		frappe.get_doc(
			{
				"doctype": "Bulk SMS Log", "status": "Delivered", "recipient": "+254712345678", "message": "x",
				"reference_doctype": "Salary Slip", "reference_name": sent.name,
			}
		).insert(ignore_permissions=True)
		names = [with_phone.name, without_phone.name, sent.name]

		result = payslip_sms.plan(names)
		self.assertEqual([i.slip for i in result.send], [with_phone.name])
		self.assertEqual(result.no_phone, [without_phone.employee_name])
		self.assertEqual(result.already_sent, [sent.employee_name])

		resend = payslip_sms.plan(names, resend=True)
		self.assertEqual({i.slip for i in resend.send}, {with_phone.name, sent.name})

	def test_send_slips_carries_on_after_a_failure(self):
		ok = self._slip("sms.send.a@example.com")
		bad = self._slip("sms.send.b@example.com", phone="0722000000")

		def fake_send(phone_number, text_message, reference_doctype, reference_name):
			if reference_name == bad.name:
				raise frappe.ValidationError("provider error")
			return {"status": "Sent"}

		with patch(SEND, side_effect=fake_send) as send:
			result = payslip_sms.send_slips([ok.name, bad.name])
		self.assertEqual(send.call_count, 2)
		self.assertEqual(result["sent"], 1)
		self.assertEqual(len(result["failed"]), 1)
		self.assertIn(bad.name, result["failed"][0])
		self.assertEqual(send.call_args_list[0].kwargs["phone_number"], "0712345678")
		self.assertEqual(send.call_args_list[0].kwargs["reference_doctype"], "Salary Slip")

	def test_preview_for_a_payroll_entry(self):
		a = self._slip("sms.preview.a@example.com")
		b = self._slip("sms.preview.b@example.com", phone="")
		for slip in (a, b):
			frappe.db.set_value("Salary Slip", slip.name, "payroll_entry", "Kenya SMS Test Entry")
		with patch.object(payslip_sms, "_require"):
			result = payslip_sms.preview("Kenya SMS Test Entry")
		self.assertEqual((result["slips"], result["to_send"]), (2, 1))
		self.assertEqual(result["no_phone"], [b.employee_name])
		self.assertEqual(result["sample"], payslip_sms.message(frappe.get_doc("Salary Slip", a.name)))
		self.assertGreaterEqual(result["units"], 1)

	def test_send_one_slip(self):
		slip = self._slip("sms.one@example.com")
		with patch.object(payslip_sms, "_require"), patch(SEND) as send:
			text = payslip_sms.send_slip(slip.name)
		send.assert_called_once()
		self.assertEqual(send.call_args.kwargs["text_message"], text)

	def test_not_available_while_bulk_sms_is_disabled(self):
		enabled = frappe.db.get_single_value("Bulk SMS Settings", "enabled")
		frappe.db.set_single_value("Bulk SMS Settings", "enabled", 0)
		try:
			self.assertIn("disabled", payslip_sms.unavailable_reason())
		finally:
			frappe.db.set_single_value("Bulk SMS Settings", "enabled", enabled)
