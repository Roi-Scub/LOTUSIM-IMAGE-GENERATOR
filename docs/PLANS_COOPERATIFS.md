# Générer et modifier les plans coopératifs

Le dashboard conserve les scénarios coopératifs dans une base SQLite locale.
Chaque plan associe trajectoires, hypothèses, rapport de contrôle et empreintes des
fichiers. Il peut être relu dans la carte sans lancer LOTUSim ni un moteur graphique.
Une modification crée une révision, sans écraser le plan d'origine.

## Générer un scénario

Deux entrées sont disponibles sur le dashboard local :

- Dans **Trafic coopératif**, créer un scénario depuis le catalogue de modèles avec
  un nom, une graine aléatoire, une durée et un profil de circulation.
- Dans **Paramétrage**, choisir le bloc à transformer en scénario continu, puis
  cliquer sur **Générer le scénario coopératif**. Le bloc fournit les objets et
  l'environnement ; la commande habituelle de préparation des images indépendantes
  reste distincte.

Les profils « pleine mer », « croisements » et « routes parallèles » expriment une
intention de placement. Le planificateur recherche des trajectoires compatibles
avec les limites des modèles et les marges de séparation. Un espace trop petit,
une vitesse incompatible ou une contrainte impossible provoque un refus explicite.

Le mode de vitesses automatiques utilise les plages du catalogue et tient compte
des restrictions du modèle de mer. Le mode de vitesses demandées conserve les
valeurs du bloc, y compris zéro. Les caractéristiques du catalogue restent des
hypothèses de simulation et non des performances constructeur certifiées.

Après génération, le plan est enregistré et sélectionné dans **Trafic coopératif**.
Les distances sont des demandes géométriques, pas une garantie de visibilité ou de
reconnaissance sur les images. Le nombre d'images du bloc ne garantit pas autant de
détections exploitables.

Dans un épisode en mouvement, la distance demandée est respectée à l'instant central
de l'objet ; elle varie ensuite avec sa trajectoire. La météo et la mer du bloc
décrivent les demandes de rendu et les hypothèses du planificateur. Cet export ne
change pas automatiquement l'océan ou les éclairages d'un moteur graphique.

## Lire et choisir un plan

Le sélecteur de la bibliothèque présente les plans et leurs révisions. L'entrée
« source historique » lit toujours le plan existant sans le remplacer. Une sélection
ne définit pas de scénario actif dans LOTUSim.

Le curseur temporel et la lecture animent les trajectoires prévues. La carte n'est
ni un relevé de positions reçues en direct, ni une carte nautique. Les positions sont
exprimées en ENU : est, nord et altitude en mètres.

## Modifier et contrôler une révision

1. Choisir un objet, régler son centre est/nord, sa vitesse et son cap ; l'altitude
   est modifiable pour les aéronefs. Le centre correspond à l'instant central
   indiqué, pas nécessairement au début de la trajectoire.
2. Prévisualiser les changements puis enregistrer le brouillon. Une nouvelle
   révision est créée avec un lien vers son parent et le statut « à recontrôler ».
3. Lancer les contrôles de cette révision. Ils ne déplacent aucun objet pour la
   rendre acceptable : un échec reste enregistré avec son rapport. Une correction
   des trajectoires passe par une nouvelle édition.

Une révision contrôlée reste un résultat dans un modèle cinématique borné. Ce statut
ne signifie ni certification de sécurité, ni validation de l'affichage natif. Le
fichier de scénario YAML n'est inclus dans l'export que si les contrôles requis ont
réussi ; les versions à recontrôler ou refusées restent consultables en JSON.

## Portée des contrôles COLREG

Le rapport distingue la séparation géométrique des objets et les contrôles de
rencontre maritime implémentés. Les règles internationales traitent notamment le
dépassement, le face-à-face et le croisement ; elles comportent aussi des obligations
de veille, de vitesse de sécurité et des cas de visibilité restreinte. Voir
[la présentation de la convention par l'OMI](https://www.imo.org/en/about/conventions/pages/colreg.aspx)
et le [manuel officiel USCG, partie internationale](https://www.navcen.uscg.gov/sites/default/files/pdf/navRules/Handbook/Nav%20Rules%20Handbook_Corrected_08-12-2024.pdf).

Le contrôle local porte sur des rencontres géométriques dans les hypothèses du
scénario. Il ne constitue pas une implémentation complète des COLREG : statuts
particuliers des navires, règles de voile ou de pêche, chenaux, dispositifs de
séparation, veille et visibilité restreinte demandent des traitements supplémentaires.
La catégorie d'un mesh ne suffit pas à établir le statut réglementaire d'un navire.
Les règles maritimes ne certifient pas non plus les trajectoires des aéronefs.

## Base locale et exports

La base se trouve dans le clone LOTUSim actif :

```text
runtime/LOTUSim/artifacts/traffic-library/library.sqlite3
```

Elle contient les plans et leurs contextes, et non des commandes de lancement.
Les écritures sont verrouillées et publiées atomiquement. Les noms de fichiers et
les requêtes SQL ne sont pas fournis par le navigateur. La base est bornée à 200
révisions et 64 Mio ; elle n'est pas incluse dans le manifeste des sources portables.

Le ZIP d'un plan contient le plan JSON, les instantanés de configuration et de
catalogue, les messages de planification, le rapport et un manifeste avec empreintes
SHA-256. Le YAML de scénario n'est présent que pour une version contrôlée. Les
modèles 3D eux-mêmes et les moteurs ne sont pas embarqués.

Le téléchargement ne démarre rien. L'exécution dans LOTUSim et le branchement du
rendu nécessitent toujours les services, modèles et adaptateurs compatibles. Le
paquet n'est pas un importeur universel pour Unity, Unreal ou un autre moteur.
