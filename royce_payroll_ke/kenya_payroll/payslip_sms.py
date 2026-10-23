# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""Payslips by SMS (v16.9.0): a short pay summary to each employee's mobile, sent through
the Bulk SMS app (royce_talk) when it's installed and enabled.

- A summary, not the payslip: anyone holding the phone, or a forwarded text, sees it, so no
  KRA PIN, loans or link to the full slip. The wording is a template in Kenya Payroll
  Settings.
- Sent on request only (the Payroll Entry's Send Payslips by SMS, or one slip's Send by
  SMS): every message costs money, and a wrong payroll run shouldn't text everyone before
  anyone has checked it.
- Every message is a Bulk SMS Log linked to its Salary Slip (sent, failed, cost, delivery).
  A slip with a Sent or Delivered log is skipped unless a resend is asked for.

royce_talk is optional: nothing here imports it at module level.
"""

import frappe
from frappe import _
from frappe.utils import flt, formatdate

DEFAULT_TEMPLATE = (
	"{{ employee_name }}, {{ month }} pay: gross {{ gross }}, deductions {{ deductions }}, "
	"net KES {{ net }}. {{ company }}"
)
SENT = ("Sent", "Delivered")


def _whole(value):
	return f"{flt(value):,.0f}"


def unavailable_reason():
	"""Why SMS can't be sent from this site, or None."""
	if "royce_talk" not in frappe.get_installed_apps():
		return _("The Bulk SMS app is not installed on this site.")
	settings = frappe.get_single("Bulk SMS Settings")
	if not settings.enabled:
		return _("Bulk SMS is disabled. Enable it in Bulk SMS Settings.")
	if not settings.get_password("api_key", raise_exception=False):
		return _("Set the API Key in Bulk SMS Settings first.")
	return None


def template():
	return frappe.db.get_single_value("Kenya Payroll Settings", "payslip_sms_template") or DEFAULT_TEMPLATE


def message(slip, text=None):
	"""The SMS for one Salary Slip."""
	paye = sum(flt(d.amount) for d in slip.get("deductions") or [] if d.salary_component == "PAYE")
	context = {
		"doc": slip,
		"employee_name": slip.employee_name,
		"first_name": (slip.employee_name or "").split(" ")[0],
		"month": formatdate(slip.start_date, "MMM yyyy"),
		"gross": _whole(slip.gross_pay),
		"deductions": _whole(flt(slip.total_deduction) + flt(slip.get("total_loan_repayment"))),
		"net": _whole(slip.net_pay),
		"paye": _whole(paye),
		"company": slip.company,
	}
	return " ".join(frappe.render_template(text or template(), context).split())


def already_sent(slip_names):
	if not slip_names:
		return set()
	return set(
		frappe.get_all(
			"Bulk SMS Log",
			filters={"reference_doctype": "Salary Slip", "reference_name": ["in", slip_names], "status": ["in", SENT]},
			pluck="reference_name",
		)
	)


def plan(slip_names, resend=False):
	"""Split slips into to-send (with their phone and message), no phone, and already sent."""
	slips = [frappe.get_doc("Salary Slip", name) for name in slip_names]
	phones = dict(
		frappe.get_all(
			"Employee",
			filters={"name": ["in", [s.employee for s in slips] or [""]]},
			fields=["name", "cell_number"],
			as_list=True,
		)
	)
	sent = set() if resend else already_sent(slip_names)
	text = template()
	result = frappe._dict(send=[], no_phone=[], already_sent=[])
	for slip in slips:
		phone = (phones.get(slip.employee) or "").strip()
		if slip.name in sent:
			result.already_sent.append(slip.employee_name)
		elif not phone:
			result.no_phone.append(slip.employee_name)
		else:
			result.send.append(frappe._dict(slip=slip.name, phone=phone, message=message(slip, text)))
	return result


def _payroll_entry_slips(payroll_entry):
	return frappe.get_all(
		"Salary Slip", filters={"payroll_entry": payroll_entry, "docstatus": 1}, pluck="name", order_by="employee_name"
	)


