# Pipeline d'images maritimes annotées — LOTUSim, Gazebo et Unity

Version : 12 octobre 2026. Poste de Gabriel : macOS, Docker `lotusim-dev`, Nix,
ROS 2 Jazzy, Gazebo Harmonic, Unity 2022.3.18f1 et HDRP 14.0.10.

## 1. Est-ce qu'on utilise LOTUSim et est-ce conforme au sujet ?

**L'architecture recommandée conserve LOTUSim pour les scénarios, les objets et
leur physique lorsqu'elle est nécessaire. Unity produit les images réalistes et
les annotations correspondant à ces images.**

Cela répond à l'objectif général de génération d'un corpus maritime et d'étude
de la validité de ses annotations. Mais le sujet demande explicitement la mise
en service des **capteurs d'annotation Gazebo** : une chaîne uniquement Unity ne
remplit pas à elle seule cette exigence. Leur remplacement demanderait une
validation de l'encadrant.

Recommandation : conserver deux volets, une chaîne Gazebo de référence et une
chaîne Unity pour les rendus réalistes. Elles partagent les définitions d'objets
et les conditions d'expérience ; chacune annote ses propres images. Ne pas
associer directement une boîte Gazebo à une image Unity.

### Correspondance avec les livrables

| Besoin du sujet | Réalisation prévue | Limite |
|---|---|---|
| Bibliothèque d'objets non-navires | Modèle LOTUSim/Gazebo et prefab Unity pour bouée, oiseau, aéronef, débris | Une bouée ne constitue pas toute la bibliothèque |
| Capteurs d'annotation Gazebo | Conserver et étendre le prototype `boundingbox_camera` ; segmentation si nécessaire | Une annotation Unity ne remplace pas ce livrable |
| Production d'images annotées | Capture Unity HDRP, masque d'instance, boîte et export | Annotation issue du rendu concerné |
| Règles pour les cas limites | Convention de boîte, occultation, immersion, reflets, ambiguïtés | Géométrie connue ne signifie pas reconnaissabilité |
| Facteurs contrôlés | Distance, taille, mer, lumière, météo, caméra | Enregistrer les valeurs réellement appliquées |
| Comparaison automatique/manuelle | Référence annotée sur les RGB sans montrer les annotations automatiques | Ce contrôle scientifique reste nécessaire |
| Seuils et filtre de validité | Estimation sur les observations, puis filtre versionné | Aucun seuil arbitraire présenté comme validé |

Le corpus sera **synthétique**, destiné à entraîner ou évaluer des modèles pour
le réel. Une évaluation sur des images réelles indépendantes reste nécessaire.
Automatiser la génération ne supprime pas l'annotation manuelle de référence
explicitement demandée pour l'étude.

## 2. Statut de cette documentation

Ce document est un **processus de réalisation et de validation**, pas le manuel
d'une pipeline Unity déjà implémentée.

| Élément | Statut |
|---|---|
| LOTUSim dans Docker/Nix avec ROS 2 | Installation existante |
| Connexion ROS-TCP et création du LRAUV dans Unity | Fonctionnement obtenu pendant la session précédente |
| RGB et boîte d'une bouée dans Gazebo | Prototype testé avec Mesa llvmpipe sur CPU |
| Océan HDRP dans `defenseScenario` | Présent |
| Publication RGB Unity vers ROS | `CameraSensor.cs` présent ; pas un exporteur de dataset |
| Prefab Unity de bouée pour cette chaîne | Créé et enregistré (`buoy`) |
| Masques Unity fiables avec l'eau | À développer ou intégrer, puis à valider |
| Configuration de campagne, export RGB et arrêt automatique Unity | Pilote de bouée implémenté ; première capture Unity à vérifier |
| Référence manuelle, seuils et filtre scientifique | À réaliser |

Les noms `DatasetMarine`, `DatasetRunner` et les autres modules proposés dans
ce document désignent des **éléments à créer**. Leur futur lanceur n'existe pas
encore. Les exemples de configuration sont des contrats proposés, pas des
fichiers déjà pris en charge par le projet.

