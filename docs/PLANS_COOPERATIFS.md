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

## Régler la cadence des photos

Dans le panneau de scénario continu, choisir **Nombre d'images** ou **Une photo
toutes les X secondes**. Le premier mode répartit le nombre demandé sur la durée ;
le second calcule automatiquement le nombre de prises. La composition du bloc et
son budget d'images indépendantes ne sont pas modifiés.

Le temps est celui de la simulation, pas le temps réel passé à calculer le rendu.
La première prise est prévue à **0 seconde**, et l'instant exact de fin n'est pas
capturé. Ainsi, 60 secondes avec un intervalle de 2 secondes donnent 30 photos,
aux instants 0, 2, 4, …, 58 secondes.

Les instants sont compilés sur une grille de 30 frames par seconde. Chaque instant
demandé est arrondi indépendamment à la frame la plus proche, sans accumulation
de dérive. Un intervalle non multiple de 1/30 seconde peut donc produire des écarts
alternés entre les prises ; l'écart de quantification est indiqué dans l'aperçu.
Les calendriers dépassant 2 000 captures ou confondant plusieurs prises sur une
même frame sont refusés. Le réglage est conservé dans le plan et son contexte ;
une altération des frames sans calendrier cohérent bloque le contrôle.

Les anciens plans gardent leur calendrier. Dans Trafic coopératif, **Calendrier
hérité** conserve aussi les éventuelles rafales du planificateur. Une cadence
explicite remplace ces rafales ; le nombre annoncé correspond à ce calendrier seul.

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

## Capturer ce calendrier dans Unity

1. Télécharger le ZIP d'un plan **contrôlé**, puis l'extraire dans un dossier local.
2. Avec Play arrêté, dans le projet Unity actif, choisir **LOTUSim > Dataset >
   Cooperative traffic > Import library bundle manifest (no Play)** et sélectionner
   le `manifest.json` extrait. L'import vérifie les empreintes et les références ;
   il ne démarre aucun scénario ni nouvelle connexion ROS.
3. Ouvrir seule la nouvelle scène `Assets/Scenes/Dataset/Library_<identifiant>.unity`.
   Les services LOTUSim et ROS TCP habituels doivent être prêts, sans autre scénario
   en cours. Passer en Play, puis utiliser **Start randomized sequence** dans le menu
   du composant `DatasetSequenceRunner`. Le démarrage automatique reste désactivé
   pour éviter un lancement involontaire.
4. Les sorties se trouvent dans le projet Unity sous
   `artifacts/dataset-library-captures/<identifiant>/`. Le calendrier compilé et le
   reçu d'import permettent de comparer les prises prévues aux fichiers réellement
   produits. Un plan enregistré ne prouve pas qu'un rendu a été effectué.

L'import crée une nouvelle configuration, une scène et un YAML ; il refuse
d'écraser un import existant et préserve les JSON sources. Il nécessite la scène
connectée et la configuration `MaritimeTrafficAgents` déjà installées, ainsi que
les prefabs natifs correspondants. Les modèles importés dynamiquement depuis le
dashboard nécessitent encore leur propre raccord d'import avec version figée ;
ils ne sont pas acceptés silencieusement par cet importeur de bibliothèque.

La houle et l'éclairage utilisent les réglages visuels existants, non calibrés.
Les demandes de nuages et de pluie sont archivées, mais cet importeur ne les
applique pas encore aux shaders. Les durées produisant une différence de nombre
de frames entre Python et la précision native Unity sont refusées : utiliser alors
une durée entière et régénérer le plan. La compilation des scripts ne remplace pas
une validation des images sur le moteur et le GPU de la machine.
