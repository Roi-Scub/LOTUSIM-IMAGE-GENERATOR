# Randomizer maritime multi-objets — caméra mobile et annotations

Le mode **connecté à LOTUSim**, livré séparément via le menu 7, est décrit dans
[le guide du randomizer LOTUSim–Unity](guide-randomizer-lotusim-unity.md).
Le présent guide concerne le mode autonome du menu 6.

Cette première version ajoute un mode **séquence**, indépendant du pilote mono-bouée de 432 images. La caméra garde son cap de visée, se déplace suivant une route linéaire et reçoit un petit mouvement amorti à partir de la houle HDRP. Elle rencontre des bouées, oiseaux, drones, un petit avion à hélice et un hélicoptère. Les objets sont annotés automatiquement avec leur classe et une identité stable d'une image à l'autre.

**Périmètre : les trajectoires de cette version sont pilotées dans Unity.** Elle utilise la bibliothèque de modèles du projet LOTUSim, mais n'appelle pas les services de scénario ROS et ne simule ni le vol ni l'hydrodynamique d'un navire. Elle n'ajoute aucun client ROS et ne modifie pas les scènes Launcher/defenseScenario ni la configuration du pilote de 432 images. Un couplage des trajectoires à LOTUSim/Gazebo reste une étape distincte. Ces images restent des données synthétiques.

## Lancer

1. Quitter Play, faire **Assets → Refresh**, puis attendre la compilation.
2. Ouvrir **LOTUSim → Dataset → 6 - Open randomized multi-object sequence (no ROS)**.
3. Les fichiers `Assets/Scenes/Dataset/MaritimeRandomSequence.unity` et `Assets/Dataset/MaritimeRandomSequence.asset` sont créés s'ils n'existent pas. Une scène/configuration déjà présente n'est pas remplacée.
4. Cliquer **Play**, sans Pause, puis ouvrir **4 - Campaign monitor**.
5. Attendre `complete`, puis **Ouvrir la galerie**. La caméra capture dans une texture dédiée : le suivi est la référence, pas une fenêtre Game vide.

Le premier test peut être raccourci : hors Play, sélectionner la configuration, mettre `Duration Seconds = 8` et `Capture Every Frames = 15` pour **16 images à 2 Hz**. Garder le préchauffage. Revenir ensuite à 60 s et 5 frames pour le pilote de 360 images. Ces paramètres ne sont pas une liste de combinaisons comme le pilote précédent : ce sont des instants successifs d'une même scène.

Les cinq prefabs doivent exister : `buoy`, `small_drone`, `helicopter`, `airplane`, `seagull`. Au besoin, utiliser les menus de création de la bibliothèque avant le randomizer. Un océan HDRP sans masque doit activer Water, Script Interactions et Custom Pass, et le projet doit utiliser l'espace couleur **Linear** (le projet principal le fait déjà). Aucun lancement Docker, xDyn ou ROS n'est requis pour ce mode.

## Premier épisode par défaut

- Graine : `20261014`, durée nominale : **60 s**.
- Simulation : 30 rendus/s simulés ; une capture toutes les 5 frames, soit **360 images à 6 Hz**.
- Caméra à 3,5 m au-dessus de l'origine, vitesse de route 4 m/s, cap de route nord et cap de visée nord. L'axe nord conventionnel est **Unity +Z**, l'est **+X**, le haut **+Y**.
- Champ vertical : 55°, légère visée vers le bas de 2°.
- Trois bouées, quatre oiseaux (modèle de mouette), deux drones, un avion et un hélicoptère sont **planifiés dans l'épisode**, pas nécessairement visibles ensemble ni tous annotés à chaque image.
- La mer et l'éclairage sont choisis une fois par épisode, parmi calme/modérée/forte et jour/contre-jour/crépuscule. Pas de changement aléatoire d'éclairage entre deux images voisines.

Avec les réglages par défaut de cette version, la graine `20261014` produit une **mer forte de jour**. Une autre graine ou un changement du nombre/plages d'objets peut changer ces choix, car ils font partie du même plan aléatoire.

| Classe | Distance horizontale demandée au milieu du passage | Hauteur au-dessus de l'origine | Vitesse monde |
| --- | ---: | ---: | ---: |
| Bouée | 20–70 m | 0 m à la racine, visuel flottant | 0 m/s |
| Drone | 20–55 m | 6–18 m | 3–7 m/s |
| Hélicoptère | 280–700 m | 40–110 m | 25–45 m/s |
| Petit avion | 750–1 600 m | 160–350 m | 50–70 m/s |
| Oiseau | 25–110 m | 3–22 m | 8–14 m/s |

