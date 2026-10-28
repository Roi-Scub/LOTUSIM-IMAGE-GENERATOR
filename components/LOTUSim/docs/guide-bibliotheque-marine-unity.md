# Bibliothèque marine détaillée : sept bateaux

Les modèles sont des créations procédurales originales et génériques, en mètres,
pas des scans ni des reproductions certifiées de navires existants. Le rendu le
plus détaillé est fourni par Unity HDRP. Les mêmes géométries sont exportées dans
LOTUSim pour que les objets existent aussi côté simulateur.

## Les regarder immédiatement

Dans le projet `LOTUSim-Unity-modules`, quitter Play, puis ouvrir :

**LOTUSim > Models > Open marine library — waves and physics**

Appuyer sur Play. Le panneau permet de choisir un bateau, l'angle, la hauteur de
vue, le zoom et le vent. La caméra suit le bateau sélectionné. Cette scène est
indépendante : elle ne démarre ni ROS ni une campagne et ne demande pas LOTUSim.
Elle n'interrompt pas un scénario en cours dans le conteneur.

Scène enregistrée : `Assets/Scenes/Models/MarineLibrary.unity`. Les sept prefabs
sont déjà générés dans `Assets/Prefabs/` ; il n'est pas nécessaire de les reconstruire.

| Objet | Modèle / adresse Unity | Classe | Longueur de coque × largeur |
| --- | --- | ---: | --- |
| Chalutier | `fishing_trawler` | 6 | 24 × 7,2 m |
| Porte-conteneurs | `container_ship` | 7 | 185 × 30 m |
| Petit yacht à moteur | `motor_yacht` | 8 | 14 × 4,3 m |
| Hors-bord | `speedboat` | 9 | 6,4 × 2,4 m |
| Jetski | `jetski` | 10 | 3,2 × 1,2 m |
| Ferry | `ferry` | 11 | 72 × 16,5 m |
| Voilier | `sailboat` | 12 | 11,8 × 3,8 m |

Ces dimensions concernent la coque, pas le débordement des équipements.

Les détails incluent : coques profilées, antifouling et ligne de flottaison,
garde-corps, vitrages teintés et encadrements, défenses, amarres, accastillage et
feux de navigation émissifs. Le chalutier possède son portique, des treuils et du
matériel de pêche ; le cargo des conteneurs nervurés avec portes et barres de
verrouillage ; le voilier des voiles bombées double face, du gréement et une quille.
Les textures HDRP comprennent couleur, normales et masques de matériau.

## Réaction aux vagues : deux modes distincts

Chaque prefab contient `MarineVesselWaveMotion`, un Rigidbody et trois volumes
de collision simples. Le maillage détaillé n'est pas utilisé comme un immense
collider dynamique.

### Mode par défaut : compatible LOTUSim / annotations

`VisualResponse` interroge l'océan HDRP en neuf points, puis applique au seul enfant
visuel la montée/descente, le roulis et le tangage amortis. Les dimensions et le
tirant d'eau modulent la réponse : un cargo est moins mobile qu'un jetski.

La racine reste cinématique et appartient à LOTUSim/ROS. Il n'y a donc pas deux
contrôleurs concurrents de position. Le chargement par l'interface ROS et par le
pilote de dataset force ce mode, même si le prefab a été réglé autrement.

La houle est calculée **dans Unity**, pas par le moteur physique Gazebo. Le
composant nécessite un océan HDRP avec **Water / Script Interactions** disponibles
dans le pipeline. La scène de présentation et la scène dataset utilisent le
pipeline `HDRP High Fidelity` prévu pour cela. Les autres pipelines du projet ne
sont pas modifiés globalement. Sans données CPU de l'eau, le composant avertit et
n'invente pas un mouvement aléatoire.

### Option : « Physique Unity libre (approximation) »

Dans la scène de présentation, cocher cette option réinstancie le bateau avec
gravité, poussées hydrostatiques réparties sur neuf colonnes, amortissement et
traînée simplifiée. Décocher revient au mode visuel. Le centre de masse et une
masse approximative sont dérivés des dimensions et du déplacement estimé.

Il s'agit d'une **approximation de flottabilité**, pas d'une hydrodynamique navale
validée : pas de propulsion, de voiles poussées par le vent, de sillage ni de
coefficients de tenue à la mer calibrés. Les gros chocs et le chavirage ne sont
pas validés. Réserver ce mode aux objets dont Unity possède entièrement la
trajectoire ; il est volontairement désactivé pour les objets contrôlés par ROS.

## Les utiliser dans LOTUSim

Les sept dossiers `LOTUSim/assets/models/<modèle>/` contiennent les géométries
OBJ, matériaux MTL, `model.config`, `model.sdf` et leurs métadonnées. Les matériaux
Gazebo sont plus simples que les matériaux HDRP ; la présence du modèle dans
Gazebo ne donne pas automatiquement le rendu d'eau et d'éclairage Unity.

