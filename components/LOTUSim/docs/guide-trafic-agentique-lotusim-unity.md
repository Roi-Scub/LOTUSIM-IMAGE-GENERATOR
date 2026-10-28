# MaritimeTrafficAgents — scénario multi-objets coopératif

Version du 16 octobre 2026. Scénario séparé de `MaritimeRandomLotusim`, qui reste
disponible et dont le YAML et l’identifiant de plan sont conservés.

## Lancer la scène

Le module LOTUSim corrigé est installé pour le **prochain démarrage**. La
simulation déjà en mémoire n’a pas été arrêtée ni remplacée à chaud. Une seule
fois, pour charger les capacités de vitesse et les virages bornés des drones :

1. Sortir de Play dans Unity et arrêter le simulateur du terminal 1 avec Ctrl+C.
   Garder le conteneur et le serveur ROS TCP existants ouverts.
2. Dans l’environnement LOTUSim du conteneur, relancer :

   ```sh
   mise run sim maritime_dataset.world
   ```

3. Dans Unity, menu `LOTUSim → Dataset → Cooperative traffic →
   1 - Generate and open all-model scenario`, puis Play.

La scène est également disponible directement dans
`Assets/Scenes/Dataset/MaritimeTrafficAgents.unity` du projet Unity. Ne pas lancer
manuellement le scénario depuis une autre interface : le pilote le lance et
l’arrête avec son jeton de propriété. Un scénario déjà actif n’est jamais arrêté
automatiquement pour lui faire de la place.

À chaque Play **depuis cette scène dédiée**, le périmètre est relu, les agents
préparent et vérifient les routes, puis le YAML et le plan Unity sont synchronisés.
Une erreur de configuration annule Play avant le lancement du scénario. La
génération nécessite Python 3 sur le poste de l’éditeur, sans dépendance externe
(`/usr/bin/python3` sur ce Mac) ; aucun compte, clé API ou modèle de langage.

Le module ancien refusait une composante de vitesse supérieure à 200 m/s.
La limite est maintenant de 350 m/s sur la norme, et annoncée dans le protocole.
Unity refuse de lancer un avion rapide si le simulateur encore en mémoire ne
présente pas cette capacité, ou une approche avec déviation s’il n’annonce pas
`boundedTurnTrajectories`. L’ancienne bibliothèque compilée est conservée dans
`artifacts/traffic-agents-install/rollback/` ; l’installation a été faite par
remplacement atomique, sans modifier les fichiers mappés par le processus courant.

## Où modifier la configuration

- Périmètre : [MaritimeTrafficAgents.json](../assets/scenarios/scopes/MaritimeTrafficAgents.json).
- Capacités par apparence : [traffic_assets.json](../assets/scenarios/catalogs/traffic_assets.json).
- Réglages de rendu et caméra : `Assets/Dataset/MaritimeTrafficAgents.asset`
  dans Unity. Les champs pilotés par le périmètre (durée, graine, cadence,
  observateur, effectifs et profils) sont régénérés à chaque Play.

Le périmètre contient la graine, durée, cadence, déplacement de la FREMM, vent
local, hypothèse de houle, espace navigable, disques interdits et distances de
sécurité. Le catalogue contient pour chaque modèle ses dimensions approximatives,
catégorie, domaine, vitesse opérationnelle, plafond, distances préférées et
provenance des hypothèses. Les objets génériques n’ont pas de fiche constructeur
inventée : leurs profils sont explicitement des approximations représentatives.

Les vitesses du catalogue ont une unité explicite : `kn`, `kmh` ou `mps`.
Les surcharges suivantes utilisent l’unité déjà déclarée pour le modèle :

```json
"overrides": [
  {"model": "container_ship", "count": 2},
  {"model": "speedboat_racing", "speedMin": 12, "speedMax": 18},
  {"model": "airplane_c172", "altitudeM": [3200, 3500]},
  {"model": "small_drone", "enabled": false}
]
```

Une surcharge ne peut pas relever une capacité intrinsèque. Un Cessna demandé
au-dessus de son plafond, un avion de ligne à 1000 km/h dans ce profil ou un
petit drone sous 20 m/s de vent font refuser le plan. Le nombre total est borné
à 40 objets plus l’observateur, et à 12 objets par catégorie. Les rayons
`rangeM` sont des préférences de mise en scène ; ils peuvent être élargis lors
d’une négociation. Les bornes d’eau, zones interdites et capacités restent des
contraintes, non des préférences.

## Scénario préparé

