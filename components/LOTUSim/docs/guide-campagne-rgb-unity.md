# Première campagne RGB annotée automatiquement — bouée, LOTUSim et Unity

Poste : macOS, Unity 2022.3.18f1 / HDRP 14.0.10 natifs ; LOTUSim/ROS 2 dans `lotusim-dev`.

Cette campagne enregistre **432 images RGB**, avec leurs paramètres et désormais des **masques d'instance, boîtes et exports COCO/YOLO**. La règle initiale est **géométrique** : l'eau est traitée comme un occultant pour les labels, même si une partie immergée reste perceptible dans le RGB. Ce n'est pas encore une validation de reconnaissabilité. Depuis le 14 octobre, le modèle de bouée suit visuellement la houle Unity : montée/descente et inclinaison amorties. Sa position d'amarrage reste fixe dans LOTUSim. **Ce flottement cinématique n'est pas une simulation hydrodynamique Gazebo.**

## 1. Ce qui a été ajouté

- Une scène `Assets/Scenes/Dataset/BuoyDatasetPilot.unity`, indépendante de la scène interactive.
- Une scène de test `Assets/Scenes/Dataset/BuoyDatasetSmoke.unity` : une image, sans ROS ni Docker.
- Une configuration `Assets/Dataset/BuoyPilot.asset` et une configuration de test `BuoySmoke.asset`.
- Un scénario LOTUSim `assets/scenarios/BuoyDatasetPilot.yaml`, avec la seule instance `Buoy_001`.
- Un menu **LOTUSim → Dataset** et une fenêtre de suivi.

Les scènes/configurations sont créées par le générateur d'éditeur après importation des scripts. Le générateur ne remplace pas une scène/configuration déjà présente. Il copie uniquement le décor maritime depuis `defenseScenario`, sans enregistrer de modification dans cette dernière. La scène Dataset ne contient ni Launcher, ni Photon, ni Leap, ni HUD, et possède une seule caméra et un seul connecteur logique LOTUSim.

## 2. Vérifier d'abord une seule image

1. Quitter le mode Play dans Unity.
2. **Assets → Refresh**, attendre la compilation.
3. **LOTUSim → Dataset → 1 - Create pilot scenes** si les scènes ne sont pas encore créées.
4. **LOTUSim → Dataset → 2 - Open one-image smoke test (no ROS)**.
5. Accepter ou annuler la demande de sauvegarde des scènes ouvertes selon les modifications que tu souhaites conserver.
6. Cliquer sur **Play**, sans activer Pause.
7. Regarder **LOTUSim → Dataset → 4 - Campaign monitor**. La caméra rend vers une texture dédiée ; la fenêtre Game n'est pas la référence de capture. Le suivi et son texte ne sont jamais dans les images.
8. Attendre `complete`, puis ouvrir le dossier indiqué dans le suivi.

La sortie du test est dans le projet Unity : `artifacts/dataset-smoke/buoy_<dateUTC>_<identifiant>/`. Ouvrir `index.html` pour voir l'aperçu annoté (boîte verte, contour jaune, libellé « bouée » au-dessus) et les liens RGB/masque/paramètres. Vérifier bouée, eau, ciel, cadrage, couleurs, alignement du masque et absence de texte/HUD dans le RGB avant la campagne complète. Ce mode est identifié `LocalPreview` dans les métadonnées ; ce n'est pas un test du couplage ROS.

## 3. Lancer les 432 images avec LOTUSim

Préparer LOTUSim comme dans le guide de démarrage : conteneur accessible, monde `lotusim.world` démarré et ROS TCP Endpoint sur le port 10000. xDyn n'est pas nécessaire : LOTUSim maintient l'ancre, Unity anime le visuel. Garder leurs terminaux ouverts pour les logs.

