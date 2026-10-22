// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.listview_settings["Staff Loan"] = {
	get_indicator(doc) {
		const colours = { Active: "blue", Repaid: "green", "Written Off": "orange", Cancelled: "red", Draft: "gray" };
		return [__(doc.status), colours[doc.status] || "gray", "status,=," + doc.status];
	},
};
