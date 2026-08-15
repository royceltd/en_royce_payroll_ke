# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from royce_payroll_ke.royce_payroll_ke.report_utils import statutory_component_report


def execute(filters=None):
	# Both sides on purpose: "Housing Levy Payable" accumulates employee and employer
	# contributions together (guide section 6.8/11) — what actually gets remitted is
	# their sum, so the report reconciles against the account balance only if it shows
	# both, not just the employee-side deduction.
	return statutory_component_report(
		filters,
		components=["Housing Levy", "Housing Levy Employer"],
		amount_label="Housing Levy Amount (Employee + Employer)",
	)
