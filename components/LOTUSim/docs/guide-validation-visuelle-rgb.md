# Validation visuelle des images Unity

Cette chaîne fonctionne localement, sans API d’image externe, sans téléchargement
de poids à l’exécution et sans nouvelle connexion ROS. Elle conserve les RGB
originaux et écrit chaque traitement dans un nouveau dossier.

## Depuis Unity

Menu **LOTUSim > Dataset > RGB observer > Analyze an existing capture folder**,
puis choisir une campagne contenant `rgb/`. Le bouton **Analyser les RGB avec
l’agent indépendant** de la fenêtre de suivi lance le même traitement. Le bouton
**Ouvrir les prédictions de l’agent** ouvre ensuite `index.html`.

Par défaut, le pilote traite au plus **12 images réparties sur la campagne**.
La galerie et le manifeste indiquent qu’il s’agit d’un aperçu, pas d’une analyse
complète. Le tuilage conserve mieux les petites cibles mais coûte davantage sur
CPU : une image 4K utilise une vue globale et 15 tuiles de 1024 pixels. Le nombre
de tuiles réellement évaluées apparaît dans les journaux du worker.

Le passage par Gazebo Transport reste disponible dans le menu. Si Docker ou le
relais est indisponible, le coordinateur utilise explicitement les RGB directs
et consigne le repli dans `transport-status.json`. Il ne démarre pas Docker,
Gazebo ou Unity et ne touche pas à une simulation existante.

## Rôles des agents

1. **Préparation des connaissances** : découpe des exemples dans des RGB propres
   à l’aide d’annotations d’autres scènes. Index local de caractéristiques
   visuelles Swin, extrait des poids Grounding DINO déjà présents.
2. **Détecteur RGB** : recherche des objets sur l’image complète et les tuiles.
   Ses seules entrées sont les RGB renommés, un vocabulaire fixe et la partie
   publique de la base. Aucune annotation de l’image de test n’est transmise.
3. **Vérificateur visuel** : compare les propositions du détecteur aux exemples
   de référence. Un désaccord est signalé. Il ne remplace pas arbitrairement une
   classe par celle du voisin le plus ressemblant.
4. **Évaluateur** : lit les annotations Unity seulement après l’inférence, apparie
   les classes et les boîtes, puis conserve les faux positifs et objets manqués.
5. **Rapporteur** : produit la galerie, les preuves visuelles, le bilan par classe
   et par taille native, les JSON et le journal `agent-events.json`.

Ces agents sont des étapes logicielles spécialisées, pas des appels à un LLM
externe. Leur orchestration et leurs entrées sont enregistrées. La séparation
des entrées n’est pas un bac à sable de sécurité du système d’exploitation.

**Gazebo transporte les images. Grounding DINO effectue l’inférence.** Un capteur
`boundingbox_camera` Gazebo natif annote sa propre scène 3D étiquetée, pas un PNG
Unity importé.

## Comprendre les nombres

- **Score modèle (%)** : score brut de Grounding DINO multiplié par 100. Ce n’est
  pas une probabilité de justesse calibrée.
- **Similarité cosinus** : ressemblance des caractéristiques visuelles avec un
  exemple connu. Elle ne constitue ni une probabilité ni une preuve de classe.
- **Précision empirique (%)** : fraction de prédictions correctes observée dans
  un intervalle de scores, sur des images de calibration séparées. La cible est
  ici **bonne classe et IoU ≥ 0,5 contre la géométrie Unity**, pas reconnaissance
  humaine. Le rapport donne l’effectif et un intervalle Wilson descriptif à 95 %.
- Sans assez de prédictions de calibration dans la tranche de score, le champ de
  confiance reste **nul**, plutôt qu’un pourcentage inventé. Un changement de
  modèle, seuil, tuilage ou base invalide l’estimation précédente.
- Une cible de quelques pixels peut rester indéterminée. Agrandir son crop ne
  recrée aucun détail. NR/PR/R reste un autre indicateur, initialement heuristique.

Le seuil de support initial vaut 20 prédictions par tranche de score, par classe
si possible, sinon sur un pool explicitement identifié. Ce minimum technique ne
garantit pas la validité statistique. Plusieurs objets d’une même image et des
images voisines sont corrélés. Les premiers essais sur une seule séquence sont
des pilotes descriptifs, pas une mesure généralisable de sûreté.

## Vérifier un objet déjà localisé par Unity

Hors Play : **LOTUSim > Dataset > RGB observer > Verify Unity-localized
instances (diagnostic)**, puis sélectionner une campagne annotée. Le menu
**Open last visual report** ouvre le rapport une fois le traitement terminé.
Les deux modes partagent le même verrou de processus : aucun second worker ni
client ROS n’est créé pour la vérification.

Le second mode répond à une question différente : **la classe d’un objet connu
géométriquement est-elle suggérée par son apparence ?** Unity fournit la boîte,
mais sa catégorie attendue reste dans le coordinateur. Le classificateur séparé
ne lit que le crop RGB neutre et la base publique d’exemples.

```sh
.venv-vision/bin/python tools/rgb_verify_instances.py \
  --campaign "/chemin/vers/campagne" \
  --knowledge artifacts/rgb-validation/knowledge \
  --config assets/perception/rgb_observer_tiled.json \
  --output artifacts/rgb-validation/nouvelle-verification
```