Mise à jour du 13 octobre : un pilote **RGB uniquement** a été ajouté sous le
nom `DatasetCampaignRunner`, avec les scènes `BuoyDatasetPilot` (432 images,
LOTUSim) et `BuoyDatasetSmoke` (une image locale). Le lancement des infrastructures
Docker/ROS reste séparé. La pipeline d'annotation complète décrite ci-dessous
n'est toujours pas implémentée. Voir le
[guide de la campagne RGB](guide-campagne-rgb-unity.md) pour les menus réellement
disponibles, le test de rendu et les limites.

Guides existants :

- [Démarrage Docker → Unity](<guide-demarrage-macos-docker-unity.md>).
- [Première image annotée Gazebo](<first-annotated-image.md>).

## 3. Architecture et variantes

### Mode recommandé : LOTUSim + Unity, avec volet Gazebo conservé

Un lanceur sur le Mac pilote :

1. Dans Docker : monde LOTUSim/Gazebo, contrôle de scénario ROS et ROS TCP
   Endpoint. xDyn est ajouté seulement si le modèle physique le demande.
2. Sur le Mac : application Unity de génération, utilisant le GPU local pour
   l'océan, les matériaux, l'éclairage et la caméra.
3. Sur le Mac : export des captures, contrôles de cohérence, filtre et rapport.
4. Dans une campagne distincte : captures annotées Gazebo pour le volet exigé et
   la comparaison des méthodes selon un protocole explicite.

Les poses d'un objet ne doivent avoir qu'une autorité. Si elles viennent de
LOTUSim, ne pas laisser simultanément un Rigidbody Unity ou un autre script
modifier la même pose sans règle de couplage définie.

### Mode Unity seul

Utile pour développer caméra, masques et export sans dépendre de ROS. Il peut
produire une première bouée annotée. Ce banc ne constitue pas à lui seul une
bibliothèque intégrée à LOTUSim ni une mise en service de capteurs Gazebo.

### Mode Gazebo seul

Le prototype existant utilise une bouée procédurale, une caméra fixe et un plan
bleu représentant l'eau. Il valide le chemin image/annotation, pas le réalisme
maritime, la flottaison ou la validité des annotations dans les vagues.

Les deux moteurs peuvent être comparés sur des conditions définies, mais leurs
images, matériaux et vagues ne sont pas supposés identiques au pixel près.
Évaluer chacun contre la référence manuelle de ses propres images, puis comparer
les résultats par condition. Ne pas calculer un IoU entre boîtes Gazebo et Unity
comme s'il s'agissait nécessairement de la même image.

## 4. Environnement et prérequis

| Élément | Emplacement / adresse |
|---|---|
| Dépôt LOTUSim sur le Mac | `/chemin/projets/LOTUSim` |
| Projet Unity sur le Mac | `/chemin/projets/LOTUSim-Unity-modules` |
| Dépôt LOTUSim monté dans Docker | `/workspace` |
| Scénarios du shell de développement | `/workspace/assets/scenarios` |
| ROS TCP Endpoint depuis Unity | `127.0.0.1:10000` |
| Namespace actuel | `lotusim` |
| xDyn du LRAUV actuel | `ws://127.0.0.1:12346`, dans le conteneur |

Le nom du YAML, le nom de la scène Unity et le namespace ROS sont distincts :
`TestScenario.yaml`, `defenseScenario` et `lotusim` n'ont pas à être identiques.

Le rendu Unity reste natif sur le Mac : il n'exige pas de passer le GPU à Docker.
Le shell `.#software-rendering` sert au chemin Gazebo sur CPU, indépendamment.

L'UI Web LOTUSim n'est pas nécessaire à la génération automatique. Utiliser les
services ROS pour lancer/arrêter les scénarios, plutôt que des clics ou un registre
d'instances REST non opérationnel sur cette installation.

### Contrôles déjà disponibles — terminal macOS

```sh
cd "/chemin/projets/LOTUSim"
docker ps -a --filter name=lotusim-dev
docker port lotusim-dev
```

Le futur lanceur vérifiera montage réel, ports, build du workspace, ROS TCP
Endpoint, build Unity et espace disque. Il ne recréera pas le conteneur et ne
reconstruira pas toutes les dépendances à chaque campagne.

