# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""v16.8.0: staff loans.

1. Staff Loan, its deductions table and the FBT market rates table (doctype sync).
2. Staff Loan Interest and Staff Loan Write-off components, and a Staff Loan Interest
   Income account for every provisioned company (where the chart has Indirect Income).

Existing loans deducted through Additional Salary (Staff Loan Repayment) are not changed:
an employee is only handled by Staff Loan once they have one."""

import frappe


def execute():
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