Ces plages sont des **choix de génération**, pas des règles de vol ni des distributions validées de trafic réel. Le modèle d'avion a environ 10,9 m d'envergure : ce n'est pas un avion de ligne. Les couples hauteur/distance sont ajustés dans leurs plages pour que le centre du passage entre dans le champ vertical nominal. La distance oblique effective varie avec le temps et est enregistrée par objet dans le JSON ; elle n'est pas égale à la distance horizontale demandée.

## Logique des événements

La graine détermine horaires, côtés de passage, distances, hauteurs, vitesses et phase des feux. Les trajectoires sont des droites dans le repère monde, avec orientation du modèle suivant la vitesse : **les objets ne suivent pas la caméra**. Les bouées restent ancrées dans le monde, seul leur visuel flotte sur la houle.

Le calcul d'entrée/sortie prend en compte la translation de l'observateur et une marge hors du champ nominal. Les appareils ne sont pas créés puis détruits au centre de l'image. Certains sont déjà présents au début du clip ; d'autres entrent plus tard. Un objet sorti du champ ne reçoit plus de boîte, même si sa trajectoire existe encore dans la scène. Les mouvements de roulis peuvent naturellement le faire réapparaître au bord.

Une vérification de distance minimale entre les centres de trajectoires évite les passages trop proches : 5 m pour les bouées, 3 m pour les drones, 20 m pour l'hélicoptère, 30 m pour l'avion, 1 m pour les oiseaux. Une marge d'au moins 5 m est aussi vérifiée autour de la route de l'observateur (dans le plan horizontal pour les bouées), pour ne pas faire passer la caméra à travers une bouée. Les vérifications sont faites sur les plages de temps communes. Ce n'est pas un système réglementaire de séparation aérienne, un contrôleur anti-collision physique ou une vérification des collisions avec le terrain. Les figures très serrées et les vols près d'obstacles exigent un modèle plus complet.

La capacité est limitée à 12 objets actifs pour borner la mémoire des masques. Si une configuration ne satisfait pas la capacité ou les espacements, le générateur refuse le plan au lieu de déplacer silencieusement des objets au milieu d'une capture. Réduire les nombres ou augmenter la durée selon le diagnostic.

## Mouvement de l'observateur et houle

Le cap de route et le cap de visée sont indépendants. Pour avancer vers le nord tout en regardant au sud : `Route Heading Deg = 0`, `View Heading Deg = 180`. Un angle de 90° regarde vers l'est. La caméra ne cherche pas un objet cible.

Cinq recherches de hauteur près de l'observateur donnent la pente locale de l'eau. Elle produit un roulis limité à ±2,5°, un tangage additionnel limité à ±1,5° et un déplacement vertical limité à ±1,2 m, avec un gain réduit et une réponse amortie. Ces maxima ne sont pas atteints systématiquement : en mer calme, la réponse est petite. **Ce n'est pas le modèle de réponse d'un navire aux vagues.** Aucun bateau observateur, coque, interaction coque/eau ni sillage n'est ajouté.

La recherche caméra est faite avant le rendu à partir des données d'eau du dernier rendu terminé ; elle possède donc un petit délai documenté, plutôt que de modifier la caméra après le calcul de ses matrices. Le RGB, les masques et la pose effective de caméra viennent néanmoins du même rendu. Le visuel des bouées utilise le contrôleur de flottement existant, avec ses recherches de hauteur avant la capture.

La graine reproduit **le plan d'événements**, pas les pixels de l'océan ni une phase identique de houle entre machines ou sessions. Les presets de mer restent non calibrés en hauteur significative.

## Feux des appareils

