# Copyright (c) 2026, Royce Technologies LTD and contributors
# For license information, please see license.txt

"""What the Kenya Payslip print format needs: the employer's identity, the
employee's statutory numbers, and the PAYE working an employee checks first
(taxable pay, tax charged, personal relief).

Ownership rule (ADR-023 in royce_ip): Kenya Payslip is a standard print format,
so fixes reach every client still using it; which format is the Salary Slip
DEFAULT is set once at install and is the client's from then on.
"""

import base64

import frappe
from frappe.utils import flt, getdate

PRINT_FORMAT = "Kenya Payslip"
NEUTRAL_ACCENT = "#1f2937"
MAX_LOGO_BYTES = 2 * 1024 * 1024

# ERPNext's installer creates these letterheads (the grey one as default). Untouched,
# they aren't the client's letterhead, so the payslip uses its own header instead.
STOCK_LETTER_HEADS = {
	"Company Letterhead": "company_letterhead.html",
	"Company Letterhead - Grey": "company_letterhead_grey.html",
}

# The employee deductions Kenya allows before PAYE (the Taxable Income formula in
# setup.py: gross_pay - NSSF_T1 - NSSF_T2 - SHIF - AHL).
ALLOWABLE_ABBRS = ("NSSF_T1", "NSSF_T2", "SHIF", "AHL")


def set_default_print_format() -> bool:
	"""Kenya Payslip becomes the Salary Slip default only if the site has none yet.
	Install-time only, so a client's own choice is never overwritten."""
	if not frappe.db.exists("Print Format", PRINT_FORMAT):
		return False
	if frappe.db.exists(
		"Property Setter",
		{"doc_type": "Salary Slip", "doctype_or_field": "DocType", "property": "default_print_format"},
	):
		return False
	frappe.make_property_setter(
		{
			"doctype": "Salary Slip",
			"doctype_or_field": "DocType",
			"property": "default_print_format",
			"value": PRINT_FORMAT,
			"property_type": "Data",
		},
		is_system_generated=False,
	)
	return True


def kenya_payslip_context(doc) -> frappe._dict:
	pay = [r for r in doc.get("earnings") or [] if not r.statistical_component and not r.do_not_include_in_total]
	employer = [r for r in doc.get("earnings") or [] if not r.statistical_component and r.do_not_include_in_total]
	deductions = [r for r in doc.get("deductions") or [] if not r.statistical_component and not r.do_not_include_in_total]
	return frappe._dict(
		accent=_accent(doc.company),
		company=_company(doc.company),
		use_letter_head=uses_own_letter_head(doc),
		employee=_employee(doc),
		period=pay_period(doc.start_date, doc.end_date),
		month=getdate(doc.end_date or doc.start_date).strftime("%B %Y"),
		earnings=pay,
		deductions=deductions,
		employer=employer,
		employer_total=sum(flt(r.amount) for r in employer),
		tax=tax_summary(doc, deductions),
	)


def uses_own_letter_head(doc) -> bool:
	name = doc.get("letter_head") or frappe.db.get_value("Letter Head", {"is_default": 1, "disabled": 0}, "name")
	if not name:
		return False
	stock_file = STOCK_LETTER_HEADS.get(name)
	if not stock_file:
		return True
	try:
		shipped = frappe.read_file(frappe.get_app_path("erpnext", "accounts", "letterhead", stock_file))
	except Exception:
		return True
	return (frappe.db.get_value("Letter Head", name, "content") or "").strip() != (shipped or "").strip()


def tax_summary(doc, deductions) -> frappe._dict | None:
	"""Gross pay -> taxable pay -> tax charged -> personal relief -> PAYE, from the
	rates in force for the slip's period. None when the slip carries no PAYE row
	and no rates exist (nothing honest to show)."""
	from royce_payroll_ke.kenya_payroll.doctype.kenya_payroll_rates.kenya_payroll_rates import KenyaPayrollRates

	rates_name = KenyaPayrollRates.get_effective(doc.start_date)
	paye = sum(flt(r.amount) for r in deductions if r.abbr == "PAYE")
	if not rates_name:
		return None
	rates = frappe.get_doc("Kenya Payroll Rates", rates_name)

	allowable = [r for r in deductions if r.abbr in ALLOWABLE_ABBRS]
	taxable = flt(doc.gross_pay) - sum(flt(r.amount) for r in allowable)
	relief = flt(rates.personal_relief)
	# Match the slip: when PAYE was charged, tax charged is exactly PAYE + relief.
	charged = paye + relief if paye else band_tax(taxable, rates.paye_bands)
	return frappe._dict(
		gross=flt(doc.gross_pay),
		allowable=allowable,
		taxable=taxable,
		charged=charged,
		relief=min(relief, charged),
		paye=paye,
	)


