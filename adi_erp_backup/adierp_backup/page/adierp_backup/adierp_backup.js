// adiERP Backup — backup and restore this site from Desk (Frappe v15 / v16)
frappe.pages["adierp-backup"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("adiERP Backup"), single_column: true });
	new AdiErpBackup(page);
};

const API = "adi_erp_backup.api.";
const CHUNK = 5 * 1024 * 1024;
const esc = (s) => frappe.utils.escape_html(s == null ? "" : String(s));

class AdiErpBackup {
	constructor(page) {
		this.page = page;
		this.$root = $(`<div class="adierp"></div>`).appendTo(page.main);
		this.tab = "backup";
		this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
		this.injectStyle();
		this.load();
	}

	injectStyle() {
		if (document.getElementById("adierp-style")) return;
		$("head").append(`<style id="adierp-style">
			.adierp{display:flex;flex-direction:column;gap:16px;padding:8px 0 40px}
			.adierp .card-box{background:var(--card-bg);border:1px solid var(--border-color);border-radius:12px;padding:18px 20px}
			.adierp .strip{display:flex;flex-wrap:wrap;gap:22px;font-size:13px;color:var(--text-muted)}
			.adierp .strip b{color:var(--text-color);font-weight:600}
			.adierp .tabs{display:flex;gap:6px}
			.adierp .tabs button{border:1px solid var(--border-color);background:var(--card-bg);border-radius:999px;padding:6px 16px;font-size:13px;font-weight:500;color:var(--text-color)}
			.adierp .tabs button.on{background:var(--text-color);color:var(--card-bg);border-color:var(--text-color)}
			.adierp h4{margin:0 0 4px;font-size:15px;font-weight:600}
			.adierp .muted{color:var(--text-muted);font-size:13px}
			.adierp .row-line{display:flex;align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--border-color);flex-wrap:wrap}
			.adierp .row-line:first-child{border-top:none}
			.adierp .pill{display:inline-flex;align-items:center;gap:4px;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:500;background:var(--control-bg)}
			.adierp .pill.ok{background:var(--green-100,#dcfce7);color:var(--green-800,#166534)}
			.adierp .pill.bad{background:var(--red-100,#fee2e2);color:var(--red-800,#991b1b)}
			.adierp .pill.run{background:var(--blue-100,#dbeafe);color:var(--blue-800,#1e40af)}
			.adierp .bar{height:10px;border-radius:999px;background:var(--control-bg);overflow:hidden}
			.adierp .bar>div{height:100%;background:var(--primary);border-radius:999px;transition:width .6s}
			.adierp pre.term{background:#0f172a;color:#e2e8f0;border-radius:10px;padding:12px 14px;max-height:340px;overflow:auto;font-size:12px;line-height:1.5;margin:0;white-space:pre-wrap}
			.adierp .steps{margin:8px 0 0;padding-left:18px;font-size:13px;color:var(--text-muted);line-height:1.8}
			.adierp .warn{background:var(--yellow-50,#fefce8);border:1px solid var(--yellow-200,#fde68a);color:var(--yellow-800,#854d0e);border-radius:10px;padding:10px 14px;font-size:13px}
			.adierp .danger-box{background:var(--red-50,#fef2f2);border:1px solid var(--red-200,#fecaca);border-radius:10px;padding:12px 14px;font-size:13px}
			.adierp .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
			.adierp label.f{display:flex;flex-direction:column;gap:4px;font-size:12px;font-weight:500;color:var(--text-muted)}
			.adierp input[type=file],.adierp input[type=text],.adierp input[type=password],.adierp select{font-size:13px}
			.adierp .up{font-size:12px;color:var(--text-muted)}
		</style>`);
	}

	async load() {
		const r = await frappe.call({ method: API + "overview" });
		this.data = r.message;
		this.render();
		if (this.data.busy && !this.watching) this.watch(this.data.busy);
	}

	render() {
		const d = this.data;
		const lowDisk = d.disk.free_bytes < 5 * 1024 ** 3;
		this.$root.html(`
			<div class="card-box strip">
				<span>${__("Site")}: <b>${esc(d.site)}</b></span>
				<span>Frappe <b>${esc(d.frappe)}</b></span>
				<span>${__("Database")}: <b>${esc(d.db_size)}</b></span>
				<span>${__("Disk free")}: <b style="${lowDisk ? "color:var(--red-600,#dc2626)" : ""}">${esc(d.disk.free)}</b> ${__("of")} ${esc(d.disk.total)}</span>
				<span>${__("DB root password")}: <b>${d.root_password_set ? __("configured") : __("not configured")}</b></span>
			</div>
			${lowDisk ? `<div class="warn">⚠ ${__("Low disk space — backups and restores need room for the database and files. Free space before running one.")}</div>` : ""}
			<div class="tabs">
				${[["backup", __("Backup")], ["restore", __("Restore")], ["history", __("History")]].map(([k, l]) => `<button data-tab="${k}" class="${this.tab === k ? "on" : ""}">${l}</button>`).join("")}
			</div>
			<div class="job-panel"></div>
			<div class="tab-body"></div>`);
		this.$root.find(".tabs button").on("click", (e) => { this.tab = $(e.currentTarget).data("tab"); this.render(); });
		const body = this.$root.find(".tab-body");
		if (this.tab === "backup") this.renderBackup(body);
		if (this.tab === "restore") this.renderRestore(body);
		if (this.tab === "history") this.renderHistory(body);
		if (this.lastState) this.renderJob(this.lastState);
	}

