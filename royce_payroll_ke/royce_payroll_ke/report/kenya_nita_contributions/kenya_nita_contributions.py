# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from royce_payroll_ke.royce_payroll_ke.report_utils import statutory_component_report


def execute(filters=None):
	# NITA is employer-only — no employee-side deduction — so unlike NSSF/SHIF/
	# Housing Levy this is purely an employer cost report, not a "what did we
	# withhold" one. Same shape regardless: one component, summed per employee.
	return statutory_component_report(
		filters,
		components=["NITA"],
		amount_label="NITA Amount",
	)