Le scénario doit être visible dans `/workspace/assets/scenarios/BuoyDatasetPilot.yaml` depuis le conteneur. Le service actuel cherche un **nom de fichier relatif** dans `LOTUSIM_SCENARIOS_PATH`, et non un chemin absolu dans la requête.

Ne pas lancer manuellement ce scénario avant Unity : le pilote le lance après l'abonnement ROS. Aucun autre scénario ne doit être actif. S'il y en a un, le pilote échoue avec une explication et ne l'arrête pas automatiquement.

Ensuite :

1. Quitter le mode Play du test.
2. **LOTUSim → Dataset → 3 - Open 432-image LOTUSim pilot**.
3. Cliquer sur **Play**.
4. Ouvrir le suivi et laisser la campagne tourner, sans Pause et sans arrêter LOTUSim.

Le pilote utilise la connexion existante, configurée par les préférences ROS (`127.0.0.1:10000` par défaut), et le namespace `lotusim`. Il attend une connexion effective, lance `BuoyDatasetPilot.yaml`, puis attend le prefab et une pose ROS de `Buoy_001`.

Il parcourt ensuite toutes les combinaisons. Les changements sont appliqués dans Unity ; le YAML d'environnement ne pilote pas automatiquement le rendu Unity.

Après les captures, il vérifie les fichiers RGB/métadonnées/annotations, crée l'index COCO et la galerie, puis demande l'arrêt **uniquement du scénario qu'il a lui-même lancé**. `complete` signifie 432 captures complètes et, si demandé, arrêt confirmé. `complete_cleanup_unconfirmed` signifie que le dataset est complet mais qu'il faut vérifier l'arrêt de LOTUSim avant de relancer. Les annotations restent à valider scientifiquement.

## 4. Valeurs de la campagne

| Facteur | Valeurs |
| --- | --- |
| Objet | Une bouée, `Buoy_001`, catégorie `buoy`, classe 1 |
| Distance caméra–point visé | 10, 25, 50 m |
| Azimut, repère Unity | 0°, 90°, 180°, 270° |
| Élévation de caméra au-dessus du point visé | 5°, 20° |
| Mer visuelle | `calm`, `moderate`, `rough` |
| Lumière | `front`, `backlight` |
| Captures par combinaison | 3, espacées de 1 seconde simulée |
| Résolution | 1280 × 720 |
| Champ de vision | 50° vertical |
| Stabilisation | 60 rendus avant chaque combinaison |
| Petits mouvements de caméra | Roulis ≤ ±1,5° et tangage ≤ ±0,8° en mer forte |

3 × 4 × 2 × 3 × 2 = **144 combinaisons** ; × 3 = **432 images**.

Les trois mers sont des **presets non calibrés**, pas des hauteurs de vague annoncées en mètres :

| Preset | Vent lointain km/h | Multiplicateurs bandes 0/1 | Vent rides km/h | Écume |
| --- | --- | --- | --- | --- |
| calm | 0 | 0 / 0 | 2 | 0 |
| moderate | 35 | 0,7 / 0,6 | 10 | 0,20 |
| rough | 70 | 1 / 0,9 | 18 | 0,50 |

Les zones de répétition sont respectivement 128, 192 et 256 m. Le preset `rough` utilise davantage les grandes bandes et un vent plus fort pour accentuer la houle. Pour revendiquer une hauteur significative ou un état de mer mesuré, une calibration distincte reste nécessaire. La hauteur ponctuelle interrogée près de la bouée ne constitue pas une mesure de hauteur significative. L'interrogation CPU utilise la résolution complète, mais exclut les petites rides : elles restent visibles sans agiter artificiellement la bouée à haute fréquence.

### Flottement et aperçu rapide

Hors Play : **Assets → Refresh**, puis **LOTUSim → Dataset → 5 - Open floating buoy wave test (no ROS)** et **Play**. Ouvrir **4 - Campaign monitor** : ce test crée sa propre bouée sans Docker ni ROS, puis capture 12 images (4 par mer) à 6 m. Les fichiers sont dans `artifacts/dataset-waves/buoy_<dateUTC>_<identifiant>/index.html`. Le mode `LocalPreview` reste identifié dans les fichiers ; il ne valide pas le couplage LOTUSim.

