# Payslips by SMS (branch `feat/casual-monthly`, target v16.9.0)

Status: **built and committed, not released** (2026-10-23). How to use it: `user-guide.md` §7H.
Design agreed with the user 2026-10-23: a summary only (no link to the payslip), sent on
request only (no automatic send on submit).

## What changes

1. `kenya_payroll/payslip_sms.py`:
   - `message(slip)`: Jinja template from Kenya Payroll Settings (`payslip_sms_template`,
     default about 100-140 characters); whole-shilling amounts with commas; whitespace collapsed.
   - `plan(slips, resend)`: to send (phone from Employee `cell_number`), no phone, already sent
     (a Bulk SMS Log for the slip with status Sent or Delivered).
   - `preview` / `send_for_payroll_entry` (whitelisted, Payroll Entry submit permission):
     counts, skipped names, sample, units and cost (royce_talk's `estimate_cost`); the send is
     one background job (`send_slips`, queue long) that sends one SMS per slip through
     royce_talk's `send_single_sms`, carries on after a failure, commits per message (outside
     tests), comments the outcome on the Payroll Entry and tells the user.
   - `send_slip` (whitelisted, Salary Slip submit permission): one slip, synchronous, always sends.
   - royce_talk is optional: imported only inside functions; `unavailable_reason()` explains
     why not (not installed, disabled, no API key). Buttons show only when royce_talk is installed.
2. Buttons: Payroll Entry **Send Payslips by SMS** (preview dialog; the resend box refreshes
   the preview in place), Salary Slip **Send by SMS** (`public/js/`, `doctype_js`).
3. Kenya Payroll Settings: "Payslips by SMS" section with the template.

Tests: `test_payslip_sms.py` (7 integration, provider mocked; skipped without royce_talk).
Full suite 38 unit + 96 integration on HRMS 16.51 (1 pre-existing skip); `check_names.py`
passes. Browser check on 16.52: real preview call returns the "set the API key" message;
the dialog, resend refresh, send call and the slip confirm work with the preview stubbed
(no payroll data on the dev site). The check found and fixed a loop: the first version
rebuilt the dialog when the resend box changed, which re-fired its change event forever.

## Not done

- A link to the full payslip (expiring share key, or HRMS's employee self-service).
- Automatic sending on submit (could be an opt-in setting).
- Not tried against the real SMS provider from payroll (royce_talk's own send is in use).