## 5. Étape A — modèles, catégories et intégration LOTUSim

Commencer par `buoy`. Chaque modèle dispose d'une fiche : source, licence,
dimensions, échelle, origine, axes, catégorie et version des fichiers.

### Modèle LOTUSim/Gazebo

Le prototype existe déjà :

- [model.config](<../assets/models/buoy/model.config>).
- [model.sdf](<../assets/models/buoy/model.sdf>).

Il est statique et porte le label Gazebo `1`. Pour un modèle réaliste, vérifier
la cohérence des géométries physique et visible. Une collision simplifiée ne doit
pas devenir automatiquement le contour d'annotation de l'objet visible.

Ne pas recopier la propulsion du LRAUV pour une bouée ou un oiseau. Valider
d'abord une représentation statique, puis le comportement adapté : flottaison,
dérive, vol ou mouvement prescrit.

### Prefab Unity

Créer le prefab `buoy`, avec matériaux HDRP, et son adresse Addressables `buoy`.
Vérifier la même échelle et le même point de référence que le modèle LOTUSim.
Chaque instance reçoit un identifiant durable, par exemple `Buoy_001`.

Distinguer catégorie (`buoy`), modèle/adresse (`buoy`), instance (`Buoy_001`) et
identifiant de capture. Le label Gazebo `1` est une catégorie dans le prototype,
pas un identifiant unique de chaque bouée. Le masque Unity doit distinguer les
instances. Versionner la correspondance vers catégories COCO et indices YOLO.

### Fragment de scénario proposé — pas encore validé de bout en bout

À ajouter à un YAML complet après création/enregistrement du prefab et test du
modèle dans LOTUSim :

```yaml
agents:
  Buoy_001:
    model: buoy
    position:
      latitude: 1.2427748599592028
      longitude: 103.7206792831421
      altitude: 0
    heading: 0
    render_interface:
      enabled: true
      renderer_type: buoy
```

Le parser actuel transforme `enabled` en valeur interne `publish_render` et
utilise `renderer_type` comme adresse de prefab. Si un domaine physique est
ajouté, ses clés YAML restent en minuscules, notamment `surface`. Une erreur de
casse a déjà empêché le chargement de la physique.

## 6. Étape B — scène et caméra de génération Unity

Créer une scène `DatasetMarine`, sans modifier la scène interactive qui fonctionne.
Réutiliser l'océan HDRP, le ciel, la lumière, le brouillard et les décors utiles
de `defenseScenario`.

La scène de génération est indépendante du Launcher/Photon, de Leap Motion, de
la VR et du contrôle clavier de la caméra. Exclure HUD, textes, logos, marqueurs
et gizmos des images d'entraînement. Conserver une seule instance logique de
connexion ROS et du connecteur LOTUSim.

Ne pas déduire le nombre d'instances logiques du seul nombre de sockets TCP :
vérifier leurs rôles et la réception effective des données.

Ajouter `DatasetCamera`. Fixer résolution, champ de vision, clipping, exposition
et effets autorisés. La capture ne dépend pas de la taille de la fenêtre Game.
Enregistrer le profil de qualité : le support de l'eau n'est pas activé dans tous
les profils HDRP du projet.

Enregistrer les matrices de vue/projection ou les paramètres intrinsèques et
extrinsèques effectivement utilisés. Tester la conversion d'axes LOTUSim/Gazebo
vers Unity avec des translations et rotations connues : Gazebo est Z-up et Unity
Y-up, et le connecteur réalise déjà une conversion. Ne pas l'appliquer une
deuxième fois dans le générateur. La caméra et l'objet doivent partager la même
référence et des unités cohérentes.

La préparation et la construction initiale de cette scène sont du développement.
« Sans action manuelle » signifie ensuite aucune interaction pendant une campagne,
pas absence de préparation ou de contrôle scientifique.

## 7. Étape C — moteur d'annotation et occlusion par l'eau

Choisir entre Unity Perception à version figée et des passes dédiées HDRP, après
un test de compatibilité avec l'eau de ce projet.