Le contrôleur `BuoyWaveMotion` interroge cinq points de l'eau (centre et quatre points autour du flotteur, rayon 0,35 m). Il suit la hauteur moyenne et la pente locale, avec une réponse amortie et une inclinaison limitée à 25°. Il déplace uniquement `MarineBuoyVisual_v1` : ROS continue à contrôler la racine `Buoy_001`, sans concurrence entre les deux. Aucun Rigidbody, dérive horizontale, effort d'amarrage ou interaction bouée→eau n'est simulé. La chaîne immergée fait partie du visuel : elle n'est pas une chaîne mécanique articulée.

La **position** de caméra reste fixe pour chaque combinaison, autour du point de visée moyen. Dans le cycle principal, sa **rotation** reçoit désormais de petites oscillations de roulis/tangage ; elle ne poursuit pas les oscillations de la bouée. La distance réellement obtenue et le point de visée visuel sont enregistrés : ils peuvent donc différer légèrement de la distance demandée. Une forte vague peut masquer la bouée ou passer devant la caméra basse ; c'est une image possible de la campagne, pas une erreur de rendu.

### Cycle principal : houle renforcée et légère instabilité de caméra

La configuration existante `Assets/Dataset/BuoyPilot.asset` conserve **432 images** : 3 distances × 4 azimuts × 2 élévations × 3 mers × 2 éclairages × 3 captures. Les mers `moderate` et `rough` sont déjà celles de l'aperçu à grosses vagues (vents HDRP 35/70 km/h et zones 192/256 m). La référence calme est conservée pour comparaison. Le flottement, l'immersion à -0,15 m, l'eau absorbante et la lampe clignotante s'appliquent aussi à ce cycle principal.

Le groupe `Camera Motion` active un mouvement angulaire **synthétique**, lisse, sans secousses aléatoires par image : maxima de ±1,5° en roulis et ±0,8° en tangage, périodes de base de 5,5 s et 7 s. Les maxima sont multipliés par `Camera Motion Scale` du preset de mer : 0,15 en calme, 0,65 en modérée, 1 en forte. Les phases sont déterminées par la graine et l'identifiant de combinaison. Le mouvement utilise le temps Unity, se fige en Pause et se remet autour de la nouvelle vue nominale à chaque combinaison. Il s'applique avant que HDRP calcule les matrices de caméra, pour que le RGB et les poses/matrices enregistrées restent cohérents.

Les tests d'une image et des vagues ont `Camera Motion → Enabled` désactivé pour conserver leur cadrage de contrôle. On peut l'activer volontairement sur leurs configurations. Désactiver cette option dans le pilote retrouve la caméra fixe. Ces oscillations ne sont pas mesurées sur l'eau ni reçues d'un bateau réel/simulé : elles évoquent seulement une caméra légèrement instable à bord. Aucun bateau observateur, déplacement de vaisseau, pilonnement ou mouvement physique supplémentaire n'est implémenté ici.

Pour exécuter le cycle principal : quitter Play, **Assets → Refresh**, garder LOTUSim et ROS TCP actifs, ouvrir **3 - Open 432-image LOTUSim pilot**, puis Play et **4 - Campaign monitor**. Le pilote lance son propre scénario ; ne pas lancer manuellement une seconde instance. Les nouveaux réglages ne modifient pas les anciennes images.

Pour modifier le mouvement, sélectionner `Assets/Dataset/BuoyPilot.asset` (ou `BuoyWaves.asset`) et ouvrir `Flotation` dans l'Inspector : `Enabled` désactive le mouvement pour retrouver une référence statique ; `Waterline Offset M` ajuste l'immersion ; `Max Tilt Deg` limite le roulis/tangage ; les deux `Response Per Second` règlent la vitesse de réponse. Une réponse plus faible donne un mouvement plus lent. La valeur d'immersion reste une convention visuelle, pas un résultat de poussée d'Archimède.

