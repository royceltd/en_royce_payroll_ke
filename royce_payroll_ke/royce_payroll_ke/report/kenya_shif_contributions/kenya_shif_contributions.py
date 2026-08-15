# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

from royce_payroll_ke.royce_payroll_ke.report_utils import statutory_component_report


def execute(filters=None):
	return statutory_component_report(
		filters,
		components=["SHIF"],
		amount_label="SHIF Amount",
		id_fieldname="royce_shif_no",
		id_label="SHIF No",
	)
