# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""The Kenya statutory engine (engine.py).

TestCompute: the rules, as a table of hand-checked cases against the 2026 rates
(no database). Every expected figure below is worked out by hand in the comment
next to it, so a reader can check the arithmetic without running anything.

TestEngineOnRealSlips: the same engine through HRMS's real Salary Slip, for what
only a real slip can show (part-month pay, Additional Salary rows)."""

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from royce_payroll_ke.kenya_payroll.engine import (
	INSURANCE_PREMIUM,
	MEALS,
	MORTGAGE_INTEREST,
	PENSION,
	PRMF,
	SECONDARY,
	Deduction,
	Earning,
	TaxProfile,
	band_tax,
	compute,
)
from royce_payroll_ke.kenya_payroll.setup import provision
from royce_payroll_ke.kenya_payroll.tests.utils import (
	DEFAULT_RATES,
	get_test_company,
	make_test_kenya_payroll_rates,
	make_test_payslip,
)


def rates_2026():
	values = {k: v for k, v in DEFAULT_RATES.items() if k != "paye_bands"}
	return frappe._dict(
		values,
		paye_bands=[frappe._dict(b, upper_bound=b["upper_bound"] or 0) for b in DEFAULT_RATES["paye_bands"]],
	)


def pay(amount, **flags):
	"""Ordinary taxable pay that counts for NSSF, SHIF and Housing Levy, unless told otherwise."""
	return Earning(amount=amount, **flags)


def not_pay(amount, **flags):
	"""A reimbursement: not taxable, no statutory charges."""
	return Earning(**{"amount": amount, "taxable": False, "nssf": False, "shif": False, "housing_levy": False, **flags})


class TestCompute(UnitTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.rates = rates_2026()

	def run_case(self, earnings, deductions=None, profile=None):
		return compute(earnings, deductions or [], profile or TaxProfile(), self.rates)

	def test_band_edges(self):
		bands = self.rates.paye_bands
		self.assertEqual(band_tax(24000, bands), 2400)  # 24,000 x 10%
		self.assertEqual(band_tax(32333, bands), 4483.25)  # + 8,333 x 25% = 2,083.25
		self.assertEqual(band_tax(500000, bands), 144783.35)  # + 467,667 x 30% = 140,300.10
		self.assertEqual(band_tax(800000, bands), 242283.35)  # + 300,000 x 32.5% = 97,500
		self.assertEqual(band_tax(1000000, bands), 312283.35)  # + 200,000 x 35% = 70,000
		self.assertEqual(band_tax(0, bands), 0)

	def test_guides_worked_example(self):
		# Gross 187,550. NSSF 540 + 5,940; SHIF 5,157.625 -> 5,158; AHL 2,813.25 -> 2,813.
		# Taxable 187,550 - 6,480 - 5,158 - 2,813 = 173,099.
		# Tax 4,483.25 + (173,099 - 32,333) x 30% = 46,713.05; less 2,400 = 44,313.05 -> 44,313.
		r = self.run_case([pay(187550)])
		self.assertEqual((r.nssf_tier_i, r.nssf_tier_ii, r.shif, r.housing_levy), (540, 5940, 5158, 2813))
		self.assertEqual(r.taxable_pay, 173099)
		self.assertEqual(r.tax_charged, 46713.05)
		self.assertEqual(r.paye, 44313)
		# Employer: NSSF on the capped base 108,000 x 6%; AHL 1.5%; NITA flat.
		self.assertEqual((r.nssf_employer, r.housing_levy_employer, r.nita), (6480, 2813, 50))

	def test_low_earner_gets_shif_minimum_and_pays_no_paye(self):
		# Gross 8,000: NSSF 480; SHIF 220 -> minimum 300; AHL 120; taxable 7,100; tax 710.
		# Relief applied is capped at the tax (710), so PAYE is 0, never negative.
		r = self.run_case([pay(8000)])
		self.assertEqual((r.nssf_tier_i, r.nssf_tier_ii, r.shif, r.housing_levy), (480, 0, 300, 120))
		self.assertEqual(r.taxable_pay, 7100)
		self.assertEqual(r.personal_relief, 710)
		self.assertEqual(r.paye, 0)

	def test_pension_pool_is_capped(self):
		# Gross 500,000 + pension scheme 40,000. Pool 6,480 + 40,000 = 46,480 -> 30,000.
		# SHIF 13,750; AHL 7,500. Taxable 500,000 - 30,000 - 13,750 - 7,500 = 448,750.
		# Tax 4,483.25 + 416,417 x 30% = 129,408.35; PAYE 127,008.35 -> 127,008.
		r = self.run_case([pay(500000)], [Deduction(40000, PENSION)])
		self.assertEqual(r.pension_allowed, 30000)
		self.assertEqual(r.taxable_pay, 448750)
		self.assertEqual(r.paye, 127008)

	def test_prmf_and_mortgage_are_capped(self):
		# Gross 300,000: NSSF 6,480; SHIF 8,250; AHL 4,500. PRMF 20,000 -> 15,000.
		# Mortgage declared 25,000 + deducted 10,000 = 35,000 -> 30,000.
		# Taxable 300,000 - 6,480 - 15,000 - 30,000 - 8,250 - 4,500 = 235,770.
		r = self.run_case(
			[pay(300000)],
			[Deduction(20000, PRMF), Deduction(10000, MORTGAGE_INTEREST)],
			TaxProfile(mortgage_interest=25000),
		)
		self.assertEqual(r.prmf_allowed, 15000)
		self.assertEqual(r.mortgage_interest_allowed, 30000)
		self.assertEqual(r.taxable_pay, 235770)

	def test_insurance_relief_is_capped(self):
		# Gross 100,000: NSSF 6,000; SHIF 2,750; AHL 1,500; taxable 89,750.
		# Tax 4,483.25 + 57,417 x 30% = 21,708.35. Premiums 50,000 x 15% = 7,500 -> 5,000.
		# PAYE 21,708.35 - 2,400 - 5,000 = 14,308.35 -> 14,308.
		r = self.run_case([pay(100000)], profile=TaxProfile(insurance_premium=50000))
		self.assertEqual(r.insurance_relief, 5000)
		self.assertEqual(r.paye, 14308)

	def test_insurance_relief_from_a_payroll_deduction(self):
		# Same pay, premium 10,000 deducted through payroll: relief 1,500.
		r = self.run_case([pay(100000)], [Deduction(10000, INSURANCE_PREMIUM)])
		self.assertEqual(r.insurance_relief, 1500)
		self.assertEqual(r.paye, 17808)  # 21,708.35 - 2,400 - 1,500 = 17,808.35

	def test_secondary_employment(self):
		# Gross 50,000: NSSF 540 + 2,460; SHIF 1,375; AHL 750; taxable 44,875.
		# Flat 35%, no personal relief: 15,706.25 -> 15,706.
		r = self.run_case([pay(50000)], profile=TaxProfile(category=SECONDARY))
		self.assertEqual(r.taxable_pay, 44875)
		self.assertEqual(r.personal_relief, 0)
		self.assertEqual(r.paye, 15706)

	def test_disability_exemption(self):
		# Gross 180,000: NSSF 6,480; SHIF 4,950; AHL 2,700; 165,870 before exemption.
		# Less 150,000 = 15,870; tax 1,587; relief covers it; PAYE 0.
		r = self.run_case([pay(180000)], profile=TaxProfile(disability_exempt_amount=150000))
		self.assertEqual(r.disability_exemption, 150000)
		self.assertEqual(r.taxable_pay, 15870)
		self.assertEqual(r.paye, 0)

	def test_reimbursement_changes_nothing(self):
		base = self.run_case([pay(60000)])
		with_reimbursement = self.run_case([pay(60000), not_pay(10000)])
		for attr in ("nssf_tier_i", "nssf_tier_ii", "shif", "housing_levy", "taxable_pay", "paye"):
			self.assertEqual(getattr(base, attr), getattr(with_reimbursement, attr), attr)

	def test_non_cash_benefits_below_threshold_are_tax_free(self):
		base = self.run_case([pay(60000)])
		below = self.run_case([pay(60000), not_pay(4999, non_cash=True)])
		at = self.run_case([pay(60000), not_pay(5000, non_cash=True)])
		self.assertEqual(below.taxable_pay, base.taxable_pay)
		self.assertEqual(at.taxable_non_cash_pay, 5000)
		self.assertEqual(at.taxable_pay, base.taxable_pay + 5000)

	def test_meals_tax_free_up_to_the_limit(self):
		base = self.run_case([pay(60000)])
		meals = self.run_case([pay(60000), not_pay(7000, taxable=True, tax_free_allowance=MEALS)])
		self.assertEqual(meals.taxable_pay, base.taxable_pay + 2000)  # 7,000 - 5,000

	def test_nssf_only_on_pensionable_pay(self):
		# A taxable commission that the client marked as not pensionable.
		r = self.run_case([pay(20000), pay(30000, nssf=False)])
		self.assertEqual(r.nssf_base, 20000)
		self.assertEqual(r.nssf_tier_ii, 660)  # (20,000 - 9,000) x 6%
		self.assertEqual(r.shif_base, 50000)

	def test_no_pay_no_charges(self):
		r = self.run_case([])
		self.assertEqual(
			(r.nssf_tier_i, r.shif, r.housing_levy, r.paye, r.nssf_employer, r.nita), (0, 0, 0, 0, 0, 0)
		)


class TestEngineOnRealSlips(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.rates = make_test_kenya_payroll_rates("1981-01-01")

	def _amount(self, slip, table, component):
		return sum(r.amount for r in slip.get(table) if r.salary_component == component)

	def test_mid_month_joiner_keeps_full_shif_minimum(self):
		# June 1981, 30 days, no holidays; joins on the 16th: 15 of 30 days paid.
		# Base 8,000 -> full-month gross 10,000, paid 5,000. NSSF 300; SHIF 137.50 -> 300
		# (the minimum is not halved); AHL 75. Before v16.4.0 HRMS halved SHIF to 150.
		_employee, slip = make_test_payslip(
			self.company,
			self.rates,
			"royce.payroll.joiner@example.com",
			base=8000,
			posting_date="1981-06-30",
			period_start="1981-06-01",
			period_end="1981-06-30",
			joining_date="1981-06-16",
		)
		self.assertEqual(slip.payment_days, 15)
		self.assertEqual(slip.gross_pay, 5000)
		self.assertEqual(self._amount(slip, "deductions", "NSSF Tier I - Employee"), 300)
		self.assertEqual(self._amount(slip, "deductions", "SHIF"), 300)
		self.assertEqual(self._amount(slip, "deductions", "Housing Levy"), 75)
		self.assertEqual(slip.royce_taxable_pay, 4325)  # 5,000 - 300 - 300 - 75
		self.assertEqual(self._amount(slip, "deductions", "PAYE"), 0)

	def test_high_earner_mid_month_nssf_on_actual_pay(self):
		# Base 150,000 -> full gross 187,500; joins on the 16th: paid 93,750.
		# NSSF on actual pay: 540 + (93,750 - 9,000) x 6% = 5,625 (pro-rating the
		# full-month 6,480 would give 3,240).
		_employee, slip = make_test_payslip(
			self.company,
			self.rates,
			"royce.payroll.joiner2@example.com",
			base=150000,
			posting_date="1981-06-30",
			period_start="1981-06-01",
			period_end="1981-06-30",
			joining_date="1981-06-16",
		)
		self.assertEqual(slip.gross_pay, 93750)
		nssf = self._amount(slip, "deductions", "NSSF Tier I - Employee") + self._amount(
			slip, "deductions", "NSSF Tier II - Employee"
		)
		self.assertEqual(nssf, 5625)

	def test_working_is_saved_on_the_slip(self):
		_employee, slip = make_test_payslip(
			self.company,
			self.rates,
			"royce.payroll.working@example.com",
			base=150000,
			posting_date="1981-07-31",
			period_start="1981-07-01",
			period_end="1981-07-31",
		)
		self.assertEqual(slip.royce_kenya_payroll_rates, self.rates.name)
		self.assertEqual(slip.royce_tax_category, "Primary Employment")
		paye = self._amount(slip, "deductions", "PAYE")
		self.assertEqual(paye, round(slip.royce_tax_charged - slip.royce_personal_relief))

	def test_pre_v16_4_structure_rows_are_overwritten(self):
		"""A structure built before v16.4.0 still carries formula rows for the statutory
		components (here: SHIF depending on payment days, and a PAYE formula). The
		v16_4 patch marks it as a Kenya structure; the engine must replace those rows'
		amounts, not add second rows next to them."""
		company = get_test_company("Royce Payroll Legacy Co", "RPLC")
		provision(company, rates=self.rates.name)
		structure = frappe.new_doc("Salary Structure")
		structure.name = "RPLC Legacy Structure"
		structure.company = company
		structure.currency = "KES"
		structure.payroll_frequency = "Monthly"
		structure.royce_kenya_statutory = 1
		structure.append("earnings", {"salary_component": "Basic Salary", "abbr": "Basic",
			"amount_based_on_formula": 1, "formula": "base", "depends_on_payment_days": 1})
		structure.append("deductions", {"salary_component": "SHIF", "abbr": "SHIF",
			"amount_based_on_formula": 1, "formula": "gross_pay * 0.0275", "depends_on_payment_days": 1})
		structure.append("deductions", {"salary_component": "PAYE", "abbr": "PAYE",
			"amount_based_on_formula": 1, "formula": "1000"})
		structure.insert(ignore_permissions=True)
		structure.submit()

		# Base 10,000, joins on the 16th: paid 5,000. The old SHIF row alone would give
		# 10,000 x 2.75% halved = 137.50; the engine gives the 300 minimum. Taxable
		# 5,000 - 300 - 300 - 75 = 4,325, so the old PAYE row's 1,000 is gone.
		_employee, slip = make_test_payslip(
			company,
			self.rates,
			"royce.payroll.legacy@example.com",
			base=10000,
			posting_date="1981-09-30",
			period_start="1981-09-01",
			period_end="1981-09-30",
			joining_date="1981-09-16",
			structure_name=structure.name,
		)
		self.assertEqual(slip.gross_pay, 5000)
		self.assertEqual([r.amount for r in slip.deductions if r.salary_component == "SHIF"], [300])
		self.assertEqual([r for r in slip.deductions if r.salary_component == "PAYE"], [])
		self.assertEqual(self._amount(slip, "deductions", "NSSF Tier I - Employee"), 300)