def _require(payroll_entry=None, slip=None):
	reason = unavailable_reason()
	if reason:
		frappe.throw(reason, title=_("SMS not available"))
	if payroll_entry:
		frappe.get_doc("Payroll Entry", payroll_entry).check_permission("submit")
	if slip:
		frappe.get_doc("Salary Slip", slip).check_permission("submit")


@frappe.whitelist()
def preview(payroll_entry, resend=0):
	"""What Send Payslips by SMS would do: counts, who's skipped, a sample, the cost."""
	_require(payroll_entry=payroll_entry)
	from royce_talk.bulk_sms.bulk_send import estimate_cost

	slips = _payroll_entry_slips(payroll_entry)
	if not slips:
		frappe.throw(_("This Payroll Entry has no submitted salary slips."))
	result = plan(slips, resend=int(resend))
	units = cost = 0
	for item in result.send:
		estimate = estimate_cost(item.message, 1)
		units += estimate["total_units"]
		cost += estimate["estimated_cost"]
	return {
		"slips": len(slips),
		"to_send": len(result.send),
		"no_phone": result.no_phone,
		"already_sent": result.already_sent,
		"sample": result.send[0].message if result.send else None,
		"units": units,
		"estimated_cost": flt(cost, 2),
	}


@frappe.whitelist()
def send_for_payroll_entry(payroll_entry, resend=0):
	"""Queue the SMS for every submitted slip of the Payroll Entry."""
	_require(payroll_entry=payroll_entry)
	slips = _payroll_entry_slips(payroll_entry)
	frappe.enqueue(
		"royce_payroll_ke.kenya_payroll.payslip_sms.send_slips",
		queue="long",
		enqueue_after_commit=True,
		slip_names=slips,
		resend=int(resend),
		payroll_entry=payroll_entry,
		user=frappe.session.user,
	)
	return len(slips)


@frappe.whitelist()
def send_slip(salary_slip):
	"""Send (or resend) one slip's SMS now."""
	_require(slip=salary_slip)
	if frappe.db.get_value("Salary Slip", salary_slip, "docstatus") != 1:
		frappe.throw(_("Submit the salary slip first."))
	result = plan([salary_slip], resend=True)
	if not result.send:
		frappe.throw(_("{0} has no mobile number on their Employee record.").format(result.no_phone[0]))
	from royce_talk.bulk_sms.utils import send_single_sms

	item = result.send[0]
	send_single_sms(
		phone_number=item.phone, text_message=item.message, reference_doctype="Salary Slip", reference_name=item.slip
	)
	return item.message


def send_slips(slip_names, resend=0, payroll_entry=None, user=None):
	"""Background job: send one SMS per slip. A failure is logged (Bulk SMS Log) and the
	rest carry on. The outcome goes on the Payroll Entry as a comment and to the user."""
	from royce_talk.bulk_sms.utils import send_single_sms

	result = plan(slip_names, resend=int(resend))
	sent, failed = 0, []
	for item in result.send:
		try:
			send_single_sms(
				phone_number=item.phone,
				text_message=item.message,
				reference_doctype="Salary Slip",
				reference_name=item.slip,
			)
			sent += 1
		except Exception as e:
			failed.append(f"{item.slip}: {e}")
		if not frappe.flags.in_test:
			frappe.db.commit()  # keep each sent message's log even if the job dies later

	summary = _("Payslips by SMS: {0} sent, {1} failed, {2} without a mobile number, {3} already sent.").format(
		sent, len(failed), len(result.no_phone), len(result.already_sent)
	)
	if payroll_entry:
		frappe.get_doc("Payroll Entry", payroll_entry).add_comment(
			"Info", summary + ("<br>" + "<br>".join(failed) if failed else "")
		)
	if user:
		frappe.publish_realtime(
			"msgprint",
			{"message": summary, "title": _("Payslips by SMS"), "indicator": "red" if failed else "green"},
			user=user,
		)
	return {"sent": sent, "failed": failed, "no_phone": result.no_phone, "already_sent": result.already_sent}
