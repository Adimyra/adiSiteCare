// adiSiteCare — backup, restore and site tools from Desk (Frappe v15 / v16)
frappe.pages["sitecare"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("adiSiteCare"), single_column: true });
	wrapper.sitecare = new adiSiteCarePage(page);
};
frappe.pages["sitecare"].on_page_show = function (wrapper) {
	wrapper.sitecare && wrapper.sitecare.data && !wrapper.sitecare.watching && wrapper.sitecare.load();
};

const API = "adisitecare.api.";
const CHUNK = 5 * 1024 * 1024;
const esc = (s) => frappe.utils.escape_html(s == null ? "" : String(s));
const dl = (f) => `/api/method/adisitecare.api.download?file=${encodeURIComponent(f)}`;
const human = (n) => { n = +n || 0; for (const u of ["B", "KB", "MB", "GB", "TB"]) { if (n < 1024) return u === "B" ? `${n} B` : `${n.toFixed(1)} ${u}`; n /= 1024; } return `${n.toFixed(1)} PB`; };
const dur = (s) => { s = Math.max(0, Math.round(s || 0)); return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`; };

const P = {
	db: "M12 3c4.97 0 9 1.34 9 3s-4.03 3-9 3-9-1.34-9-3 4.03-3 9-3zm9 3v6c0 1.66-4.03 3-9 3s-9-1.34-9-3V6m18 6v6c0 1.66-4.03 3-9 3s-9-1.34-9-3v-6",
	files: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
	down: "M12 4v12m0 0-5-5m5 5 5-5M5 20h14",
	up: "M12 20V8m0 0-5 5m5-5 5 5M5 4h14",
	restore: "M3 12a9 9 0 1 0 3-6.7L3 8m0-5v5h5",
	tools: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z",
	history: "M12 8v4l3 2m6-2a9 9 0 1 1-9-9 9 9 0 0 1 9 9z",
	check: "M5 12.5l4.5 4.5L19 7.5",
	x: "M6 6l12 12M18 6 6 18",
	alert: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
	shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
	mail: "M4 6h16v12H4zM4 7l8 6 8-6",
	clock: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
	power: "M12 3v8M6.3 6.3a8 8 0 1 0 11.4 0",
	server: "M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01",
	cpu: "M9 9h6v6H9zM4 9h2m-2 6h2m12-6h2m-2 6h2M9 4v2m6-2v2M9 18v2m6-2v2M6 6h12v12H6z",
	copy: "M9 9h11v11H9zM5 15H4V4h11v1",
	migrate: "M4 7h11l-3-3m3 3-3 3M20 17H9l3 3m-3-3 3-3",
	broom: "M19 5 9 15m-3 0 3 3-4 2-2-2 2-4zM14 4l6 6",
};
const ic = (n, size = 16, extra = "") => `<svg class="ae-ic ${extra}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${P[n]}"/></svg>`;

class adiSiteCarePage {
	constructor(page) {
		this.page = page;
		this.$root = $(`<div class="ae"></div>`).appendTo(page.main);
		this.tab = "backup";
		this.opt = { withFiles: 0, source: "upload" };
		this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
		this.injectStyle();
		this.load();
	}

	// ============================================================ data
	async load() {
		const r = await frappe.call({ method: API + "overview" });
		this.data = r.message;
		this.render();
		if (this.data.busy && !this.watching) {
			const j = (this.data.jobs || []).find((x) => x.name === this.data.busy);
			this.watch(this.data.busy, (j && j.status_token) || undefined);
		}
	}

	render() {
		this.$root.html(`
			${this.heroHtml()}
			${this.statsHtml()}
			<div class="ae-tabs">
				${[["backup", "db", __("Backup")], ["restore", "restore", __("Restore")], ["tools", "tools", __("Tools")], ["history", "history", __("History")]]
					.map(([k, i, l]) => `<button data-tab="${k}" class="${this.tab === k ? "on" : ""}">${ic(i, 15)}<span>${l}</span></button>`).join("")}
			</div>
			<div class="ae-job"></div>
			<div class="ae-body"></div>`);
		this.$root.find(".ae-tabs button").on("click", (e) => { this.tab = $(e.currentTarget).data("tab"); this.render(); });
		this.$root.find(".ae-chip[data-sw]").on("click", (e) => this.switchAction($(e.currentTarget).data("sw")));
		const body = this.$root.find(".ae-body");
		({ backup: () => this.renderBackup(body), restore: () => this.renderRestore(body), tools: () => this.renderTools(body), history: () => this.renderHistory(body) })[this.tab]();
		if (this.lastState) this.renderJob(this.lastState);
	}

	heroHtml() {
		const d = this.data, h = d.health || {};
		const usedPct = d.disk.pct_used, low = d.disk.free_bytes < 5 * 1024 ** 3;
		const chip = (ok, icon, label, value, sw, badTone, act) => `<div class="ae-chip ${ok ? "ok" : badTone || "warn"}" ${sw ? `data-sw="${sw}" role="button" title="${esc(act)}"` : ""}>
			<span class="dot"></span>${ic(icon, 14)}<span class="l">${label}</span><b>${value}</b>${sw ? `<span class="ae-chip-act">${esc(act)}</span>` : ""}</div>`;
		return `<div class="ae-hero">
			<div class="ae-hero-main">
				<div class="ae-logo"><img src="/assets/adisitecare/images/adiSiteCare_logo.png" alt="adiSiteCare"></div>
				<div>
					<div class="ae-eyebrow">adiSiteCare</div>
					<div class="ae-site">${esc(d.site)}</div>
					<div class="ae-meta">Frappe ${esc(d.frappe)} · ${__("Database")} ${esc(d.db_size)} · ${d.apps.length} ${__("apps")}</div>
				</div>
				<div class="ae-disk">
					<div class="ae-disk-top"><span>${__("Disk")}</span><b class="${low ? "bad" : ""}">${esc(d.disk.free)} ${__("free")}</b></div>
					<div class="ae-disk-bar"><div style="width:${usedPct}%" class="${usedPct > 90 ? "bad" : ""}"></div></div>
					<div class="ae-disk-sub">${usedPct}% ${__("of")} ${esc(d.disk.total)} ${__("used")}</div>
				</div>
			</div>
			<div class="ae-chips">
				${chip(!h.maintenance, "shield", __("Maintenance"), h.maintenance ? __("On") : __("Off"), "maintenance", null, __("Turn on"))}
				${chip(!h.scheduler_paused, "clock", __("Scheduler"), h.scheduler_disabled ? __("Disabled") : h.scheduler_paused ? __("Paused") : __("Running"), "scheduler", null, h.scheduler_paused ? __("Resume") : __("Pause"))}
				${chip(!h.emails_muted, "mail", __("Emails"), h.emails_muted ? __("Muted") : __("Sending"), h.emails_muted_bench ? null : "emails", null, h.emails_muted ? __("Unmute") : __("Mute"))}
				${chip(h.workers !== 0, "cpu", __("Workers"), h.workers == null ? "—" : h.workers, null, "bad")}
			</div>
			${h.workers === 0 ? `<div class="ae-note bad">${ic("alert", 15)}<span>${__("No background worker is running — jobs will wait in the queue. Start one with")} <code>bench worker</code> ${__("(supervisor does this in production).")}</span></div>` : ""}
			${low ? `<div class="ae-note warn">${ic("alert", 15)}<span>${__("Low disk space — a backup or restore needs room for the files, a safety backup and the database.")}</span></div>` : ""}
		</div>`;
	}

	statsHtml() {
		const d = this.data, h = d.health || {}, st = d.stats || {};
		const issues = [];
		if (h.workers === 0) issues.push(__("no background worker"));
		if (h.maintenance) issues.push(__("maintenance mode is on"));
		if (h.scheduler_paused) issues.push(__("scheduler paused"));
		if (h.emails_muted) issues.push(__("emails muted"));
		if (d.disk.free_bytes < 5 * 1024 ** 3) issues.push(__("low disk space"));
		if (st.last_failed) issues.push(__("last job failed"));
		const lastB = d.backups[0];
		const stat = (icon, cls, label, value) => `<div class="ae-stat"><div class="ae-stat-ic ${cls}">${ic(icon, 19)}</div><div><small>${label}</small><b>${value}</b></div></div>`;
		return `<div class="ae-status ${issues.length ? "warn" : "ok"}">
				<div class="ae-status-ic">${ic(issues.length ? "alert" : "check", 16)}</div>
				<div><b>${issues.length ? __("Needs attention") : __("All good")}</b> — <span>${issues.length ? issues.join(" · ") : __("backups are available and the site is running normally.")}</span></div>
			</div>
			<div class="ae-stats">
				${stat("clock", "", __("Last backup"), lastB ? `${esc(lastB.when.split(" ")[1])} · ${esc(lastB.when.split(" ")[0])}` : __("None yet"))}
				${stat("db", "dark", __("Backups on server"), `${d.backups.length} · ${human(st.backup_bytes)}`)}
				${stat("restore", "", __("Last restore"), st.last_restore ? esc(frappe.datetime.prettyDate(st.last_restore)) : __("Never"))}
				${stat(st.failed_30 ? "alert" : "check", st.failed_30 ? "bad" : "", __("Jobs · 30 days"), `${st.ok_30 || 0} ${__("ok")} · ${st.failed_30 || 0} ${__("failed")}`)}
			</div>`;
	}

	// ============================================================ backup tab
	renderBackup(body) {
		const d = this.data;
		const tile = (v, icon, t, s) => `<label class="ae-tile ${this.opt.withFiles === v ? "on" : ""}"><input type="radio" name="bk" value="${v}" ${this.opt.withFiles === v ? "checked" : ""}>
			<span class="ae-tile-ic">${ic(icon, 20)}</span><span><b>${t}</b><small>${s}</small></span></label>`;
		body.html(`
			<div class="ae-card">
				<div class="ae-card-head"><div><h3>${__("Create a backup")}</h3><p>${__("Runs")} <code>bench --site ${esc(d.site)} backup</code> ${__("in the background — you can leave this page, you'll get a notification.")}</p></div></div>
				<div class="ae-tiles">
					${tile(0, "db", __("Database only"), __("Fast · all data, no attachments"))}
					${tile(1, "files", __("Database + files"), __("--with-files · public & private attachments"))}
				</div>
				<div class="ae-actions"><button class="btn btn-primary ae-btn bk-go" ${d.busy ? "disabled" : ""}>${ic("db", 15)} ${__("Start backup")}</button>
					${d.busy ? `<span class="ae-muted">${__("A job is running…")}</span>` : ""}</div>
			</div>
			<div class="ae-card">
				<div class="ae-card-head"><div><h3>${__("Backups on this server")}</h3><p><code>sites/${esc(d.site)}/private/backups</code> · ${__("Frappe keeps backups for about a day")}</p></div></div>
				${d.backups.length ? `<div class="ae-list">${d.backups.map((b) => `
					<div class="ae-row">
						<div class="ae-row-when"><b>${esc(b.when.split(" ")[1])}</b><small>${esc(b.when.split(" ")[0])}</small></div>
						<div class="ae-files">
							${[["db", "db", __("Database")], ["public", "files", __("Public")], ["private", "files", __("Private")], ["config", "server", __("Config")]]
								.filter(([k]) => b.files[k]).map(([k, i, l]) => `<a class="ae-file" href="${esc(b.files[k].url)}" title="${esc(b.files[k].name)}">${ic(i, 13)} ${l} <span>${esc(b.files[k].size)}</span>${ic("down", 13, "dl")}</a>`).join("")}
							${/uploaded/.test((b.files.db || {}).name || "") ? `<span class="ae-tag">${__("uploaded")}</span>` : ""}
						</div>
						${b.files.db ? `<button class="btn btn-default btn-xs bk-restore" data-stamp="${esc(b.stamp)}">${ic("restore", 13)} ${__("Restore")}</button>` : ""}
					</div>`).join("")}</div>` : `<div class="ae-empty">${ic("db", 28)}<div>${__("No backups yet — create one above.")}</div></div>`}
			</div>`);
		body.find("input[name=bk]").on("change", (e) => { this.opt.withFiles = +e.target.value; this.render(); });
		body.find(".bk-go").on("click", async () => {
			const r = await frappe.call({ method: API + "start_backup", args: { with_files: this.opt.withFiles }, freeze: true });
			frappe.show_alert({ message: __("Backup started"), indicator: "blue" });
			this.watch(r.message.job);
			this.load();
		});
		body.find(".bk-restore").on("click", (e) => {
			this.preset = this.data.backups.find((x) => x.stamp === $(e.currentTarget).data("stamp"));
			this.opt.source = "server";
			this.tab = "restore";
			this.render();
		});
	}

	// ============================================================ restore tab
	renderRestore(body) {
		const d = this.data, p = this.preset, src = this.opt.source;
		const LABEL = { db: __("Database backup"), public: __("Public files"), private: __("Private files"), config: __("Site config") };
		const ACCEPT = { db: ".gz,.sql", public: ".tar,.tgz", private: ".tar,.tgz", config: ".json" };
		const HINT = { db: ".sql.gz / .sql", public: ".tar / .tgz", private: ".tar / .tgz", config: ".json · " + __("optional") };
		const slot = (kind, req) => src === "upload"
			? `<label class="ae-drop" data-kind="${kind}"><input type="file" class="rs-file" data-kind="${kind}" accept="${ACCEPT[kind]}">
				<span class="ae-drop-ic">${ic(kind === "db" ? "db" : kind === "config" ? "server" : "files", 18)}</span>
				<span class="ae-drop-t"><b>${LABEL[kind]}${req ? " *" : ""}</b><small class="fn">${__("Drop a file or click")} · ${HINT[kind]}</small></span>
				<span class="ae-drop-bar"><span></span></span></label>`
			: `<label class="ae-field"><span>${LABEL[kind]}${req ? " *" : ""} <small>${HINT[kind]}</small></span>
				<select class="form-control rs-pick" data-kind="${kind}"><option value="">${__("— none —")}</option>
				${d.backups.filter((b) => b.files[kind]).map((b) => `<option value="${esc(b.files[kind].name)}" ${p && p.files[kind] && p.stamp === b.stamp ? "selected" : ""}>${esc(b.when)} · ${esc(b.files[kind].size)}</option>`).join("")}</select></label>`;
		const hasFiles = src === "server" ? !!(p && (p.files.public || p.files.private)) : !!this.opt.rsFiles;
		body.html(`
			<div class="ae-card">
				<div class="ae-card-head"><div><h3>${__("Restore a backup")}</h3><p>${__("Replaces this site's database (and files, if chosen). A safety backup is always taken first.")}</p></div></div>
				<div class="ae-flow">
					${[["shield", __("Check files")], ["db", __("Safety backup")], ["alert", __("Maintenance on")], ["restore", __("Restore")], ["migrate", __("Migrate")], ["power", __("Back online")]]
						.map(([i, l], n) => `<div class="ae-flow-step"><span>${ic(i, 15)}</span><small>${n + 1}. ${l}</small></div>`).join(`<div class="ae-flow-line"></div>`)}
				</div>
				<div class="ae-sec"><div class="ae-sec-n">1</div><div class="ae-sec-b">
					<h4>${__("Where is the backup?")}</h4>
					<div class="ae-seg">
						<button data-src="upload" class="${src === "upload" ? "on" : ""}">${ic("up", 14)} ${__("Upload from my computer")}</button>
						<button data-src="server" class="${src === "server" ? "on" : ""}">${ic("server", 14)} ${__("Backup on this server")}</button>
					</div>
					<p class="ae-muted">${src === "upload" ? __("E.g. a backup downloaded from production, restored here on staging. Files are saved into private/backups.") : __("E.g. go back to an earlier state of this same site.")}</p>
					<div class="ae-grid2">${slot("db", true)}${slot("config")}</div>
					<label class="ae-check"><input type="checkbox" class="rs-files" ${hasFiles ? "checked" : ""}><span><b>${__("Also restore files")}</b><small>${__("Public and/or private attachments")}</small></span></label>
					<div class="ae-grid2 rs-files-box" style="${hasFiles ? "" : "display:none"}">${slot("public")}${slot("private")}</div>
					${src === "upload" ? `<p class="ae-muted small">${__("Restoring another site's backup? Add its site config — only its encryption key is used, so saved passwords (email accounts, integrations) keep working.")}</p>` : ""}
				</div></div>
				<div class="ae-sec"><div class="ae-sec-n">2</div><div class="ae-sec-b">
					<h4>${__("Options")}</h4>
					<label class="ae-check"><input type="checkbox" class="rs-staging"><span><b>${__("This is a staging / test copy")}</b><small>${__("Emails stay muted and the scheduler stays paused, so production data here never emails real customers. Switch them on later in Tools.")}</small></span></label>
					<label class="ae-check ${d.health.restart_available ? "" : "dim"}"><input type="checkbox" class="rs-restart" ${d.health.restart_available ? "" : "disabled"}><span><b>${__("Restart bench at the end")}</b><small>${d.health.restart_available ? __("Usually not needed — you can also do it later from Tools.") : __("Not possible on this server without a password — run it later from Tools (After-restore tasks) or the terminal if needed.")}</small></span></label>
				</div></div>
				<div class="ae-sec"><div class="ae-sec-n">3</div><div class="ae-sec-b">
					<h4>${__("Confirm")}</h4>
					<div class="ae-grid2">
						<label class="ae-field"><span>${__("Type the site name")} *</span><input type="text" class="form-control rs-site" placeholder="${esc(d.site)}" autocomplete="off"></label>
						<label class="ae-field"><span>${__("Your login password")} *</span><input type="password" class="form-control rs-pwd" autocomplete="current-password">
							<small>${__("The password you sign in to this site with ({0}) — not the database or server password.", [esc(frappe.session.user)])}</small></label>
					</div>
					<div class="ae-actions"><button class="btn btn-danger ae-btn rs-go" ${d.busy ? "disabled" : ""}>${ic("restore", 15)} ${__("Start restore")}</button></div>
				</div></div>
			</div>`);
		body.find(".ae-seg button").on("click", (e) => { this.opt.source = $(e.currentTarget).data("src"); this.render(); });
		body.find(".rs-files").on("change", (e) => { this.opt.rsFiles = e.target.checked; body.find(".rs-files-box").toggle(e.target.checked); });
		body.find(".rs-file").on("change", (e) => {
			const f = e.target.files[0], $d = $(e.target).closest(".ae-drop");
			$d.removeClass("done err").toggleClass("has", !!f).find(".fn").text(f ? `${f.name} · ${human(f.size)}` : "");
		});
		body.find(".ae-drop").on("dragover", (e) => { e.preventDefault(); $(e.currentTarget).addClass("over"); })
			.on("dragleave drop", (e) => $(e.currentTarget).removeClass("over"))
			.on("drop", (e) => {
				e.preventDefault();
				const input = $(e.currentTarget).find("input")[0];
				input.files = e.originalEvent.dataTransfer.files;
				$(input).trigger("change");
			});
		body.find(".rs-go").on("click", () => this.startRestore(body));
	}

	async uploadFile(file, kind, stamp, $drop) {
		const id = Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
		const total = Math.max(1, Math.ceil(file.size / CHUNK));
		const $bar = $drop.find(".ae-drop-bar span"), $fn = $drop.find(".fn");
		$drop.addClass("busy");
		let ref = null;
		for (let i = 0; i < total; i++) {
			const fd = new FormData();
			fd.append("upload_id", id); fd.append("kind", kind); fd.append("filename", file.name); fd.append("stamp", stamp);
			fd.append("index", i); fd.append("total", total);
			fd.append("chunk", file.slice(i * CHUNK, (i + 1) * CHUNK), file.name);
			const res = await fetch("/api/method/" + API + "upload_chunk", { method: "POST", body: fd, headers: { "X-Frappe-CSRF-Token": frappe.csrf_token } });
			const j = await res.json().catch(() => ({}));
			if (!res.ok) {
				$drop.removeClass("busy").addClass("err");
				let msg = __("Upload failed");
				try { msg = JSON.parse(JSON.parse(j._server_messages)[0]).message; } catch (e) { /* keep default */ }
				$fn.text(msg);
				throw new Error(msg);
			}
			const pct = Math.round(((i + 1) / total) * 100);
			$bar.css("width", pct + "%");
			$fn.text(`${__("Uploading")} ${file.name} · ${pct}%`);
			ref = j.message.ref;
		}
		$drop.removeClass("busy").addClass("done");
		$fn.text(`✓ ${file.name} · ${human(file.size)} · ${__("saved to backups")}`);
		return ref;
	}

	async startRestore(body) {
		const withFiles = body.find(".rs-files").is(":checked");
		const now = new Date(), z = (n) => String(n).padStart(2, "0");
		const stamp = `${now.getFullYear()}${z(now.getMonth() + 1)}${z(now.getDate())}_${z(now.getHours())}${z(now.getMinutes())}${z(now.getSeconds())}`;
		const fileOf = (kind) => { const el = body.find(`.rs-file[data-kind=${kind}]`)[0]; return el && el.files[0]; };
		const refOf = async (kind) => {
			const f = fileOf(kind);
			if (f) return this.uploadFile(f, kind, stamp, body.find(`.ae-drop[data-kind=${kind}]`));
			return body.find(`.rs-pick[data-kind=${kind}]`).val() || null;
		};
		const site = body.find(".rs-site").val().trim(), pwd = body.find(".rs-pwd").val();
		if (!fileOf("db") && !body.find(".rs-pick[data-kind=db]").val()) return frappe.msgprint(__("Choose the database backup."));
		if (site !== this.data.site) return frappe.msgprint(__("Type the site name exactly: {0}", [this.data.site]));
		if (!pwd) return frappe.msgprint(__("Enter your login password for this site."));
		const $btn = body.find(".rs-go").prop("disabled", true);
		try {
			const db = await refOf("db");
			const config = await refOf("config");
			const pub = withFiles ? await refOf("public") : null;
			const priv = withFiles ? await refOf("private") : null;
			if (withFiles && !pub && !priv) throw new Error(__("Choose the public and/or private files backup, or untick Also restore files."));
			frappe.confirm(`<div style="line-height:1.6">${__("Restore {0} into {1}?", [`<b>${esc(db)}</b>`, `<b>${esc(this.data.site)}</b>`])}<br>
				<span class="text-muted">${__("The site goes into maintenance mode while it runs. A safety backup is taken first.")}</span></div>`, async () => {
				const r = await frappe.call({ method: API + "start_restore", freeze: true, args: {
					db, config, public: pub, private: priv, confirm_site: site, password: pwd,
					restart: body.find(".rs-restart").is(":checked") ? 1 : 0, staging: body.find(".rs-staging").is(":checked") ? 1 : 0 } });
				this.watch(r.message.job, r.message.token);
			}, () => { $btn.prop("disabled", false); });
		} catch (e) {
			$btn.prop("disabled", false);
			frappe.msgprint({ title: __("Can't start restore"), message: esc(e.message), indicator: "red" });
		}
	}

	// ============================================================ tools tab
	renderTools(body) {
		const d = this.data, h = d.health;
		const tool = (action, icon, title, text, cls = "", disabled = false, note = "") => `<div class="ae-tool ${cls}">
			<div class="ae-tool-ic">${ic(icon, 20)}</div>
			<div class="ae-tool-b"><b>${title}</b><small>${text}</small>${note ? `<small class="ae-tool-note">${note}</small>` : ""}</div>
			<button class="btn btn-default btn-sm ae-act" data-action="${action}" data-label="${esc(title)}" ${d.busy || disabled ? "disabled" : ""}>${__("Run")}</button></div>`;
		body.html(`
			<div class="ae-card">
				<div class="ae-card-head"><div><h3>${__("Site switches")}</h3><p>${__("Saved in this site's site_config.json — take effect within a minute.")}</p></div></div>
				<div class="ae-switch">
					<div class="ae-switch-ic ${h.emails_muted ? "warn" : "ok"}">${ic("mail", 20)}</div>
					<div class="ae-switch-b"><b>${__("Outgoing emails")} · <span class="${h.emails_muted ? "t-warn" : "t-ok"}">${h.emails_muted ? __("Muted") : __("Sending")}</span></b>
						<small>${h.emails_muted
							? __("mute_emails = 1 — emails are still created but wait in the Email Queue instead of being sent. Unmuting sends everything that is waiting.")
							: __("Emails are sent normally.")}</small>
						${h.emails_muted && h.pending_emails ? `<small class="t-warn">${__("{0} emails are waiting in the queue — you can discard them when unmuting.", [h.pending_emails])}</small>` : ""}
						${h.emails_muted_bench ? `<small class="t-warn">${__("Muted for the whole bench in common_site_config.json — change it there.")}</small>` : ""}</div>
					<button class="btn btn-sm ${h.emails_muted ? "btn-primary" : "btn-default"} em-toggle" ${h.emails_muted_bench ? "disabled" : ""}>${h.emails_muted ? __("Unmute emails") : __("Mute emails")}</button>
				</div>
				<div class="ae-switch">
					<div class="ae-switch-ic ${h.scheduler_paused ? "warn" : "ok"}">${ic("clock", 20)}</div>
					<div class="ae-switch-b"><b>${__("Scheduler")} · <span class="${h.scheduler_paused ? "t-warn" : "t-ok"}">${h.scheduler_paused ? __("Paused") : __("Running")}</span></b>
						<small>${h.scheduler_disabled ? __("Disabled in System Settings — scheduled jobs (auto emails, reminders, syncs, auto backups) don't run. Resume switches it back on.") : h.scheduler_paused ? __("pause_scheduler = 1 — scheduled jobs (auto emails, reminders, syncs, auto backups) don't run.") : __("Scheduled jobs run normally.")}</small>
						${h.scheduler_paused_bench ? `<small class="t-warn">${__("Paused for the whole bench in common_site_config.json — change it there.")}</small>` : ""}</div>
					<button class="btn btn-sm ${h.scheduler_paused ? "btn-primary" : "btn-default"} sc-toggle" ${h.scheduler_paused_bench ? "disabled" : ""}>${h.scheduler_paused ? __("Resume scheduler") : __("Pause scheduler")}</button>
				</div>
				<div class="ae-switch">
					<div class="ae-switch-ic ${h.maintenance ? "warn" : "ok"}">${ic("shield", 20)}</div>
					<div class="ae-switch-b"><b>${__("Maintenance mode")} · <span class="${h.maintenance ? "t-warn" : "t-ok"}">${h.maintenance ? __("On") : __("Off")}</span></b>
						<small>${__("Everyone — you included — sees the maintenance page while it's on, so it runs for a set time and switches off by itself.")}</small></div>
					<button class="btn btn-sm btn-default mm-on" ${d.busy ? "disabled" : ""}>${__("Turn on…")}</button>
				</div>
			</div>
			<div class="ae-card">
				<div class="ae-card-head"><div><h3>${__("Run a command")}</h3><p>${__("Runs in the background with the live terminal — same as typing it on the server.")}</p></div></div>
				<div class="ae-tools">
					${tool("post_restore", "restore", __("After-restore tasks"), __("migrate → clear-cache → clear-website-cache → restart. Use it if you restored without restart, or something looks stale."), "hi", false,
						h.restart_available ? "" : esc(__("Restart is skipped here.") + " " + this.restartHint()))}
					${tool("migrate", "migrate", __("Migrate"), "bench --site " + esc(d.site) + " migrate · " + __("then clears the cache"))}
					${tool("clear_cache", "broom", __("Clear cache"), "clear-cache · clear-website-cache")}
					${tool("restart", "power", __("Restart bench"), __("Restarts web and background workers (supervisor)."), "", !h.restart_available,
						h.restart_available ? "" : esc(this.restartHint()))}
				</div>
			</div>`);
		body.find(".ae-act").on("click", (e) => {
			const $b = $(e.currentTarget);
			frappe.confirm(__("Run {0} now?", [`<b>${esc($b.data("label"))}</b>`]), async () => {
				const r = await frappe.call({ method: API + "start_action", args: { action: $b.data("action") }, freeze: true });
				this.watch(r.message.job);
				this.load();
			});
		});
		body.find(".em-toggle").on("click", () => this.switchAction("emails"));
		body.find(".sc-toggle").on("click", () => this.switchAction("scheduler"));
		body.find(".mm-on").on("click", () => this.switchAction("maintenance"));
	}

	restartHint() {
		return this.data && this.data.health.dev_mode
			? __("Development bench (bench start): press Ctrl+C in that terminal and run bench start again.")
			: __("Restart needs a one-time server setup: sudo bench setup production [user] — or run bench restart in the terminal.");
	}

	// ============================================================ site switches (chips + Tools)
	switchAction(sw) {
		const h = this.data.health;
		if (sw === "emails") {
			if (!h.emails_muted)
				return frappe.confirm(__("Mute outgoing emails? New emails wait in the Email Queue until you unmute."), () => this.setEmails(1, 0));
			const d = new frappe.ui.Dialog({
				title: __("Unmute emails"),
				fields: [
					{ fieldtype: "HTML", options: `<p class="text-muted">${__("Emails will be sent again.")} ${h.pending_emails ? __("{0} emails are waiting in the queue and would be sent now.", [h.pending_emails]) : ""}</p>` },
					...(h.pending_emails ? [{ fieldname: "discard", fieldtype: "Check", default: 1,
						label: __("Discard the {0} waiting emails first", [h.pending_emails]),
						description: __("Recommended on staging — they may be copies of production emails to real customers.") }] : []),
				],
				primary_action_label: __("Unmute"),
				primary_action: (v) => { d.hide(); this.setEmails(0, v.discard ? 1 : 0); },
			});
			return d.show();
		}
		if (sw === "scheduler") {
			return frappe.confirm(h.scheduler_paused
				? __("Resume the scheduler? Scheduled jobs (auto emails, reminders, syncs, auto backups) start running again.")
				: __("Pause the scheduler? Scheduled jobs stop until you resume."), async () => {
				const r = await frappe.call({ method: API + "set_scheduler", args: { paused: h.scheduler_paused ? 0 : 1 }, freeze: true });
				frappe.show_alert({ message: h.scheduler_paused ? __("Scheduler resumed") : __("Scheduler paused"), indicator: "green" });
				this.data.health = r.message.health;
				this.render();
			});
		}
		if (sw === "maintenance") {
			if (h.maintenance) return;
			if (this.data.busy) return frappe.msgprint(__("Another job is running — wait for it to finish."));
			const d = new frappe.ui.Dialog({
				title: __("Turn on maintenance mode"),
				fields: [
					{ fieldtype: "HTML", options: `<div class="ae-note warn" style="margin-bottom:10px;background:rgba(217,119,6,.11);color:#b45309">${ic("alert", 15)}<span>${__("Everyone sees the maintenance page — <b>you included</b>. It can't be switched off from here while it's on, so it switches off automatically when the time is up. This page shows a countdown.")}</span></div>` },
					{ fieldname: "minutes", fieldtype: "Select", label: __("For how long?"), options: "5\n15\n30\n60", default: "15", description: __("minutes · to end early, run on the server: bench --site {0} set-maintenance-mode off", [this.data.site]) },
				],
				primary_action_label: __("Turn on"),
				primary_action: async (v) => {
					d.hide();
					const r = await frappe.call({ method: API + "start_maintenance", args: { minutes: v.minutes }, freeze: true });
					this.watch(r.message.job, r.message.token);
				},
			});
			d.get_primary_btn().removeClass("btn-primary").addClass("btn-danger");
			return d.show();
		}
	}

	async setEmails(muted, discard) {
		const r = await frappe.call({ method: API + "set_emails", freeze: true, args: { muted, discard_pending: discard } });
		frappe.show_alert({ message: muted ? __("Emails muted") : __("Emails unmuted") + (r.message.discarded ? ` · ${__("{0} waiting emails discarded", [r.message.discarded])}` : ""), indicator: "green" });
		this.data.health = r.message.health;
		this.render();
	}

	// ============================================================ history tab
	renderHistory(body) {
		const jobs = this.data.jobs || [];
		const tone = (s) => ({ Success: "ok", Failed: "bad", Interrupted: "mute" }[s] || "run");
		const icon = (j) => (j.job_type === "Restore" ? "restore" : j.job_type === "Action" ? "tools" : "db");
		body.html(`<div class="ae-card">
			<div class="ae-card-head"><div><h3>${__("History")}</h3><p>${__("The last 15 jobs")}</p></div><a class="btn btn-default btn-xs" href="/app/sitecare-job">${__("All jobs")}</a></div>
			${jobs.length ? `<div class="ae-list">${jobs.map((j) => `<div class="ae-row">
				<div class="ae-hist-ic ${tone(j.status)}">${ic(icon(j), 15)}</div>
				<div class="ae-hist-b">
					<div><a href="/app/sitecare-job/${esc(j.name)}"><b>${esc(j.action || j.job_type)}${j.job_type === "Backup" && j.with_files ? " · " + __("with files") : ""}</b></a>
						<span class="ae-pill ${tone(j.status)}">${esc(j.status)}</span></div>
					<small>${esc(j.name)} · ${esc(j.by)} · ${esc(frappe.datetime.str_to_user(j.creation))} (${frappe.datetime.prettyDate(j.creation)})</small>
					${this.howHtml(j)}
					${j.error ? `<small class="t-bad">${esc(j.error.slice(0, 140))}</small>` : ""}
				</div>
				${j.db_file ? `<a class="btn btn-default btn-xs" href="${dl(j.db_file)}">${ic("down", 13)} ${__("Database")}</a>` : ""}
				<button class="btn btn-default btn-xs hs-log" data-job="${esc(j.name)}" data-token="${esc(j.status === "Queued" || j.status === "Running" ? j.status_token || "" : "")}">${j.status === "Queued" || j.status === "Running" ? __("Show progress") : __("View log")}</button>
			</div>`).join("")}</div>` : `<div class="ae-empty">${ic("history", 28)}<div>${__("Nothing yet.")}</div></div>`}
		</div>`);
		body.find(".hs-log").on("click", (e) => {
			const $b = $(e.currentTarget);
			this.watch($b.data("job"), $b.data("token") || undefined);
			$("html,body").animate({ scrollTop: this.$root.find(".ae-job").offset().top - 70 }, 200);
		});
	}

	howHtml(j) {
		const files = (arr) => arr.filter(Boolean).map((f) => `<code>${esc(f)}</code>`).join(" ");
		if (j.job_type === "Restore" && j.restore_db)
			return `<small class="ae-how">${__("Restored from")} ${files([j.restore_db, j.restore_public, j.restore_private])}</small>`;
		if (j.job_type === "Backup" && j.db_file)
			return `<small class="ae-how">${__("Created")} ${files([j.db_file, j.public_file, j.private_file])}</small>`;
		return "";
	}

	// ============================================================ live job: checklist + terminal
	watch(job, token) {
		this.watching = job;
		clearInterval(this._poll);
		const tick = async () => {
			let st = null;
			try {
				if (token) {  // restore: read the public status file — the site itself is in maintenance
					const r = await fetch(`/files/sitecare-status-${token}.json?t=${Date.now()}`, { cache: "no-store" });
					if (r.ok) st = await r.json();
				} else {
					const r = await fetch(`/api/method/${API}job_status?job=${encodeURIComponent(job)}`, { headers: { Accept: "application/json" } });
					if (r.ok) st = (await r.json()).message;
				}
			} catch (e) { /* the site may be restarting — keep trying */ }
			if (!st || !st.status) return;
			this.lastState = st;
			this.renderJob(st);
			if (["Success", "Failed", "Interrupted"].includes(st.status)) {
				clearInterval(this._poll);
				this.watching = null;
				setTimeout(() => this.load(), st.restarted ? 8000 : 400);
			}
		};
		tick();
		this._poll = setInterval(tick, 1200);
	}

	renderJob(st) {
		const $p = this.$root.find(".ae-job");
		const running = st.status === "Queued" || st.status === "Running";
		const tone = { Success: "ok", Failed: "bad", Interrupted: "mute" }[st.status] || "run";
		const now = st.now_ts || Date.now() / 1000;
		const steps = st.steps || [];
		const out = st.outputs || {};
		const links = st.type === "Backup" && st.status === "Success"
			? [["db", __("Database")], ["public", __("Public files")], ["private", __("Private files")], ["config", __("Site config")]].filter(([k]) => out[k])
				.map(([k, l]) => `<a class="btn btn-default btn-xs" href="${dl(out[k])}">${ic("down", 13)} ${l}</a>`).join("")
			: "";
		const stepIc = { done: ic("check", 13), failed: ic("x", 13), skipped: "–", running: `<span class="ae-spin"></span>`, pending: "" };
		const $old = $p.find(".ae-term-body");
		const keepScroll = $old.length && $old[0].scrollHeight - $old[0].scrollTop - $old[0].clientHeight > 40;
		const prevScroll = $old.scrollTop();
		$p.html(`<div class="ae-card ae-jobcard ${tone}">
			<div class="ae-job-head">
				<div class="ae-job-t"><span class="ae-pill ${tone}">${running ? `<span class="ae-spin sm"></span>` : ""}${esc(st.status)}</span>
					<h3>${esc(st.title || st.type || "")}</h3><small>${esc(st.job)} · ${esc(st.stage || "")}</small></div>
				<div class="ae-job-pct">${st.progress || 0}<small>%</small></div>
				${running ? "" : `<button class="btn btn-default btn-xs ae-close" title="${__("Close")}">${ic("x", 13)}</button>`}
			</div>
			<div class="ae-bar ${tone} ${running ? "live" : ""}"><div style="width:${st.progress || 0}%"></div></div>
			${st.error ? `<div class="ae-note bad">${ic("alert", 15)}<span>${esc(st.error)}</span></div>` : ""}
			${st.type === "Restore" && st.status === "Success" ? `<div class="ae-note ok">${ic("check", 15)}<span>${__("Restore complete — the site is live.")} ${st.restarted ? "" : __("If anything looks stale, run After-restore tasks or restart.")}</span></div>
				${st.restarted ? "" : `<div class="ae-links">
					<button class="btn btn-default btn-xs ae-after" data-action="post_restore">${ic("restore", 13)} ${__("After-restore tasks")}</button>
					<button class="btn btn-default btn-xs ae-after" data-action="restart" ${this.data && this.data.health.restart_available ? "" : "disabled"}>${ic("power", 13)} ${__("Restart bench")}</button>
					${this.data && this.data.health.restart_available ? "" : `<small class="ae-muted" style="margin:0">${this.restartHint()}</small>`}
				</div>`}` : ""}
			${links ? `<div class="ae-links">${links}</div>` : ""}
			<div class="ae-job-grid ${steps.length ? "" : "nosteps"}">
				${steps.length ? `<div class="ae-steps">${steps.map((s) => `<div class="ae-step ${s.status}">
					<span class="ae-step-dot">${stepIc[s.status] || ""}</span>
					<span class="ae-step-l">${esc(__(s.label))}</span>
					<span class="ae-step-t">${s.started ? dur((s.ended || now) - s.started) : ""}</span></div>`).join("")}</div>` : ""}
				<div class="ae-term">
					<div class="ae-term-bar"><i></i><i></i><i></i><span>${esc(this.data ? this.data.site : "")} — bench</span>
						<button class="ae-term-copy" title="${__("Copy log")}">${ic("copy", 13)}</button></div>
					<div class="ae-term-body">${this.termHtml(st.log || "")}${running ? `<span class="ae-cursor"></span>` : ""}</div>
				</div>
			</div>
		</div>`);
		const t = $p.find(".ae-term-body")[0];
		if (t) t.scrollTop = keepScroll ? prevScroll : t.scrollHeight;
		$p.find(".ae-term-copy").on("click", () => frappe.utils.copy_to_clipboard(st.log || ""));
		$p.find(".ae-close").on("click", () => { this.lastState = null; $p.empty(); });
		$p.find(".ae-after").on("click", (e) => {
			const action = $(e.currentTarget).data("action");
			frappe.confirm(action === "restart" ? __("Restart bench now? Web and workers restart — a few seconds of downtime.") : __("Run migrate → clear cache → clear website cache → restart now?"), async () => {
				const r = await frappe.call({ method: API + "start_action", args: { action }, freeze: true });
				this.watch(r.message.job);
			});
		});
	}

	termHtml(text) {
		// progress bars print one line per update — keep only the latest, like a real terminal does with \r
		const lines = [];
		for (const line of text.replace(/\r/g, "\n").replace(/\n+$/, "").split("\n")) {
			const m = line.match(/^(.*?)\s*:\s*\[[=\s]*\]?\s*\d*%?$/);
			const prev = lines.length && lines[lines.length - 1].match(/^(.*?)\s*:\s*\[/);
			if (m && prev && prev[1] === m[1]) lines[lines.length - 1] = line;
			else lines.push(line);
		}
		return lines.map((line) => {
			const l = esc(line);
			if (/^\$ /.test(line)) return `<div class="c-cmd"><span class="c-ps">$</span>${l.slice(1)}</div>`;
			if (/^\s*✓/.test(line)) return `<div class="c-ok">${l}</div>`;
			if (/^\s*✗|Traceback|Error:|\bfailed\b/i.test(line)) return `<div class="c-bad">${l}</div>`;
			if (/^\s*(⚠|Warning)/i.test(line)) return `<div class="c-warn">${l}</div>`;
			if (/^\s*↻/.test(line)) return `<div class="c-info">${l}</div>`;
			if (/^\s*(Config|Database|Public|Private)\s*:/.test(line)) return `<div class="c-file">${l}</div>`;
			return `<div>${l || "&nbsp;"}</div>`;
		}).join("");
	}

	// ============================================================ styles
	injectStyle() {
		if (document.getElementById("ae-style")) return;
		$("head").append(`<style id="ae-style">
.ae{--ae-ok:#4D6443;--ae-ok-bg:rgba(77,100,67,.13);--ae-bad:#dc2626;--ae-bad-bg:rgba(220,38,38,.09);--ae-warn:#d97706;--ae-warn-bg:rgba(217,119,6,.11);--ae-run:#2563eb;--ae-run-bg:rgba(37,99,235,.1);--ae-accent:#4D6443;--ae-brand:#112921;
	display:flex;flex-direction:column;gap:18px;padding:6px 0 60px;max-width:1180px;margin:0 auto}
.ae .ae-ic{flex:none;vertical-align:-2px}
.ae code{font-size:12px;background:var(--control-bg);padding:1px 6px;border-radius:5px;color:var(--text-color)}
.ae-hero{border-radius:18px;padding:22px 24px;color:#e2e8f0;background:radial-gradient(900px 320px at 0% 0%,rgba(122,168,102,.55) 0%,transparent 60%),radial-gradient(700px 280px at 100% 110%,rgba(176,222,150,.28) 0%,transparent 60%),radial-gradient(400px 200px at 70% 0%,rgba(77,100,67,.6) 0%,transparent 70%),linear-gradient(135deg,#0d211a 0%,#112921 45%,#2c4a36 100%);box-shadow:0 18px 40px -18px rgba(17,41,33,.85),inset 0 1px 0 rgba(255,255,255,.06);display:flex;flex-direction:column;gap:16px}
.ae-hero code{background:rgba(255,255,255,.1);color:#fff}
.ae-hero-main{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.ae-logo{width:58px;height:58px;border-radius:16px;display:grid;place-items:center;background:#fff;box-shadow:0 8px 20px -8px rgba(0,0,0,.5);overflow:hidden;flex:none}.ae-logo img{width:50px;height:50px;object-fit:contain}
.ae-eyebrow{font-size:12px;letter-spacing:.04em;color:#a8dc8c;font-weight:600;text-shadow:0 0 12px rgba(168,220,140,.4)}
.ae-site{font-size:22px;font-weight:700;color:#fff;letter-spacing:-.01em}
.ae-meta{font-size:12.5px;color:#94a3b8}
.ae-disk{margin-left:auto;min-width:220px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:10px 14px}
.ae-disk-top{display:flex;justify-content:space-between;font-size:12px;color:#94a3b8}.ae-disk-top b{color:#fff}.ae-disk-top b.bad{color:#fca5a5}
.ae-disk-bar{height:6px;border-radius:9px;background:rgba(255,255,255,.12);margin:7px 0 5px;overflow:hidden}
.ae-disk-bar div{height:100%;background:linear-gradient(90deg,#4D6443,#8fc27a,#c8ecb0);border-radius:9px;box-shadow:0 0 12px rgba(160,214,130,.55)}.ae-disk-bar div.bad{background:linear-gradient(90deg,#f59e0b,#ef4444)}
.ae-disk-sub{font-size:11px;color:#64748b}
.ae-chips{display:flex;gap:8px;flex-wrap:wrap}
.ae-chip{display:flex;align-items:center;gap:7px;padding:6px 12px;border-radius:999px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.09);font-size:12.5px;color:#cbd5e1}
.ae-chip[data-sw]{cursor:pointer;transition:.15s}.ae-chip[data-sw]:hover{background:rgba(255,255,255,.14);border-color:rgba(168,220,140,.45);box-shadow:0 0 14px rgba(143,194,122,.25)}.ae-chip-act{font-size:11px;font-weight:600;color:#a8dc8c;padding-left:8px;margin-left:2px;border-left:1px solid rgba(255,255,255,.15)}
.ae-chip b{color:#fff;font-weight:600}.ae-chip .dot{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 3px rgba(34,197,94,.2)}
.ae-chip.warn .dot{background:#f59e0b;box-shadow:0 0 0 3px rgba(245,158,11,.25)}.ae-chip.bad .dot{background:#ef4444;box-shadow:0 0 0 3px rgba(239,68,68,.25)}
.ae-hero .ae-note{background:rgba(255,255,255,.07);color:#fde68a}
.ae-tabs{display:flex;gap:4px;background:var(--control-bg);padding:4px;border-radius:12px;width:max-content;max-width:100%;overflow:auto}
.ae-tabs button{display:flex;align-items:center;gap:7px;border:none;background:transparent;border-radius:9px;padding:7px 16px;font-size:13px;font-weight:500;color:var(--text-muted);white-space:nowrap}
.ae-tabs button.on{background:var(--card-bg);color:var(--text-color);box-shadow:0 1px 3px rgba(0,0,0,.1)}
.ae-card{background:var(--card-bg);border:1px solid var(--border-color);border-radius:16px;padding:20px 22px;box-shadow:0 1px 2px rgba(0,0,0,.03)}
.ae-card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:14px}
.ae-card h3{margin:0;font-size:16px;font-weight:650;letter-spacing:-.01em}.ae-card-head p{margin:3px 0 0;font-size:12.5px;color:var(--text-muted)}
.ae h4{margin:0 0 10px;font-size:14px;font-weight:600}
.ae-muted{color:var(--text-muted);font-size:12.5px;margin:8px 0}.ae-muted.small{font-size:12px}
.ae-actions{display:flex;align-items:center;gap:12px;margin-top:16px}
.ae-btn{display:inline-flex;align-items:center;gap:7px;padding:8px 18px;border-radius:10px;font-weight:600}
.ae-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.ae-tile{display:flex;gap:12px;align-items:center;border:1.5px solid var(--border-color);border-radius:13px;padding:14px 16px;cursor:pointer;margin:0;transition:.15s;font-weight:400}
.ae-tile input{display:none}.ae-tile b{display:block;font-size:13.5px}.ae-tile small{color:var(--text-muted);font-size:12px}
.ae-tile:hover{border-color:var(--gray-400,#9ca3af)}.ae-tile.on{border-color:var(--ae-accent);background:rgba(77,100,67,.05);box-shadow:0 0 0 3px rgba(77,100,67,.1)}
.ae-tile-ic{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;background:var(--control-bg);color:var(--text-muted);flex:none}.ae-tile.on .ae-tile-ic{background:linear-gradient(135deg,#112921,#4D6443);color:#fff;box-shadow:0 6px 14px -6px rgba(77,100,67,.8)}
.ae-list{display:flex;flex-direction:column}
.ae-row{display:flex;align-items:center;gap:14px;padding:12px 4px;border-top:1px solid var(--border-color);flex-wrap:wrap}.ae-row:first-child{border-top:none}
.ae-row-when{min-width:88px;display:flex;flex-direction:column}.ae-row-when b{font-size:14px}.ae-row-when small{color:var(--text-muted);font-size:11.5px}
.ae-files{display:flex;gap:6px;flex-wrap:wrap;flex:1}
.ae-file{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:9px;background:var(--control-bg);font-size:12px;color:var(--text-color);text-decoration:none!important;border:1px solid transparent;transition:.15s}
.ae-file span{color:var(--text-muted)}.ae-file .dl{opacity:.35}.ae-file:hover{border-color:var(--ae-accent);background:rgba(77,100,67,.06)}.ae-file:hover .dl{opacity:1;color:var(--ae-accent)}
.ae-tag{font-size:11px;padding:3px 8px;border-radius:6px;background:var(--ae-run-bg);color:var(--ae-run);align-self:center}
.ae-empty{display:flex;flex-direction:column;align-items:center;gap:8px;padding:28px;color:var(--text-muted);font-size:13px}
.ae-flow{display:flex;align-items:center;gap:6px;padding:14px;border-radius:12px;background:var(--control-bg);margin-bottom:6px;overflow-x:auto}
.ae-flow-step{display:flex;flex-direction:column;align-items:center;gap:5px;min-width:76px;text-align:center}
.ae-flow-step span{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:var(--card-bg);color:var(--ae-accent);box-shadow:0 1px 3px rgba(0,0,0,.08)}
.ae-flow-step small{font-size:11px;color:var(--text-muted);white-space:nowrap}.ae-flow-line{flex:1;min-width:14px;height:2px;background:var(--border-color);margin-bottom:18px}
.ae-sec{display:flex;gap:14px;padding:18px 0 4px;border-top:1px dashed var(--border-color);margin-top:12px}
.ae-sec-n{width:26px;height:26px;border-radius:50%;flex:none;display:grid;place-items:center;font-size:12px;font-weight:700;background:var(--ae-accent);color:#fff}
.ae-sec-b{flex:1;min-width:0}
.ae-seg{display:inline-flex;background:var(--control-bg);padding:3px;border-radius:10px;gap:3px;flex-wrap:wrap}
.ae-seg button{border:none;background:transparent;border-radius:8px;padding:6px 14px;font-size:12.5px;display:flex;align-items:center;gap:6px;color:var(--text-muted)}
.ae-seg button.on{background:var(--card-bg);color:var(--text-color);font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.ae-grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:10px 0}
.ae-field{display:flex;flex-direction:column;gap:5px;margin:0;font-size:12.5px;font-weight:500;color:var(--text-color)}
.ae-field small{color:var(--text-muted);font-weight:400;font-size:11.5px}
.ae-drop{position:relative;display:flex;align-items:center;gap:12px;border:1.5px dashed var(--border-color);border-radius:13px;padding:14px;margin:0;cursor:pointer;overflow:hidden;transition:.15s;font-weight:400}
.ae-drop input{position:absolute;inset:0;opacity:0;cursor:pointer}
.ae-drop:hover,.ae-drop.over{border-color:var(--ae-accent);background:rgba(77,100,67,.04)}
.ae-drop.has{border-style:solid;border-color:var(--ae-accent)}.ae-drop.done{border-color:var(--ae-ok);background:var(--ae-ok-bg)}.ae-drop.err{border-color:var(--ae-bad);background:var(--ae-bad-bg)}
.ae-drop-ic{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;background:var(--control-bg);color:var(--ae-accent);flex:none}
.ae-drop-t{display:flex;flex-direction:column;min-width:0}.ae-drop-t b{font-size:13px}.ae-drop-t small{color:var(--text-muted);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ae-drop.err .ae-drop-t small{white-space:normal;color:var(--ae-bad)}
.ae-drop-bar{position:absolute;left:0;right:0;bottom:0;height:3px}.ae-drop-bar span{display:block;height:100%;width:0;background:var(--ae-accent);transition:width .3s}
.ae-check{display:flex;gap:10px;align-items:flex-start;margin:10px 0 0;cursor:pointer;font-weight:400}.ae-check input{margin-top:3px}
.ae-check b{display:block;font-size:13px;font-weight:600}.ae-check small{color:var(--text-muted);font-size:12px}.ae-check.dim{opacity:.6}.ae-check.tight{margin-top:8px}
.ae-note{display:flex;gap:9px;align-items:flex-start;padding:10px 13px;border-radius:10px;font-size:12.5px;line-height:1.5}
.ae-note.bad{background:var(--ae-bad-bg);color:var(--ae-bad)}.ae-note.warn{background:var(--ae-warn-bg);color:var(--ae-warn)}.ae-note.ok{background:var(--ae-ok-bg);color:var(--ae-ok)}
.ae-pill{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;font-size:11.5px;font-weight:600}
.ae-pill.ok{background:var(--ae-ok-bg);color:var(--ae-ok)}.ae-pill.bad{background:var(--ae-bad-bg);color:var(--ae-bad)}.ae-pill.run{background:rgba(77,100,67,.14);color:var(--ae-accent)}.ae-pill.mute{background:var(--control-bg);color:var(--text-muted)}
.t-ok{color:var(--ae-ok)}.t-warn{color:var(--ae-warn)}.t-bad{color:var(--ae-bad)}
.ae-switch{display:flex;align-items:center;gap:14px;padding:14px 0;border-top:1px solid var(--border-color)}.ae-card-head+.ae-switch{border-top:none}
.ae-switch-ic{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;flex:none}.ae-switch-ic.ok{background:var(--ae-ok-bg);color:var(--ae-ok)}.ae-switch-ic.warn{background:var(--ae-warn-bg);color:var(--ae-warn)}
.ae-switch-b{flex:1;display:flex;flex-direction:column;gap:3px}.ae-switch-b>b{font-size:13.5px}.ae-switch-b>small{color:var(--text-muted);font-size:12px}
.ae-tools{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.ae-tool{display:flex;gap:12px;align-items:flex-start;border:1px solid var(--border-color);border-radius:13px;padding:14px}
.ae-tool.hi{border-color:rgba(77,100,67,.4);background:rgba(77,100,67,.04)}
.ae-tool-ic{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;background:var(--control-bg);color:var(--ae-accent);flex:none}
.ae-tool-b{flex:1;display:flex;flex-direction:column;gap:3px}.ae-tool-b b{font-size:13.5px}.ae-tool-b small{color:var(--text-muted);font-size:12px}.ae-tool-b small.ae-tool-note{color:var(--ae-warn)}
.ae-hist-ic{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;flex:none}
.ae-hist-ic.ok{background:var(--ae-ok-bg);color:var(--ae-ok)}.ae-hist-ic.bad{background:var(--ae-bad-bg);color:var(--ae-bad)}.ae-hist-ic.run{background:rgba(77,100,67,.14);color:var(--ae-accent)}.ae-hist-ic.mute{background:var(--control-bg);color:var(--text-muted)}
.ae-hist-b{flex:1;min-width:200px;display:flex;flex-direction:column;gap:2px}.ae-hist-b>div{display:flex;gap:8px;align-items:center}.ae-hist-b small{color:var(--text-muted);font-size:12px}.ae-how code{font-size:11px;padding:0 5px}
.ae-jobcard{display:flex;flex-direction:column;gap:12px;border-width:1.5px}.ae-jobcard.run{border-color:rgba(77,100,67,.45);animation:ae-glow 2.4s ease-in-out infinite}@keyframes ae-glow{50%{box-shadow:0 0 0 4px rgba(143,194,122,.12),0 10px 30px -12px rgba(77,100,67,.5)}}.ae-jobcard.ok{border-color:rgba(22,163,74,.35)}.ae-jobcard.bad{border-color:rgba(220,38,38,.35)}
.ae-job-head{display:flex;align-items:center;gap:14px}.ae-job-t{flex:1;min-width:0}.ae-job-t h3{margin:6px 0 2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ae-job-t small{color:var(--text-muted);font-size:12px}
.ae-job-pct{font-size:30px;font-weight:700;letter-spacing:-.03em;font-variant-numeric:tabular-nums}.ae-job-pct small{font-size:15px;color:var(--text-muted)}
.ae-bar{height:8px;border-radius:9px;background:var(--control-bg);overflow:hidden}
.ae-bar div{height:100%;border-radius:9px;box-shadow:0 0 14px rgba(143,194,122,.55);background:linear-gradient(90deg,#112921,#4D6443 40%,#8fc27a 80%,#c8ecb0);transition:width .8s ease}
.ae-bar.ok div{background:linear-gradient(90deg,#112921,#4D6443 50%,#8fc27a)}.ae-bar.bad div{background:linear-gradient(90deg,#f87171,#dc2626)}
.ae-bar.live div{background-image:linear-gradient(45deg,rgba(255,255,255,.25) 25%,transparent 25%,transparent 50%,rgba(255,255,255,.25) 50%,rgba(255,255,255,.25) 75%,transparent 75%),linear-gradient(90deg,#112921,#4D6443 40%,#8fc27a 80%,#c8ecb0);background-size:18px 18px,100% 100%;animation:ae-stripe 1s linear infinite}
@keyframes ae-stripe{to{background-position:18px 0,0 0}}
.ae-links{display:flex;gap:8px;flex-wrap:wrap}
.ae-job-grid{display:grid;grid-template-columns:250px 1fr;gap:14px}.ae-job-grid.nosteps{grid-template-columns:1fr}
.ae-steps{display:flex;flex-direction:column;gap:2px;padding:6px 0}
.ae-step{display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:9px;font-size:12.5px;color:var(--text-muted)}
.ae-step-dot{width:22px;height:22px;border-radius:50%;flex:none;display:grid;place-items:center;border:1.5px solid var(--border-color);font-size:12px}
.ae-step-l{flex:1}.ae-step-t{font-size:11px;font-variant-numeric:tabular-nums}
.ae-step.running{background:linear-gradient(90deg,rgba(77,100,67,.14),transparent);color:var(--text-color);font-weight:600}.ae-step.running .ae-step-dot{border-color:var(--ae-accent)}
.ae-step.done{color:var(--text-color)}.ae-step.done .ae-step-dot{background:linear-gradient(135deg,#4D6443,#8fc27a);border-color:transparent;color:#fff}
.ae-step.failed{color:var(--ae-bad);font-weight:600}.ae-step.failed .ae-step-dot{background:var(--ae-bad);border-color:var(--ae-bad);color:#fff}
.ae-step.skipped{opacity:.55}.ae-step.pending{opacity:.7}
.ae-spin{width:12px;height:12px;border-radius:50%;border:2px solid var(--ae-accent);border-right-color:transparent;display:inline-block;animation:ae-rot .7s linear infinite}.ae-spin.sm{width:10px;height:10px}
@keyframes ae-rot{to{transform:rotate(360deg)}}
.ae-term{border-radius:12px;overflow:hidden;background:#0c1a15;border:1px solid #1f3a2f;box-shadow:0 16px 36px -18px rgba(17,41,33,.9),0 0 0 1px rgba(143,194,122,.08);min-width:0}
.ae-term-bar{display:flex;align-items:center;gap:7px;padding:9px 12px;background:#13261e;border-bottom:1px solid #1f3a2f}
.ae-term-bar i{width:11px;height:11px;border-radius:50%;background:#ff5f57}.ae-term-bar i:nth-child(2){background:#febc2e}.ae-term-bar i:nth-child(3){background:#28c840}
.ae-term-bar span{flex:1;text-align:center;font-size:11.5px;color:#64748b;font-family:ui-monospace,Menlo,monospace}
.ae-term-copy{background:none;border:none;color:#64748b;padding:2px}.ae-term-copy:hover{color:#e2e8f0}
.ae-term-body{padding:12px 14px;height:360px;overflow:auto;font:12px/1.65 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#a3b8ad;white-space:pre-wrap;word-break:break-word}
.ae-term-body .c-cmd{color:#e2e8f0;font-weight:600;margin-top:6px}.ae-term-body .c-ps{color:#22c55e;margin-right:2px}
.ae-term-body .c-ok{color:#8fe07a}.ae-term-body .c-bad{color:#f87171}.ae-term-body .c-warn{color:#fbbf24}.ae-term-body .c-info{color:#67e8f9}.ae-term-body .c-file{color:#b8e0a0}
.ae-cursor{display:inline-block;width:8px;height:15px;background:#8fe07a;box-shadow:0 0 8px #8fe07a;vertical-align:-3px;animation:ae-blink 1s steps(1) infinite}
@keyframes ae-blink{50%{opacity:0}}
.ae .btn-primary{background:linear-gradient(135deg,#112921,#4D6443);border:none;color:#fff;box-shadow:0 6px 16px -6px rgba(77,100,67,.8)}.ae .btn-primary:hover,.ae .btn-primary:focus{background:linear-gradient(135deg,#1a3a2d,#5f7a52);box-shadow:0 8px 20px -6px rgba(95,140,80,.9)}
.ae-sec-n{background:linear-gradient(135deg,#112921,#4D6443)!important;box-shadow:0 4px 10px -3px rgba(77,100,67,.7)}
.ae-status{display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:14px;font-size:13px}
.ae-status.ok{background:linear-gradient(90deg,rgba(77,100,67,.14),rgba(143,194,122,.06));color:#3c5234;border:1px solid rgba(77,100,67,.25)}
.ae-status.warn{background:var(--ae-warn-bg);color:#92400e;border:1px solid rgba(217,119,6,.25)}
.ae-status-ic{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;color:#fff;flex:none}
.ae-status.ok .ae-status-ic{background:linear-gradient(135deg,#4D6443,#8fc27a);box-shadow:0 0 12px rgba(143,194,122,.6)}.ae-status.warn .ae-status-ic{background:var(--ae-warn)}
.ae-status b{font-size:13.5px}.ae-status span{opacity:.85}
.ae-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.ae-stat{display:flex;align-items:center;gap:12px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:14px;padding:14px 16px}
.ae-stat-ic{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;flex:none;background:rgba(77,100,67,.12);color:var(--ae-accent)}
.ae-stat-ic.dark{background:linear-gradient(135deg,#112921,#4D6443);color:#c8ecb0;box-shadow:0 6px 14px -6px rgba(77,100,67,.8)}.ae-stat-ic.bad{background:var(--ae-bad-bg);color:var(--ae-bad)}
.ae-stat small{display:block;color:var(--text-muted);font-size:11.5px}.ae-stat b{font-size:15px;font-weight:650}
@media (max-width:1100px){.ae-job-grid{grid-template-columns:1fr}.ae-steps{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr))}}
@media (max-width:768px){.ae-disk{margin-left:0;width:100%}.ae-hero{padding:18px}.ae-card{padding:16px}}
		</style>`);
	}
}