	// ------------------------------------------------------------ backup
	renderBackup(body) {
		const d = this.data;
		body.html(`
			<div class="card-box">
				<h4>${__("Backup now")}</h4>
				<div class="muted">${__("Runs")} <code>bench --site ${esc(d.site)} backup</code> ${__("in the background. You can leave this page — you'll get a notification when it's done.")}</div>
				<div style="display:flex;align-items:center;gap:18px;margin-top:14px;flex-wrap:wrap">
					<label style="display:flex;align-items:center;gap:8px;margin:0;font-size:13px"><input type="checkbox" class="bk-files"> ${__("With files")} <span class="muted">(--with-files · public + private)</span></label>
					<button class="btn btn-primary btn-sm bk-go" ${d.busy ? "disabled" : ""}>${__("Backup now")}</button>
				</div>
			</div>
			<div class="card-box">
				<h4>${__("Available backups")}</h4>
				<div class="muted" style="margin-bottom:6px">${__("In")} <code>sites/${esc(d.site)}/private/backups</code> — ${__("download, or restore one from here.")}</div>
				${d.backups.length ? d.backups.map((b) => `<div class="row-line">
					<b style="min-width:130px">${esc(b.when)}</b>
					${["db", "public", "private", "config"].map((k) => (b.files[k] ? `<a class="pill" href="${esc(b.files[k].url)}" target="_blank" title="${esc(b.files[k].name)}">⬇ ${{ db: __("Database"), public: __("Public files"), private: __("Private files"), config: __("Config") }[k]} · ${esc(b.files[k].size)}</a>` : "")).join("")}
					<span style="flex:1"></span>
					${b.files.db ? `<button class="btn btn-default btn-xs bk-restore" data-stamp="${esc(b.stamp)}">${__("Restore this")}</button>` : ""}
				</div>`).join("") : `<div class="muted">${__("No backups yet.")}</div>`}
			</div>`);
		body.find(".bk-go").on("click", async () => {
			const withFiles = body.find(".bk-files").is(":checked") ? 1 : 0;
			const r = await frappe.call({ method: API + "start_backup", args: { with_files: withFiles }, freeze: true });
			frappe.show_alert({ message: __("Backup started"), indicator: "blue" });
			this.watch(r.message.job);
			this.load();
		});
		body.find(".bk-restore").on("click", (e) => {
			const b = this.data.backups.find((x) => x.stamp === $(e.currentTarget).data("stamp"));
			this.preset = b;
			this.tab = "restore";
			this.render();
		});
	}