Les **26 apparences**, anciennes et nouvelles, sont présentes une fois chacune,
auxquelles s’ajoutent **six drones de passage rapide** avec une apparence dédiée
`drone_racer_sim` : **32 objets plus la FREMM observatrice**. Ils ne sont pas nécessairement visibles tous
ensemble. L’agent de mise en scène cherche un passage nominal de chaque centre
dans le champ de la caméra à un instant différent, sans changer la taille des
modèles ni les rapprocher artificiellement. Houle, masquage, brume et filtre de
taille peuvent encore rendre une annotation inutilisable : présence n’implique
pas reconnaissabilité. Les captures affichent maintenant le pourcentage visible
et un niveau NR / PR / R ; voir le [guide visibilité et agent RGB](guide-visibilite-agent-rgb.md).

| Famille | Profil de simulation par défaut |
| --- | --- |
| A320 | 810–870 km/h sol, 9 500–11 500 m ; contrôle supplémentaire de vitesse relative au vent et Mach ≤ 0,82 |
| Cessna 172 | 165–210 km/h sol, 3 200–3 800 m, sous la référence de plafond à 4 267 m |
| Avion léger procédural | 155–205 km/h, 2 000–2 500 m, hypothèse générique |
| Hélicoptère procédural | 110–180 km/h, 400–600 m, transit générique |
| Hélicoptère de transport | 180–245 km/h, 1 000–1 400 m, profil conservateur inspiré de l’AW101 |
| Drones | 3–8 m/s sol, 60–100 m, maximum opérationnel relatif au vent de 15 m/s et vent local ≤ 10 m/s |
| Passages rapides dédiés | 60–400 km/h, 65–78 m d’altitude ; hypothèse cinématique fictive, pas une capacité mesurée de ces quadricoptères |
| Oiseaux | 8–14 m/s, 5–28 m, hypothèse générique |
| Bouées / balises | racines fixes au niveau de l’eau ; mouvement visuel de flottabilité |
| Chalutier | 6–10 nœuds, transit et non pêche en cours |
| Porte-conteneurs | 12–18 nœuds, pas 30 nœuds systématiquement |
| Yachts / bateaux à cabine | selon modèle, 6–22 nœuds avant plafonnement par la houle |
| Hors-bords | selon modèle, 8–30 nœuds avant plafonnement par la houle |
| Jetskis | 8–22 nœuds nominaux, plafonnés à environ 14,4 nœuds avec l’hypothèse actuelle de houle |
| Ferry / voilier | 14–22 nœuds / 3–6,5 nœuds |
| FREMM observatrice | 12 nœuds, virage progressif de 8° à bâbord ; caméra solidaire de la passerelle |

Les maxima nominaux ne sont pas des objectifs à atteindre à tout prix. Les
petites embarcations ralentissent selon l’hypothèse de houle. La vitesse sol et
l’estimation de vitesse relative au vent sont enregistrées séparément ; la
simulation cinématique n’applique pas un modèle aérodynamique de crabe ou de
portance.

## Drones rapides devant la FREMM

Le bloc `fastDrones` du périmètre active six passages alternant deux formes :

| Centre du passage (temps simulé) | Mouvement | Vitesse |
| --- | --- | --- |
| 20 s | Traversée horizontale | 60 km/h |
| 42 s | Approche oblique puis déviation latérale | 180 km/h |
| 72 s | Traversée horizontale inverse | 240 km/h |
| 96 s | Approche puis déviation de l’autre côté | 300 km/h |
| 132 s | Traversée horizontale | 400 km/h |
| 156 s | Approche puis déviation latérale | 400 km/h |

Ici le bateau visé par la mise en scène est **la FREMM porte-caméra**. Ce sont
des passages visuels non armés, sans impact ni poursuite. Le centre du passage
est placé à environ 160–220 m devant la caméra, à l’altitude demandée. Une borne
conservatrice sur toute la trajectoire impose au moins 80 m de distance à la
caméra, plus la marge de planification de 5 m ; les séparations du reste du trafic
ne sont pas abaissées. Les distances exactes retenues sont archivées dans l’audit.

Les approches suivent une droite, un arc de 40° sur 8 s, puis une droite tangente.
Position et vitesse sont continues aux raccords, sans téléportation ; la vitesse
scalaire reste constante. L’inclinaison du modèle dans le virage est un effet
visuel. Ce n’est ni un solveur aérodynamique, ni un profil de vol certifié, ni une
mesure des performances d’un drone réel. L’apparence conserve les dimensions du
petit drone d’origine et ses feux ; aucun agrandissement artificiel. Les drones
ordinaires du catalogue gardent leurs limites précédentes.

