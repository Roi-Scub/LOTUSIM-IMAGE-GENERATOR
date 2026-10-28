# Deuxième lot d’objets libres — LOTUSim / Unity

Intégration du 16 octobre 2026 : huit apparences supplémentaires, sans supprimer
les anciens modèles. Bibliothèque actuelle : **26 apparences, 12 catégories**,
hors FREMM utilisée comme bateau observateur.

## Utiliser les modèles déjà installés

Les variantes sont déjà activées dans
`Assets/Dataset/MaritimeRandomLotusim.asset` du projet Unity. Ouvrir la scène
`Assets/Scenes/Dataset/MaritimeRandomLotusim.unity` et utiliser le lancement
habituel de la campagne connectée. LOTUSim et son serveur ROS TCP doivent être
disponibles comme auparavant. Ne pas lancer une deuxième interface ROS pour
ces assets ; ne pas démarrer manuellement une autre copie du scénario.

Le pilote choisit une apparence par rencontre à partir de `seed` et `trackId`.
Changer la graine fait varier les modèles. Le préfab d’origine reste un candidat.
Dans `Classes → Prefab Variants`, on peut retirer des variantes ; ne pas mélanger
les catégories. Pour imposer une variante, la choisir comme `Prefab` et vider
`Prefab Variants`. Les variantes doivent rester distinctes du préfab par défaut.

Les quantités, vitesses, distances, identifiants, trajectoires et météo sont
conservés. La campagne reste à 360 instants en 3840 × 2160, avec ses modes RGB,
IR synthétique et vision nocturne. Chaque frame enregistre `modelName` et les
crédits sont exportés dans `asset-attributions.json`.

Le YAML `assets/scenarios/MaritimeRandomLotusim.yaml` a été synchronisé avec la
sélection de la graine actuelle. Après un changement de configuration, utiliser
l’export de scénario habituel (menu Dataset 8). Une seule classe avion peut tirer
soit l’ancien avion, soit l’A320, soit le Cessna ; tous ne sont donc pas forcément
présents ensemble dans une campagne.

Pour inspecter les huit nouveaux modèles sans ROS :

1. Attendre la fin de l’import Unity et sortir de Play.
2. Ouvrir `Assets/Scenes/Models/OpenObjectsLibrary.unity`, ou le menu
   `LOTUSim → Models → External objects CC-BY → 3 - Open inspection scene`.
3. Entrer en Play, sélectionner un objet, faire varier l’angle, la houle ou
   l’éclairage. Le mode Rigidbody libre est proposé uniquement pour les bateaux.

La galerie locale est dans le projet Unity :
`artifacts/marine-library/open-objects/index.html`. Elle propose deux vues 4K par
asset, les annotations, les masques et un test connecté depuis la FREMM.

## Inventaire et sources

Les nombres de triangles ci-dessous décrivent la géométrie importée, hors feux
ajoutés. Dimensions de simulation approximatives, non certifiées.

