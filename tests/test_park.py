# SPDX-License-Identifier: GPL-3.0-or-later
# Banc d'essai du « Parc NMOS » : expansion des gabarits, sondage, publication du contrat,
# et reprise du parc bmd_nmos. Tourne dans l'image du plugin, sans matériel.
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = "/tmp/bt-nmosparc-data"
BMD = "/tmp/bt-nmosparc-bmd"
GRID = "/tmp/bt-nmosparc-grid"
DIAG = "/tmp/bt-nmosparc-diag"
for d in (DATA, BMD, GRID, DIAG):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
os.environ["DATA_DIR"] = DATA
os.environ["BMD_DIR"] = BMD
os.environ["GRID_DIR"] = GRID
os.environ["DIAG_DIR"] = DIAG

sys.path.insert(0, "/app")
sys.path.insert(0, HERE)

import mock_node                                              # noqa: E402

# Une « machine » à 4 cages : ports 8090, 8092, 8094, 8096. Seules trois répondent —
# la quatrième cage est vide, cas parfaitement normal sur un châssis.
for p, ncp in ((8090, True), (8092, False), (8094, False)):
    mock_node.start(p, f"Cage {(p - 8090) // 2 + 1}", with_ncp=ncp)
mock_node.start(8235, "Registre", with_ncp=False)

import park                                                   # noqa: E402

FAIL = []


