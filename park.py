# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 BOBI SAS, France
# Auteur : Cyril Mazouer, pour le compte de BOBI SAS
# Distribué sous licence GNU GPL v3 (ou ultérieure) ; voir le fichier LICENSE.

"""Le parc NMOS : déclaration, expansion, sondage, publication.

Cet outil est PROPRIÉTAIRE du parc. Les autres outils NMOS ne le déclarent plus chacun de
leur côté : ils lisent `park.json` dans ce volume, monté en lecture seule.

Trois façons de déclarer un équipement, et une seule notion en sortie — le *node* :

    registry  ─┐
    node      ─┼──▶ expansion ──▶ nodes[] ──▶ sondage ──▶ park.json ──▶ outils consommateurs
    machine   ─┘

La *machine* est la généralisation de ce que `bmd_nmos` appelait un « modèle » : une adresse
et un gabarit (port de base, pas, nombre de cages) qui se déplie en N nodes NMOS, un par cage
SFP. Cette dérivation était jusqu'ici recopiée à l'identique dans quatre outils
(`nmos_grid`, `nmos_diag`, `ptp_watch`, `config_backup`) : le jour où un constructeur change
sa disposition de ports, il fallait corriger quatre fois. Elle vit désormais ici, une fois.
"""

import json
import os
import threading
import time
import uuid

from nmos import Is04Source, NmosError, probe_node

DATA_DIR = os.environ.get("DATA_DIR", "/data")

LEGACY_DIRS = {          # volumes des outils d'où l'on reprend l'existant (transitoire)
    "bmd_nmos": os.environ.get("BMD_DIR", "/bmd"),
    "nmos_grid": os.environ.get("GRID_DIR", "/legacy/grid"),
    "nmos_diag": os.environ.get("DIAG_DIR", "/legacy/diag"),
}

SOURCES_FILE = os.path.join(DATA_DIR, "sources.json")
TEMPLATES_FILE = os.path.join(DATA_DIR, "templates.json")
PARK_FILE = os.path.join(DATA_DIR, "park.json")
IMPORT_FILE = os.path.join(DATA_DIR, "imported.json")

PARK_VERSION = 1        # version du contrat publié — à incrémenter si le schéma change
REFRESH_INTERVAL = 60   # s entre deux sondages de joignabilité
PROBE_PARALLEL = 16     # sondes simultanées au plus (cf. Park.refresh)

# Gabarits d'expansion livrés d'origine. Repris de `bmd_nmos` (vérifiés en direct sur un
# 8x12G : port de base 8090, pas de 2, 4 cages SFP). `count: null` ⇒ auto-découverte.
DEFAULT_TEMPLATES = {
    "auto": {"label": "Auto (découverte)", "base_port": 8090, "step": 2, "count": None,
             "vendor": ""},
    "8x12G": {"label": "Blackmagic 2110 IP Converter 8x12G SFP", "base_port": 8090,
              "step": 2, "count": 4, "vendor": "blackmagic"},
}
AUTOSCAN_MAX = 16       # garde-fou : nb max de nodes sondés en mode auto

_io_lock = threading.Lock()


# ── Persistance ────────────────────────────────────────────────────────────────

def _read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Remplacement ATOMIQUE : des outils tiers lisent park.json en continu, ils ne doivent
    # jamais tomber sur un fichier à moitié écrit.
    os.replace(tmp, path)


def load_sources():
    with _io_lock:
        s = _read(SOURCES_FILE, [])
        return s if isinstance(s, list) else []


def save_sources(sources):
    with _io_lock:
        _write(SOURCES_FILE, sources)


def load_templates():
    with _io_lock:
        t = _read(TEMPLATES_FILE, None)
        if not isinstance(t, dict) or not t:
            t = dict(DEFAULT_TEMPLATES)
            _write(TEMPLATES_FILE, t)
        return t


def save_templates(templates):
    with _io_lock:
        _write(TEMPLATES_FILE, templates)


# ── Clés historiques des consommateurs ─────────────────────────────────────────

