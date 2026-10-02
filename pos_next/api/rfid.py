# Copyright (c) 2026, BrainWise and contributors
# For license information, please see license.txt

"""Optional RFID counter mode.

POS Next has no RFID logic of its own. When the rfid_retail app is installed and
the counter is marked as an RFID counter there, the frontend switches into tray
mode and talks to rfid_retail directly. Every other site gets {"enabled": False}
and POS Next behaves exactly as before.
"""

import frappe


@frappe.whitelist()
def get_rfid_config(pos_profile):
	if not pos_profile or "rfid_retail" not in frappe.get_installed_apps():
		return {"enabled": False}
	try:
		from rfid_retail.api.pos import counter_config
	except ImportError:
		return {"enabled": False}
	return counter_config(pos_profile)
