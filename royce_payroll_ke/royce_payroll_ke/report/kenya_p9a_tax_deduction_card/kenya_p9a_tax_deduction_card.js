// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Kenya P9A Tax Deduction Card"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: frappe.defaults.get_user_default("fiscal_year"),
			reqd: 1,
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
			reqd: 1,
			description: __("The P9A is one certificate per employee — pick one."),
		},
	],
};