Pendant une fenêtre de 3 s autour de chaque passage, la cadence de capture passe
à **10 images/s simulées**, en conservant toutes les captures de base à 2 images/s.
Cela évite de manquer un petit objet rapide. Le rendu peut prendre beaucoup plus
de temps que la durée simulée. Les masques, pourcentages visibles et NR / PR / R
s’appliquent aux drones exactement comme aux autres objets : un drone présent
n’est pas automatiquement reconnaissable.

Modifier les six entrées `passes` (`speedKmh`, `focusFraction`, `side`, `kind`) puis
régénérer par le menu Unity. `focusFraction` est une fraction de la durée totale ;
`side` vaut -1 ou 1 ; `kind` vaut `crossing` ou `approach_bypass`. Les vitesses
sont bornées à 60–400 km/h pour ce profil. Mettre `fastDrones.enabled` à `false`
rétablit le trafic sans ces six passages et la cadence de base.

La référence A320 à Mach 0,78 provient d’un [document Airbus](https://safetyfirst.airbus.com/app/themes/mh_newsdesk/pdf/safety_first_03.pdf).
La plage choisie est un réglage de scénario, pas une nouvelle spécification
certifiée. Autres références primaires : [Cessna Skyhawk](https://cessna.txtav.com/en/piston/cessna-skyhawk),
[AW101](https://helicopters.leonardo.com/documents/16114711/0/AW101%20Brochure.pdf),
[classe de drone Phantom 4 Pro](https://www.dji.com/support/product/phantom-4-pro),
[FREMM DA](https://www.naval-group.com/sites/default/files/2021-04/PR%20EN%20Naval%20Group%20delivers%20the%20FREMM%20DA%20frigate%20Alsace%20VDEF.pdf).
Le drone importé n’est pas présenté comme un modèle DJI certifié ; c’est une
référence de classe utilisée pour des limites prudentes.

## Réseau d’agents : fonctionnement réel de cette V1

L’orchestrateur utilise un tableau de messages et de réservations partagées :

```text
Périmètre + catalogue
        ↓
CatalogueAgent : capacités, météo, effectifs, validation
        ↓
ObserverAgent : réserve la route courbe de la FREMM
        ↓
BuoyAgent / SeaTrafficAgent / AirTrafficAgent / FastDroneAgent : un agent par objet
        ↔ SafetyAgent : priorités, demandes de cession ou repositionnement
        ↔ DirectorAgent : passage nominal dans le champ de la caméra
        ↓
Audit global des routes → plan immuable + YAML LOTUSim
        ↓
LOTUSim → une connexion ROS TCP → Unity + annotations
        ↓
Garde-fou : arrêt de la seule session possédée si écart inattendu
```

Il s’agit d’agents logiciels déterministes, **pas de plusieurs LLM ni de clients
ROS concurrents**. Les routes sont négociées avant l’épisode : les acteurs moins
prioritaires proposent une autre vitesse, direction ou position de départ si
leur route est conflictuelle. Les flux parallèles occupent des côtés opposés du
canal synthétique ; les traversées sont vérifiées comme les autres routes.
Les voiliers ne reçoivent pas un cap directement dans le vent dans cette
approximation.

La V1 ne prétend pas effectuer une manœuvre d’évitement réactive pendant le
rendu. Les bateaux autres que l’observateur suivent des routes rectilignes à
vitesse constante ; les déviations des drones sont réservées avant le départ.
Un nouvel obstacle inconnu ou un objet déplacé manuellement
n’est pas pris en charge par un navigateur autonome : le contrôle d’exécution
arrête la session possédée avant de sauvegarder une image incohérente, plutôt que
de téléporter un objet. Une boucle réactive avec accélérations, rayons de virage
et nouveaux messages de commande serait une extension distincte.

## Garanties et limites de sécurité

- Vérification continue analytique du point de rapprochement maximal (CPA)
  pour toutes les paires à trajectoires rectilignes, pas seulement aux images
  capturées. Un croisement entre deux captures est donc détecté.
- Pour la FREMM ou un drone en virage : borne inférieure conservatrice tenant
  compte de la vitesse relative entre les échantillons, puis marge de 5 m.
  Les droites avant/après l’arc sont vérifiées par CPA analytique.
- Domaines maritimes conservateurs liés à la longueur et aux tampons de chaque
  profil ; séparation horizontale et verticale pour l’aérien ; prise en compte
  approximative de la hauteur des superstructures pour les survols bas.
- Rectangle navigable et réserves circulaires. Ce sont des zones synthétiques,
  **pas une carte marine, un relevé bathymétrique ni le vrai schéma de trafic de
  Singapour**. L’origine géographique reste celle du projet.
- Pendant l’exécution, contrôle des racines ROS contre leurs positions réservées
  et des distances instantanées. LOTUSim reste le seul auteur des trajectoires.
- Logique inspirée de la vitesse sûre et de l’anticipation des conflits, mais
  **pas une implémentation certifiée des COLREG**, des procédures ATC ou d’une
  conduite réelle : [règles et portée OMI](https://www.imo.org/en/about/conventions/pages/colreg.aspx).

## Océan, rendu et données produites

Le vent local utilisé pour les capacités des drones est de 6 m/s. La houle
distante utilise un autre paramètre de spectre HDRP : une houle peut provenir
d’un épisode météo lointain sans vent local aussi fort. Le `windKmh` de l’océan
est donc un **paramètre visuel de spectre**, pas la vitesse du vent atmosphérique.
La hauteur de houle demandée est une hypothèse de planification, non une mesure
calibrée de la surface HDRP. Ce travail ne calibre pas une hydrodynamique.

Les vues jour / soirée / nuit restent des blocs de rendu pour varier les images,
pas une journée physique accélérée validée. Les sources, animations, feux,
réponses visuelles à la houle et licences du parc existant sont conservés.

La caméra est portée à 80 km de distance de rendu pour ne pas supprimer l’avion
à 10 km d’altitude. Un avion de ligne à sa distance réelle sera petit dans
l’image, parfois quelques pixels seulement ; aucun grossissement artificiel
n’est appliqué pour obtenir une annotation.

La configuration actuelle couvre 180 s à 30 pas/s, capture toutes les 15 étapes
avec les rafales des passages rapides : **504 instants en 4K**, avec RGB, IR
synthétique et vision nocturne, soit **1 512**
images brutes si les trois modes sont activés. Cela ne signifie pas une génération
en temps réel : 32 objets, eau HDRP et masques 4K demandent du calcul.

Le tableau de bord est dans le projet Unity : `artifacts/traffic-agents/index.html`.
Il affiche les positions prévues, vitesses, altitudes, messages et contrôles de
séparation ; ce n’est pas un rendu 3D Unity. La scène produit ses images sous
`artifacts/dataset-traffic-agents/`. Chaque campagne archive périmètre, catalogue,
audit, messages, apparences, licences et empreintes du plan et du code de
planification. Le vent local et le caractère « proxy » du spectre marin figurent
aussi dans les métadonnées des frames de ce mode.

## Validation effectuée

- Dix tests Python, dont 100 graines : couverture des 26 modèles, 35 100 paires
  auditées, reproductibilité, vent/plafond/survitesse refusés, géométrie navigable,
  collision entre captures et borne de la route courbe. Aucun simulateur requis.
- Tests Unity : résolution de chaque préfab, garde-fou contre un déplacement
  inattendu, protocole ancien refusé pour l’avion rapide, ancien YAML / identifiant
  inchangés, scène séparée. Ajout des virages bornés et des 504 instants de capture.
- Cinq tests Python supplémentaires dont 100 graines avec les six passages :
  52 800 paires vérifiées, vitesses, distances caméra, virages continus, refus des
  capacités dépassées et conservation des limites des petits drones ordinaires.
- Test natif LOTUSim isolé : trajectoire de drone à 400 km/h avec arc borné,
  positions / vitesses réelles Gazebo + ROS et reprise après nettoyage.
- Test connecté dédié au drone rapide : 20 captures RGB 1920 × 1080, trajectoire
  à 400 km/h, feux de navigation, cinq annotations NR sur les pixels visibles,
  une seule connexion et arrêt confirmé de la session possédée. Résultats dans
  `artifacts/fast-drone-validation/captures/index.html` du projet Unity ; contrôle
  indépendant dans `artifacts/fast-drone-validation/verification.json`.
- Test connecté isolé raccourci : 26 objets + FREMM, trois instants / neuf images
  4K, 60 annotations, douze catégories et une seule connexion ROS. Les masques,
  boîtes, COCO RLE, YOLO et poses ont été revérifiés indépendamment.
  Ce test antérieur précède l’ajout des six passages rapides ; la campagne
  complète de 1 512 images n’a pas été générée pendant cette validation.

Commande des tests de planification : `python3 scripts/test_traffic_agents.py`.
Passages rapides : `python3 scripts/test_fast_drone_traffic.py`.
Tests Unity : menu `Cooperative traffic → Validate compiled plan and runtime guard`.
Les processus de test ont été arrêtés, sans arrêter le simulateur ou le serveur
ROS TCP habituels. Aucune génération de capteur d’image Gazebo n’est ajoutée ici.
