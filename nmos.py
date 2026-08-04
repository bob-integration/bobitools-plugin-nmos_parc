# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 BOBI SAS, France
# Auteur : Cyril Mazouer, pour le compte de BOBI SAS
# Distribué sous licence GNU GPL v3 (ou ultérieure) ; voir le fichier LICENSE.

"""Client IS-04 du parc : sonder, et résoudre.

Deux usages seulement, volontairement :

  * `probe_node()` — sonde LÉGÈRE, jouée en boucle sur tout le parc. Deux requêtes au plus.
    Un parc peut compter des centaines de points d'entrée (une machine en gabarit « auto »
    en déplie seize à elle seule) : tout ce qui est cher ici se paie en multiplié.
  * `Is04Source.scan()` — lecture complète, à la demande, pour l'écran de détail.

Contrairement aux outils consommateurs, cet outil ne pilote rien : aucun IS-05, aucune
écriture. Il regarde, il nomme, il publie.
"""

try:
    import requests
except ImportError:
    requests = None

NODE_VERS = ("v1.3", "v1.2", "v1.1", "v1.0")
QUERY_VERS = ("v1.3", "v1.2", "v1.1", "v1.0")

PROBE_TIMEOUT = 3       # s — un équipement éteint ne doit pas retenir la boucle de sondage
SCAN_TIMEOUT = 8

CONTROL_NCP = "urn:x-nmos:control:ncp"


class NmosError(Exception):
    pass


def _get(url, timeout):
    if requests is None:
        raise NmosError("module 'requests' absent dans l'image")
    try:
        r = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        raise NmosError(_short(e))
    if r.status_code >= 400:
        raise NmosError(f"HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise NmosError("réponse non JSON")


def _short(exc):
    """Message d'erreur réseau lisible : les exceptions de requests sont illisibles telles
    quelles dans une table de parc (plusieurs lignes, url répétée, trace urllib3)."""
    name = type(exc).__name__
    if "Timeout" in name:
        return "délai dépassé"
    if "ConnectionError" in name:
        return "connexion refusée"
    text = str(exc)
    return text[:120] if text else name


def probe_node(host, port, kind="node"):
    """Sonde une entrée. Ne lève jamais : l'injoignabilité est un RÉSULTAT, pas une panne.

    Rend {reachable, error, label, versions, api}. Le libellé vient de `/self` côté node —
    c'est le nom que l'équipement se donne, bien plus utile dans une table que l'adresse IP
    saisie par l'opérateur.
    """
    family = "query" if kind == "registry" else "node"
    base = f"http://{host}:{port}/x-nmos"
    out = {"reachable": False, "error": None, "label": "", "versions": [], "api": family}
    try:
        avail = _get(f"{base}/{family}/", PROBE_TIMEOUT)
    except NmosError as e:
        out["error"] = str(e)
        return out
    out["reachable"] = True
    out["versions"] = [str(v).strip("/ ") for v in avail] if isinstance(avail, list) else []

    ver = _pick(out["versions"], NODE_VERS if family == "node" else QUERY_VERS)
    if family == "node":
        try:
            me = _get(f"{base}/node/{ver}/self", PROBE_TIMEOUT)
            if isinstance(me, dict):
                out["label"] = me.get("label") or me.get("description") or ""
                out["node_id"] = me.get("id")
        except NmosError:
            pass  # joignable mais /self muet : on garde reachable, sans nom
    return out


def _pick(available, preferred):
    got = set(available or [])
    return next((v for v in preferred if v in got), preferred[-1])


class Is04Source:
    """Lecture complète d'un point d'entrée : node isolé ou registre."""

    def __init__(self, host, port, kind="node", timeout=SCAN_TIMEOUT):
        self.host = (host or "").strip()
        self.port = int(port)
        self.kind = kind if kind in ("node", "registry") else "node"
        self.timeout = timeout
        self.base = f"http://{self.host}:{self.port}/x-nmos"
        self._ver = None

    @property
    def family(self):
        return "node" if self.kind == "node" else "query"

    def ver(self):
        if self._ver is None:
            try:
                avail = _get(f"{self.base}/{self.family}/", self.timeout)
            except NmosError:
                avail = None
            got = [str(v).strip("/ ") for v in avail] if isinstance(avail, list) else []
            self._ver = _pick(got, NODE_VERS if self.family == "node" else QUERY_VERS)
        return self._ver

    def _list(self, resource):
        data = _get(f"{self.base}/{self.family}/{self.ver()}/{resource}", self.timeout)
        return data if isinstance(data, list) else []

    def scan(self):
        """Contenu IS-04 complet, mis à plat pour l'affichage.

        On retient `ncp` sur chaque device : savoir qui parle IS-12 conditionne ce que la
        supervision BCP-008 pourra faire, et c'est une information de parc — elle a sa place
        ici plutôt que redécouverte par chaque outil.
        """
        if self.kind == "registry":
            nodes = self._list("nodes")
        else:
            try:
                me = _get(f"{self.base}/node/{self.ver()}/self", self.timeout)
                nodes = [me] if isinstance(me, dict) else []
            except NmosError:
                nodes = []

        devices = []
        for d in self._list("devices"):
            if not isinstance(d, dict):
                continue
            devices.append({
                "id": d.get("id"), "label": d.get("label") or "",
                "node_id": d.get("node_id"),
                "type": str(d.get("type") or "").rsplit(":", 1)[-1],
                "ncp": ncp_url(d),
            })

        def _res(items, kind):
            out = []
            for r in items:
                if not isinstance(r, dict):
                    continue
                out.append({"id": r.get("id"), "label": r.get("label") or "",
                            "kind": kind, "device_id": r.get("device_id"),
                            "format": str(r.get("format") or "").rsplit(":", 1)[-1]})
            return out

        return {
            "nodes": [{"id": n.get("id"), "label": n.get("label") or ""}
                      for n in nodes if isinstance(n, dict)],
            "devices": devices,
            "senders": _res(self._list("senders"), "sender"),
            "receivers": _res(self._list("receivers"), "receiver"),
        }


def ncp_url(device):
    """URL WebSocket IS-12 d'un Device, ou None. Voir `nmos_monitor` pour l'usage."""
    for c in device.get("controls") or []:
        if not isinstance(c, dict):
            continue
        if str(c.get("type") or "").startswith(CONTROL_NCP):
            href = (c.get("href") or "").strip()
            if href.startswith("ws://") or href.startswith("wss://"):
                return href
    return None
