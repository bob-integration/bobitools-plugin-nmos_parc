# SPDX-License-Identifier: GPL-3.0-or-later
# Image autonome de l'outil « Parc NMOS ». requests seul suffit : cet outil ne fait que
# lire IS-04 en HTTP clair — pas d'IS-05, pas d'IS-12, aucune écriture vers les équipements.
FROM python:3.13-slim

RUN pip install --no-cache-dir requests

WORKDIR /app
COPY server.py park.py nmos.py /app/

# /data : sources déclarées, gabarits, et park.json — le contrat publié aux autres outils.
# /bmd (ro) : parc de bmd_nmos, monté UNIQUEMENT pour la reprise initiale. Ce montage
# disparaîtra quand bmd_nmos sera lui-même devenu consommateur du parc.
VOLUME ["/data"]

# Port HTTP interne — DOIT correspondre à docker.port du plugin.json.
EXPOSE 8080

CMD ["python", "-u", "/app/server.py"]