| Clé du préfab / renderer LOTUSim | Source et auteur | Classe | Détail / comportement |
| --- | --- | --- | --- |
| `buoy_navigation_ozzy` | [Buoy](https://sketchfab.com/3d-models/buoy-8e0584c27c37417f925c6be4ff7c6d13), OzzyDan | bouée, 1 | 702 triangles, texture 1K, hauteur 2,5 m ; balise légère/stylisée, lanterne ajoutée |
| `drone_amvlab` | [Aircraft Models](https://github.com/amvlab/aircraft-models), AMV Lab | drone, 2 | 5 170 triangles, texture 1K ; quatre hélices animées, feux |
| `helicopter_utility_gb` | [Helicopter](https://sketchfab.com/3d-models/helicopter-ef70283b1dea4ae8b18eec9231ce390e), Gigantic Burger | hélicoptère, 3 | 4 738 triangles, textures jusqu’à 2K ; animation source des rotors principal et arrière |
| `airplane_a320` | [Aircraft Models](https://github.com/amvlab/aircraft-models), AMV Lab | avion, 4 | 5 229 triangles, texture 1K, 37,57 m ; version sans logo de compagnie, feux |
| `airplane_c172` | [Cessna 172](https://sketchfab.com/3d-models/cessna-172-64cddaee5aff470682659a8c08525046), e737 / Nobilis the Palaeovespa | avion, 4 | 14 240 triangles, textures optimisées 256 px, 8,28 m ; feux |
| `seagull_dayvable` | [Seagull](https://sketchfab.com/3d-models/seagull-dc42ffc81c86480e9e7f7752fa134174), Dayvable ; [FBX/rig dérivé](https://github.com/viniciusbarros/msc_game_obstacle_course), viniciusbarros | oiseau, 5 | 4 412 triangles importés, envergure 1,45 m ; texture blanche et clip WingFlap, sans éclairage artificiel |
| `speedboat_smolbot` | [Boat](https://sketchfab.com/3d-models/boat-dc676eac5985450a9271f9b31eb47778), FirdausSahak | hors-bord, 9 | 11 028 triangles, matériaux de couleur, 6 m ; houle et feux |
| `speedboat_racing` | [Boat](https://sketchfab.com/3d-models/boat-bd6166ae8e294bd4a7d4e46be7f80f5d), milamila | hors-bord, 9 | 71 282 triangles, textures jusqu’à 2K, 12,8 m ; houle et feux |

Le niveau de détail n’est **pas uniforme** : ce lot diversifie les silhouettes,
textures et animations ; il ne rend pas chaque modèle plus détaillé que tous les
modèles du premier lot. Le Cessna reste limité par ses textures 256 px.

## Droits et traçabilité

Les huit sources sont sous **CC BY 4.0**, vérifiées par les pages/API des créateurs
ou, pour AMV Lab, par le dépôt original et sa licence. Partage, adaptation et
usage commercial sont permis avec attribution, lien de licence et indication
des modifications : [conditions officielles](https://creativecommons.org/licenses/by/4.0/).
Ce n’est ni du domaine public ni une conversion de leur licence en EPL-2.0.
Marques, personnes et autres droits éventuels ne sont pas couverts ; aucun
créateur n’endosse l’intégration.

Les GLB/FBX modifiables, notices, licences, versions Git des miroirs et SHA-256
sont conservés dans `ThirdParty/OpenObjects/` du projet Unity. Les captures des
licences individuelles sont archivées ; pour AMV, la provenance indique
explicitement le dépôt auteur, pas une réponse API Sketchfab. L’adaptation du
goéland conserve aussi le crédit du rig FBX dérivé.

Les candidats non commerciaux ou sans licence vérifiable ont été exclus. Un
dépôt contenant certains modèles libres ne rend pas tous ses autres modèles
réutilisables. Les modèles téléchargés sont traités comme des données ; aucun
script distant n’est exécuté.

## Physique et animations : ce qui est réellement simulé

- LOTUSim reste l’unique propriétaire de la position et orientation de la racine
  ROS. Les équivalents SDF/OBJ sont installés sous `assets/models/<clé>/`.
- Les deux bateaux utilisent la réponse amortie à neuf points de l’océan HDRP.
  La balise utilise cinq points. Seul l’enfant visuel bouge dans les captures
  connectées. La scène d’inspection permet aussi la flottabilité Rigidbody libre
  des deux bateaux, approximation hydrostatique sans propulsion calibrée.
- Chaque nouveau préfab possède un Rigidbody cinématique et des collisions
  simplifiées. Cela ne constitue **pas** une physique navale/aéronautique validée.
  Le scénario connecté garde des trajectoires cinématiques dans Gazebo ; ces
  nouveaux SDF ne prétendent pas activer une hydrodynamique Gazebo.
- Les aéronefs ont une petite perturbation visuelle d’attitude ; ils ne disposent
  pas d’un solveur de portance, décrochage ou commande de vol. Le déplacement
  reste celui de LOTUSim. Les dimensions, masses et cadences sont approximatives.
- Hélicoptère : animation source échantillonnée en 30 maillages. Drone : 24
  maillages, seules les huit pales complètes tournent autour des quatre moteurs,
  sans déchirer des triangles du corps. Oiseau : 24 maillages issus du clip
  WingFlap du FBX ; le rig, caméras et lumières étrangers ne sont pas instanciés.
- Les animations changent les vrais maillages opaques utilisés à la fois par RGB,
  IR, vision nocturne et masques. Les JSON indiquent `meshAnimationFrame`,
  `animationModel`, `visualFlightResponse` et l’état des feux.
- Feux rouge bâbord, vert tribord, blanc arrière et balise rouge sur aéronefs ;
  feux de navigation sur les bateaux ; lanterne modérée sur la balise. Positions
  exprimées dans le repère du modèle, sans photométrie ni secteurs réglementaires
  certifiés. L’oiseau n’a évidemment pas de diode.
- Les vitrages/alpha sont adaptés en opaque pour respecter notre politique de
  masque. L’IR et la vision nocturne restent des approximations synthétiques,
  pas des capteurs radiométriques validés.

## Reconstruire et contrôler

Les assets sont déjà construits. Pour une reconstruction :

1. `tools/fetch_open_objects.py --manifest <Unity>/ThirdParty/OpenObjects/manifest.json --output <staging>`
   retélécharge les versions épinglées, vérifie les SHA-256 et recontrôle les licences.
2. Avec NumPy et Pillow, `tools/prepare_open_objects.py --sources <staging> --unity <Unity> --gazebo <sortie-modeles>`
   convertit les sept GLB en maillages et matériaux HDRP ; le FBX de l’oiseau est
   conservé pour l’importeur Unity natif.
3. Dans Unity hors Play, menu `External objects CC-BY → 1 - Build audited prefabs`.
   Les GUID des assets construits sont conservés lors d’une reconstruction.
4. `tools/prepare_open_objects.py --unity <Unity> --gazebo <sortie-modeles> --finish-bird`
   exporte l’équivalent statique OBJ/SDF de l’oiseau depuis son maillage importé.
5. Menu `External objects CC-BY → 2 - Enable variants in connected dataset` puis
   contrôle/export du scénario. Cette action n’ajoute ni caméra ROS ni abonnement.

Contrôles conservés dans l’éditeur : `Validate audited prefabs` et
`Validate motion and animation invariants` sous le même menu. Ils vérifient les
matériaux opaques, collisions, crédits, animations et la stabilité des trajectoires
et identifiants sur 100 graines.

Validation réelle effectuée dans un projet isolé, sans interrompre la scène
utilisateur : **16 rendus 4K annotés**, deux par nouveau modèle ; puis Gazebo,
ROS TCP et Unity sur domaine 97 / port 10001 : **3 instants, 9 images 4K,
41 annotations et une seule connexion**. Les huit modèles étaient présents dans
les snapshots LOTUSim. Un contrôle indépendant des pixels vérifie COCO RLE,
YOLO, boîtes, surfaces visibles, masques et alignement des trois modalités. La
caméra reste fixée à la passerelle FREMM et hérite de son roulis. Scénario de
test arrêté proprement ; serveur et relais de test fermés ; simulation habituelle
non interrompue. Rapports dans la galerie, sous `captures/` et `connected/`.
