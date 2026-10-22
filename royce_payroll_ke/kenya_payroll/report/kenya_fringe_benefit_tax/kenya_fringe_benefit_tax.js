// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Kenya Fringe Benefit Tax"] = {
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
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
			description: __("Any date in the month."),
		},
	],
};
