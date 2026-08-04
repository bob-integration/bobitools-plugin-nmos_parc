# Parc NMOS

Cet outil **détient le parc NMOS**. C'est la seule liste d'équipements IS-04 du site : les
autres outils NMOS ne la déclarent plus chacun de leur côté, ils la lisent ici.

```
                    ┌──────────────┐
  registres  ──────▶│              │──park.json (RO)──▶  Supervision BCP-008
  nodes      ──────▶│  Parc NMOS   │──park.json (RO)──▶  Grille NMOS
  machines   ──────▶│              │──park.json (RO)──▶  Diagnostic NMOS
                    └──────────────┘
```

Avant, chaque outil tenait sa propre liste et refaisait le même calcul dans son coin. La
dérivation « une machine → un node par cage SFP » existait **en quatre exemplaires
identiques** (`nmos_grid`, `nmos_diag`, `ptp_watch`, `config_backup`) : le jour où un
constructeur change sa disposition de ports, il fallait corriger quatre fois et espérer
n'en oublier aucun. Elle vit désormais ici, une seule fois.

## Qui fait quoi dans la famille NMOS

Six outils partagent ce parc. Ils ne se recouvrent pas — chacun répond à une question
différente, et c'est ce qui explique qu'ils soient restés séparés plutôt que fondus en un
seul écran à onglets :

| Outil | La question à laquelle il répond |
|---|---|
| **Parc NMOS** | *Quels équipements avons-nous, et lesquels répondent ?* |
| **Grille NMOS** | *Qui envoie quoi à qui ?* — routage des flux, salvos, instantanés |
| **Diagnostic NMOS 2110** | *Pourquoi cet abonnement ne marche-t-il pas ?* — croise NMOS et table IGMP du switch |
| **Supervision NMOS (BCP-008)** | *Est-ce que quelque chose va mal, là, maintenant ?* — état continu, par abonnement IS-12 |
| **Supervision PTP** | *Tout le monde est-il verrouillé sur le même grandmaster ?* |
| **Sauvegarde de configs** | *Est-ce que tout est sauvegardé ?* |

S'y ajoute **Convertisseurs Blackmagic**, qui ne gère plus d'inventaire : il ne sert qu'au
détail par cage et à l'activation des envois de ces machines.

Trois gestes différents, faits par des gens différents, à des moments différents : router,
dépanner, surveiller. Ce qu'ils avaient en commun — la liste des équipements — est ici.

## Déclarer

Trois formes, à choisir selon ce dont vous disposez :

**Registre (Query API)** — le mode à privilégier. Une seule déclaration et tout le parc
enregistré devient visible, y compris les équipements ajoutés plus tard.

**Node isolé** — un équipement qui expose une Node API sur un port unique.

**Machine multi-nodes** — un châssis qui expose *un node par cage SFP*. Le **gabarit** dit
comment déplier les ports : port de base, pas, nombre de cages. Le gabarit `8x12G`
(8090, pas de 2, 4 cages) est celui des convertisseurs Blackmagic, vérifié en direct.

L'écran distingue volontairement deux plans, qu'il ne faut pas confondre :

- **Sources déclarées** — ce que vous avez saisi. Une machine = **une** ligne.
- **Parc publié** — ce que ça donne après expansion. Une machine = **N** lignes, une par cage.

## Reprendre les inventaires existants

Trois outils détenaient un inventaire avant la bascule : `bmd_nmos` (les châssis Blackmagic),
`nmos_grid` et `nmos_diag` (leurs nodes manuels). Un bandeau propose de les reprendre sans
ressaisie. La reprise est **non destructive** : on lit leurs volumes, on n'y écrit jamais, et
elle ne se rejoue pas.

Le dédoublonnage se fait sur l'**adresse**, pas sur l'identifiant. Le même équipement déclaré
à la fois dans la grille et dans le diagnostic donne donc **une** source, portant les **deux**
identités d'origine.

C'est ce qui rend la migration invisible côté données. Chaque outil indexait ses
enregistrements sur sa propre clé :

