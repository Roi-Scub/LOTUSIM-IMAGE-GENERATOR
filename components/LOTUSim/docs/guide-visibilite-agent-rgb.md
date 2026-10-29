# Visibilité, NR / PR / R et agent RGB indépendant

## Lancer et regarder

Garder LOTUSim et le serveur ROS TCP existant. Dans Unity, quitter Play, attendre
la compilation, rouvrir `LOTUSim → Dataset → Cooperative traffic →
1 - Generate and open all-model scenario`, puis Play. Les captures suivantes
contiennent les nouveaux libellés ; les campagnes existantes ne sont pas écrasées.

Dans **Dataset — suivi**, `Ouvrir la galerie` affiche la vérité géométrique Unity.
Une étiquette devient par exemple `voilier 38.4% PR`, sans numéro de suivi dans
l'image. Les identifiants restent dans le JSON pour suivre les objets.

L'agent visuel indépendant démarre après la fin de la campagne de trafic dans
l'éditeur. Il travaille en arrière-plan ; son résultat n'est pas immédiat.
`Ouvrir les prédictions de l'agent` ouvre sa galerie séparée. Le bouton
`Analyser les RGB avec l'agent indépendant` permet aussi un lancement manuel.

Menu `LOTUSim → Dataset → RGB observer` :

- `Automatic analysis after traffic sequence` : activer/désactiver le démarrage
  après capture, activé par défaut pour `MaritimeTrafficAgents` uniquement.
- `Pass RGB through Gazebo Transport` : passage par un canal RGB Gazebo isolé,
  activé par défaut. Ne crée aucun autre client ROS TCP Unity.
- `Analyze an existing capture folder` : choisir une campagne contenant `rgb/`.

Le serveur Docker doit rester ouvert pour le passage Gazebo. En mode direct RGB,
le détecteur local n'a besoin ni de Gazebo, ni du simulateur, ni de ROS.

## Ce que signifie le pourcentage

Le masque visible est testé contre la profondeur réelle de la caméra au même
rendu. Un navire au premier plan, le pont de l'observateur et l'eau masquent
les fragments plus éloignés. La politique d'annotation traite l'eau comme opaque,
même si une réfraction RGB peut laisser deviner un fragment immergé.

`visiblePercent = 100 × visiblePixels / amodalPixelsInFrame` : dénominateur =
silhouette projetée **dans le cadre**, calculée sans occluder. Ce n'est PAS le
pourcentage de la surface 3D totale du modèle, ni la fraction du modèle hors champ.
`occludedPercent` est son complément lorsque cette silhouette est non vide.
Le drapeau `truncatedInFrame` signale une silhouette touchant le bord du cadre.

Un objet entièrement caché reste dans `activeObjects` avec 0 pixel et un statut
NR / `fully_occluded`, mais n'a aucune boîte visible. Une silhouette vide est
notée `outside_frame_or_subpixel` : ne pas prétendre distinguer ces deux causes.
Un fragment de deux pixels a une boîte géométrique, mais est NR, même à 100 %.

## Règles initiales, non validées humainement

| Niveau | Couleur | Conditions initiales, toutes requises |
| --- | --- | --- |
| NR | rouge | Une condition du niveau PR manque |
| PR | jaune | ≥ 32 pixels visibles, petit côté ≥ 4 px, fraction visible ≥ 10 %, contraste RGB local ≥ 0,025 |
| R | vert | ≥ 256 pixels visibles, petit côté ≥ 12 px, fraction visible ≥ 65 %, contraste ≥ 0,08, sans troncature au bord |

Le contraste est une différence RMS de luminance sRGB normalisée entre les pixels
visibles et la moyenne d'une couronne de fond autour de la boîte, mesurée sur le
RGB **avant** dessin des annotations. Il ne remplace pas une étude du contraste,
de la brume, des reflets, du flou ou de la lisibilité sémantique par catégorie.
Une coque générique peut satisfaire R sans permettre de reconnaître son type.

Ces états sont un **filtre heuristique**, pas une preuve de reconnaissabilité
humaine et pas la confiance d'un réseau neuronal. Il faut les calibrer avec une
annotation manuelle tenue à l'écart du détecteur et des scènes d'entraînement.
Pour IR/NV, le pourcentage géométrique reste partagé, mais les statuts présentés
sont ceux du RGB ; la reconnaissabilité propre à chaque modalité n'est pas évaluée.

Réglage persistant : `assets/perception/recognition_policy.json`, également ouvert
par `Cooperative traffic → 4 - Open visibility and recognition thresholds`.
Les autres campagnes possèdent les mêmes paramètres dans leur configuration
Unity, section `annotations / recognition`. Changer les seuils ne modifie pas les
trajectoires LOTUSim. Chaque campagne archive `recognition-policy.json`.

Exports :

- `annotations/` : visibilité, taille, contraste, statut, raisons et version de règle.
- `annotations.coco.json`, `labels/` : géométrie complète, y compris NR ; ne pas
  entraîner sans choisir une politique sur ces cas.
- `annotations.recognizable.coco.json`, `labels-recognizable/` : R uniquement.
  PR exige une revue. Éviter de traiter les régions NR/PR exclues comme du fond
  certain dans un entraînement ; utiliser des régions d'ignorance selon l'outil.
- `overlays/`, `overlays-thermal/`, `overlays-nightvision/` : couleurs et pourcentages.
- `rgb/` : images propres, sans aucune boîte ni texte ajouté.

## Agent visuel : séparation des rôles

