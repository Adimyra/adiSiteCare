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
    @keyframes sitecare-pulse { 0% { box-shadow: 0 0 0 0 rgba(220,38,38,.55); } 70% { box-shadow: 0 0 0 7px rgba(220,38,38,0); } 100% { box-shadow: 0 0 0 0 rgba(220,38,38,0); } }
    .sitecare-staging-banner .sc-msg-short { display: none; }
    @media (max-width: 640px) { .sitecare-staging-banner .sc-msg-long { display: none; } .sitecare-staging-banner .sc-msg-short { display: inline; } }
</style>
<div class="sitecare-staging-banner" style="
    width: 100%; box-sizing: border-box; position: relative; z-index: 99999;
    background: linear-gradient(90deg, #fff7ed 0%, #fff1f2 55%, #fdf2f8 100%);
    border-bottom: 1px solid #fecdd3;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Arial, sans-serif;
    font-size: 13px; line-height: 1.4; color: #7f1d1d;
    padding: 7px 16px;
    display: flex; align-items: center; justify-content: center; gap: 8px 14px; flex-wrap: wrap;
">
    <span style="display: inline-flex; align-items: center; gap: 7px; background: #b91c1c; color: #fff;
        border-radius: 999px; padding: 3px 11px 3px 9px; font-size: 11px; font-weight: 700; letter-spacing: .08em;">
        <span style="width: 7px; height: 7px; border-radius: 50%; background: #fecaca; animation: sitecare-pulse 1.8s infinite;"></span>
        STAGING
    </span>
    <span style="color: #7f1d1d;">
        <strong style="font-weight: 600;">Test site</strong>
        <span class="sc-msg-long"> — please don't place orders or make payments. Nothing here is processed.</span>
        <span class="sc-msg-short"> — no orders or payments.</span>
    </span>
    <span style="display: inline-flex; align-items: center; gap: 8px; background: #ffffff;
        border: 1px solid #fecdd3; border-radius: 999px; padding: 3px 12px 3px 4px; font-size: 12px; color: #6b7280;
        box-shadow: 0 1px 3px rgba(127,29,29,.08);">
        <span style="display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px;
            border-radius: 50%; background: #fee2e2; flex: none;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#b91c1c" stroke-width="2.3" stroke-linecap="round"
                stroke-linejoin="round"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>
        </span>
        <span style="color: #7f1d1d; font-weight: 600;">Database backup</span>
        <span style="width: 1px; height: 12px; background: #fecdd3;"></span>
        <span style="color: #6b7280;">{date}</span>
        <span style="width: 3px; height: 3px; border-radius: 50%; background: #fca5a5;"></span>
        <strong style="color: #b91c1c; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: .02em;">{time}</strong>
    </span>
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


def parts(dt):
    """("Sat, 26 Sept 2026", "02:05 AM IST")"""
    dt = frappe.utils.get_datetime(dt)
    return f"{dt.strftime('%a')}, {dt.day} {MONTHS[dt.month - 1]} {dt.year}", f"{dt.strftime('%I:%M %p')} {_tz_label()}".strip()


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
    date, time = parts(when)
    esc = frappe.utils.escape_html
    return f"{START}\n{TEMPLATE.replace('{date}', esc(date)).replace('{time}', esc(time))}\n{END}"


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