| Outil | Clé historique | Ce qui serait cassé sans elle |
|---|---|---|
| `nmos_grid` | `bmd:<id>:<cage>` / `manual:<id>` | salvos et instantanés (croisements `clé\|uuid`) |
| `nmos_diag` | idem | sélections d'écran |
| `ptp_watch` | `bmd:<id>` (au châssis) | historique de synchro |
| `config_backup` | `nmos:<id>:<port>` | **sauvegardes archivées**, rangées par répertoire de clé |
| `bmd_nmos` | l'identifiant du châssis | cache de statut, convertisseur ouvert |

Le parc republie ces clés dans le champ `compat` de chaque point d'entrée, et les identités
d'origine dans `origins`. C'est une **couche de compatibilité assumée**, pas un élément du
modèle : le jour où plus aucun enregistrement ne référencera d'ancienne clé, `compat`
disparaîtra du contrat.

Les montages `/bmd`, `/legacy/grid` et `/legacy/diag` sont **transitoires** : ils
correspondent à l'ancien sens de dépendance et quitteront le manifeste une fois la migration
digérée.

## Ce que voit un point d'entrée injoignable

Un équipement qui ne répond pas **reste publié**, marqué injoignable. C'est délibéré : un
node absent du fichier serait indistinguable d'un node jamais déclaré, et les outils
consommateurs perdraient la capacité de signaler un trou.

La colonne « Vu » sépare deux situations que le mot « injoignable » confond :

- **jamais** — l'équipement n'a jamais répondu depuis sa déclaration. Saisie erronée,
  probablement : mauvaise adresse, mauvais port, mauvais gabarit.
- **une date** — il répondait, il ne répond plus. Panne, ou machine éteinte.

Sur une machine en gabarit `auto`, les cages vides apparaissent normalement injoignables :
un châssis à quatre cages dont deux sont peuplées, c'est le cas courant, pas une anomalie.

## Le contrat publié

`park.json`, dans le volume de cet outil, monté en lecture seule par les consommateurs :

```json
{
  "version": 1,
  "updated_at": 1754320000.0,
  "owner": "nmos_parc",
  "sources": [ { "key": "machine:ab12:1", "kind": "node", "name": "Conv 1 · SFP1",
                 "host": "10.0.0.5", "port": 8090, "machine_key": "machine:ab12",
                 "machine": "Conv 1", "slot": 1, "vendor": "blackmagic",
                 "reachable": true, "last_seen": 1754319990.0,
                 "origins": { "bmd_nmos": "aaa" },
                 "compat":  { "nmos_grid": "bmd:aaa:1", "ptp_watch": "bmd:aaa",
                              "config_backup": "nmos:aaa:8090" } } ],
  "nodes": [ "… la même liste, filtrée sur kind == node …" ]
}
```

`sources` porte tout, registres compris ; `nodes` en est la vue filtrée, pour les outils qui
ne savent parler qu'à un node.

Deux règles pour qui écrit un consommateur :

**Vérifiez `version`.** Un schéma que vous ne comprenez pas doit être refusé, pas lu au
mieux — des points d'entrée fantômes valent moins que rien.

**Utilisez `compat[<votre outil>]` comme clé** si vous en aviez une avant la migration, avec
repli sur `key`. C'est ce qui garde vos enregistrements valides.

**L'écriture est atomique** (écriture temporaire puis remplacement) : vous ne tomberez
jamais sur un fichier à moitié écrit, mais lisez-le à chaque cycle plutôt que de le garder
en mémoire.

Le fichier reste lisible **même si ce conteneur est arrêté**. C'est la raison du choix d'un
contrat fichier plutôt que d'une API : les outils consommateurs ne dépendent pas de la
disponibilité du propriétaire.

## Tester sans matériel

```sh
./tests/run.sh
```

Ouvre plusieurs nodes NMOS factices — dont un châssis à quatre cages avec une cage vide — et
vérifie l'expansion des gabarits, le sondage, le contrat publié, la reprise des trois
inventaires existants (avec fusion des doublons) et la conservation des clés historiques.