	// ------------------------------------------------------------ restore
	renderRestore(body) {
		const d = this.data, p = this.preset;
		const pick = (kind) => `<select class="form-control rs-pick" data-kind="${kind}"><option value="">${__("— upload a file instead —")}</option>
			${d.backups.filter((b) => b.files[kind]).map((b) => `<option value="backup:${esc(b.files[kind].name)}" ${p && p.files[kind] && p.stamp === b.stamp ? "selected" : ""}>${esc(b.when)} · ${esc(b.files[kind].size)}</option>`).join("")}</select>`;
		const up = (kind, accept) => `<input type="file" class="form-control rs-file" data-kind="${kind}" accept="${accept}"><div class="up up-${kind}"></div>`;
		body.html(`
			<div class="card-box">
				<h4>${__("Restore")}</h4>
				<div class="danger-box">⚠ ${__("Restore REPLACES this site's database")}${__(" (and files, if chosen)")} ${__("with the backup. Everyone is signed out. Test on a test site first when you can.")}</div>
				<div class="muted" style="margin-top:12px">${__("What happens, in order:")}</div>
				<ol class="steps">
					<li>${__("Check the backup files (valid, not partial, Frappe version)")}</li>
					<li>${__("Safety backup of the site as it is now — your undo point")}</li>
					<li>${__("Maintenance mode ON (verified) and scheduler paused")}</li>
					<li><code>bench --site ${esc(d.site)} restore &lt;db&gt; [--with-public-files] [--with-private-files] --force</code></li>
					<li><code>migrate</code>, <code>clear-cache</code>, ${__("scheduler resumed")}, ${__("maintenance mode OFF")}</li>
					<li>${__("Optional: bench restart")}</li>
				</ol>
			</div>
			<div class="card-box" style="display:flex;flex-direction:column;gap:14px">
				<div class="grid2">
					<label class="f">${__("Database backup")} (.sql.gz / .sql) *
						${pick("db")}${up("db", ".gz,.sql")}
					</label>
				</div>
				<label style="display:flex;align-items:center;gap:8px;margin:0;font-size:13px"><input type="checkbox" class="rs-files" ${p && (p.files.public || p.files.private) ? "checked" : ""}> ${__("With files")} <span class="muted">(${__("public and/or private files backup")})</span></label>
				<div class="grid2 rs-files-box" style="${p && (p.files.public || p.files.private) ? "" : "display:none"}">
					<label class="f">${__("Public files")} (.tar)${pick("public")}${up("public", ".tar,.tgz,.gz")}</label>
					<label class="f">${__("Private files")} (.tar)${pick("private")}${up("private", ".tar,.tgz,.gz")}</label>
				</div>
				<div class="grid2">
					${d.root_password_set ? "" : `<label class="f">${__("MariaDB root password")} *<input type="password" class="form-control rs-root" autocomplete="off"><span class="up">${__("Used once, never saved.")}</span></label>`}
					<label class="f">${__("Type the site name to confirm")} *<input type="text" class="form-control rs-site" placeholder="${esc(d.site)}" autocomplete="off"></label>
					<label class="f">${__("Your password")} *<input type="password" class="form-control rs-pwd" autocomplete="current-password"></label>
				</div>
				<label style="display:flex;align-items:center;gap:8px;margin:0;font-size:13px"><input type="checkbox" class="rs-restart"> ${__("Restart bench after restore")} <span class="muted">(bench restart — production with supervisor)</span></label>
				<div><button class="btn btn-danger btn-sm rs-go" ${d.busy ? "disabled" : ""}>${__("Start restore")}</button></div>
			</div>`);
		body.find(".rs-files").on("change", (e) => body.find(".rs-files-box").toggle(e.target.checked));
		body.find(".rs-go").on("click", () => this.startRestore(body));
	}

	async uploadFile(file, kind, $status) {
		const id = Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
		const total = Math.max(1, Math.ceil(file.size / CHUNK));
		let ref = null;
		for (let i = 0; i < total; i++) {
			const fd = new FormData();
			fd.append("upload_id", id); fd.append("kind", kind); fd.append("filename", file.name);
			fd.append("index", i); fd.append("total", total);
			fd.append("chunk", file.slice(i * CHUNK, (i + 1) * CHUNK), file.name);
			const res = await fetch("/api/method/" + API + "upload_chunk", { method: "POST", body: fd, headers: { "X-Frappe-CSRF-Token": frappe.csrf_token } });
			const j = await res.json().catch(() => ({}));
			if (!res.ok) throw new Error((j._server_messages && JSON.parse(JSON.parse(j._server_messages)[0]).message) || j.exception || __("Upload failed"));
			$status.text(`${__("Uploading")} ${file.name}: ${Math.round(((i + 1) / total) * 100)}%`);
			ref = j.message.ref;
		}
		$status.text(`✓ ${file.name} ${__("uploaded")}`);
		return ref;
	}

	async startRestore(body) {
		const withFiles = body.find(".rs-files").is(":checked");
		const refOf = async (kind) => {
			const picked = body.find(`.rs-pick[data-kind=${kind}]`).val();
			const file = body.find(`.rs-file[data-kind=${kind}]`)[0].files[0];
			if (file) return this.uploadFile(file, kind, body.find(`.up-${kind}`));
			return picked || null;
		};
		const site = body.find(".rs-site").val().trim(), pwd = body.find(".rs-pwd").val();
		if (site !== this.data.site) return frappe.msgprint(__("Type the site name exactly: {0}", [this.data.site]));
		if (!pwd) return frappe.msgprint(__("Enter your password."));
		const $btn = body.find(".rs-go").prop("disabled", true);
		try {
			const db = await refOf("db");
			if (!db) throw new Error(__("Choose or upload the database backup."));
			const pub = withFiles ? await refOf("public") : null;
			const priv = withFiles ? await refOf("private") : null;
			if (withFiles && !pub && !priv) throw new Error(__("Choose or upload the public and/or private files backup, or untick With files."));
			frappe.confirm(__("Restore will replace this site's data and sign everyone out. A safety backup is taken first. Continue?"), async () => {
				const r = await frappe.call({ method: API + "start_restore", freeze: true, args: {
					db, public: pub, private: priv, confirm_site: site, password: pwd,
					restart: body.find(".rs-restart").is(":checked") ? 1 : 0, db_root_password: body.find(".rs-root").val() || undefined } });
				this.restoreToken = r.message.token;
				this.watch(r.message.job, r.message.token);
			}, () => $btn.prop("disabled", false));
		} catch (e) {
			$btn.prop("disabled", false);
			frappe.msgprint({ title: __("Can't start restore"), message: esc(e.message), indicator: "red" });
		}
	}

