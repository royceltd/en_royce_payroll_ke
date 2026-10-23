// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

// Payslips by SMS (kenya_payroll/payslip_sms.py).
frappe.ui.form.on("Salary Slip", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frappe.boot.versions?.royce_talk) return;
		frm.add_custom_button(__("Send by SMS"), () =>
			frappe.confirm(__("Send {0}'s pay summary by SMS?", [frm.doc.employee_name]), () =>
				frappe
					.call("royce_payroll_ke.kenya_payroll.payslip_sms.send_slip", { salary_slip: frm.doc.name })
					.then(({ message }) =>
						frappe.msgprint({ title: __("Sent"), message: frappe.utils.escape_html(message), indicator: "green" })
					)
			)
		);
	},
});
