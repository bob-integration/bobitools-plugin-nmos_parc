# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 BOBI SAS, France
# Auteur : Cyril Mazouer, pour le compte de BOBI SAS
# Distribué sous licence GNU GPL v3 (ou ultérieure) ; voir le fichier LICENSE.

"""Façade HTTP de l'outil « Parc NMOS ».

HTTP minimal (ThreadingHTTPServer, stdlib), proxifié par l'app sous /api/tools/nmos_parc/*.

À noter : cette API sert l'UI de CET outil. Les autres outils ne passent pas par elle — ils
lisent directement `park.json` dans le volume monté en lecture seule. C'est délibéré : un
fichier reste lisible même conteneur arrêté, là où une API impose que le propriétaire tourne
pour que les consommateurs fonctionnent.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import park

PORT = int(os.environ.get("PORT", "8080"))

PARK = park.Park()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def _qs(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def do_GET(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        q = self._qs()
        try:
            if parts == ["health"]:
                return self._send(200, {"ok": True})
            if parts == ["state"]:
                st = PARK.state()
                st["sources"] = park.load_sources()
                st["templates"] = park.load_templates()
                return self._send(200, st)
            if parts == ["templates"]:
                return self._send(200, {"templates": park.load_templates()})
            if parts == ["resolve"]:
                try:
                    return self._send(200, PARK.resolve(q.get("key") or ""))
                except ValueError as e:
                    return self._send(409, {"error": str(e)})
            return self._send(404, {"error": "route inconnue"})
        except Exception as e:  # noqa: BLE001 — dernier rempart
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        body = self._body()
        try:
            if parts == ["sources"]:
                try:
                    sid = park.add_source(
                        body.get("kind"), body.get("name"), body.get("host"),
                        port=body.get("port"), template=body.get("template"),
                        base_port=body.get("base_port"), count=body.get("count"),
                        vendor=body.get("vendor") or "")
                except ValueError as e:
                    return self._send(409, {"error": str(e)})
                PARK.refresh()
                return self._send(201, {"ok": True, "id": sid})
            if parts == ["refresh"]:
                PARK.refresh()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "route inconnue"})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})

    def do_DELETE(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        try:
            if len(parts) == 2 and parts[0] == "sources":
                try:
                    park.remove_source(parts[1])
                except ValueError as e:
                    return self._send(404, {"error": str(e)})
                PARK.refresh()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "route inconnue"})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
