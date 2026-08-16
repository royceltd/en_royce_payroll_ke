# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

import calendar

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate
from frappe.utils.pdf import get_pdf

from royce_payroll_ke.royce_payroll_ke.doctype.payroll_rates.payroll_rates import PayrollRates
from royce_payroll_ke.royce_payroll_ke.report_utils import card_type_sums


def get_columns():
	return [
		{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 110},
		{"label": _("Basic Salary | A"), "fieldname": "basic_salary", "fieldtype": "Currency", "width": 130},
		{"label": _("Total Gross Pay | D"), "fieldname": "total_gross_pay", "fieldtype": "Currency", "width": 140},
		{
			"label": _("Retirement Scheme (NSSF) | E1"),
			"fieldname": "retirement_scheme",
			"fieldtype": "Currency",
			"width": 180,
		},
		{"label": _("Housing Levy"), "fieldname": "housing_levy", "fieldtype": "Currency", "width": 120},
		{"label": _("SHIF"), "fieldname": "shif", "fieldtype": "Currency", "width": 110},
		{"label": _("Chargeable Pay | H"), "fieldname": "chargeable_pay", "fieldtype": "Currency", "width": 140},
		{"label": _("Tax Charged | I"), "fieldname": "tax_charged", "fieldtype": "Currency", "width": 130},
		{"label": _("Personal Relief | K"), "fieldname": "personal_relief", "fieldtype": "Currency", "width": 140},
		{"label": _("PAYE Tax | L"), "fieldname": "paye_tax", "fieldtype": "Currency", "width": 120},
	]


def month_rows(employee, company, year_start, year_end):
	"""One row per calendar month in the fiscal year, computed from what's
	actually persisted on submitted Salary Slips — no phantom lookups. Months
	with no submitted slip come back as all zeros rather than being skipped,
	matching the real P9A form's fixed 12-row layout."""
	rows = []
	month_date = get_first_day(year_start)
	while month_date <= year_end:
		month_start, month_end = get_first_day(month_date), get_last_day(month_date)

		slips = frappe.get_all(
			"Salary Slip",
			filters={
				"employee": employee,
				"company": company,
				"docstatus": 1,
				"start_date": [">=", month_start],
				"end_date": ["<=", month_end],
			},
			fields=["name", "gross_pay"],
		)

		row = {"month": calendar.month_name[month_date.month]}
		if not slips:
			for col in get_columns()[1:]:
				row[col["fieldname"]] = 0
			rows.append(row)
			month_date = _next_month(month_date)
			continue

		slip_names = [s.name for s in slips]
		gross_pay = sum(flt(s.gross_pay) for s in slips)
		sums = card_type_sums(slip_names, "royce_p9a_tax_deduction_card_type")

		basic_salary = flt(sums.get("Basic Salary"))
		retirement = flt(sums.get("E1 Defined Contribution Retirement Scheme"))
		housing_levy = flt(sums.get("Housing Levy"))
		shif = flt(sums.get("SHIF"))
		paye_tax = flt(sums.get("PAYE Tax"))

		rates_name = PayrollRates.get_effective(month_end)
		personal_relief = flt(frappe.db.get_value("Payroll Rates", rates_name, "personal_relief")) if rates_name else 0

		# Neither exists as its own Salary Detail row — both are statistical
		# components HRMS never persists (verified against the source, not
		# assumed) — so they're derived here from what is persisted, using the
		# same relationships the generator itself computes them with. Relief is
		# declared every month a payslip exists, not only when PAYE actually
		# fired — a very low earner can have Gross PAYE under the relief
		# threshold, meaning PAYE = 0 with no persisted trace of what the true
		# pre-relief tax was; tax_charged is a reasonable derivation in that
		# case, not an exact one — a genuine limit of what's persisted, not a
		# bug to paper over.
		chargeable_pay = gross_pay - retirement - housing_levy - shif
		tax_charged = paye_tax + personal_relief

		row.update(
			{
				"basic_salary": basic_salary,
				"total_gross_pay": gross_pay,
				"retirement_scheme": retirement,
				"housing_levy": housing_levy,
				"shif": shif,
				"chargeable_pay": chargeable_pay,
				"tax_charged": tax_charged,
				"personal_relief": personal_relief,
				"paye_tax": paye_tax,
			}
		)
		rows.append(row)
		month_date = _next_month(month_date)

	return rows


def _next_month(d):
	return getdate(f"{d.year + 1}-01-01") if d.month == 12 else getdate(f"{d.year}-{d.month + 1:02d}-01")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("company"):
		frappe.throw(_("Company is required"))
	if not filters.get("fiscal_year"):
		frappe.throw(_("Fiscal Year is required"))
	if not filters.get("employee"):
		frappe.throw(_("Employee is required — the P9A is one certificate per employee"))

	fiscal_year = frappe.db.get_value(
		"Fiscal Year", filters.fiscal_year, ["year_start_date", "year_end_date"], as_dict=True
	)
	if not fiscal_year:
		frappe.throw(_("Fiscal Year {0} not found").format(filters.fiscal_year))

	data = month_rows(filters.employee, filters.company, fiscal_year.year_start_date, fiscal_year.year_end_date)
	return get_columns(), data


def _totals_row(data):
	totals = {"month": "Total"}
	for col in get_columns()[1:]:
		totals[col["fieldname"]] = sum(flt(row.get(col["fieldname"])) for row in data)
	return totals


@frappe.whitelist()
def download_certificate(company, fiscal_year, employee):
	"""The P9A as a printable certificate — this is a document handed to an
	employee, not just a screen table, so it needs to actually be one."""
	columns, data = execute(frappe._dict(company=company, fiscal_year=fiscal_year, employee=employee))
	data = [*data, _totals_row(data)]

	employee_name, kra_pin = frappe.db.get_value("Employee", employee, ["employee_name", "royce_kra_pin"])

	html = frappe.render_template(
		"royce_payroll_ke/royce_payroll_ke/report/kenya_p9a_tax_deduction_card/kenya_p9a_tax_deduction_card.html",
		{
			"company": company,
			"employee": employee,
			"employee_name": employee_name,
			"kra_pin": kra_pin,
			"fiscal_year": fiscal_year,
			"columns": columns,
			"data": data,
		},
	)

	pdf = get_pdf(
		html,
		options={
			"page-size": "A4",
			"orientation": "Landscape",
			"margin-top": "10mm",
			"margin-bottom": "10mm",
			"margin-left": "8mm",
			"margin-right": "8mm",
		},
	)

	frappe.local.response.filename = f"P9A-{employee}-{fiscal_year}.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "download"