def compat_keys(entry, source):
    """Clés qu'un point d'entrée portait AVANT la reprise, chez chaque outil consommateur.

    Sans elles, la migration serait destructrice : `nmos_grid` compose ses crosspoints en
    « <node_key>|<uuid de ressource> » et les salvos comme les instantanés enregistrés
    stockent ces chaînes. Changer la dérivation des clés invaliderait silencieusement toutes
    les grilles mémorisées par les utilisateurs — une perte de données déguisée en refactor.

    Ce dictionnaire est donc une COUCHE DE COMPATIBILITÉ assumée, pas un élément du modèle.
    Elle a une fin de vie : quand plus aucun enregistrement ne référencera d'ancienne clé,
    `compat` pourra disparaître du contrat et les consommateurs se contenteront de `key`.

    Chaque outil avait sa propre convention, d'où le dictionnaire plutôt qu'une valeur :
        nmos_grid / nmos_diag  « bmd:<id>:<cage> »  ou  « manual:<id> »
        ptp_watch              « bmd:<id> »          (au CHÂSSIS, pas à la cage)
        config_backup          « nmos:<id>:<port> »  (le port, pas le numéro de cage)
    """
    origins = source.get("origins") or {}
    out = {}
    bmd = origins.get("bmd_nmos")
    if bmd:
        slot = entry.get("slot")
        if slot:
            out["nmos_grid"] = f"bmd:{bmd}:{slot}"
            out["nmos_diag"] = f"bmd:{bmd}:{slot}"
        out["ptp_watch"] = f"bmd:{bmd}"
        out["config_backup"] = f"nmos:{bmd}:{entry.get('port')}"
    if origins.get("nmos_grid"):
        out["nmos_grid"] = f"manual:{origins['nmos_grid']}"
    if origins.get("nmos_diag"):
        out["nmos_diag"] = f"manual:{origins['nmos_diag']}"
    return out


# ── Expansion : sources déclarées → nodes ──────────────────────────────────────

def expand(sources=None, templates=None):
    """Déplie les sources déclarées en la liste plate des points d'entrée IS-04.

    Rend (sources_resolues, nodes) où `nodes` ne contient que les points de type node —
    la vue dont se contentent les outils qui ne savent pas interroger un registre.
    """
    sources = load_sources() if sources is None else sources
    templates = load_templates() if templates is None else templates
    out = []
    for s in sources:
        kind = s.get("kind")
        if kind in ("registry", "node"):
            entry = {
                "key": f"{kind}:{s['id']}", "kind": kind,
                "name": s.get("name") or f"{s.get('host')}:{s.get('port')}",
                "host": s.get("host"), "port": int(s.get("port") or 80),
                "machine_key": None, "machine": None, "slot": None,
                "vendor": s.get("vendor") or "", "source_id": s["id"],
                "origins": dict(s.get("origins") or {}),
            }
            entry["compat"] = compat_keys(entry, s)
            out.append(entry)
        elif kind == "machine":
            out.extend(_expand_machine(s, templates))
    return out


def _expand_machine(s, templates):
    """Une machine → un node par cage. C'est LA règle qui était recopiée quatre fois."""
    tpl = templates.get(s.get("template")) or DEFAULT_TEMPLATES["auto"]
    base = int(s.get("base_port") or tpl.get("base_port") or 8090)
    step = int(s.get("step") or tpl.get("step") or 2)
    count = s.get("count") if s.get("count") is not None else tpl.get("count")
    # count absent = gabarit « auto » : on ne devine pas ici, le sondage tranchera. En
    # attendant on publie la borne haute, les nodes injoignables seront marqués tels quels
    # plutôt que disparaître silencieusement du parc.
    count = int(count) if count else AUTOSCAN_MAX
    machine_name = s.get("name") or s.get("host") or "?"
    out = []
    for i in range(count):
        entry = {
            "key": f"machine:{s['id']}:{i + 1}", "kind": "node",
            "name": f"{machine_name} · SFP{i + 1}",
            "host": s.get("host"), "port": base + step * i,
            "machine_key": f"machine:{s['id']}", "machine": machine_name, "slot": i + 1,
            "vendor": s.get("vendor") or tpl.get("vendor") or "", "source_id": s["id"],
            "auto": not (s.get("count") or tpl.get("count")),
            # Identités d'origine publiées telles quelles : un outil qui indexait son état
            # sur son propre identifiant (bmd_nmos et son cache de statut) le retrouve sans
            # avoir à décortiquer les clés de compatibilité.
            "origins": dict(s.get("origins") or {}),
        }
        entry["compat"] = compat_keys(entry, s)
        out.append(entry)
    return out


# ── Reprise de l'existant (transitoire) ────────────────────────────────────────

def legacy_available():
    """Outils dont le volume est monté et porte un inventaire à reprendre.

    Ces montages n'existent QUE pour la reprise : c'est l'ancien sens de dépendance,
    conservé le temps que chaque outil devienne consommateur du parc. Ils disparaîtront
    des manifestes une fois la migration digérée.
    """
    out = {}
    devices = os.path.join(LEGACY_DIRS["bmd_nmos"], "devices.json")
    if os.path.exists(devices):
        out["bmd_nmos"] = len(_read(devices, []) or [])
    for tool in ("nmos_grid", "nmos_diag"):
        path = os.path.join(LEGACY_DIRS[tool], "targets.json")
        if os.path.exists(path):
            out[tool] = len(_read(path, []) or [])
    return out


