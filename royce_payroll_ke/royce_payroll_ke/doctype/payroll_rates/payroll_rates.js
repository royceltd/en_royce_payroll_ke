// Copyright (c) 2026, Royce Technologies LTD and contributors
// For license information, please see license.txt

// Desk-level triggers for setup.provision()/regenerate()/verify() — these
// used to only be reachable via `bench execute` or a raw API call, which is
// fine when Royce staff always have console access to a client's site, and
// stops being fine the moment they don't (a self-hosted client, or a site
// created through a hosting platform's own self-serve flow). Every call
// below is explicit about which Payroll Rates record it acts on
// (frm.doc.name) — never relies on "whatever's currently effective" — so
// clicking a button from an older, superseded record can't silently act on
// a different, newer one instead.

frappe.ui.form.on("Payroll Rates", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}

		// Provision/Regenerate mutate Salary Components, the Chart of Accounts,
		// and Salary Structures for every company on the site — shown only to
		// whoever can already write Payroll Rates itself (frm.perm mirrors the
		// same has_permission("Payroll Rates", "write") check setup.py makes
		// server-side; this is UX, the server-side check is the real gate).
		if (frm.perm[0].write) {
			frm.add_custom_button(
				__("Regenerate Components"),
				() => regenerate_components(frm),
				__("Actions")
			);
			frm.add_custom_button(
				__("Provision Company"),
				() => provision_company(frm),
				__("Actions")
			);
		}

		// Verify is read-only — anyone who can see this record can run it.
		frm.add_custom_button(__("Verify Company"), () => verify_company(frm), __("Actions"));
	},
});

function regenerate_components(frm) {
	frappe.confirm(
		__(
			"This re-templates all 22 Salary Components from this rates record, and builds a new Salary Structure for every already-provisioned company. Existing Salary Structure Assignments are left untouched. Continue?"
		),
		() => {
			frappe.call({
				method: "royce_payroll_ke.royce_payroll_ke.setup.regenerate",
				args: { rates: frm.doc.name },
				freeze: true,
				freeze_message: __("Regenerating payroll components..."),
				callback(r) {
					if (r.exc) return;
					const structure_count = Object.keys(r.message.structures || {}).length;
					frappe.msgprint({
						title: __("Regenerated"),
						indicator: "green",
						message: __("Rates: {0}<br>Salary Structures rebuilt: {1}", [
							r.message.rates,
							structure_count,
						]),
					});
				},
			});
		}
	);
}

function provision_company(frm) {
	frappe.prompt(
		{
			fieldname: "company",
			fieldtype: "Link",
			options: "Company",
			label: __("Company"),
			reqd: 1,
		},
		(values) => {
			frappe.call({
				method: "royce_payroll_ke.royce_payroll_ke.setup.provision",
				args: { company: values.company, rates: frm.doc.name },
				freeze: true,
				freeze_message: __("Provisioning {0}...", [values.company]),
				callback(r) {
					if (r.exc) return;
					frappe.msgprint({
						title: __("Provisioned"),
						indicator: "green",
						message: __("Salary Structure: {0}", [r.message.salary_structure]),
					});
				},
			});
		},
		__("Provision Company"),
		__("Provision")
	);
}

function verify_company(frm) {
	frappe.prompt(
		{
			fieldname: "company",
			fieldtype: "Link",
			options: "Company",
			label: __("Company"),
			reqd: 1,
		},
		(values) => {
			frappe.call({
				method: "royce_payroll_ke.royce_payroll_ke.setup.verify",
				args: { company: values.company, rates: frm.doc.name },
				freeze: true,
				freeze_message: __("Verifying {0}...", [values.company]),
				callback(r) {
					if (r.exc) return;
					frappe.msgprint({
						title: __("Verification Passed"),
						indicator: "green",
						message: __("{0} components checked against {1}.", [
							r.message.components_checked,
							r.message.rates,
						]),
					});
				},
			});
		},
		__("Verify Company"),
		__("Verify")
	);
}
