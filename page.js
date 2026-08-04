// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 BOBI SAS, France
// Auteur : Cyril Mazouer, pour le compte de BOBI SAS
// Distribué sous licence GNU GPL v3 (ou ultérieure) ; voir le fichier LICENSE.

// UI de « Parc NMOS ». Front pur : toute la logique tourne dans le conteneur, atteinte via
// ctx.api(...). L'écran distingue volontairement deux plans :
//   « Sources déclarées » = ce que l'opérateur a saisi (une machine = UNE ligne)
//   « Parc publié »       = ce que ça donne après expansion (une machine = N nodes)
// Confondre les deux est la première source de malentendu sur ce genre d'outil.
window.BTTools = window.BTTools || {};
window.BTTools.nmos_parc = (function () {
    "use strict";
    let ctx = null, root = null;
    let state = { entries: [], sources: [], templates: {} };
    let selKey = null, pollTimer = null;

    const POLL_MS = 5000;

    const esc = (s) => (window.BT && BT.esc ? BT.esc(s) : String(s == null ? "" : s));
    const tr = (key, fb) => { const v = ctx && ctx.t ? ctx.t(key) : null; return (v && v !== key) ? v : fb; };
    const $ = (sel) => root.querySelector(sel);

    function mount(el, context) {
        ctx = context; root = el;
        applyI18n();
        $("#np-refresh").addEventListener("click", doRefresh);
        $("#np-add").addEventListener("click", () => { $("#np-form").hidden = false; onKindChange(); });
        $("#np-f-cancel").addEventListener("click", () => { $("#np-form").hidden = true; });
        $("#np-f-kind").addEventListener("change", onKindChange);
        $("#np-form").addEventListener("submit", onAdd);
        $("#np-import-btn").addEventListener("click", doImport);
        $("#np-only-down").addEventListener("change", renderPark);
        $("#np-sources").addEventListener("click", onSourceClick);
        $("#np-tbody").addEventListener("click", onRowClick);
        $("#np-detail-close").addEventListener("click", () => {
            selKey = null; $("#np-detail").hidden = true; renderPark();
        });
        poll();
    }

    function unmount() {
        if (pollTimer) clearTimeout(pollTimer);
        ctx = root = null; pollTimer = null; selKey = null;
        state = { entries: [], sources: [], templates: {} };
    }

    function applyI18n() {
        root.querySelectorAll("[data-i18n]").forEach((el) => {
            const v = ctx.t(el.getAttribute("data-i18n"));
            if (v && v !== el.getAttribute("data-i18n")) el.textContent = v;
        });
    }

    async function poll() {
        try {
            state = await ctx.api("state");
            render();
        } catch (e) { /* on garde l'affichage précédent */ }
        if (ctx) pollTimer = setTimeout(poll, POLL_MS);
    }

    // ── Rendu ────────────────────────────────────────────────
    function render() {
        renderTallies();
        renderSources();
        renderPark();
        renderTemplates();
        // La reprise ne se propose que pour les outils dont l'inventaire n'a pas encore
        // été repris : un bandeau qui reste après coup laisserait croire à un travail en
        // attente alors qu'il est fait.
        const legacy = state.legacy || {}, imported = state.imported || {};
        const pending = Object.keys(legacy).filter((t) => !(t in imported));
        $("#np-import").hidden = pending.length === 0;
        if (pending.length) {
            $("#np-import-list").textContent = pending
                .map((t) => `${t} (${legacy[t]})`).join(", ");
        }
        const at = state.updated_at ? new Date(state.updated_at * 1000).toLocaleTimeString() : "—";
        $("#np-updated").textContent = tr("plugin.nmos_parc.lastProbe", "dernier sondage") + " : " + at;
    }

    function renderTallies() {
        const e = state.entries || [];
        const up = e.filter((x) => x.reachable).length;
        const down = e.filter((x) => !x.reachable).length;
        const reg = e.filter((x) => x.kind === "registry").length;
        const cells = [
            ["np-ok", up, tr("plugin.nmos_parc.t.up", "joignables")],
            ["np-bad", down, tr("plugin.nmos_parc.t.down", "injoignables")],
            ["np-neutral", reg, tr("plugin.nmos_parc.t.registries", "registres")],
            ["np-neutral", (state.sources || []).length, tr("plugin.nmos_parc.t.sources", "sources déclarées")],
        ];
        $("#np-tallies").innerHTML = cells.map(([cls, n, lbl]) =>
            `<div class="np-tally ${cls}${n ? "" : " np-tally-zero"}">
                <span class="np-tally-n">${n}</span><span class="np-tally-l">${esc(lbl)}</span>
             </div>`).join("");
    }

    function renderSources() {
        const list = state.sources || [];
        if (!list.length) {
            $("#np-sources").innerHTML = `<p class="np-hint">${esc(tr("plugin.nmos_parc.noSources",
                "Aucune source déclarée. Commencez par un registre si vous en avez un — une seule déclaration suffit alors pour tout le parc."))}</p>`;
            return;
        }
        const kindLbl = {
            registry: tr("plugin.nmos_parc.f.registry", "Registre"),
            node: tr("plugin.nmos_parc.f.node", "Node"),
            machine: tr("plugin.nmos_parc.f.machine", "Machine"),
        };
        $("#np-sources").innerHTML = list.map((s) => {
            // Une machine ne dit pas grand-chose seule : on montre ce qu'elle a produit.
            const derived = (state.entries || []).filter((e) => e.source_id === s.id);
            const upCount = derived.filter((e) => e.reachable).length;
            const detail = s.kind === "machine"
                ? `${esc(s.template || "auto")} — ${derived.length} ${esc(tr("plugin.nmos_parc.nodes", "nodes"))}, ${upCount} ${esc(tr("plugin.nmos_parc.upShort", "joignables"))}`
                : `${esc(s.host)}:${esc(s.port)}`;
            // Une source peut porter PLUSIEURS identités d'origine : le même équipement
            // déclaré autrefois dans deux outils a été fusionné ici, et chacun garde sa clé.
            const origins = Object.keys(s.origins || {});
            const origin = origins.length
                ? `<span class="np-origin" title="${esc(tr("plugin.nmos_parc.originHint",
                    "identités conservées pour ne pas casser les données enregistrées"))}">${esc(origins.join(" · "))}</span>`
                : "";
            return `<div class="np-source">
                <span class="np-chip np-chip-${esc(s.kind)}">${esc(kindLbl[s.kind] || s.kind)}</span>
                <div class="np-source-main">
                    <b>${esc(s.name || s.host)}</b> ${origin}
                    <span class="np-sub">${detail}</span>
                </div>
                <button class="btn btn-sm btn-red" data-del="${esc(s.id)}"
                    data-i18n="plugin.nmos_parc.del">Retirer</button>
            </div>`;
        }).join("");
    }

    function renderPark() {
        const onlyDown = $("#np-only-down").checked;
        let items = (state.entries || []).slice();
        if (onlyDown) items = items.filter((e) => !e.reachable);
        items.sort((a, b) => (a.reachable === b.reachable)
            ? String(a.name).localeCompare(String(b.name))
            : (a.reachable ? 1 : -1));

        $("#np-tbody").innerHTML = items.map((e) => {
            const cls = e.reachable ? "np-ok" : "np-bad";
            const stateLbl = e.reachable
                ? (e.versions || []).slice(0, 1).join("") || tr("plugin.nmos_parc.up", "joignable")
                : (e.error || tr("plugin.nmos_parc.down", "injoignable"));
            // « Jamais vu » ≠ « était là ce matin » : la première est une erreur de saisie
            // probable, la seconde une panne. La colonne les sépare.
            const seen = e.reachable ? "—"
                : (e.last_seen ? new Date(e.last_seen * 1000).toLocaleString()
                    : tr("plugin.nmos_parc.never", "jamais"));
            const label = e.label && e.label !== e.name
                ? `<span class="np-sub">${esc(e.label)}</span>` : "";
            return `<tr data-key="${esc(e.key)}" class="${e.key === selKey ? "np-row-sel" : ""}">
                <td><div>${esc(e.name)}</div>${label}</td>
                <td class="np-mono">${esc(e.host)}:${esc(e.port)}</td>
                <td>${esc(e.kind === "registry" ? tr("plugin.nmos_parc.f.registry", "Registre") : "node")}</td>
                <td><span class="np-badge ${cls}">${esc(stateLbl)}</span></td>
                <td class="np-sub">${esc(seen)}</td>
            </tr>`;
        }).join("");

        const empty = $("#np-empty");
        if (!items.length) {
            empty.hidden = false;
            empty.textContent = (state.entries || []).length
                ? tr("plugin.nmos_parc.allUp", "Tout le parc répond.")
                : tr("plugin.nmos_parc.emptyPark", "Parc vide — déclarez une source.");
        } else {
            empty.hidden = true;
        }
    }

    function renderTemplates() {
        const sel = $("#np-f-template");
        const tpls = state.templates || {};
        const keys = Object.keys(tpls);
        if (sel.dataset.filled === String(keys.length)) return;
        sel.innerHTML = keys.map((k) => {
            const t = tpls[k];
            const shape = t.count ? `${t.count} × ${t.base_port}+${t.step}`
                : tr("plugin.nmos_parc.autoScan", "découverte");
            return `<option value="${esc(k)}">${esc(t.label || k)} (${esc(shape)})</option>`;
        }).join("");
        sel.dataset.filled = String(keys.length);
    }

    // ── Formulaire ───────────────────────────────────────────
    function onKindChange() {
        const kind = $("#np-f-kind").value;
        const isMachine = kind === "machine";
        $("#np-f-port-wrap").hidden = isMachine;
        $("#np-f-tpl-wrap").hidden = !isMachine;
        $("#np-f-port").required = !isMachine;
        const hints = {
            registry: tr("plugin.nmos_parc.hint.registry",
                "Une seule déclaration suffit : tout le parc enregistré devient visible."),
            node: tr("plugin.nmos_parc.hint.node",
                "Un équipement exposant une Node API sur un port unique."),
            machine: tr("plugin.nmos_parc.hint.machine",
                "Un châssis qui expose un node par cage SFP. Le gabarit dit comment déplier les ports."),
        };
        $("#np-f-hint").textContent = hints[kind] || "";
        if (!isMachine) $("#np-f-port").value = kind === "registry" ? 8235 : 80;
    }

    async function onAdd(ev) {
        ev.preventDefault();
        const kind = $("#np-f-kind").value;
        const body = {
            kind: kind,
            name: $("#np-f-name").value.trim(),
            host: $("#np-f-host").value.trim(),
        };
        if (kind === "machine") body.template = $("#np-f-template").value;
        else body.port = parseInt($("#np-f-port").value, 10);
        try {
            await ctx.api("sources", { method: "POST", body: body });
            $("#np-form").reset();
            $("#np-form").hidden = true;
            poll();
        } catch (e) { ctx.toast(String(e.message || e), "error"); }
    }

    async function onSourceClick(ev) {
        const btn = ev.target.closest("[data-del]");
        if (!btn) return;
        try {
            await ctx.api("sources/" + encodeURIComponent(btn.dataset.del), { method: "DELETE" });
            poll();
        } catch (e) { ctx.toast(String(e.message || e), "error"); }
    }

    async function doRefresh() {
        try {
            await ctx.api("refresh", { method: "POST", body: {} });
            poll();
        } catch (e) { ctx.toast(String(e.message || e), "error"); }
    }

    async function doImport() {
        try {
            const r = await ctx.api("import/legacy", { method: "POST", body: {} });
            ctx.toast(r.skipped
                ? tr("plugin.nmos_parc.importSkipped", "Inventaires déjà repris")
                : `${r.total} ${tr("plugin.nmos_parc.importOk", "source(s) reprise(s)")}`, "success");
            poll();
        } catch (e) { ctx.toast(String(e.message || e), "error"); }
    }

    // ── Détail ───────────────────────────────────────────────
    async function onRowClick(ev) {
        const row = ev.target.closest("tr[data-key]");
        if (!row) return;
        selKey = row.dataset.key === selKey ? null : row.dataset.key;
        $("#np-detail").hidden = !selKey;
        renderPark();
        if (!selKey) return;
        $("#np-detail-body").innerHTML = `<p class="np-hint">${esc(tr("plugin.nmos_parc.loading", "Lecture IS-04…"))}</p>`;
        try {
            const r = await ctx.api("resolve?key=" + encodeURIComponent(selKey));
            $("#np-detail-title").textContent = r.name || selKey;
            const ncp = (r.devices || []).filter((d) => d.ncp).length;
            const blocks = [
                [tr("plugin.nmos_parc.d.devices", "Devices"), (r.devices || []).map((d) =>
                    `${esc(d.label || d.id)}${d.ncp ? ` <span class="np-badge np-ok">IS-12</span>` : ""}`)],
                [tr("plugin.nmos_parc.d.senders", "Senders"), (r.senders || []).map((s) =>
                    `${esc(s.label || s.id)} <span class="np-sub">${esc(s.format)}</span>`)],
                [tr("plugin.nmos_parc.d.receivers", "Receivers"), (r.receivers || []).map((s) =>
                    `${esc(s.label || s.id)} <span class="np-sub">${esc(s.format)}</span>`)],
            ];
            // Le nombre de Devices parlant IS-12 conditionne ce que la supervision BCP-008
            // pourra faire : c'est l'information de parc la plus utile de cet écran.
            const ncpLine = `<p class="np-hint">${ncp} ${esc(tr("plugin.nmos_parc.ncpCount",
                "Device(s) exposent le contrôle IS-12 (supervision BCP-008 possible)"))}</p>`;
            $("#np-detail-body").innerHTML = ncpLine + blocks.map(([title, items]) =>
                `<div class="np-d-block"><h4>${esc(title)} <span class="np-sub">${items.length}</span></h4>` +
                (items.length ? `<ul class="np-d-list">${items.map((i) => `<li>${i}</li>`).join("")}</ul>`
                    : `<p class="np-hint">—</p>`) + `</div>`).join("");
        } catch (e) {
            $("#np-detail-body").innerHTML = `<p class="np-hint">${esc(String(e.message || e))}</p>`;
        }
    }

    return { mount: mount, unmount: unmount };
})();