Un scénario indépendant est fourni :
`LOTUSim/assets/scenarios/MarineLibraryDemo.yaml`.
Il place les sept objets à des positions séparées, avec leur interface de rendu
activée. Les racines sont statiques ; la réponse à la houle est côté Unity.
Lancer ce scénario à la place d'un autre scénario, avec l'interface Unity ROS
habituelle et un océan HDRP actif. Le champ **Model name in Renderer** doit être
exactement l'adresse du tableau, pas le nom de l'instance.

Ce scénario n'ajoute pas de moteur XDyn, de dynamique Gazebo ou de propulsion.
Pour une campagne connectée, préférer le processus ci-dessous, sans lancer le
scénario manuellement dans l'interface Web.

## Les inclure dans les images annotées

La campagne connectée a maintenant été enrichie à la demande : les sept bateaux
y sont actifs, avec leurs vitesses distinctes, en plus des cinq classes initiales.
Elle garde 360 images et son cycle jour / soirée / nuit. Voir le
[guide de la campagne avec houle évolutive et caméra sur le pont](guide-randomizer-lotusim-unity.md).

Pour ajouter ces catégories à une autre configuration ou à une installation
qui ne les possède pas encore :

1. Hors Play, ouvrir **LOTUSim > Dataset > 7 - Open multi-object sequence connected
   to LOTUSim** si la configuration connectée n'existe pas encore.
2. Choisir **LOTUSim > Models > Add marine categories to connected dataset (count 0)**.
   Ce menu ajoute les catégories absentes avec `count = 0`, conserve les anciennes
   catégories et refuse les collisions d'identifiants.
3. Sélectionner `Assets/Dataset/MaritimeRandomLotusim.asset`. Dans **Classes**, mettre
   le nombre souhaité sur un ou deux bateaux pour commencer, puis ajuster les
   distances. Les valeurs proposées tiennent compte de la caméra élevée de la FREMM.
4. Les bateaux sont initialement `moored = true` : ils restent dans la scène tout
   en réagissant à la houle. Pour des traversées, désactiver `moored` et définir une
   vitesse non nulle ; LOTUSim pilote alors la trajectoire cinématique, pas une
   propulsion hydrodynamique.
5. Réexporter avec **LOTUSim > Dataset > 8 - Export connected configuration to
   LOTUSim YAML**, puis suivre le [guide de lancement connecté](guide-randomizer-lotusim-unity.md).
   Unity doit lancer lui-même son scénario et en confirmer l'arrêt.

Les catégories, masques d'instance, rectangles, libellés, JSON, COCO et YOLO passent
par la chaîne existante. Les identifiants COCO du tableau sont distincts des
indices YOLO contigus décrits dans `class-map.json` ; ne pas les confondre.
Les états d'objet enregistrent aussi `flotationModel`, `vesselHeaveM`,
`vesselRollDeg`, `vesselPitchDeg` et l'instant d'échantillonnage de l'eau. La
position de racine ROS reste distincte de celle du visuel flottant.

## Poids des modèles et reconstruction

Le porte-conteneurs est volontairement détaillé : environ 514 000 triangles,
contre environ 8 000 à 65 000 pour les autres bateaux. Aucun LOD automatique n'est
livré. Commencer avec un seul cargo et mesurer le temps de rendu avant d'en
multiplier les instances. Le photoréalisme dépend aussi de la lumière, de la
caméra et de l'échelle dans l'image ; le nombre de polygones ne le garantit pas.

Les sources de génération sont `Assets/Editor/MarineLibrary*.cs`.
**LOTUSim > Models > Build detailed marine library (7 vessels)** régénère les
visuels appartenant à cette bibliothèque et les exports LOTUSim. Les GUID des
assets existants sont conservés et les prefabs étrangers ne sont pas écrasés.
Enregistrer les modifications avant une reconstruction ; toute retouche manuelle
à l'intérieur de l'enfant visuel généré sera remplacée.

**LOTUSim > Models > Validate marine library and flotation** vérifie les maillages,
colliders, dimensions et règles de propriété de la racine.

## Vérifications effectuées

- Compilation C# des scripts d'exécution et d'éditeur.
- Construction native des sept prefabs, validation des indices, normales et
  triangles, puis rendus réels HDRP avec échantillonnage de la houle.
- Racines ROS inchangées pendant les tests de réponse visuelle des sept modèles.
- Scène de présentation réellement chargée : une caméra, aucune connexion ROS,
  échantillonnage de l'eau et bascule entre modes physique et visuel vérifiés.
- Équilibre physique sur eau calme : jetski et cargo, 600 pas PhysX de 20 ms
  chacun, après une petite perturbation initiale. Ce test n'est pas une validation
  navale en mer formée.
- Test isolé Gazebo → ROS TCP → Unity HDRP avec les sept classes : huit images,
  56 annotations, une connexion, alignement des poses et cohérence masques / COCO /
  YOLO vérifiés ; arrêt confirmé du scénario de test uniquement.

Les aperçus sont dans `LOTUSim-Unity-modules/artifacts/marine-library/index.html`.