def band_tax(taxable: float, bands) -> float:
	tax, previous = 0.0, 0.0
	for band in sorted(bands, key=lambda b: b.band_number):
		upper = flt(band.upper_bound) or float("inf")
		portion = min(taxable, upper) - previous
		if portion <= 0:
			break
		tax += portion * flt(band.rate) / 100
		previous = upper
	return round(tax, 2)


def pay_period(start, end) -> str:
	"""1 - 31 Jan 2026, or 15 Dec 2025 - 14 Jan 2026 across months."""
	start, end = getdate(start), getdate(end)
	if (start.year, start.month) == (end.year, end.month):
		return f"{start.day} – {end.day} {end.strftime('%b %Y')}"
	return f"{start.day} {start.strftime('%b %Y')} – {end.day} {end.strftime('%b %Y')}"


def masked(account_no) -> str:
	account_no = (account_no or "").strip()
	return f"•••• {account_no[-4:]}" if len(account_no) > 4 else account_no


def _employee(doc) -> frappe._dict:
	fields = ["royce_kra_pin", "royce_nssf_no", "royce_shif_no", "royce_national_id", "bank_name", "bank_ac_no",
		"designation", "department"]
	meta = frappe.get_meta("Employee")
	values = frappe.db.get_value("Employee", doc.employee, [f for f in fields if meta.has_field(f)], as_dict=True) or {}
	rows = [
		("Employee", doc.employee_name),
		("Employee No.", doc.employee),
		("ID No.", values.get("royce_national_id")),
		("KRA PIN", values.get("royce_kra_pin")),
		("NSSF No.", values.get("royce_nssf_no")),
		("SHA No.", values.get("royce_shif_no")),
		# The slip's own copy first; the employee's current one for a slip made before it was set.
		("Designation", doc.get("designation") or values.get("designation")),
		("Department", _department_name(doc.get("department") or values.get("department"))),
		("Bank", " ".join(filter(None, [doc.get("bank_name") or values.get("bank_name"),
			masked(doc.get("bank_account_no") or values.get("bank_ac_no"))]))),
	]
	return frappe._dict(rows=[(label, value) for label, value in rows if value])


def _department_name(department) -> str:
	"""'Accounts - MTC' -> 'Accounts': the company-abbreviation suffix means nothing on a payslip."""
	if not department:
		return ""
	return frappe.db.get_value("Department", department, "department_name") or department


def _accent(company) -> str:
	"""A client's colour from Kenya Accounting Settings, when that app is installed."""
	try:
		if frappe.db.exists("Kenya Accounting Settings", company) and frappe.get_meta(
			"Kenya Accounting Settings"
		).has_field("print_accent_color"):
			return frappe.db.get_value("Kenya Accounting Settings", company, "print_accent_color") or NEUTRAL_ACCENT
	except Exception:
		pass
	return NEUTRAL_ACCENT


def _company(company) -> frappe._dict:
	values = frappe.db.get_value(
		"Company", company, ["company_name", "company_logo", "tax_id", "phone_no", "email"], as_dict=True
	) or frappe._dict()
	address = ""
	try:
		from frappe.contacts.doctype.address.address import get_company_address

		address = get_company_address(company).get("company_address_display") or ""
	except Exception:
		pass
	contact = [f"{frappe._('PIN')}: {values.tax_id}" if values.tax_id else "", values.phone_no or "", values.email or ""]
	return frappe._dict(
		name=values.company_name or company,
		logo=_inline_image(values.company_logo),
		address=address,
		contact_line="  ·  ".join(bit for bit in contact if bit),
	)


def _inline_image(file_url) -> str:
	if not file_url:
		return ""
	try:
		content = frappe.get_doc("File", {"file_url": file_url}).get_content()
	except Exception:
		return ""
	if isinstance(content, str):
		content = content.encode()
	mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
		"svg": "image/svg+xml", "webp": "image/webp"}.get(file_url.rsplit(".", 1)[-1].lower())
	if not content or not mime or len(content) > MAX_LOGO_BYTES:
		return ""
	return f"data:{mime};base64,{base64.b64encode(content).decode()}"