```text
Unity : RGB propres ──► copies neutres / Gazebo Transport RGB ──► détecteur local
                                                                   │
                                                        prédictions indépendantes
                                                                   │
Unity : annotations géométriques ──► comparateur APRÈS inférence ◄────┘
```

Le worker reçoit seulement des PNG renommés `i000000.png`, sans EXIF ni textes,
et un vocabulaire fixe de douze catégories. Aucun nom d'instance, trajectoire,
pose, masque, boîte de référence, classe présente dans une frame ou image
annotée n'est transmis. Le comparateur est un processus/logique distinct, qui
lit la référence **après** la fin de l'inférence. C'est une séparation de contrat
d'entrée, **pas un bac à sable de sécurité OS**.

Grounding DINO tiny est un détecteur open-vocabulary, révision figée, licence
Apache-2.0. Il produit ses propres boîtes, catégories et scores sur CPU. Les
poids safetensors sont chargés localement, hors ligne, sans code distant exécuté
et sans envoi d'image à une API. Aucun entraînement sur les images de cette
campagne n'a été effectué. Les classes ambiguës sont conservées comme
`unknown`, plutôt que remplacées par le nom connu du simulateur.

Le score du modèle n'est pas calibré. Un détecteur RGB ne peut pas connaître le
pourcentage exact d'une partie cachée sans hypothèse sur le modèle complet.
Ses libellés cyan affichent donc un **score**, jamais un faux pourcentage visible.

Le modèle redimensionne l'image entière pour l'inférence ; les boîtes sont
ramenées aux coordonnées natives 4K. `tileSize` dans
`assets/perception/rgb_observer.json` permet une analyse supplémentaire par tuiles
(ex. 1024), avec recouvrement et NMS. Cela multiplie fortement le temps de calcul.
Le paramètre par défaut 0 est un premier niveau rapide, peu performant sur les
très petites cibles maritimes. Les objets manqués et fausses détections ne sont
jamais corrigés avec la vérité Unity. Une FREMM visible au premier plan mais non
annotée parmi les cibles peut aussi provoquer une prédiction non appariée.

Résultats sous `visual-observer/<date_identifiant>/` de chaque campagne :
`index.html`, `predictions/`, `comparison.json`, `status.json`, manifeste du modèle,
SHA-256 des pixels RGB et, en mode Gazebo, `transport/transport-proof.json`.
La comparaison utilise un appariement par classe et IoU ≥ 0,5, et conserve TP,
FP, FN et résultats par niveau NR/PR/R de la référence. Ce n'est pas une mesure
scientifique de qualité sans protocole de test et vérité manuelle.

## Gazebo : ce qui est réellement fait

Les capteurs `boundingbox_camera` / segmentation de Gazebo produisent une vérité
géométrique à partir d'une **scène 3D étiquetée**, pas une reconnaissance d'un PNG.
Source : [capteur bounding box](https://gazebosim.org/api/sensors/9/boundingbox_camera.html).

Le relais fourni échange seulement des `gz.msgs.Image` RGB_INT8 avec
`gz-transport13`, dans une partition de transport et un topic
`/dataset/rgb_observer/image_raw` isolés. Le résultat est vérifié pixel par pixel
avant remise au détecteur. Aucune nouvelle scène Gazebo, service de contrôle,
connexion ROS TCP ou connaissance de modèle n'est nécessaire. Ce chemin valide
le transit Gazebo, **pas la mise en service des capteurs d'annotation Gazebo** du
sujet initial. Le relais propose aussi `send` et `receive` pour deux processus.
Source : [transport Gazebo](https://gazebosim.org/api/transport/13/python.html).

## Installation sur un autre poste et lancement en ligne de commande

Sur ce poste, l'environnement isolé, les poids et le relais sont installés.
Sur un autre poste, utiliser Python 3.12 (version validée pour ces dépendances),
puis, depuis le dépôt LOTUSim :

```bash
python3.12 -m venv .venv-vision
.venv-vision/bin/python -m pip install -r tools/vision-requirements.txt
```

Télécharger `IDEA-Research/grounding-dino-tiny` à la révision inscrite dans
`assets/perception/rgb_observer.json` dans `artifacts/vision-models/grounding-dino-tiny`.
N'utiliser que les JSON/TXT et `model.safetensors`, pas un pickle ou du code distant.
Modèle : [fiche et licence](https://huggingface.co/IDEA-Research/grounding-dino-tiny),
[API de détection](https://huggingface.co/docs/transformers/model_doc/grounding-dino).

Pour compiler le relais dans l'environnement du conteneur, sans arrêter Gazebo :

```bash
mkdir -p artifacts/rgb-observer-gazebo
c++ -std=c++17 tools/gazebo_rgb_observer_relay.cpp \
  -o artifacts/rgb-observer-gazebo/relay \
  $(pkg-config --cflags --libs gz-transport13 gz-msgs10)
```

Sur le Mac, depuis LOTUSim, choisir un nouveau dossier de résultat :

```bash
.venv-vision/bin/python tools/rgb_observer.py \
  --rgb "/chemin/vers/campagne/rgb" \
  --output "/chemin/vers/nouvelle-analyse" --compare --via-gazebo
```

Omettre `--via-gazebo` pour l'entrée directe RGB. `--limit 3` permet un essai
court. L'agent peut analyser un jeu sans vérité Unity en omettant `--compare`.
Ne pas lui fournir les aperçus annotés comme images d'entrée.

Tests : `PYTHONPATH=tools:. python3 tests/python/vision/test_rgb_observer.py` et menu Unity
`Validate visibility and NR PR R rules`. Les tests de superposition GPU sont
effectués dans un projet isolé, pas sur une simulation de travail.
