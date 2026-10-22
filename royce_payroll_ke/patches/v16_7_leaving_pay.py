# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""v16.7.0: leaving pay.

1. Notice Pay, Severance Pay and Gratuity catalogue components (created if missing, mapped
   to Salary Expense for every provisioned company).
2. The Gratuity Rule "Kenya Service Gratuity" (15 days' basic per year of service).
3. Encashable Leave Types without an earning component are pointed at Leave Pay.

Nothing existing is changed: a component, rule or leave type the client already set up is
kept."""

import frappe


def execute():
	if not frappe.db.exists("Salary Component", "PAYE"):
		return  # Kenya payroll was never set up on this site.

	from royce_payroll_ke.kenya_payroll.setup import (
		_provisioned_companies,
		ensure_components,
		ensure_gratuity_rule,
		link_leave_encashment,
		map_accounts,
	)

	ensure_components()
	for company in _provisioned_companies():
		map_accounts(company)
	ensure_gratuity_rule()
	link_leave_encashment()
