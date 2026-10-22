# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""The Kenya statutory engine: NSSF, SHIF, Housing Levy, taxable pay and PAYE for one
Salary Slip, calculated monthly (never annualised).

HRMS calls SalarySlip.apply_regional_deductions() after earnings and deductions are
evaluated and before totals and net pay are set; hooks.py's `regional_overrides` points
it here for Kenya. Spec: docs/taxable-income-engine.md.

Two layers, on purpose:
  compute()                - pure arithmetic over plain inputs. No database, so the
                             statutory rules are tested with a table of cases.
  apply_kenya_statutory()  - reads a real slip into those inputs, calls compute(), and
                             writes the statutory rows and the PAYE working back.
"""

from dataclasses import dataclass, field

import frappe
from frappe import _
from frappe.utils import flt, getdate, rounded

# Salary Components the generator (setup.py) owns and this engine fills. Names, not
# abbreviations: a client can rename an abbreviation, not the component it belongs to.
NSSF_TIER_I = "NSSF Tier I - Employee"
NSSF_TIER_II = "NSSF Tier II - Employee"
SHIF = "SHIF"
HOUSING_LEVY = "Housing Levy"
PAYE = "PAYE"
NSSF_EMPLOYER = "NSSF Employer"
HOUSING_LEVY_EMPLOYER = "Housing Levy Employer"
NITA = "NITA"

STATUTORY_DEDUCTIONS = (NSSF_TIER_I, NSSF_TIER_II, SHIF, HOUSING_LEVY, PAYE)
EMPLOYER_EARNINGS = (NSSF_EMPLOYER, HOUSING_LEVY_EMPLOYER, NITA)

# royce_kenya_deduction_type options on a deduction Salary Component.
PENSION = "Pension Contribution"
PRMF = "Post-Retirement Medical Fund"
MORTGAGE_INTEREST = "Mortgage Interest"
INSURANCE_PREMIUM = "Insurance Premium"

# royce_tax_free_allowance options on an earning Salary Component.
MEALS = "Meals"

PRIMARY = "Primary Employment"
SECONDARY = "Secondary Employment"

# Saved on the Salary Slip (Kenya PAYE section), read by the payslip, P9A and P10A.
RESULT_FIELDS = {
	"royce_tax_category": "tax_category",
	"royce_taxable_cash_pay": "taxable_cash_pay",
	"royce_taxable_non_cash_pay": "taxable_non_cash_pay",
	"royce_pension_allowed": "pension_allowed",
	"royce_prmf_allowed": "prmf_allowed",
	"royce_mortgage_interest_allowed": "mortgage_interest_allowed",
	"royce_disability_exempted": "disability_exemption",
	"royce_taxable_pay": "taxable_pay",
	"royce_tax_charged": "tax_charged",
	"royce_personal_relief": "personal_relief",
	"royce_insurance_relief": "insurance_relief",
}


@dataclass
class Earning:
	amount: float
	taxable: bool = True
	nssf: bool = True
	shif: bool = True
	housing_levy: bool = True
	non_cash: bool = False
	tax_free_allowance: str = ""
	basic: bool = False  # mapped to P9A "Basic Salary": the base of the 30% pension limit


@dataclass
class Deduction:
	amount: float
	kind: str = ""


@dataclass
class TaxProfile:
	category: str = PRIMARY
	disability_exempt_amount: float = 0
	mortgage_interest: float = 0
	insurance_premium: float = 0


@dataclass
class Result:
	tax_category: str = PRIMARY
	nssf_base: float = 0
	shif_base: float = 0
	housing_levy_base: float = 0
	nssf_tier_i: float = 0
	nssf_tier_ii: float = 0
	shif: float = 0
	housing_levy: float = 0
	taxable_cash_pay: float = 0
	taxable_non_cash_pay: float = 0
	pension_allowed: float = 0
	prmf_allowed: float = 0
	mortgage_interest_allowed: float = 0
	disability_exemption: float = 0
	taxable_pay: float = 0
	tax_charged: float = 0
	personal_relief: float = 0
	insurance_relief: float = 0
	paye: float = 0
	nssf_employer: float = 0
	housing_levy_employer: float = 0
	nita: float = 0
	notes: list = field(default_factory=list)


def _pct(value) -> float:
	return flt(value) / 100


def _whole(value) -> float:
	"""Statutory deductions are charged in whole shillings, matching the generator's
	round_to_the_nearest_integer on every statutory component."""
	return flt(rounded(flt(value, 2)))


def band_tax(taxable_pay: float, bands) -> float:
	"""Graduated monthly tax over the Kenya Payroll Rates bands (contiguous, last one
	open-ended, as KenyaPayrollRates.validate_paye_bands() guarantees)."""
	tax, previous = 0.0, 0.0
	for band in sorted(bands, key=lambda b: b.band_number):
		upper = flt(band.upper_bound) or float("inf")
		portion = min(taxable_pay, upper) - previous
		if portion <= 0:
			break
		tax += portion * _pct(band.rate)
		previous = upper
	return flt(tax, 2)


def compute(earnings: list[Earning], deductions: list[Deduction], profile: TaxProfile, rates) -> Result:
	"""One month's statutory deductions and PAYE.

	`earnings` are the slip's actual (already part-month adjusted) pay rows, excluding
	statistical and employer-contribution rows. `deductions` are the slip's other
	deductions (loans, pension, insurance...), excluding the statutory rows this
	engine produces. `rates` is a Kenya Payroll Rates record (or anything with the same
	attributes). Limits and minimums apply in full in a part month: KRA, NSSF and SHA
	charge on what was actually paid this month, they don't pro-rate their limits.
	"""
	r = Result(tax_category=profile.category or PRIMARY)

	# 1. Earnings: taxable cash pay, non-cash benefits, and the three statutory bases.
	cash, non_cash, basic = 0.0, 0.0, 0.0
	for e in earnings:
		if e.basic:
			basic += flt(e.amount)
		amount = flt(e.amount)
		if e.non_cash:
			non_cash += amount
		elif e.taxable:
			if e.tax_free_allowance == MEALS:
				amount = max(0.0, amount - flt(rates.meals_tax_free_limit))
			cash += amount
		if e.nssf:
			r.nssf_base += flt(e.amount)
		if e.shif:
			r.shif_base += flt(e.amount)
		if e.housing_levy:
			r.housing_levy_base += flt(e.amount)

	r.taxable_cash_pay = flt(cash, 2)
	# Benefits are tax-free while their total doesn't exceed the threshold; above it, all
	# of it is taxable (KRA PAYE guide 2025/26: "non-cash benefits (exceeding Kshs 5,000
	# per month)").
	r.taxable_non_cash_pay = flt(non_cash, 2) if non_cash > flt(rates.non_cash_benefit_threshold) else 0.0

	# 2-4. NSSF, SHIF, Housing Levy (employee).
	lel, uel = flt(rates.nssf_tier_i_limit), flt(rates.nssf_tier_ii_limit)
	r.nssf_tier_i = _whole(min(r.nssf_base, lel) * _pct(rates.nssf_employee_rate))
	r.nssf_tier_ii = _whole(max(0.0, min(r.nssf_base, uel) - lel) * _pct(rates.nssf_employee_rate))
	if r.shif_base > 0:
		r.shif = _whole(max(flt(rates.shif_minimum), r.shif_base * _pct(rates.shif_rate)))
	r.housing_levy = _whole(r.housing_levy_base * _pct(rates.ahl_employee_rate))

	# 5. Capped deductions allowed before tax.
	by_kind = {}
	for d in deductions:
		if d.kind:
			by_kind[d.kind] = by_kind.get(d.kind, 0.0) + flt(d.amount)

	pension = r.nssf_tier_i + r.nssf_tier_ii + by_kind.get(PENSION, 0.0)
	# P9A column E: the lowest of 30% of basic salary (E1), actual contributions (E2) and
	# the fixed limit (E3, 30,000 a month from December 2024). KRA P9A template 2025.
	pension_limits = [flt(rates.pension_deduction_limit)]
	# Skipped when no earning is mapped as Basic Salary (a client's own structure), rather
	# than read as a basic of 0, which would disallow every pension contribution.
	if basic > 0 and flt(rates.pension_limit_percent_of_basic):
		pension_limits.append(basic * _pct(rates.pension_limit_percent_of_basic))
	r.pension_allowed = flt(min(pension, *pension_limits), 2)
	r.prmf_allowed = min(by_kind.get(PRMF, 0.0), flt(rates.prmf_deduction_limit))
	mortgage = flt(profile.mortgage_interest) + by_kind.get(MORTGAGE_INTEREST, 0.0)
	r.mortgage_interest_allowed = min(mortgage, flt(rates.mortgage_interest_limit))

	# 6. Taxable pay.
	taxable = (
		r.taxable_cash_pay
		+ r.taxable_non_cash_pay
		- r.pension_allowed
		- r.prmf_allowed
		- r.mortgage_interest_allowed
		- r.shif
		- r.housing_levy
	)
	taxable = max(0.0, taxable)
	if flt(profile.disability_exempt_amount) > 0:
		r.disability_exemption = min(taxable, flt(profile.disability_exempt_amount))
		taxable -= r.disability_exemption
	r.taxable_pay = flt(taxable, 2)

	# 7-9. Tax charged, reliefs, PAYE.
	if r.tax_category == SECONDARY:
		r.tax_charged = flt(r.taxable_pay * _pct(rates.secondary_employment_rate), 2)
	else:
		r.tax_charged = band_tax(r.taxable_pay, rates.paye_bands)
		r.personal_relief = min(flt(rates.personal_relief), r.tax_charged)

	premiums = flt(profile.insurance_premium) + by_kind.get(INSURANCE_PREMIUM, 0.0)
	insurance_relief = min(premiums * _pct(rates.insurance_relief_rate), flt(rates.insurance_relief_limit))
	r.insurance_relief = flt(min(insurance_relief, r.tax_charged - r.personal_relief), 2)
	r.paye = _whole(max(0.0, r.tax_charged - r.personal_relief - r.insurance_relief))

	# 10. Employer side, on the same bases as the employee's.
	r.nssf_employer = _whole(min(r.nssf_base, uel) * _pct(rates.nssf_employer_rate))
	r.housing_levy_employer = _whole(r.housing_levy_base * _pct(rates.ahl_employer_rate))
	r.nita = flt(rates.nita_amount) if r.nssf_base > 0 or r.taxable_cash_pay > 0 else 0.0

	return r


# ---------------------------------------------------------------------------
# Salary Slip integration
# ---------------------------------------------------------------------------


def is_kenya_structure(salary_structure) -> bool:
	return bool(
		salary_structure
		and frappe.get_cached_value("Salary Structure", salary_structure, "royce_kenya_statutory")
	)


def apply_kenya_statutory(slip):
	"""regional_overrides target for SalarySlip.apply_regional_deductions (Kenya).

	Leaves any slip whose structure isn't a Kenya Payroll structure untouched, so a
	site's other structures keep HRMS's default behaviour."""
	if not is_kenya_structure(slip.salary_structure):
		return

	from royce_payroll_ke.kenya_payroll.doctype.kenya_payroll_rates.kenya_payroll_rates import (
		KenyaPayrollRates,
	)

	period_date = slip.end_date or slip.start_date
	rates_name = KenyaPayrollRates.get_effective(period_date)
	if not rates_name:
		frappe.throw(
			_("No submitted Kenya Payroll Rates record is effective on {0}. Create one before running payroll.").format(
				frappe.format(getdate(period_date), "Date")
			),
			title=_("Kenya Payroll Rates missing"),
		)
	rates = frappe.get_cached_doc("Kenya Payroll Rates", rates_name)

	result = compute(
		_slip_earnings(slip),
		_slip_deductions(slip),
		_tax_profile(slip.employee, rates, slip.start_date),
		rates,
	)

	_set_row(slip, "deductions", NSSF_TIER_I, result.nssf_tier_i)
	_set_row(slip, "deductions", NSSF_TIER_II, result.nssf_tier_ii)
	_set_row(slip, "deductions", SHIF, result.shif)
	_set_row(slip, "deductions", HOUSING_LEVY, result.housing_levy)
	_set_row(slip, "deductions", PAYE, result.paye)
	for component, amount in (
		(NSSF_EMPLOYER, result.nssf_employer),
		(HOUSING_LEVY_EMPLOYER, result.housing_levy_employer),
		(NITA, result.nita),
	):
		_set_employer_row(slip, component, amount)

	meta = slip.meta
	for fieldname, attr in RESULT_FIELDS.items():
		if meta.has_field(fieldname):
			slip.set(fieldname, getattr(result, attr))
	if meta.has_field("royce_kenya_payroll_rates"):
		slip.royce_kenya_payroll_rates = rates_name


def validate_salary_component(doc, method=None):
	"""A non-cash benefit is never paid in cash: if it counted in the total it would be
	added to net pay and paid out."""
	if doc.type == "Earning" and doc.get("royce_non_cash_benefit") and not doc.do_not_include_in_total:
		frappe.throw(
			_("{0} is a Non-Cash Benefit, so it must also have Do Not Include in Total ticked. Otherwise it would be paid out in net pay.").format(
				frappe.bold(doc.name or doc.salary_component)
			),
			title=_("Non-cash benefit paid in cash"),
		)


def _component_flags(component) -> frappe._dict:
	return frappe._dict(
		frappe.get_cached_value(
			"Salary Component",
			component,
			[
				"is_tax_applicable",
				"royce_nssf_pensionable",
				"royce_shif_applicable",
				"royce_ahl_applicable",
				"royce_non_cash_benefit",
				"royce_tax_free_allowance",
				"royce_kenya_deduction_type",
				"royce_p9a_tax_deduction_card_type",
			],
			as_dict=True,
		)
		or {}
	)


def _slip_earnings(slip) -> list[Earning]:
	earnings = []
	for row in slip.get("earnings") or []:
		if row.statistical_component or row.salary_component in EMPLOYER_EARNINGS:
			continue
		flags = _component_flags(row.salary_component)
		# A row left out of the total is not pay (an informational line), unless it's a
		# non-cash benefit: those are never paid in cash but are still taxable.
		if row.do_not_include_in_total and not flags.royce_non_cash_benefit:
			continue
		earnings.append(
			Earning(
				amount=flt(row.amount),
				taxable=bool(row.is_tax_applicable),
				nssf=bool(flags.royce_nssf_pensionable),
				shif=bool(flags.royce_shif_applicable),
				housing_levy=bool(flags.royce_ahl_applicable),
				non_cash=bool(flags.royce_non_cash_benefit),
				tax_free_allowance=flags.royce_tax_free_allowance or "",
				basic=flags.royce_p9a_tax_deduction_card_type == "Basic Salary",
			)
		)
	return earnings


def _slip_deductions(slip) -> list[Deduction]:
	deductions = []
	for row in slip.get("deductions") or []:
		if row.statistical_component or row.salary_component in STATUTORY_DEDUCTIONS:
			continue
		kind = _component_flags(row.salary_component).royce_kenya_deduction_type or ""
		deductions.append(Deduction(amount=flt(row.amount), kind=kind))
	return deductions


def _tax_profile(employee, rates, period_start) -> TaxProfile:
	if not employee:
		return TaxProfile()
	emp = frappe.db.get_value(
		"Employee",
		employee,
		[
			"royce_tax_category",
			"royce_disability_exemption",
			"royce_disability_certificate_expiry",
			"royce_disability_exempt_amount",
			"royce_mortgage_interest",
			"royce_insurance_premium",
		],
		as_dict=True,
	) or frappe._dict()

	exempt = 0.0
	expiry = emp.royce_disability_certificate_expiry
	if emp.royce_disability_exemption and (not expiry or getdate(expiry) >= getdate(period_start)):
		exempt = flt(emp.royce_disability_exempt_amount) or flt(rates.disability_exemption_amount)

	return TaxProfile(
		category=emp.royce_tax_category or PRIMARY,
		disability_exempt_amount=exempt,
		mortgage_interest=flt(emp.royce_mortgage_interest),
		insurance_premium=flt(emp.royce_insurance_premium),
	)


def _set_employer_row(slip, component, amount):
	"""Employer contributions go to HRMS's own Employer Contributions section (v16.5.0+:
	the components are of type Employer Contribution, posted to their own expense and
	liability accounts). A structure from before v16.5.0 may still list them as earnings
	left out of the total; those rows are dropped, never paid and never posted twice."""
	component_type = frappe.get_cached_value("Salary Component", component, "type")
	if component_type == "Employer Contribution" and slip.meta.has_field("employer_contributions"):
		for row in [d for d in slip.get("earnings") or [] if d.salary_component == component]:
			slip.remove(row)
		_set_row(slip, "employer_contributions", component, amount)
	else:
		_set_row(slip, "earnings", component, amount)


def _set_row(slip, parentfield, component, amount):
	"""Write one engine-owned row. Done here rather than through HRMS's
	update_component_row(), which re-applies payment-days proration to a row that
	depends on payment days: these amounts are already computed on the month's actual
	pay, and pro-rating them again is exactly the part-month bug this engine fixes
	(SHIF's 300 minimum becoming 150, NSSF limits halved)."""
	rows = [
		d
		for d in slip.get(parentfield) or []
		if d.salary_component == component and not d.get("additional_salary")
	]
	row = rows[0] if rows else None
	for extra in rows[1:]:
		slip.remove(extra)

	if not amount:
		if row:
			slip.remove(row)
		return

	if not row:
		if not frappe.db.exists("Salary Component", component):
			return
		data = frappe.get_cached_value(
			"Salary Component",
			component,
			["salary_component_abbr", "do_not_include_in_total", "do_not_include_in_accounts", "is_tax_applicable"],
			as_dict=True,
		)
		row = slip.append(parentfield)
		row.salary_component = component
		row.abbr = data.salary_component_abbr
		row.do_not_include_in_total = data.do_not_include_in_total
		row.do_not_include_in_accounts = data.do_not_include_in_accounts
		row.is_tax_applicable = data.is_tax_applicable

	row.depends_on_payment_days = 0
	row.default_amount = amount
	row.additional_amount = 0
	row.amount = amount