	// ------------------------------------------------------------ progress (works during maintenance mode too)
	watch(job, token) {
		this.watching = job;
		clearInterval(this._poll);
		const tick = async () => {
			let st = null;
			try {
				if (token) {  // restore: read the public status file — the site itself is in maintenance
					const r = await fetch(`/files/adierp-status/${token}.json?t=${Date.now()}`, { cache: "no-store" });
					if (r.ok) st = await r.json();
				} else {
					const r = await frappe.call({ method: API + "job_status", args: { job } });
					st = r.message;
				}
			} catch (e) { /* the site may be restarting — keep trying */ }
			if (!st || !st.status) return;
			this.lastState = st;
			this.renderJob(st);
			if (st.status === "Success" || st.status === "Failed") {
				clearInterval(this._poll);
				this.watching = null;
				if (!token) this.load();
			}
		};
		tick();
		this._poll = setInterval(tick, 1500);
	}

	renderJob(st) {
		const $p = this.$root.find(".job-panel");
		const cls = st.status === "Success" ? "ok" : st.status === "Failed" ? "bad" : "run";
		const out = st.outputs || {};
		const links = st.type === "Backup" && st.status === "Success"
			? ["db", "public", "private", "config"].filter((k) => out[k]).map((k) => `<a class="btn btn-default btn-xs" href="/backups/${esc(out[k])}" target="_blank">⬇ ${{ db: __("Database"), public: __("Public files"), private: __("Private files"), config: __("Site config") }[k]}</a>`).join(" ")
			: "";
		const done = st.type === "Restore" && st.status === "Success";
		$p.html(`<div class="card-box" style="display:flex;flex-direction:column;gap:10px">
			<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
				<h4 style="margin:0">${esc(st.type)} · ${esc(st.job)}</h4><span class="pill ${cls}">${esc(st.status)}</span>
				<span class="muted">${esc(st.stage || "")}</span><span style="flex:1"></span><b>${st.progress || 0}%</b>
			</div>
			<div class="bar"><div style="width:${st.progress || 0}%"></div></div>
			${st.error ? `<div class="danger-box">${esc(st.error)}</div>` : ""}
			${links ? `<div style="display:flex;gap:8px;flex-wrap:wrap">${links}</div>` : ""}
			${done ? `<div class="warn">✓ ${__("Restore complete. Everyone was signed out — sign in again to continue.")} <a href="/login?redirect-to=/app/adierp-backup">${__("Sign in")}</a></div>` : ""}
			<pre class="term">${esc(st.log || "")}</pre>
		</div>`);
		const t = $p.find("pre.term")[0];
		if (t) t.scrollTop = t.scrollHeight;
	}

	// ------------------------------------------------------------ history
	renderHistory(body) {
		const jobs = this.data.jobs || [];
		body.html(`<div class="card-box">
			<h4>${__("History")}</h4>
			${jobs.length ? jobs.map((j) => `<div class="row-line">
				<a href="/app/erp-backup-job/${esc(j.name)}" style="min-width:130px"><b>${esc(j.name)}</b></a>
				<span class="pill">${esc(j.job_type)}${j.with_files ? " · " + __("with files") : ""}</span>
				<span class="pill ${j.status === "Success" ? "ok" : j.status === "Failed" ? "bad" : "run"}">${esc(j.status)}</span>
				<span class="muted">${esc(j.by)} · ${frappe.datetime.str_to_user(j.creation)}</span>
				<span style="flex:1"></span>
				${j.status === "Queued" || j.status === "Running" ? `<button class="btn btn-default btn-xs hs-watch" data-job="${esc(j.name)}" data-token="${esc(j.job_type === "Restore" ? j.status_token || "" : "")}">${__("Show progress")}</button>` : ""}
				${j.db_file ? `<a class="btn btn-default btn-xs" href="/backups/${esc(j.db_file)}" target="_blank">⬇ ${__("Database")}</a>` : ""}
			</div>`).join("") : `<div class="muted">${__("Nothing yet.")}</div>`}
		</div>`);
		body.find(".hs-watch").on("click", (e) => { const $b = $(e.currentTarget); this.watch($b.data("job"), $b.data("token") || undefined); });
	}
}
