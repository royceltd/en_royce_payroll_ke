# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.fixtures import sync_fixtures

from royce_payroll_ke.kenya_payroll.printing import (
	PRINT_FORMAT,
	band_tax,
	masked,
	pay_period,
	set_default_print_format,
)

PS_FILTERS = {"doc_type": "Salary Slip", "doctype_or_field": "DocType", "property": "default_print_format"}

# The 2026 bands as seeded (setup.py / Kenya Payroll Rates), top band open-ended.
BANDS_2026 = [
	frappe._dict(band_number=1, upper_bound=24000, rate=10),
	frappe._dict(band_number=2, upper_bound=32333, rate=25),
	frappe._dict(band_number=3, upper_bound=500000, rate=30),
	frappe._dict(band_number=4, upper_bound=800000, rate=32.5),
	frappe._dict(band_number=5, upper_bound=0, rate=35),
]


class TestPayslipFigures(IntegrationTestCase):
	def test_band_tax_matches_the_engine(self):
		# gross 62,500 - NSSF 3,750 - SHIF 1,719 - AHL 938 = 56,093; the real slip's
		# PAYE was 9,211 = 11,611.25 tax charged - 2,400 relief (rounded).
		self.assertEqual(band_tax(56093, BANDS_2026), 11611.25)
		self.assertEqual(band_tax(20000, BANDS_2026), 2000)
		self.assertEqual(band_tax(0, BANDS_2026), 0)

	def test_pay_period(self):
		self.assertEqual(pay_period("2026-01-01", "2026-01-31"), "1 – 31 Jan 2026")
		self.assertEqual(pay_period("2025-12-15", "2026-01-14"), "15 Dec 2025 – 14 Jan 2026")

	def test_bank_account_is_masked(self):
		self.assertEqual(masked("0123456789"), "•••• 6789")
		self.assertEqual(masked(""), "")


class TestPayslipDefault(IntegrationTestCase):
	"""ADR-023: set once at install, a client's own default survives every migrate."""

	def tearDown(self):
		frappe.db.rollback()

	def _client_default(self, value):
		frappe.db.delete("Property Setter", PS_FILTERS)
		frappe.make_property_setter(
			{
				"doctype": "Salary Slip",
				"doctype_or_field": "DocType",
				"property": "default_print_format",
				"value": value,
				"property_type": "Data",
			}
		)

	def test_sets_ours_where_there_is_no_default(self):
		frappe.db.delete("Property Setter", PS_FILTERS)
		self.assertTrue(set_default_print_format())
		self.assertEqual(frappe.db.get_value("Property Setter", PS_FILTERS, "value"), PRINT_FORMAT)

	def test_never_replaces_a_clients_own_default(self):
		self._client_default("Salary Slip Standard")
		self.assertFalse(set_default_print_format())
		self.assertEqual(frappe.db.get_value("Property Setter", PS_FILTERS, "value"), "Salary Slip Standard")

	def test_a_clients_default_survives_migrate(self):
		self._client_default("Salary Slip Standard")
		sync_fixtures("royce_payroll_ke")
		self.assertEqual(frappe.db.get_value("Property Setter", PS_FILTERS, "value"), "Salary Slip Standard")

	def test_payslip_is_a_standard_format(self):
		self.assertEqual(frappe.db.get_value("Print Format", PRINT_FORMAT, "standard"), "Yes")

	def test_template_parses(self):
		path = frappe.get_app_path("royce_payroll_ke", "kenya_payroll", "print_format", "kenya_payslip", "kenya_payslip.html")
		with open(path) as f:
			frappe.get_jenv().from_string(f.read())