La bouée est maintenant abaissée de **15 cm** (`Waterline Offset M = -0.15`) par rapport à la surface interrogée. Le signe négatif descend le **visuel** : il ne modifie ni l'ancre ROS ni le calcul hydrodynamique. Les vagues peuvent ainsi recouvrir davantage le flotteur.

### Eau plus absorbante et lanterne clignotante

L'océan hérité du décor avait une distance d'absorption de 75 m, laissant très visibles les objets proches sous l'eau. Le pilote applique désormais les valeurs de `Water Optics` : distance d'absorption **0,8 m**, distance maximale de réfraction **0,6 m**, couleurs de réfraction/diffusion bleu-vert. Une distance d'absorption plus faible rend la partie immergée moins visible. Ce n'est ni un alpha uniforme de l'eau, ni une couleur appliquée à toute la bouée : HDRP atténue la lumière sur le trajet sous l'eau, en fonction de la profondeur et de la vue. Ces valeurs restent un preset visuel de mer trouble, pas une mesure réelle de turbidité. [Propriétés d'eau HDRP 14](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@14.0/manual/WaterSystem-Properties.html).

Dans `Lantern`, un flash ambre dure **0,25 s toutes les 2 s**, avec des transitions de 0,03 s. Le contrôleur `BuoyLanternFlash` anime uniquement l'émission de la lentille `AmberFresnelLens`, par instance, et une petite lumière ponctuelle de **3 lumens** à portée de 2 m. Le multiplicateur d'émission est réduit de 12 000 à **1 000** pour limiter l'éblouissement. Les matériaux partagés du prefab ne sont pas modifiés. L'intensité HDR de la lentille est un réglage visuel, pas une puissance de feu de navigation certifiée ; aucune conformité IALA n'est revendiquée. `Enabled` désactive ce feu dans les scènes Dataset ; `Period Seconds`, `Flash Seconds`, `Phase Offset Seconds` et les intensités règlent son comportement. Le temps utilisé est celui d'Unity : Pause arrête la cadence.

Ces réglages sont appliqués aux trois configurations existantes (pilote, test d'une image, aperçu des vagues), sans régénérer leurs scènes ni arrêter le serveur ROS. Après changement : quitter Play, **Assets → Refresh**, puis relancer l'aperçu **5**. Les nouvelles images sont écrites dans un nouveau dossier ; aucune ancienne capture n'est modifiée. Observer le suivi pendant Play pour voir le flash : une image unique peut tomber pendant l'intervalle éteint. Un intervalle d'échantillonnage régulier peut également sous-échantillonner la cadence ; ne pas déduire le rythme d'un feu de quelques PNG.

Le HDRP utilisé et l'océan doivent activer **Script Interactions**. Le pilote configure l'océan et vérifie le support CPU de l'asset. La requête est faite avant le rendu de la caméra, après la mise à jour de l'eau HDRP 14. Il ne capture pas une image si les cinq recherches de hauteur sont indisponibles/non convergentes ; une attente trop longue produit un diagnostic. Les masques d'eau sont refusés pour ce mode, car le calcul CPU HDRP 14 ne les applique pas. [Référence Unity HDRP 14](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@14.0/manual/WaterSystem-scripting.html).

L'éclairage est lié à l'azimut caméra : soleil du côté caméra à 45° / 80 000 lux pour `front`, de l'autre côté à 12° / 30 000 lux pour `backlight`. Le ciel physiquement basé suit ce soleil. Les expositions fixes sont respectivement EV100 13 et 12,5. Il n'y a pas d'exposition automatique qui annule involontairement les variations de luminosité.

Le temps de capture est fixé à 30 images par seconde simulée. La durée réelle dépend du GPU et des lectures/écritures ; ne pas attendre nécessairement 30 images/s en temps réel. Les 432 fichiers ne sont pas 432 observations statistiquement indépendantes.

## 5. Où sont les fichiers ?

Dans le **projet Unity sur le Mac**, pas dans Docker :

```text
artifacts/datasets/buoy_<dateUTC>_<identifiant>/
  requested-config.json
  provenance.json
  status.json
  index.html
  rgb/
    c0000_s00.png
    ...
  metadata/
    c0000_s00.json
    ...
  masks/              # binaire : géométrie visible, eau occultante
  amodal/             # silhouette de la cible sans occultants, limitée à l'image
  overlays/           # aperçu annoté ; le RGB original n'est pas dessiné dessus
  labels/             # fichiers texte YOLO, indice de classe 0 = buoy
  annotations/        # JSON détaillé de chaque capture
  annotations.coco.json
  classes.txt
  class-map.json
  review-required.txt
```

`status.json` décrit la progression, les erreurs, le nombre demandé/enregistré, les identifiants complets et l'état de l'arrêt du scénario. Les écritures passent par un fichier `.partial` puis une publication atomique. Une nouvelle exécution crée un nouveau dossier : elle ne remplace pas une campagne précédente. Cette version ne reprend pas automatiquement une campagne interrompue.

Chaque JSON d'image contient identité, classe, paramètres demandés et appliqués, caméra/objet, matrices de vue/projection, temps/frame Unity et dernier timestamp de pose ROS disponible. La distance est mesurée au **point visé sur le corps de la bouée**, également enregistré, et non à son point d'amarrage immergé.

Les vecteurs et poses sont en mètres dans le repère Unity Y-up. Les matrices sont sérialisées dans l'ordre de l'indexeur Unity `Matrix4x4` (colonnes). Le timestamp ROS est une provenance de pose, **pas une preuve de synchronisation pas à pas avec Gazebo**. L'ancre ROS est vérifiée fixe pendant la campagne ; le modèle visuel peut osciller avec l'eau.

Le schéma d'image est désormais `lotusim-rgb-frame-2` : `targetPosition`/`targetRotation` sont la pose **visuelle rendue**, tandis que `anchorPosition`/`anchorRotation` sont la pose de racine reçue de LOTUSim. Les champs `motionModel`, `flotationRequested`, `flotationSampleUnityFrame`, hauteur moyenne, heave, inclinaison, normale de surface et erreur de recherche décrivent le mouvement. Le numéro de frame de la recherche correspond au RGB capturé. Les anciens JSON ne sont pas réécrits.

Les champs additionnels `waterOpticsRequested`/`waterOpticsApplied` enregistrent les réglages optiques. `lanternRequested`, `lanternOn`, `lanternLevel`, `lanternPhaseSeconds`, `lanternLightLumens` et `lanternSampleUnityFrame` enregistrent l'état effectivement appliqué à la lentille/lumière pour ce rendu. Cela ne garantit pas que la lanterne est visible dans l'image : une vague peut la masquer.

`cameraMotionModel` distingue `fixed` et `synthetic_small_angle_sway`. Les paramètres demandés, la pose nominale, les angles locaux réellement appliqués (`cameraPitchDeg`, `cameraRollDeg`), le facteur de mer, le temps du mouvement et le numéro de frame sont enregistrés. `cameraPosition`/`cameraRotation` et les matrices restent les valeurs effectives de capture. Les captures ne sont pas ajoutées comme une dimension de plan supplémentaire : les trois répétitions de chaque combinaison utilisent des instants différents de ce mouvement.

## 6. Changer les paramètres

Sélectionner `Assets/Dataset/BuoyPilot.asset` **hors Play** et éditer ses listes dans l'Inspector. Une copie de la configuration est figée au démarrage ; les changements pendant Play ne modifient pas la campagne en cours.

Les paramètres invalides, dupliqués ou non finis sont refusés. Le nombre total découle des listes et du nombre de captures. Le mélange facultatif `shuffleConditions` est déterministe avec `seed` ; avec le mélange désactivé, l'ordre est fixe. La graine ne garantit pas un rejeu des pixels ni une phase identique de l'océan entre machines/exécutions.

Changer de modèle nécessite une configuration et un scénario correspondants. Désactiver `Flotation` **et** `Lantern` pour un objet qui n'est pas la bouée réaliste. Ce pilote reste limité à une seule cible amarrée ; les scènes multi-objets et les cibles navigantes viendront ensuite.

## 7. Arrêt et diagnostic

- En cas de perte de connexion, de disparition/mouvement de l'ancre ROS, d'échec prolongé du calcul de l'eau ou de problème de capture, la campagne passe à `failed` et conserve les paires déjà écrites. Le flottement visuel ne déclenche pas l'erreur de cible statique.
- Quitter Play annule la campagne (`cancelled`) et restaure les réglages temporaires de pipeline/temps. L'arrêt du scénario détenu est demandé si possible ; à la sortie de Play, le transport peut disparaître avant confirmation. Vérifier alors LOTUSim et `status.json` avant de relancer.
- `Scenario already running` : aucun scénario existant n'a été arrêté. Arrêter le scénario courant volontairement dans LOTUSim, puis repartir dans une nouvelle session Play.
- `waiting_for_ros` : contrôler le serveur TCP et le namespace ; des tentatives de reconnexion ne suffisent pas à établir une réception effective.
- `waiting_for_object` : vérifier le YAML, la clé Addressables `buoy`, l'apparition de `Buoy_001` et les poses ROS.
- Si le lancement répond positivement mais que les poses restent vides : vérifier les modules natifs LOTUSim, pas seulement Unity. Le correctif du 13 octobre place les opérations des services de scénario dans `MultiAgentSystem::PreUpdate` et détecte les créations/suppressions dans `RenderPlugin::Update`, après les créateurs. Une ancienne bibliothèque déjà chargée dans Gazebo ne bénéficie pas d'une modification de source : compiler puis redémarrer le monde.
- Une vue Game vide n'implique pas une absence de capture : regarder le suivi, qui affiche la texture dédiée.
- `CreateImpl is not allowed ... BuoyLanternFlash`, puis `Value cannot be null (dest)` : ancienne initialisation de `MaterialPropertyBlock` dans les champs du composant. Le correctif crée ces objets natifs dans `Awake`/`Configure`, y compris si la bouée est configurée avant activation. Quitter Play, **Assets → Refresh** puis relancer le test 5. Aucun changement ROS ou Docker n'est nécessaire.
- `status.json` conserve désormais la pile complète dans `errorDetails` ; la console affiche aussi l'exception d'origine au lieu du seul message final.
- `All images saved, but stopping ... timed out` dans une ancienne campagne : ses captures sont conservées. Le message `std_srvs/Trigger` fourni par le connecteur omettait l'octet nécessaire pour une structure vide ROS 2 ; le décodeur Fast DDS rejetait la requête. `DatasetTriggerRequest` sérialise désormais la requête complète, vérifiée avec ROS 2 Jazzy. Le pilote ne lance qu'une demande d'arrêt, sans multiplier les appels en cas d'attente. Un nettoyage non confirmé est signalé comme avertissement, avec `capturesComplete=true`, pas comme une perte de dataset. Si l'ancien scénario est toujours actif, quitter Play et l'arrêter volontairement avec `ros2 service call /lotusim/stop_scenario std_srvs/srv/Trigger '{}'`, puis relancer le pilote.

Tests supplémentaires : **LOTUSim → Dataset → Validate campaign planning**. Le test d'une image reste indispensable pour le chemin de rendu réel.

Le menu **Validate lantern Unity lifecycle (in Play)** ajoute brièvement des objets de test indépendants puis les supprime. Il vérifie avec le véritable `AddComponent` Unity la création sur un objet actif/inactif, la configuration, le flash, la préservation du matériau partagé et la restauration des paramètres à l'arrêt. Les tests de cadence seuls ne détectent pas les appels natifs interdits dans un constructeur.

### Recompiler le correctif natif

Dans un shell Nix du conteneur, **après avoir arrêté le monde Gazebo** :

```bash
cd /workspace
source /workspace/install/setup.bash
colcon build --merge-install --packages-select lotusim_mas render_interface_plugin
source /workspace/install/setup.bash
mise run sim lotusim.world
```

Ne pas utiliser `mise run clean` ou `rebuild` pour ce correctif : les deux modules suffisent, sans supprimer l'installation. Garder le serveur ROS TCP du terminal 4. Dans Unity, quitter Play, faire **Assets → Refresh**, puis rouvrir le pilote et cliquer Play, sans lancer manuellement son scénario.

Test natif automatisé disponible : `scripts/test_dataset_scenario_lifecycle.py --plugin-dir <dossier-des-bibliotheques> --cycles 8`. Il démarre et arrête son propre monde, utilise le domaine ROS 96 et une partition Gazebo unique, et vérifie pour chaque cycle CREATE, pose, refus d'un lancement concurrent et DELETE. Il ne contrôle pas la session ROS habituelle.

Gazebo précise que la détection `EachNew` doit se faire après les créations de
`PreUpdate`, dans `Update` ou une lecture const en `PostUpdate`.
[Référence de l'EntityComponentManager](https://gazebosim.org/api/sim/8/classgz_1_1sim_1_1EntityComponentManager.html).

## 8. Annotations automatiques : règle et limites

`Annotations → Enabled` est activé dans les configurations pilote, test d'une image et vagues. Il n'y a pas de manipulation manuelle des matériaux/caméras : la passe se crée à l'exécution et ne vise que la cible attendue. Elle nécessite les Custom Pass HDRP et des MeshRenderer opaques non alpha-découpés ; les matériaux transparents, végétations alpha-test et SkinnedMeshRenderer ne sont pas couverts par cette première version.

La passe dessine la **géométrie des meshes**, pas les coins de leur boîte 3D. Le masque visible est testé contre le depth buffer HDRP, après le GBuffer de l'eau : terrain, objets opaques et vagues devant la cible retirent des pixels. Une seconde passe fournit la silhouette de la cible sans les occultants, limitée au cadre. La capture lit RGB et masques dans le même rendu, avec la même caméra/pose/frame, sans avance temporelle entre eux.

**Convention initiale importante** : une surface d'eau plus proche est un occultant opaque pour les labels (`nearest_depth_water_is_opaque`). Les pixels réfractés, les parties perçues à travers l'eau, les reflets et le halo de la lampe ne sont pas inclus. L'écume n'est pas une classe d'objet. Le masque décrit une visibilité géométrique, pas un seuil optique de transmittance ou la reconnaissabilité de l'objet. Pour rendre ces cas exploitables scientifiquement, comparer ce choix à l'annotation manuelle et étudier/refaire le traitement de la transparence, de la réfraction et des reflets. [Custom Pass HDRP](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@14.0/manual/Custom-Pass-Scripting.html).

La boîte est serrée autour des pixels du masque visible. Les coordonnées sont en pixels, origine **en haut à gauche**, format COCO `[x,y,width,height]`. Les masques PNG ont noir=0/fond et blanc=255/cible. L'export COCO inclut `area` et une segmentation RLE **non compressée**, colonne par colonne selon la convention COCO. Les labels YOLO utilisent centre et dimensions normalisés, indice **0** pour la classe `buoy`, distinct du `category_id=1` COCO. `class-map.json` explique la correspondance. Ce sont des exports de labels : aucune séparation train/validation/test ni configuration d'entraînement YOLO n'est créée ; préparer la disposition des images/labels et séparer les groupes de conditions avant entraînement.

Les aperçus dans `overlays/` portent le **nom de classe « bouée » au-dessus de la boîte**, en blanc sur fond sombre. Au bord supérieur, le cartouche est déplacé sous la boîte ou à l'intérieur du cadre pour rester lisible. Les accents sont pris en charge sans ajouter de caméra/UI au rendu. Un objet sans pixel visible ne reçoit ni boîte ni texte. Les RGB et les masques restent sans texte ; le cartouche ne modifie ni les coordonnées ni l'aire de l'objet.

Le JSON d'annotation et les métadonnées conservent `category: "buoy"` et `instance: "Buoy_001"`, avec le champ supplémentaire `displayName: "bouée"`. Les catégories COCO et `class-map.json` portent également ce libellé, sans changer les noms/indices de classe machine existants. `overlayLabelBox` décrit uniquement le cartouche d'aperçu, en pixels `[x,y,width,height]`, **pas une boîte d'objet à entraîner**. Dans `Annotations → Display Name`, un libellé facultatif peut remplacer le nom automatique ; laisser vide pour utiliser la correspondance française de la classe. Les autres correspondances prévues sont `airplane` → avion, `helicopter` → hélicoptère, `small_drone` → drone et `seagull` → mouette. Cela ne rend pas le pilote multi-objets : celui-ci capture encore une seule cible.

Les JSON par capture indiquent pixels visibles, pixels de silhouette dans le cadre, ratio géométrique, boîte, proximité du bord et règle d'annotation. Une cible totalement cachée ne reçoit pas de boîte/segmentation COCO et son fichier YOLO est vide. Les fichiers de masque/aperçu et le JSON existent quand même pour examiner ce cas.

Les seuils de révision par défaut sont **16 pixels visibles** et **2 pixels de côté de boîte**. Ce sont des seuils provisoires de signalement, pas des seuils scientifiques de validité. `review-required.txt` liste les images sans pixels de cible ou avec une cible trop petite ; les petites annotations restent dans les exports bruts au lieu de transformer silencieusement un objet présent en négatif. La luminosité/contraste ne sont pas évalués : même une image non signalée peut être inexploitable. Le ratio est calculé dans le cadre et ne mesure pas la partie hors image ; le drapeau de bord n'est qu'une alerte de troncature potentielle.

Tests : **Validate annotation coordinates and RLE** vérifie origine, dimensions inclusives, normalisation YOLO et RLE. Les essais GPU isolés sur Metal/HDRP 14 ont vérifié cible non occultée, occultation partielle par objet, occultation par eau plane, bouée dans une grosse houle et cible totalement occultée. La correspondance PNG/boîtes/RLE/YOLO a été contrôlée sur ces fichiers. Faire ensuite le test d'une image dans le décor réel avant les 432 captures.

Les tests de libellé vérifient en plus son placement, l'accent de « bouée », les bords de l'image, l'absence de texte pour une cible masquée et la conservation de la boîte d'objet.

**Les anciens PNG ne sont pas annotés rétroactivement.** Leurs positions/matrices ne suffisent pas à reconstruire exactement l'état GPU de l'eau et ses occultations. Relancer la capture produit un nouveau dossier RGB + annotations, sans toucher aux images précédentes.

Conserver le volet capteurs d'annotation Gazebo exigé par le sujet, la comparaison manuelle et l'étude des seuils de validité. Ce pilote annoté Unity ne remplace pas ces étapes.

Un mode séparé de caméra mobile et rencontres multi-objets est décrit dans le [guide du randomizer maritime Unity](guide-randomizer-maritime-unity.md). Il ne modifie pas ce pilote et utilise pour l'instant des trajectoires Unity, sans ROS.
