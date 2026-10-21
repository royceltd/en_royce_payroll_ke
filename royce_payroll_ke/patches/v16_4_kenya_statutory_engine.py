# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""v16.4.0: move existing sites onto the Kenya statutory engine (kenya_payroll/engine.py).

1. Fill the new Kenya Payroll Rates fields (deduction limits, reliefs) on every
   existing record, with the Tax Laws (Amendment) Act 2024 values.
2. Re-apply Kenya Payroll's own component definitions: the statutory components lose
   their formulas (the engine fills them) and stop depending on payment days.
3. A client's own earnings count for NSSF, SHIF and Housing Levy exactly when they are
   taxable. Before, everything in gross pay did.
4. Mark structures built by the generator before v16.4.0 as Kenya structures, so the
   engine runs on slips from them. They're recognised by their Taxable Income row.

Already-submitted Salary Slips are not touched."""

import frappe
from frappe.utils.fixtures import sync_fixtures

NEW_RATES_VALUES = {
	"pension_deduction_limit": 30000,
	"prmf_deduction_limit": 15000,
	"mortgage_interest_limit": 30000,
	"disability_exemption_amount": 150000,
	"non_cash_benefit_threshold": 5000,
	"meals_tax_free_limit": 5000,
	"insurance_relief_rate": 15,
	"insurance_relief_limit": 5000,
	"secondary_employment_rate": 35,
}


def execute():
	# Custom fields are normally synced after post-model-sync patches; this patch
	# reads and writes them, so sync them now.
	sync_fixtures("royce_payroll_ke")
	frappe.clear_cache(doctype="Salary Component")
	frappe.clear_cache(doctype="Salary Structure")

	for name in frappe.get_all("Kenya Payroll Rates", pluck="name"):
		current = frappe.db.get_value("Kenya Payroll Rates", name, list(NEW_RATES_VALUES), as_dict=True)
		missing = {k: v for k, v in NEW_RATES_VALUES.items() if not current.get(k)}
		if missing:
			frappe.db.set_value("Kenya Payroll Rates", name, missing, update_modified=False)

	if not frappe.db.exists("Salary Component", "PAYE"):
		return  # Kenya payroll was never set up on this site.

	from royce_payroll_ke.kenya_payroll.setup import component_specs, upsert_component

	owned = set()
	for spec in component_specs():
		owned.add(spec["salary_component"])
		upsert_component(spec)

	for name, taxable in frappe.get_all(
		"Salary Component",
		filters={"type": "Earning", "name": ["not in", list(owned)]},
		fields=["name", "is_tax_applicable"],
		as_list=True,
	):
		flag = 1 if taxable else 0
		frappe.db.set_value(
			"Salary Component",
			name,
			{"royce_nssf_pensionable": flag, "royce_shif_applicable": flag, "royce_ahl_applicable": flag},
			update_modified=False,
		)

	generated = frappe.get_all(
		"Salary Detail",
		filters={"salary_component": "Taxable Income", "parenttype": "Salary Structure"},
		pluck="parent",
		distinct=True,
	)
	for structure in generated:
		frappe.db.set_value("Salary Structure", structure, "royce_kenya_statutory", 1, update_modified=False)
