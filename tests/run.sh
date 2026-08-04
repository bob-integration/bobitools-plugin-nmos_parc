#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Banc d'essai du « Parc NMOS », SANS matériel ni dépendance sur la machine hôte :
# les tests tournent dans l'image du plugin, qui embarque déjà requests.
#
#   ./tests/run.sh          → construit l'image si besoin, puis joue la suite
#
# mock_node.py ouvre un node NMOS factice par port, ce qui permet de simuler un châssis à
# plusieurs cages SFP — dont une cage vide, pour vérifier qu'un point d'entrée injoignable
# reste PUBLIÉ plutôt que de disparaître silencieusement du parc.
set -e

DIR=$(cd "$(dirname "$0")/.." && pwd)
IMAGE=$(sed -n 's/.*"image": *"\([^"]*\)".*/\1/p' "$DIR/plugin.json")

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "→ construction de $IMAGE"
    docker build -t "$IMAGE" "$DIR"
fi

FAIL=0
for t in test_park; do
    echo
    echo "══ $t ══"
    # --network host : le banc écoute sur 127.0.0.1, le code testé doit pouvoir l'atteindre.
    docker run --rm --network host -v "$DIR/tests:/tests:ro" "$IMAGE" \
        python -u "/tests/$t.py" || FAIL=1
done

echo
[ $FAIL -eq 0 ] && echo "✔ la suite passe" || echo "✘ la suite échoue"
exit $FAIL
