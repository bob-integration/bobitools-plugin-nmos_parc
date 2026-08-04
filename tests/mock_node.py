# SPDX-License-Identifier: GPL-3.0-or-later
# Node NMOS factice minimal (IS-04 seulement) pour éprouver le sondage du parc.
# Un port = un node, ce qui permet de simuler une machine à plusieurs cages SFP en
# ouvrant plusieurs ports.
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVERS = []


def make_handler(label, node_id, with_ncp=False):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            routes = {
                "/x-nmos/node/": ["v1.3/"],
                "/x-nmos/node/v1.3/self": {"id": node_id, "label": label},
                "/x-nmos/node/v1.3/devices": [{
                    "id": f"dev-{node_id}", "label": f"Device {label}", "node_id": node_id,
                    "type": "urn:x-nmos:device:generic",
                    "controls": ([{"type": "urn:x-nmos:control:ncp/v1.0",
                                   "href": "ws://127.0.0.1:9999"}] if with_ncp else []),
                }],
                "/x-nmos/node/v1.3/senders": [{"id": f"snd-{node_id}", "label": f"TX {label}",
                                               "format": "urn:x-nmos:format:video",
                                               "device_id": f"dev-{node_id}"}],
                "/x-nmos/node/v1.3/receivers": [{"id": f"rcv-{node_id}", "label": f"RX {label}",
                                                 "format": "urn:x-nmos:format:video",
                                                 "device_id": f"dev-{node_id}"}],
            }
            if self.path not in routes:
                self.send_response(404); self.end_headers(); return
            body = json.dumps(routes[self.path]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return H


def start(port, label, with_ncp=False):
    srv = ThreadingHTTPServer(("127.0.0.1", port),
                              make_handler(label, f"id-{port}", with_ncp))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SERVERS.append(srv)
    return srv