Perception fournit notamment segmentation et boîtes 2D, mais est abandonné par
Unity. Sa documentation signale des limites avec des effets modifiant géométrie
ou visibilité. Cela ne prouve pas une incompatibilité systématique de cet océan ;
cela impose une validation avant adoption. [Projet Perception](https://github.com/Unity-Technologies/com.unity.perception),
[labelers et limites](https://github.com/Unity-Technologies/com.unity.perception/blob/main/com.unity.perception/Documentation~/PerceptionCamera.md).

Pour une implémentation dédiée, les [Custom Pass HDRP](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@14.0/manual/Custom-Pass.html)
sont un point d'intégration possible, pas une garantie de masque correct pour
l'eau. Versionner le code dans le projet ou un package maîtrisé, pas uniquement
dans `Library/PackageCache`, qui peut être régénéré.

### Sorties d'une capture

- RGB brut destiné à l'entraînement, sans rectangle dessiné.
- Masque d'instance : identifiant de l'objet par pixel, dans un format entier
  sans correction gamma, compression avec pertes ou mélange non maîtrisé des IDs.
- Boîte visible issue du masque, selon une convention définie.
- Métadonnées : identités, caméra, poses rendues, temps et paramètres appliqués.
- Aperçu RGB + boîte pour les vérifications, séparé de l'image d'entraînement.

Profondeur et boîte projetée complète peuvent compléter le diagnostic ; elles
ne remplacent pas la visibilité dans le rendu.

### Boîte visible

Pour chaque ID d'instance, trouver ses pixels et calculer les bornes. Définir une
convention unique, par exemple des bornes maximales exclusives, pour éviter les
erreurs d'un pixel. Un masque vide ne produit pas une boîte visible de taille
nulle présentée comme un objet détectable.

Conserver coordonnées en pixels, résolution et origine en haut à gauche ; tester
les inversions verticales des textures. Pour YOLO, normaliser ensuite centre et
dimensions par la largeur/hauteur, avec un mapping de catégories explicite.

### Tests avec l'eau

Le masque doit respecter les mêmes objets, poses, vagues et état de rendu que le
RGB. Un remplacement de matériau ou une projection de `Renderer.bounds` ne prouve
pas que les vagues masquent correctement l'objet.

Tester : absence d'occlusion, occlusion opaque connue, vague devant l'objet,
immersion partielle, objet entièrement masqué, hors champ, écume, réflexion et
transparence. L'eau peut déplacer la géométrie et réfracter ce qui est dessous :
un simple test de profondeur ne résout pas toute la visibilité optique.

Définir ce qui est annoté lorsque des parties immergées apparaissent atténuées ou
réfractées. Garder les cas ambigus pour l'étude, sans les annoncer fiables avant
validation. Ce traitement est un point technique majeur, pas un réglage garanti
par l'ajout d'un package.

## 8. Étape D — facteurs contrôlés et mouvement

Contrôler distance, taille, hauteur/angle de caméra, lumière, exposition, mer,
occultation et immersion. Ajouter ensuite météo, pluie, brouillard, bruit de
capteur et diversité de modèles.

Les champs `environment` d'un YAML ne démontrent pas que Unity applique ces
réglages. Développer un adaptateur et enregistrer les valeurs réellement appliquées,
pas seulement demandées.

Le code HDRP 14 local convertit `largeWindSpeed` et `ripplesWindSpeed` depuis des
km/h. Une configuration en m/s nécessite une conversion explicite. Un vent donné
ou un preset nommé `rough` n'est pas automatiquement une mesure d'état de mer ou
de hauteur significative des vagues.

L'eau HDRP est une simulation visuelle pilotée notamment par vent et courant.
Définir et calibrer les presets avant de les utiliser comme conditions scientifiques.
[Simulation d'eau HDRP](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@14.0/manual/WaterSystem-simulation.html).

Une belle surface ne garantit pas une flottaison correcte. Déclarer la bouée
statique du premier test comme simplification. Pour une bouée flottante, choisir
une autorité de mouvement et vérifier l'accord avec l'eau rendue. Une animation
prescrite est un test contrôlé, pas un modèle hydrodynamique validé.

Plan pilote possible : trois distances, trois presets de mer, deux éclairages,
dix captures temporelles par combinaison, soit 180 captures demandées. C'est un
exemple d'organisation, pas une taille statistique démontrée suffisante. Inclure
aussi fonds sans objet et distracteurs.

Faire varier un facteur à la fois pour les premiers diagnostics, puis les croiser.
Des milliers d'images identiques d'une scène fixe ne sont pas autant d'exemples
indépendants.

## 9. Étape E — synchronisation LOTUSim / Unity / capture

Il faut distinguer temps Gazebo, temps Unity, arrivée ROS et état temporel des
vagues/effets. Un numéro d'image commun ne les synchronise pas.

Le connecteur actuel interpole les poses et le script RGB publie un timestamp
nul : ce n'est pas un protocole de capture synchronisée. Le nouveau contrôleur
conservera timestamps de pose, poses réellement appliquées et état Unity.

Deux niveaux :

- Pilote statique : RGB et masque dans le même état Unity. Ne pas annoncer une
  synchronisation exacte avec une simulation dynamique.
- Couplage dynamique : avancer LOTUSim, attendre les poses, appliquer l'état
  Unity et préparer l'eau, capturer, attendre un accusé de fin, puis avancer.
  Contrôle pas à pas, horloge et accusés restent à implémenter.

Entre les passes RGB et masque, ne pas appliquer un nouvel état d'objet ou d'eau.
Attendre lectures GPU et écritures disque. Définir le traitement de l'exposition,
de l'anti-aliasing temporel et du flou de mouvement ; stabiliser ou réinitialiser
leurs historiques après les changements brutaux de scène.

Enregistrer : campagne/capture, frame et temps Unity, timestamps ROS utilisés,
interpolation éventuelle, poses rendues des objets/caméra, paramètres d'eau,
modèles et réglages du rendu. La graine rejoue les choix de paramètres, mais ne
garantit pas des pixels identiques entre matériels.

## 10. Étape F — lancement automatique et cycle de campagne

Le lanceur Mac vérifie configuration, modèles, Docker, builds, ports et espace
disque. Il crée une nouvelle sortie, sans écraser une campagne existante.

### Ordre automatique

1. Démarrer ou vérifier le conteneur.
2. Démarrer le monde LOTUSim et attendre ses services de scénario.
3. Démarrer xDyn si le modèle physique le demande.
4. Démarrer ou vérifier le ROS TCP Endpoint.
5. Démarrer Unity directement en génération, namespace `lotusim`.
6. Attendre connexion et abonnement effectifs aux commandes et poses.
7. Lancer le scénario par ROS, puis attendre les prefabs complètement chargés.
8. Attendre une pose exploitable et un accusé `READY` de la caméra/dataset.
9. Générer, contrôler les sorties et écrire le rapport.
10. Arrêter le scénario, vider les écritures, fermer Unity et les seuls services
    créés par cette campagne.

Le scénario est lancé après l'abonnement Unity et avant la capture. Ne pas se
fier seulement aux événements anciens conservés sur un topic : vérifier scénario,
objets attendus et campagne courante. Après déconnexion, reconstruire un état
connu plutôt que supposer que toutes les créations ont été reçues.

États explicites du lanceur : préparation, services prêts, abonnement, scénario
chargé, objets prêts, capture, export, validation, arrêt. Chaque attente a une
durée maximale et une erreur lisible. `RegisterSubscriber` ne prouve pas que le
prefab est effectivement chargé.

Une passerelle ROS persistante dans Docker évite de relancer Nix pour chaque
capture. Un canal de statut dédié ou des fichiers atomiques peuvent porter les
accusés Unity. Ces interfaces restent à coder.

### Diagnostics déjà disponibles

Depuis le terminal macOS :

```sh
docker exec -it -w /workspace lotusim-dev sh
```

Puis dans le conteneur :

```sh
nix --extra-experimental-features 'nix-command flakes' --option filter-syscalls false develop -c bash
source /workspace/install/setup.bash
ros2 service list
ros2 topic info --verbose /lotusim/renderer_cmd
ros2 topic echo /lotusim/renderer_cmd --qos-durability transient_local
```

L'écho reste actif ; `Ctrl-C` rend le prompt. Une suppression `cmd_type: 1` n'est
pas une création `cmd_type: 0`. L'adresse du prefab doit être non vide et exister.

Les services suivants existent dans `lotusim.world`. Ils modifient la session :
ne les appeler que lorsque son lancement/arrêt est souhaité.

```sh
ros2 service call /lotusim/launch_scenario lotusim_msgs/srv/String "{data: 'TestScenario.yaml'}"
ros2 service call /lotusim/stop_scenario std_srvs/srv/Trigger "{}"
```

Ils contrôlent le test LRAUV actuel, pas la future campagne de bouées. Ne pas
les exécuter à la suite pour une génération : l'arrêt vient après capture ou échec.

### Commande cible — non encore implémentée

Après développement, l'utilisateur lance une configuration et choisit une sortie.
Contrat CLI proposé, **pas une commande disponible aujourd'hui** :

```text
generate-unity-dataset --config buoy-pilot.json --output <nouveau-dossier-de-campagne>
```

Construire l'application avec la scène Dataset en entrée. La capture doit garder
un périphérique graphique : ne pas ajouter `-nographics`. Tester `-batchmode`, les
callbacks de rendu et les lectures GPU sur le build macOS avant d'utiliser un
fonctionnement sans fenêtre ; ne pas supposer que toutes les coroutines de
l'éditeur fonctionneront dans ce mode.
[Arguments du Player Unity](https://docs.unity3d.com/2022.3/Documentation/Manual/PlayerCommandLineArguments.html).

### Échecs et nettoyage

Prefab absent, masque incohérent, déconnexion et écriture incomplète marquent le
job incomplet, avec erreur et code de sortie non nul. Distinguer nombres demandés,
capturés et validés.

Le lanceur n'arrête que ses processus. Pas de redémarrage global de Docker,
d'arrêt global de Unity ou de suppression d'anciennes images comme récupération
automatique. Une reprise utilise identifiants et sorties complètes pour éviter
les doublons.

## 11. Contrat de configuration proposé

Ce JSON illustre la future pipeline ; aucun module actuel ne le lit encore.
Les presets doivent être associés à des réglages concrets et calibrés. Ici,
18 combinaisons et dix captures par combinaison donnent 180 captures demandées,
hors éventuels jobs sans objet.

```json
{
  "schema_version": "1.0-proposed",
  "mode": "lotusim_unity",
  "class_name": "buoy",
  "object_count": 1,
  "seed": 42,
  "namespace": "lotusim",
  "resolution_px": [1280, 720],
  "horizontal_fov_deg": 70,
  "distance_m": [10, 20, 40],
  "sea_presets": ["calm", "moderate", "rough"],
  "lighting_presets": ["day", "backlight"],
  "samples_per_condition": 10,
  "annotation_convention": "visible_bbox_v1",
  "export_format": "coco",
  "thresholds_profile": "not_estimated_yet"
}
```

Enregistrer configuration demandée et configuration résolue/appliquée. Les
seuils non estimés restent identifiés comme tels : un corpus brut n'est pas
automatiquement valide pour l'entraînement.

## 12. Dataset, exports et traçabilité

Créer un dossier par campagne avec RGB bruts, masques, annotations, aperçus,
métadonnées et logs. Un même ID relie les fichiers d'une capture. Les aperçus
ne remplacent jamais les RGB d'entraînement.

Pour COCO : catégories, images et annotations, avec boîte `[x, y, width, height]`
selon la convention choisie. Si une aire est renseignée, préciser si elle vient
du masque ou de la boîte. Garder les masques dans les sorties de travail, même
si le modèle final apprend uniquement des boîtes.

Archiver configuration, graine, versions Unity/HDRP/ROS/Gazebo, modèles, état
des dépôts et modifications locales, caméra, presets, convention et filtre.
Un commit seul ne décrit pas un checkout modifié non commité.

Enregistrer `render_source` pour distinguer Gazebo et Unity et analyser leurs
résultats séparément avant un éventuel mélange pour l'entraînement. Prévoir un
index ou une visionneuse associant chaque image à son annotation.

## 13. Règles d'annotation initiales à discuter et versionner

Proposition à valider avant l'annotation manuelle :

- Une instance reçoit une catégorie, même avec plusieurs sous-meshes.
- La boîte visible encadre les pixels attribuables à l'objet selon la convention ;
  une boîte complète projetée peut rester un diagnostic distinct.
- Ombres, reflets de l'objet et écume environnante ne font pas partie de l'objet
  dans cette convention initiale. Toute autre règle doit être documentée.
- Pour un objet hors champ partiel, garder une boîte découpée au cadre avec
  indicateur de troncature.
- Immersion et occultation ne sont pas assimilées : définir les parties visibles
  à travers l'eau et les pixels fortement atténués.
- Un masque non vide ne prouve pas la reconnaissabilité.
- Conserver les cas ambigus avec leur statut, pas comme annotations certaines.

Un objet entièrement invisible peut n'avoir aucune boîte visible. Mais pour un
objet encore discernable rejeté par un seuil, retirer simplement la boîte crée
un faux négatif : exclure l'image du sous-ensemble d'entraînement concerné ou
utiliser une région ignorée réellement prise en charge par l'outil. Si l'export
ne sait pas représenter cette région, exclure l'image plutôt que simuler ce support.

## 14. Référence manuelle, mesures et filtre de validité

### Référence manuelle

Échantillonner distances, tailles, mer, lumière et occultations. Faire annoter
les RGB sans montrer les masques/boîtes automatiques, avec la même convention
et des définitions de catégorie explicites. Annoter une partie en double, mesurer
les désaccords et consigner les arbitrages et incertitudes.

Séparer les données servant à estimer les seuils de celles servant à les évaluer.

### Mesures

Mesurer IoU après association correcte des instances, erreurs de centre et
dimensions, objets manqués, annotations injustifiées et concordance de catégorie/
reconnaissabilité. Analyser par condition, pas seulement avec une moyenne globale.

Compléter par surface visible en pixels, taille apparente, troncature, immersion
et contraste. Un ratio de visibilité nécessite un dénominateur défini : surface
projetée de référence, dans le cadre ou objet complet. Il ne se déduit pas de
la seule aire de la boîte visible.

### Filtre

Construire un profil versionné de seuils issus de l'étude : taille, visibilité,
contraste, éventuelle dépendance aux conditions. Produire décision, mesures et
raison de rejet. Distinguer erreur technique de masque et image correctement
capturée mais trop ambiguë pour l'usage défini.

Conserver **corpus brut traçable** et **corpus filtré**. Ne pas effacer le brut ou
réestimer les seuils sur le test final. La politique d'images ambiguës doit rester
compatible avec le modèle d'entraînement et l'export.

### Évaluation sur le réel

Séparer entraînement et test par campagne, séquence, configuration et, si possible,
modèle 3D. Des images voisines d'une séquence ne se retrouvent pas des deux côtés.
Ajouter une évaluation indépendante sur le réel. La variation du domaine est
une piste, pas une garantie de succès maritime.
[Recherche simulation → réel](https://arxiv.org/abs/1703.06907).

## 15. Jalons et tests d'acceptation

### Jalon 1 : première capture Unity complète

Une bouée visible produit RGB, masque, boîte non vide, catégorie et métadonnées
cohérentes. Contrôle visuel de l'alignement. Capture et export déclenchés par le
runner, pas un bouton. Ce jalon reste à réaliser dans Unity.

### Jalon 2 : cas limites

Tester occlusions opaque/maritime, immersion, hors-champ, multi-objets, effets
optiques et temporels. Un défaut de masque lié à l'eau bloque la déclaration
de validité des conditions concernées, même si les PNG sont beaux.

### Jalon 3 : génération autonome

Relancer plusieurs campagnes pilotes à configuration figée et état connu.
Vérifier identités, paramètres appliqués, complétude et arrêt propre. Tester
prefab absent, ROS indisponible, déconnexion, pose absente, sortie non inscriptible
et disque insuffisant.

La réussite nécessite un rapport expliquant nombres demandés, capturés, rejetés
et exportés. Le simple nombre de PNG ne constitue pas un rapport de succès.

### Jalon 4 : conformité au sujet complet

Bibliothèque complète, capteurs Gazebo, protocole manuel et filtre doivent être
livrés ou leur adaptation validée par l'encadrant. Une bonne première capture
ne signifie pas que le travail complet est terminé.

## 16. Plan de développement recommandé

1. Faire valider l'architecture à deux volets et la convention d'annotation.
2. Créer prefab de bouée et scène Dataset, sans changer la scène interactive.
3. Tester le moteur de masques avec l'eau avant de généraliser son intégration.
4. Développer capture appariée et export local pour une image.
5. Ajouter runner, contrôle des paramètres et statuts de campagne.
6. Intégrer au scénario LOTUSim et valider la synchronisation.
7. Ajouter lanceur unique, arrêt propre et tests d'échec/reprise.
8. Générer le pilote, annoter la référence manuelle et estimer le filtre.
9. Étendre classes/conditions et conserver/étendre les capteurs Gazebo.
10. Évaluer corpus et transfert sur des images réelles indépendantes.

Modules proposés à créer : `DatasetRunner`, `DatasetLabel`,
`DatasetEnvironmentController`, `DatasetCapture`, `DatasetExporter`, pont de
synchronisation LOTUSim. Côté Mac : lanceur, validation des sorties et filtre.
Le script RGB actuel ne devient pas responsable de tous les services, de la
physique et de l'étude scientifique.

Livrables attendus : catalogue de modèles intégré, code et configurations de
génération, démonstration des capteurs Gazebo, pilote Unity, guide d'annotation,
référence manuelle, rapport de comparaison, profil de seuils et filtre exécutable.
Les scripts de reconstruction et d'export doivent accompagner le corpus pour
qu'il soit réutilisable, pas seulement consultable sous forme de PNG.

## 17. Refaire le test Gazebo déjà disponible

Ce test fonctionne et reste indépendant de la future pipeline Unity. Terminal
macOS :

```sh
docker exec -it -w /workspace lotusim-dev sh
```

Puis dans le conteneur :

```sh
nix --extra-experimental-features 'nix-command flakes' --option filter-syscalls false develop .#software-rendering -c bash
mise run capture:buoy
```

Arrêter avec `Ctrl-C`. PNG et CSV sont sous `/workspace/artifacts/annotated-buoy/`,
dans le dépôt partagé sur le Mac. Le lanceur maintient l'abonné nécessaire au
capteur dans cette version. Ces images ne viennent pas de Unity.

Parcourir les résultats existants depuis un terminal macOS :

```sh
open "/chemin/projets/LOTUSim/artifacts/annotated-buoy/images"
open "/chemin/projets/LOTUSim/artifacts/annotated-buoy/preview.png"
```

RGB bruts dans `images`, annotations dans les CSV associés ; `preview.png` est
un aperçu annoté distinct, pas celui de chaque image.

## 18. Sources et observations locales

- [Wiki LOTUSim — Unity Development](https://github.com/naval-group/LOTUSim/wiki/unity-development) : rôle des scènes, interfaces et caméra RGB.
- [Capteur Gazebo Sensors 8](https://github.com/gazebosim/gz-sensors/blob/gz-sensors8/src/BoundingBoxCameraSensor.cc) : sauvegarde et formats du prototype.
- [Tutoriel Gazebo Bounding Box Camera](https://github.com/gazebosim/gz-sensors/blob/main/tutorials/boundingbox_camera.md) : référence générale ; vérifier la version avant de recopier les exemples.
- [Eau HDRP 14](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@14.0/manual/WaterSystem-simulation.html).
- [Custom Pass HDRP 14](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@14.0/manual/Custom-Pass.html).
- [Unity Perception](https://github.com/Unity-Technologies/com.unity.perception) et [limites](https://github.com/Unity-Technologies/com.unity.perception/blob/main/com.unity.perception/Documentation~/PerceptionCamera.md).
- [Arguments Player Unity 2022.3](https://docs.unity3d.com/2022.3/Documentation/Manual/PlayerCommandLineArguments.html).

Les constats d'installation viennent aussi du parser LOTUSim, des services de
scénario, du connecteur de poses, du script RGB et du code WaterSurface local.
Cette documentation ne modifie ni ces sources ni les scènes existantes et ne
valide pas un exporteur Unity encore absent.