def _machine_for(host, template, sources):
    for s in sources:
        if s.get("kind") == "machine" and s.get("host") == host and s.get("template") == template:
            return s
    return None


def _node_for(host, port, sources):
    for s in sources:
        if s.get("kind") == "node" and s.get("host") == host and int(s.get("port") or 0) == port:
            return s
    return None


def import_legacy(force=False):
    """Reprend l'inventaire des outils qui le détenaient avant. Non destructif.

    On LIT leurs volumes, on n'y écrit jamais : l'inventaire d'un utilisateur est sacré.
    La reprise ne se rejoue pas (sauf `force`, qui se contente d'ajouter ce qui manque).

    Le dédoublonnage se fait sur l'ADRESSE, pas sur l'identifiant : le même équipement
    déclaré à la fois dans `nmos_grid` et dans `nmos_diag` doit donner UNE source, portant
    les DEUX identités d'origine — c'est ce qui permet à chacun des deux outils de
    retrouver ses données enregistrées après la migration (cf. compat_keys).
    """
    done = _read(IMPORT_FILE, {})
    report = {}
    sources = load_sources()
    changed = False

    # ── bmd_nmos : des machines multi-cages, avec leurs gabarits ──
    if "bmd_nmos" not in done or force:
        devices = _read(os.path.join(LEGACY_DIRS["bmd_nmos"], "devices.json"), [])
        models = _read(os.path.join(LEGACY_DIRS["bmd_nmos"], "models.json"), {}) or {}
        templates = load_templates()
        for name, m in (models or {}).items():
            if name not in templates and isinstance(m, dict):
                templates[name] = {"label": m.get("label") or name,
                                   "base_port": m.get("base_port") or 8090,
                                   "step": m.get("step") or 2, "count": m.get("count"),
                                   "vendor": "blackmagic"}
        save_templates(templates)
        added = 0
        for d in devices if isinstance(devices, list) else []:
            if not isinstance(d, dict) or not d.get("host"):
                continue
            tpl = d.get("model") or "auto"
            existing = _machine_for(d["host"], tpl, sources)
            if existing:
                existing.setdefault("origins", {}).setdefault("bmd_nmos", d.get("id"))
                changed = True
                continue
            sources.append({
                "id": uuid.uuid4().hex[:8], "kind": "machine",
                "name": d.get("name") or d.get("host"), "host": d["host"],
                "template": tpl, "base_port": d.get("base_port"), "vendor": "blackmagic",
                "origins": {"bmd_nmos": d.get("id")},
            })
            added += 1
            changed = True
        report["bmd_nmos"] = added
        done["bmd_nmos"] = time.time()

    # ── nmos_grid / nmos_diag : des nodes déclarés à la main ──
    for tool in ("nmos_grid", "nmos_diag"):
        if tool in done and not force:
            continue
        targets = _read(os.path.join(LEGACY_DIRS[tool], "targets.json"), [])
        added = 0
        for t in targets if isinstance(targets, list) else []:
            if not isinstance(t, dict) or not t.get("host"):
                continue
            port = int(t.get("port") or 80)
            existing = _node_for(t["host"], port, sources)
            if existing:
                existing.setdefault("origins", {}).setdefault(tool, t.get("id"))
                changed = True
                continue
            sources.append({
                "id": uuid.uuid4().hex[:8], "kind": "node",
                "name": t.get("name") or f"{t['host']}:{port}",
                "host": t["host"], "port": port, "vendor": "",
                "origins": {tool: t.get("id")},
            })
            added += 1
            changed = True
        report[tool] = added
        done[tool] = time.time()

    if changed:
        save_sources(sources)
    with _io_lock:
        _write(IMPORT_FILE, done)
    return {"imported": report, "total": sum(report.values()), "skipped": not report}


# ── Sondage et publication ─────────────────────────────────────────────────────

