# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Tests for the two things Payroll Rates guarantees on its own: that
validate() rejects a record whose bands don't actually form a consistent
KRA band table, and that get_effective() picks the right version for a
given date. Both are the safety net that stops a malformed or
wrongly-dated rates record — the kind that would silently miscalculate
PAYE for every employee on every company on the site — from ever being
saved or ever being picked up by the generator."""

import frappe
from frappe.tests import IntegrationTestCase

from royce_payroll_ke.royce_payroll_ke.doctype.payroll_rates.payroll_rates import PayrollRates
from royce_payroll_ke.royce_payroll_ke.tests.utils import make_test_payroll_rates

VALID_BANDS = [
	{"band_number": 1, "lower_bound": 0, "upper_bound": 24000, "rate": 10},
	{"band_number": 2, "lower_bound": 24000, "upper_bound": 32333, "rate": 25},
	{"band_number": 3, "lower_bound": 32333, "upper_bound": 500000, "rate": 30},
	{"band_number": 4, "lower_bound": 500000, "upper_bound": 800000, "rate": 32.5},
	{"band_number": 5, "lower_bound": 800000, "upper_bound": None, "rate": 35},
]


def _bands(row_overrides):
	"""A fresh copy of VALID_BANDS with one or more rows patched by
	band_number, e.g. _bands({1: {"lower_bound": 100}}) overrides just band
	1's lower_bound. Takes a plain dict (not **kwargs) since band_number is
	an int and can't be a keyword-argument name."""
	bands = [dict(row) for row in VALID_BANDS]
	for band_number, changes in row_overrides.items():
		for row in bands:
			if row["band_number"] == band_number:
				row.update(changes)
	return bands


class TestPayrollRates(IntegrationTestCase):
	def test_valid_rates_record_submits(self):
		doc = make_test_payroll_rates("1980-01-01")
		self.assertEqual(doc.docstatus, 1)

	def test_rejects_wrong_band_count(self):
		bands = [VALID_BANDS[0], {**VALID_BANDS[1], "upper_bound": None}]
		with self.assertRaises(frappe.ValidationError):
			make_test_payroll_rates("1980-02-01", paye_bands=bands)

	def test_rejects_duplicate_or_missing_band_numbers(self):
		bands = _bands({3: {"band_number": 2}})  # band 3 relabelled as 2 — no 3, two 2s
		with self.assertRaises(frappe.ValidationError):
			make_test_payroll_rates("1980-03-01", paye_bands=bands)

	def test_rejects_band1_lower_bound_nonzero(self):
		bands = _bands({1: {"lower_bound": 100}})
		with self.assertRaises(frappe.ValidationError):
			make_test_payroll_rates("1980-04-01", paye_bands=bands)

	def test_rejects_non_contiguous_bands(self):
		bands = _bands({2: {"lower_bound": 25000}})  # gap: band 1 ends at 24000
		with self.assertRaises(frappe.ValidationError):
			make_test_payroll_rates("1980-05-01", paye_bands=bands)

	def test_rejects_last_band_with_upper_bound(self):
		bands = _bands({5: {"upper_bound": 900000}})
		with self.assertRaises(frappe.ValidationError):
			make_test_payroll_rates("1980-06-01", paye_bands=bands)

	def test_rejects_intermediate_band_missing_upper_bound(self):
		bands = _bands({2: {"upper_bound": None}})  # band 2 isn't the last band
		with self.assertRaises(frappe.ValidationError):
			make_test_payroll_rates("1980-07-01", paye_bands=bands)

	def test_rejects_rate_out_of_range(self):
		bands = _bands({1: {"rate": 110}})
		with self.assertRaises(frappe.ValidationError):
			make_test_payroll_rates("1980-08-01", paye_bands=bands)

	def test_rejects_nssf_tier_ii_not_greater_than_tier_i(self):
		with self.assertRaises(frappe.ValidationError):
			make_test_payroll_rates("1980-09-01", nssf_tier_i_limit=9000, nssf_tier_ii_limit=9000)

	def test_get_effective_picks_latest_submitted_enabled_on_or_before_date(self):
		make_test_payroll_rates("1990-01-01")
		make_test_payroll_rates("1991-01-01")
		disabled = make_test_payroll_rates("1992-01-01")
		disabled.db_set("disabled", 1)
		make_test_payroll_rates("1993-01-01", submit=False)  # draft — must never be picked

		self.assertEqual(PayrollRates.get_effective("1990-06-01"), "1990-01-01")
		self.assertEqual(PayrollRates.get_effective("1991-06-01"), "1991-01-01")
		# 1992's record exists and is on/before this date but is disabled —
		# 1991 should still win, not None and not 1992.
		self.assertEqual(PayrollRates.get_effective("1992-06-01"), "1991-01-01")
		# 1993's record is a draft — must never be picked, disabled or not.
		self.assertEqual(PayrollRates.get_effective("1999-01-01"), "1991-01-01")
		self.assertIsNone(PayrollRates.get_effective("1989-01-01"))
