# Parc NMOS — plugin Bobi.Tools

La liste des équipements **NMOS IS-04** d'un site, tenue en un seul endroit pour
[Bobi.Tools](https://github.com/bob-integration/bobitools) : on déclare les équipements ici,
une fois, et les autres outils NMOS lisent ce parc au lieu d'en tenir chacun une copie.

## Ce que fait l'outil

- **Trois façons de déclarer** : un registre (Query API, le mode à privilégier), un node
  isolé, ou une machine multi-nodes qui expose un node par cage SFP.
- **Gabarits d'expansion** pour les machines multi-nodes : port de base, pas, nombre de
  cages. Le gabarit `8x12G` (port 8090, pas de 2, 4 cages) correspond aux convertisseurs
  Blackmagic de cette gamme.
- **Sondage de joignabilité** (toutes les 60 s) et colonne « Vu » qui sépare un équipement
  qui n'a *jamais* répondu (saisie erronée, probablement) d'un équipement qui a cessé de
  répondre (panne, machine éteinte).
- **Publication du parc** dans `park.json`, contrat versionné écrit de façon atomique dans le
  volume de l'outil. Les équipements injoignables restent publiés, marqués comme tels.
- **Détail IS-04 à la demande**, avec repérage des Devices qui exposent le contrôle IS-12.

## À savoir

- Le fichier publié reste lisible **même conteneur arrêté** : les outils consommateurs ne
  dépendent pas de la disponibilité de celui-ci. C'est la raison d'un contrat fichier plutôt
  que d'une API.
- Pour qui écrit un consommateur : vérifier le champ `version` et refuser un schéma inconnu
  plutôt que le lire au mieux ; relire le fichier à chaque cycle. Le format est décrit dans
  l'aide.
- Le gabarit `auto` publie la borne haute (16 nodes) et laisse le sondage marquer les cages
  vides : ce n'est pas encore une vraie découverte. Pas de découverte DNS-SD.

## Prérequis

- **Bobi.Tools** avec **Docker** : l'outil tourne en conteneur (`runtime: docker`).
- Des équipements ou un registre **NMOS IS-04** joignables depuis le serveur.
- Consommateurs publics de ce parc :
  **[Grille NMOS](https://github.com/bob-integration/bobitools-plugin-nmos_grid)** (`nmos_grid`)
  et **[Supervision NMOS (BCP-008)](https://github.com/bob-integration/bobitools-plugin-nmos_monitor)**
  (`nmos_monitor`).

## Installation

Dans Bobi.Tools : **Réglages → Outils → Catalogue**, bouton « Installer ». Ou, sur une machine
neuve, en une ligne :

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/bob-integration/bobitools/main/get.sh) --outils nmos_parc
```

L'aide complète est dans [`help.md`](help.md), affichée dans Bobi.Tools (menu « ? » → Aide).
Un banc d'essai sans matériel (nodes NMOS factices) se lance avec `./tests/run.sh`.

## Sécurité

Le conteneur n'a pas d'authentification propre : son port n'est publié que sur `127.0.0.1`,
il n'est donc joignable qu'à travers Bobi.Tools, qui contrôle les droits. Les sondages IS-04
partent du serveur qui héberge Bobi.Tools.

## In English

Single source of truth for a site's **NMOS IS-04** equipment in Bobi.Tools. Declare a
registry (Query API), a standalone node, or a multi-node chassis with a port-expansion
template (one node per SFP cage); the tool probes reachability and publishes the park as a
versioned `park.json` contract in its Docker volume, mounted read-only by the other NMOS
tools (`nmos_grid`, `nmos_monitor`). The file stays readable even when this container is
stopped. Requires Docker.

## Licence

GPL-3.0-or-later — © 2026 BOBI SAS. Voir [LICENSE](LICENSE).
