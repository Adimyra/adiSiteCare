"""Staging banner — shown above the website navbar via Website Settings → Banner HTML.

Our block sits between two markers, so any banner HTML that was already there stays
untouched and "remove" takes out only our part.
"""

import os
import re
import subprocess
from datetime import datetime

import frappe

START = "<!-- adisitecare:staging-banner -->"
END = "<!-- /adisitecare:staging-banner -->"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sept", "Oct", "Nov", "Dec"]
FOOTER = re.compile(r"Dump completed on (\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}:\d{2})")
STAMP = re.compile(r"^(\d{8})_(\d{6})-")

TEMPLATE = """<style>
    /* full width: take away the padding/border of whatever box the theme puts the banner in */
    :has(> .sitecare-staging-banner) { padding: 0 !important; border: 0 !important; background: none !important; }
    .sitecare-staging-banner { margin: 0 !important; }
</style>
<div class="sitecare-staging-banner" style="
    width: 100%;
    background: linear-gradient(135deg, #fff7ed 0%, #fff1f2 100%);
    color: #7f1d1d;
    border-bottom: 1px solid #fecaca;
    padding: 12px 20px;
    text-align: center;
    font-family: Arial, Helvetica, sans-serif;
    box-sizing: border-box;
    position: relative;
    z-index: 99999;
">
    <div style="display: flex; align-items: center; justify-content: center; gap: 10px; flex-wrap: wrap; line-height: 1.5;">
        <span style="display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px;
            background: #fee2e2; border: 1px solid #fecaca; border-radius: 50%; font-size: 16px;">⚠️</span>
        <strong style="color: #b91c1c; font-size: 14px; letter-spacing: .5px;">STAGING SITE</strong>
        <span style="color: #7f1d1d; font-size: 13px;">Demo / Testing Environment</span>
    </div>
    <div style="margin-top: 5px; font-size: 13px; color: #991b1b; line-height: 1.5;">
        🚫 <strong>Please do not place orders or make payments.</strong>
        This is a demo/testing environment and no transactions will be processed.
    </div>
    <div style="margin-top: 9px; display: flex; justify-content: center; align-items: center;">
        <span style="display: inline-flex; align-items: center; gap: 6px; background: #f0fdf4; color: #166534;
            border: 1px solid #bbf7d0; border-radius: 20px; padding: 6px 13px; font-size: 12px; font-weight: 600;">
            💾 Database Backup:
            <span style="font-weight: 500;">Updated till {when}</span>
        </span>
    </div>
</div>"""


# ---------------------------------------------------------------- when was the backup taken


def backup_time(path):
    """Exact time the database backup was taken, or None.
    1. the dump's own footer: "-- Dump completed on 2026-09-26  2:05:27"
    2. the time in a Frappe backup file name (not for uploaded files — that's the upload time)"""
    if not path or not os.path.isfile(path):
        return None
    try:
        reader = ["gzip", "-cd", path] if path.endswith(".gz") else ["cat", path]
        tail = subprocess.run(f"{' '.join(_q(x) for x in reader)} | tail -c 400", shell=True,
            capture_output=True, text=True, timeout=600).stdout
        m = FOOTER.search(tail)
        if m:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    name = os.path.basename(path)
    m = STAMP.match(name)
    if m and "-uploaded-" not in name:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    return None


def _q(s):
    import shlex

    return shlex.quote(s)


def label(dt):
    """21 Sept, Monday, 2026 — 05:33 AM IST"""
    dt = frappe.utils.get_datetime(dt)
    return f"{dt.day} {MONTHS[dt.month - 1]}, {dt.strftime('%A')}, {dt.year} — {dt.strftime('%I:%M %p')} {_tz_label()}".strip()


def _tz_label():
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(frappe.utils.get_system_timezone())).tzname() or ""
    except Exception:
        return ""


def last_restore():
    """The latest successful restore and the best known time of its backup."""
    job = frappe.get_all("SiteCare Job", {"job_type": "Restore", "status": "Success"},
        ["name", "restore_db", "backup_taken_on", "creation"], order_by="creation desc", limit=1)
    if not job:
        return None
    job = job[0]
    when, source = job.backup_taken_on, "backup"
    if not when and job.restore_db:
        when = backup_time(frappe.get_site_path("private", "backups", job.restore_db))
        if when:
            frappe.db.set_value("SiteCare Job", job.name, "backup_taken_on", when, update_modified=False)
    if not when:
        when, source = job.creation, "job"
    return {"job": job.name, "file": job.restore_db, "when": str(when), "source": source}


# ---------------------------------------------------------------- Website Settings


def html(when):
    return f"{START}\n{TEMPLATE.replace('{when}', frappe.utils.escape_html(label(when)))}\n{END}"


def current():
    return frappe.db.get_single_value("Website Settings", "banner_html") or ""


def is_on():
    return START in current()


def _without_ours(text):
    return re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S).strip()


def apply(when):
    rest = _without_ours(current())
    frappe.db.set_single_value("Website Settings", "banner_html", html(when) + ("\n" + rest if rest else ""))
    _refresh()


def remove():
    frappe.db.set_single_value("Website Settings", "banner_html", _without_ours(current()))
    _refresh()


def _refresh():
    frappe.db.commit()
    try:
        from frappe.website.utils import clear_cache

        clear_cache()
    except Exception:
        pass