def check(label, cond, detail=""):
    print(("  OK   " if cond else "  ÉCHEC") + f" {label}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAIL.append(label)


print("── Reprise des inventaires existants ──")
# On fabrique les inventaires tels qu'ils existent en production.
json.dump([
    {"id": "aaa", "name": "Conv régie 1", "host": "127.0.0.1", "model": "8x12G"},
    {"id": "bbb", "name": "Conv régie 2", "host": "10.9.9.9", "model": "8x12G"},
], open(os.path.join(BMD, "devices.json"), "w"))
json.dump({
    "auto": {"label": "Auto", "base_port": 8090, "step": 2, "count": None},
    "8x12G": {"label": "2110 IP Converter 8x12G SFP", "base_port": 8090, "step": 2, "count": 4},
}, open(os.path.join(BMD, "models.json"), "w"))
# Le MÊME équipement manuel déclaré dans les deux outils, avec des identifiants DIFFÉRENTS :
# c'est le cas qui doit fusionner en une source portant les deux identités.
json.dump([{"id": "g1", "name": "Node partagé", "host": "127.0.0.1", "port": 8235},
           {"id": "g2", "name": "Node grille seul", "host": "10.8.8.8", "port": 80}],
          open(os.path.join(GRID, "targets.json"), "w"))
json.dump([{"id": "d1", "name": "Node partagé", "host": "127.0.0.1", "port": 8235}],
          open(os.path.join(DIAG, "targets.json"), "w"))
bmd_before = open(os.path.join(BMD, "devices.json")).read()
grid_before = open(os.path.join(GRID, "targets.json")).read()

avail = park.legacy_available()
check("trois inventaires détectés", set(avail) == {"bmd_nmos", "nmos_grid", "nmos_diag"}, str(avail))
res = park.import_legacy()
check("2 machines + 2 nodes repris", res["imported"] == {"bmd_nmos": 2, "nmos_grid": 2, "nmos_diag": 0},
      json.dumps(res))
check("gabarit 8x12G repris", "8x12G" in park.load_templates())
check("rien écrit dans /bmd (inventaire de l'utilisateur)",
      open(os.path.join(BMD, "devices.json")).read() == bmd_before)
check("rien écrit dans /legacy/grid",
      open(os.path.join(GRID, "targets.json")).read() == grid_before)

srcs = park.load_sources()
check("4 sources au total (le node partagé n'est pas dupliqué)", len(srcs) == 4, str(len(srcs)))
shared = [s for s in srcs if s.get("host") == "127.0.0.1" and s.get("kind") == "node"]
check("le node partagé porte les DEUX identités",
      len(shared) == 1 and shared[0]["origins"] == {"nmos_grid": "g1", "nmos_diag": "d1"},
      json.dumps(shared[0]["origins"]) if shared else "absent")

again = park.import_legacy()
check("reprise NON rejouée", again["skipped"] is True, json.dumps(again))
check("toujours 4 sources", len(park.load_sources()) == 4)

print("\n── Clés historiques (compatibilité des données enregistrées) ──")
# Sans ces clés, tous les salvos et instantanés de nmos_grid deviendraient orphelins.
ents = {e["key"]: e for e in park.expand()}
cage2 = next(e for e in ents.values() if e.get("machine_key") and e["host"] == "127.0.0.1"
             and e["slot"] == 2)
check("clé nmos_grid inchangée", cage2["compat"]["nmos_grid"] == "bmd:aaa:2",
      cage2["compat"].get("nmos_grid"))
check("clé nmos_diag inchangée", cage2["compat"]["nmos_diag"] == "bmd:aaa:2")
check("ptp_watch pointe le CHÂSSIS, pas la cage", cage2["compat"]["ptp_watch"] == "bmd:aaa",
      cage2["compat"].get("ptp_watch"))
check("config_backup indexe par PORT", cage2["compat"]["config_backup"] == "nmos:aaa:8092",
      cage2["compat"].get("config_backup"))
node_shared = next(e for e in ents.values() if e["kind"] == "node" and e["port"] == 8235)
check("node partagé : une clé par outil d'origine",
      node_shared["compat"] == {"nmos_grid": "manual:g1", "nmos_diag": "manual:d1"},
      json.dumps(node_shared["compat"]))

print("\n── Expansion des gabarits ──")
entries = park.expand()
check("2 machines × 4 cages = 8 nodes", len([e for e in entries if e.get("machine_key")]) == 8,
      str(len([e for e in entries if e.get("machine_key")])))
# On ne regarde que les entrées issues d'une MACHINE : le node manuel repris partage
# la même adresse mais n'a ni cage ni gabarit.
cages = [e for e in entries if e.get("machine_key") and e["host"] == "127.0.0.1"]
ports = sorted(e["port"] for e in cages)
check("ports dépliés 8090/92/94/96", ports == [8090, 8092, 8094, 8096], str(ports))
check("cages numérotées 1..4", sorted(e["slot"] for e in cages) == [1, 2, 3, 4])
check("machine_key commun aux 4 cages", len({e["machine_key"] for e in cages}) == 1)
check("constructeur propagé", all(e["vendor"] == "blackmagic" for e in cages))

print("\n── Déclaration directe ──")
park.add_source("registry", "Registre du site", "127.0.0.1", port=8235)
park.add_source("node", "Node isolé", "127.0.0.1", port=8090)
try:
    park.add_source("registry", "Doublon", "127.0.0.1", port=8235)
    check("doublon refusé", False)
except ValueError as e:
    check("doublon refusé", "déjà" in str(e), str(e))
try:
    park.add_source("node", "Sans port", "127.0.0.1")
    check("port obligatoire pour un node", False)
except ValueError:
    check("port obligatoire pour un node", True)

print("\n── Sondage et publication ──")
p = park.Park()
st = p.state()
by_key = {e["key"]: e for e in st["entries"]}
check("12 points d'entrée", len(st["entries"]) == 12, str(len(st["entries"])))

local = [e for e in st["entries"] if e["host"] == "127.0.0.1" and e["kind"] == "node"]
up = [e for e in local if e["reachable"]]
down = [e for e in local if not e["reachable"]]
check("3 cages + les nodes locaux répondent", len(up) == 5, str(len(up)))
check("la cage vide est publiée comme injoignable", len(down) == 1, str(len(down)))
check("motif d'échec lisible", down and down[0]["error"] in ("connexion refusée", "délai dépassé"),
      down[0]["error"] if down else "")
check("libellé repris de /self", any(e.get("label", "").startswith("Cage") for e in up),
      str([e.get("label") for e in up]))
check("injoignable jamais vu → last_seen vide", down and down[0].get("last_seen") is None)

print("\n── Contrat publié ──")
published = json.load(open(os.path.join(DATA, "park.json")))
check("version du contrat", published["version"] == park.PARK_VERSION)
check("propriétaire annoncé", published["owner"] == "nmos_parc")
check("sources ET vue nodes", len(published["sources"]) == 12 and len(published["nodes"]) == 11,
      f"{len(published['sources'])}/{len(published['nodes'])}")
check("le registre est hors de la vue nodes",
      all(n["kind"] == "node" for n in published["nodes"]))
check("les injoignables restent publiés (un trou doit rester visible)",
      any(not n["reachable"] for n in published["nodes"]))
need = {"key", "kind", "name", "host", "port", "machine_key", "machine", "slot",
        "reachable", "compat"}
check("schéma d'un node complet", need <= set(published["nodes"][0]), str(need - set(published["nodes"][0])))

print("\n── Résolution IS-04 à la demande ──")
node_key = next(e["key"] for e in up if e["port"] == 8090)
r = p.resolve(node_key)
check("devices lus", len(r["devices"]) == 1)
check("contrôle IS-12 repéré", r["devices"][0]["ncp"] is not None, str(r["devices"][0]))
check("senders/receivers lus", len(r["senders"]) == 1 and len(r["receivers"]) == 1)

print("\n── Retrait ──")
sid = park.load_sources()[0]["id"]
park.remove_source(sid)
p.refresh()
check("machine retirée → ses 4 cages disparaissent du parc",
      len(p.state()["entries"]) == 8, str(len(p.state()["entries"])))
try:
    park.remove_source("inexistant")
    check("retrait d'une source inconnue refusé", False)
except ValueError:
    check("retrait d'une source inconnue refusé", True)

print("\n" + ("TOUT PASSE" if not FAIL else f"{len(FAIL)} ÉCHEC(S) : " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