class Park:
    """Tient le parc résolu à jour et le publie pour les autres outils."""

    def __init__(self):
        self._lock = threading.RLock()
        self.entries = []           # points d'entrée + état de joignabilité
        self.resolved = {}          # key → {devices, senders, receivers} (registres surtout)
        self.last_refresh = 0
        self._stop = threading.Event()
        self.refresh()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self._stop.is_set():
            self._stop.wait(REFRESH_INTERVAL)
            if not self._stop.is_set():
                self.refresh()

    def refresh(self):
        """Sonde toutes les entrées, puis publie.

        Les sondes tournent en parallèle — un équipement éteint ne doit pas retarder le
        rafraîchissement de tout le parc — mais avec un plafond : une machine en gabarit
        « auto » déplie seize nodes à elle seule, et lâcher un thread par node sur un parc
        de cinquante machines mettrait la machine à genoux pour rien.
        """
        entries = expand()
        results = {}
        gate = threading.Semaphore(PROBE_PARALLEL)
        threads = []

        def work(e):
            with gate:
                results[e["key"]] = probe_node(e["host"], e["port"], e["kind"])

        for e in entries:
            t = threading.Thread(target=work, args=(e,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=30)

        now = time.time()
        with self._lock:
            previous = {e["key"]: e for e in self.entries}
            merged = []
            for e in entries:
                probe = results.get(e["key"]) or {"reachable": False, "error": "sonde non revenue"}
                before = previous.get(e["key"]) or {}
                item = dict(e)
                item.update(probe)
                item["checked_at"] = now
                # `last_seen` garde la dernière fois où l'équipement a répondu, même s'il est
                # injoignable maintenant : c'est ce qui distingue « jamais vu » (saisie
                # erronée) de « était là ce matin » (panne).
                item["last_seen"] = now if probe.get("reachable") else before.get("last_seen")
                merged.append(item)
            self.entries = merged
            self.last_refresh = now
        self.publish()

    def publish(self):
        """Écrit le contrat lu par les autres outils.

        `sources` porte tout (nodes ET registres) ; `nodes` en est la vue filtrée, pour les
        outils qui ne savent parler qu'à un node. On publie même les entrées injoignables :
        un node absent du fichier serait indistinguable d'un node jamais déclaré, et les
        consommateurs perdraient la capacité de signaler un trou.
        """
        with self._lock:
            entries = list(self.entries)
        payload = {
            "version": PARK_VERSION,
            "updated_at": self.last_refresh,
            "owner": "nmos_parc",
            "sources": entries,
            "nodes": [e for e in entries if e.get("kind") == "node"],
        }
        with _io_lock:
            _write(PARK_FILE, payload)

    # ── Résolution IS-04 (pour l'UI de cet outil) ──────────────────────────────

    def resolve(self, key):
        """Contenu IS-04 d'une entrée : devices, senders, receivers. À la demande."""
        with self._lock:
            entry = next((e for e in self.entries if e["key"] == key), None)
        if not entry:
            raise ValueError("entrée inconnue")
        src = Is04Source(entry["host"], entry["port"],
                         "registry" if entry["kind"] == "registry" else "node")
        try:
            scan = src.scan()
        except NmosError as e:
            raise ValueError(str(e))
        return {
            "key": key, "name": entry["name"],
            "devices": scan["devices"], "senders": scan["senders"],
            "receivers": scan["receivers"], "nodes": scan["nodes"],
        }

    def state(self):
        with self._lock:
            return {"entries": list(self.entries), "updated_at": self.last_refresh,
                    "version": PARK_VERSION}


# ── CRUD des sources ───────────────────────────────────────────────────────────

def add_source(kind, name, host, port=None, template=None, base_port=None,
               count=None, vendor=""):
    if kind not in ("registry", "node", "machine"):
        raise ValueError("type de source inconnu")
    host = (host or "").strip()
    if not host:
        raise ValueError("adresse requise")
    if kind in ("registry", "node") and not port:
        raise ValueError("port requis")

    sources = load_sources()
    entry = {"id": uuid.uuid4().hex[:8], "kind": kind, "name": (name or "").strip() or host,
             "host": host, "vendor": vendor or ""}
    if kind in ("registry", "node"):
        entry["port"] = int(port)
    else:
        entry["template"] = template or "auto"
        if base_port:
            entry["base_port"] = int(base_port)
        if count:
            entry["count"] = int(count)
    # Un même couple (type, adresse, port/gabarit) déclaré deux fois créerait des doublons
    # dans le parc de TOUS les outils consommateurs : on refuse à la source.
    for s in sources:
        if (s.get("kind") == kind and s.get("host") == host
                and s.get("port") == entry.get("port")
                and s.get("template") == entry.get("template")):
            raise ValueError("déjà déclaré")
    sources.append(entry)
    save_sources(sources)
    return entry["id"]


def remove_source(source_id):
    sources = load_sources()
    kept = [s for s in sources if s.get("id") != source_id]
    if len(kept) == len(sources):
        raise ValueError("source inconnue")
    save_sources(kept)
