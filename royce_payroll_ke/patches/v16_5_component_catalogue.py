# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""v16.5.0: employer contributions on HRMS's native type, and the Kenyan catalogue.

1. NSSF Employer, Housing Levy Employer and NITA become Employer Contribution
   components, each with a liability account (NSSF / Housing Levy / NITA Payable). Before,
   as earnings left out of the total, Payroll Entry credited them to Payroll Payable.
2. Catalogue components (overtime, bonus, pension, HELB, SACCO...) are created where
   missing. Existing components with the same names are left as they are.
3. Every provisioned company gets the catalogue's accounts and component mappings.
4. Kenya Payroll Rates get the 30%-of-basic pension limit (P9A column E1).

Existing Salary Structures are not changed: the engine moves their employer rows to the
slip's Employer Contributions section, and their House/Transport formulas stay as they
were (a pay change must be an explicit, dated decision). Submitted slips aren't touched."""

import frappe
from frappe.utils.fixtures import sync_fixtures


def execute():
	sync_fixtures("royce_payroll_ke")
	frappe.clear_cache(doctype="Salary Structure Assignment")

	# P9A column E1 (30% of basic), added after v16.4.0's rates fields.
	for name in frappe.get_all("Kenya Payroll Rates", filters={"pension_limit_percent_of_basic": ["in", [None, 0]]}, pluck="name"):
		frappe.db.set_value("Kenya Payroll Rates", name, "pension_limit_percent_of_basic", 30, update_modified=False)

	if not frappe.db.exists("Salary Component", "PAYE"):
		return  # Kenya payroll was never set up on this site.

	from royce_payroll_ke.kenya_payroll.setup import (
		_provisioned_companies,
		ensure_accounts,
		ensure_components,
		map_accounts,
	)

	ensure_components()
	for company in _provisioned_companies():
		ensure_accounts(company)
		map_accounts(company)