Les avions/hélicoptères possèdent leurs feux rouges et verts existants, une petite diode blanche arrière et un petit feu rouge intermittent. Le schéma rouge à gauche / vert à droite / blanc arrière reprend la convention décrite dans le [manuel de vol FAA, chapitre vol de nuit](https://www.faa.gov/sites/faa.gov/files/regulations_policies/handbooks_manuals/aviation/airplane_handbook/12_afh_ch11.pdf). Le drone conserve ses diodes avant/arrière du modèle et reçoit également de petits feux supplémentaires ; son schéma n'est pas présenté comme un standard universel de drone.

L'émission est discrète : multiplicateur visuel 300 pour les feux fixes, 700 au sommet du flash, période 1,2 s et impulsion 0,12 s avec transitions de 0,02 s. Les phases diffèrent entre appareils. Les diodes supplémentaires gardent une taille physique fixe, sans grossir artificiellement les modèles éloignés. Elles ne seront donc pas nécessairement résolues de jour ou à grande distance.

Ces réglages ne sont ni des intensités certifiées, ni une reproduction réglementaire du champ angulaire des feux. Le halo/reflet n'est pas un objet à annoter. Aucun matériau partagé de prefab n'est modifié : les émissions utilisent des blocs de propriétés par instance et les nouvelles petites géométries sont créées uniquement à l'exécution. L'état des feux est enregistré dans les JSON. Les rotors/hélices et battements d'ailes ne sont pas animés dans cette première version : le modèle d'oiseau est en vol plané et les autres géométries restent celles de la bibliothèque existante.

## Fichiers et annotations

Sortie sur le Mac, dans le projet Unity :

```text
artifacts/dataset-sequences/seq_<dateUTC>_<id>/
  requested-config.json
  events.json
  provenance.json
  status.json
  classes.txt
  class-map.json
  annotations.coco.json
  review-required.txt
  index.html
  rgb/f000000.png
  overlays/f000000.png
  labels/f000000.txt
  annotations/f000000.json
  masks/f000000/buoy_001.png
  amodal/f000000/buoy_001.png
  ...
```

- `events.json` décrit les horaires/trajectoires planifiés, avec les identifiants stables et les presets choisis.
- Les aperçus affichent boîte, contour, classe française et numéro de suivi, par exemple `bouée 1` ou `avion 7`. Les cartouches sont déplacés si nécessaire pour éviter leur superposition, avec un trait vers leur objet. Les RGB d'entraînement et les masques restent sans texte.
- Dans chaque JSON d'image, `annotations` ne contient que les objets avec des pixels géométriquement visibles. `activeObjects` contient les objets dont l'événement est actif, même s'ils sont cachés/hors cadre ; **ce n'est pas la liste de boîtes à entraîner**. `visiblePixels=0` permet de repérer leur absence géométrique.
- `instance` et `trackId` restent identiques pendant le clip. COCO ajoute `track_id` et `instance`. Utiliser aussi `sequenceId` pour distinguer deux clips.
- COCO : classes 1–5 ; YOLO : indices 0–4, dans l'ordre bouée, drone, hélicoptère, avion, oiseau. `class-map.json` fixe la correspondance.
- Masques individuels, boîtes serrées et RLE COCO suivent la convention précédente : origine haut-gauche, eau occultante opaque pour les labels, silhouette amodale limitée au cadre. Plusieurs objets peuvent s'occulter mutuellement. Un objet entièrement caché/hors cadre ne reçoit pas de boîte ni de texte.
- Une image sans objet visible est conservée avec une liste d'annotations et un fichier YOLO vides : c'est une image négative, pas un échec.
- Les cibles de moins de 16 pixels ou avec un côté de boîte de moins de 2 pixels sont signalées pour révision mais restent dans les exports bruts. Ces seuils ne mesurent pas la reconnaissabilité ni le contraste.
- Les JSON enregistrent le temps du clip, le temps d'eau Unity, le numéro de rendu, les matrices/poses de caméra, les poses/distances des objets et l'état des feux.

Le pilote ne reprend pas automatiquement une session interrompue. Une nouvelle exécution crée un nouveau dossier. Les index/galerie sont publiés périodiquement et à la fin ; en cas d'échec, les fichiers complets restent disponibles. Il n'arrête aucun scénario LOTUSim.

Ces fichiers sont des **exports d'annotations**, pas encore un projet d'entraînement YOLO prêt à lancer. Préparer la disposition attendue des images/labels et le fichier de classes selon l'outil d'entraînement choisi ; aucune séparation automatique train/validation/test n'est créée.

## Modifier et vérifier

Dans la configuration, changer la graine pour un autre épisode, puis les nombres/ranges par classe, la durée, le cap de visée, la vitesse et les limites du mouvement de caméra. Faire les changements **hors Play** : la configuration est copiée au lancement. Les noms de classe de fichiers ne doivent contenir que lettres, chiffres ou underscores ; le libellé français se règle séparément.

**Validate randomized sequence planning** vérifie 100 graines, identités, plages, séparations, capacité, calendrier, entrée/sortie du champ nominal, orientation des prefabs et cadence des feux. **Validate annotation coordinates and RLE** vérifie les coordonnées et les libellés. La vérification de ces calculs ne dispense pas du test de rendu d'un clip court dans Unity.

Avant entraînement, vérifier visuellement les annotations et séparer entraînement/validation/test **par clip et par groupes de paramètres**, pas au hasard entre frames voisines. Les 360 images sont fortement corrélées. Conserver les étapes du sujet initial : capteurs d'annotation Gazebo, annotation manuelle de référence, analyse des cas limites et calibration d'un filtre de validité. Ce randomizer Unity ne les remplace pas.
