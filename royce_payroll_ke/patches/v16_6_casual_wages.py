# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""v16.6.0: casual workers paid monthly on a daily rate.

1. The Casual Wages flag on Salary Structure and Days Worked on Salary Slip (fixtures).
2. The Casual Wages component, and a Kenya Casual Wages structure for every provisioned
   company (Base on the assignment = daily rate, pay = daily rate x Days Worked).

Existing structures and slips are not changed. A Kenya Payroll structure must now be
Monthly; the engine refuses slips from one that isn't (see engine._require_monthly)."""

import frappe
from frappe.utils.fixtures import sync_fixtures


def execute():
	sync_fixtures("royce_payroll_ke")
	frappe.clear_cache(doctype="Salary Structure")
	frappe.clear_cache(doctype="Salary Slip")

	if not frappe.db.exists("Salary Component", "PAYE"):
		return  # Kenya payroll was never set up on this site.

	from royce_payroll_ke.kenya_payroll.setup import (
		_provisioned_companies,
		ensure_casual_structure,
		ensure_components,
		map_accounts,
	)

	ensure_components()
	for company in _provisioned_companies():
		map_accounts(company)
		ensure_casual_structure(company)