Le pilote prend au plus quatre images uniformément espacées et les douze plus
grandes instances visibles. C’est une sélection diagnostique, pas un échantillon
statistique. La galerie présente le crop, les trois voisins et leur similarité,
la marge entre classes, puis la référence Unity après classification. Une marge
inférieure à 0,03 ou un crop trop petit provoque une abstention ; ces seuils
initiaux ne sont pas encore validés expérimentalement. Une classe absente de la
base peut malgré tout ressembler à une classe connue : la galerie signale ce
risque, sans transformer la similarité en probabilité.

`rawClassification` garde la sortie visuelle. `geometryQualityGate` est un
contrôle distinct, après inférence, qui peut rejeter une instance comportant
moins de 32 pixels visibles selon Unity. Cela ne doit pas être présenté comme
une abstention du modèle RGB.

Ce mode n’est **pas une détection indépendante** : ne pas utiliser ses résultats
pour calibrer le détecteur ni calculer sa précision/rappel/IoU. Aucun pourcentage
de justesse n’est donné à partir du cosinus seul.

## Construire ou enrichir la base

Les galeries `marine-library/open-objects/captures` et
`marine-library/open-boats/captures` fournissent des vues rapprochées annotées.
L’index limite le nombre d’exemples par classe et ne copie jamais les overlays.

```sh
.venv-vision/bin/python tools/rgb_validate.py knowledge \
  --source "/chemin/vers/campagne-de-reference" \
  --output artifacts/rgb-validation/nouvelle-base
```

Sources prises en charge : `rgb/` et `annotations/*.json`, ou
`annotations.coco.json`. Les images non annotées restent dans la provenance sans
recevoir de classe inventée. Un répertoire de sortie existant est refusé.

`public/` contient uniquement les crops neutres, catégories et vecteurs.
`coordinator/provenance.json` conserve les chemins, groupes et hashes des pixels
décodés. Les sources de la base et du test ne doivent partager ni groupe de
scènes ni pixels, même après réencodage d’un PNG. Des groupes correctement
déclarés restent nécessaires pour repérer les scènes proches non identiques.

## Lancer une analyse et la calibration

```sh
.venv-vision/bin/python tools/rgb_observer.py \
  --rgb "/chemin/campagne/rgb" --compare \
  --knowledge artifacts/rgb-validation/knowledge --limit 12
```

`--all` traite toute la campagne. `--via-gazebo` active le transport optionnel,
et `--strict-transport` refuse le repli direct. Un dossier sans annotation peut
être analysé : la galerie explique alors que l’évaluation est omise.

Pour préparer une estimation, analyser une **autre campagne** avec
`--role calibration`, puis :

```sh
.venv-vision/bin/python tools/rgb_validate.py calibrate \
  --run "/chemin/resultat-calibration" \
  --knowledge artifacts/rgb-validation/knowledge \
  --output artifacts/rgb-validation/nouvelle-calibration.json
```

Analyser ensuite une campagne de test distincte avec
`--calibration artifacts/rgb-validation/nouvelle-calibration.json`.
Les images de calibration sans détection figurent aussi dans le contrôle de
lignage. Réutiliser un groupe ou des pixels connus pour le test provoque un refus.

Une référence manuelle indépendante et de nouvelles scènes sont nécessaires
avant de présenter ces valeurs comme une validation scientifique finale.

## Reprendre un rapport sans refaire l’inférence

Les prédictions terminées sont conservées si l’évaluation échoue :

```sh
.venv-vision/bin/python tools/rgb_validate.py report \
  --run-folder "/chemin/resultat" --source "/chemin/campagne"
```

Ce mode ne modifie pas les prédictions ni les captures. Les anciens sidecars
mono-bouée `lotusim-instance-geometry-1` sont adaptés en plus des séquences COCO.

## Configuration et limites

- `assets/perception/rgb_validation.json` : base utilisée et taille de l’aperçu.
- `assets/perception/rgb_observer_tiled.json` : modèle, seuils et tuilage.
- `assets/perception/rgb_observer.json` : ancienne configuration conservée.
- Le détecteur sait rechercher douze classes, mais la première base rapprochée
  n’offre pas encore des exemples de toutes ces classes.
- La base installée contient 26 exemples issus de 28 vues, sur huit classes.
  Chalutier, cargo, ferry et voilier restent recherchables par le détecteur, mais
  ne disposent pas encore de prototypes rapprochés isolés dans cette base.
- La séparation des scènes n’impose pas des modèles 3D distincts entre base et
  test : la généralisation à de nouveaux assets n’est pas démontrée.
- La base publique conserve l’empreinte des poids de l’encodeur. Réutiliser les
  vecteurs avec d’autres poids provoque un refus ; les anciennes bases sans
  empreinte restent explicitement identifiées comme non vérifiées.
- Le bateau observateur, les îles et d’autres éléments hors annotations peuvent
  produire des prédictions non appariées. Le rapport les garde au lieu de les
  effacer à l’aide de la vérité terrain.

Sources : [Grounding DINO](https://huggingface.co/docs/transformers/v4.57.1/model_doc/grounding-dino),
[Gazebo Transport](https://gazebosim.org/api/transport/13/python.html),
[calibration des réseaux](https://arxiv.org/abs/1706.04599).
