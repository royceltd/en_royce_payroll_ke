# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Post-install hooks."""

import frappe

from royce_payroll_ke.royce_payroll_ke.setup import seed_default_rates


def after_install():
	"""Seed the bundled Kenya statutory rates immediately after install, so a
	fresh site has a working Payroll Rates record without anyone needing to
	remember a separate manual step. Matters most exactly where there's no
	Royce staff in the loop to run it by hand: a self-hosted client's own
	`bench install-app`, or a site created through a hosting platform's own
	self-serve flow (e.g. Frappe Cloud).

	Deliberately only seeds rates here, not provision(company) — a fresh
	site may not have the target Company created yet (provisioning needs a
	real Company with its Chart of Accounts already applied), so that step
	stays an explicit, orchestrated call. Safe to run unconditionally:
	seed_default_rates() is idempotent and no-ops if this site already has
	an effective Payroll Rates record."""
	result = seed_default_rates()
	frappe.logger("royce_payroll_ke").info(f"after_install: seed_default_rates -> {result}")
