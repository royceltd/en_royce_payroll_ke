// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Staff Loan", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.status !== "Active") return;

		if (!frm.doc.write_off_date) {
			frm.add_custom_button(__("Write Off"), () => {
				frappe.prompt(
					{
						fieldname: "write_off_date",
						fieldtype: "Date",
						label: __("Write Off On"),
						default: frappe.datetime.get_today(),
						reqd: 1,
						description: __(
							"The salary slip covering this date clears the balance and adds it to the employee's pay as a taxable benefit (Staff Loan Write-off)."
						),
					},
					(values) =>
						frm.call("write_off", values).then(() => frm.reload_doc()),
					__("Write Off Loan"),
					__("Write Off")
				);
			});
		} else {
			frm.add_custom_button(__("Cancel Write Off"), () =>
				frm.call("cancel_write_off").then(() => frm.reload_doc())
			);
		}
	},
});
