# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class PayrollRates(Document):
	"""Source of truth for Kenyan statutory payroll rates.

	One record per Finance Act / rate change, keyed by ``effective_from``.
	Nothing here is applied automatically to existing Salary Components —
	the generator (not yet built) reads a Payroll Rates record and writes
	the resulting formulas onto the 22 components. This doctype only
	guarantees the numbers it holds are internally consistent.
	"""

	def validate(self):
		self.validate_paye_bands()
		self.validate_nssf_tiers()

	def validate_paye_bands(self):
		bands = sorted(self.paye_bands, key=lambda row: row.band_number)

		if len(bands) != 5:
			frappe.throw(
				_("PAYE Bands must have exactly 5 rows (KRA's current band structure has 5). Found {0}.").format(
					len(bands)
				)
			)

		if [row.band_number for row in bands] != [1, 2, 3, 4, 5]:
			frappe.throw(_("PAYE Bands must be numbered 1 through 5, one row each."))

		if flt(bands[0].lower_bound) != 0:
			frappe.throw(_("Band 1's Lower Bound must be 0."))

		for previous, current in zip(bands, bands[1:]):
			if not previous.upper_bound:
				frappe.throw(
					_("Band {0} is missing an Upper Bound — only Band 5 (the last band) may be open-ended.").format(
						previous.band_number
					)
				)
			if flt(current.lower_bound) != flt(previous.upper_bound):
				frappe.throw(
					_(
						"Band {0}'s Lower Bound ({1}) must equal Band {2}'s Upper Bound ({3}) —"
						" bands must be contiguous with no gap or overlap."
					).format(current.band_number, current.lower_bound, previous.band_number, previous.upper_bound)
				)

		if bands[-1].upper_bound:
			frappe.throw(_("Band 5 (the last band) must be open-ended — leave its Upper Bound blank."))

		for row in bands:
			if not (0 <= flt(row.rate) <= 100):
				frappe.throw(_("Band {0}'s Rate must be between 0 and 100.").format(row.band_number))

	def validate_nssf_tiers(self):
		if flt(self.nssf_tier_ii_limit) <= flt(self.nssf_tier_i_limit):
			frappe.throw(_("NSSF Tier II Limit must be greater than NSSF Tier I Limit."))

	@staticmethod
	def get_effective(as_of_date=None):
		"""Return the name of the Payroll Rates record in force on a given date.

		Picks the submitted, non-disabled record with the latest
		``effective_from`` that is on or before ``as_of_date`` (today, if not
		given). Returns None if no such record exists.
		"""
		as_of_date = getdate(as_of_date) if as_of_date else getdate()

		return frappe.db.get_value(
			"Payroll Rates",
			{
				"docstatus": 1,
				"disabled": 0,
				"effective_from": ["<=", as_of_date],
			},
			"name",
			order_by="effective_from desc",
		)
