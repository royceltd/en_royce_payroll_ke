// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

// Payslips by SMS (kenya_payroll/payslip_sms.py).
frappe.ui.form.on("Payroll Entry", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frappe.boot.versions?.royce_talk) return;
		frm.add_custom_button(__("Send Payslips by SMS"), () => royce_payslip_sms_dialog(frm));
	},
});

function royce_payslip_sms_dialog(frm) {
	const method = "royce_payroll_ke.kenya_payroll.payslip_sms.";
	let preview = null;

	const d = new frappe.ui.Dialog({
		title: __("Send Payslips by SMS"),
		fields: [
			{ fieldname: "summary", fieldtype: "HTML" },
			{
				fieldname: "resend",
				fieldtype: "Check",
				label: __("Also resend to those already sent"),
				hidden: 1,
				// Built once; ticking the box only refreshes the summary.
				onchange: () => load(),
			},
		],
		primary_action_label: __("Send"),
		primary_action() {
			if (!preview?.to_send) return d.hide();
			frappe
				.call(method + "send_for_payroll_entry", { payroll_entry: frm.doc.name, resend: resend() })
				.then(() => {
					d.hide();
					frappe.show_alert({
						message: __("Sending in the background. The result will appear here and in the comments."),
						indicator: "blue",
					});
				});
		},
	});

	const resend = () => (d.get_value("resend") ? 1 : 0);

	function load() {
		frappe.call(method + "preview", { payroll_entry: frm.doc.name, resend: resend() }).then(({ message: p }) => {
			preview = p;
			const lines = [
				__("{0} of {1} submitted slips will be sent.", [p.to_send, p.slips]),
				__("Estimated {0} SMS units, about KES {1}.", [p.units, format_number(p.estimated_cost, null, 2)]),
			];
			if (p.already_sent.length) lines.push(__("Already sent, skipped: {0}", [p.already_sent.join(", ")]));
			if (p.no_phone.length)
				lines.push(__("No mobile number on the Employee, skipped: {0}", [p.no_phone.join(", ")]));
			if (p.sample) lines.push(__("Example:") + ` <i>${frappe.utils.escape_html(p.sample)}</i>`);
			d.fields_dict.summary.$wrapper.html(lines.map((l) => `<p>${l}</p>`).join(""));
			d.set_df_property("resend", "hidden", !p.already_sent.length && !resend());
			d.show();
		});
	}

	load();
}
