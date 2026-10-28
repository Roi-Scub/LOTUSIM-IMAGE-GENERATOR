# Images 4K, infrarouge synthétique et vision nocturne

La campagne connectée `MaritimeRandomLotusim` conserve sa scène, ses 360 instants,
ses trajectoires LOTUSim et ses annotations. Le rendu est désormais en
**3840 × 2160 pixels natifs**, avec trois images par instant : RGB, IR synthétique
et vision nocturne simulée. Les anciens PNG ne sont pas agrandis artificiellement.
Cela représente 1 080 images brutes pour les 360 instants, auxquelles s'ajoutent
les aperçus annotés et les masques.

## Lancement et réglages

Dans Unity, hors Play : **LOTUSim > Dataset > 7**, puis Play, avec le simulateur
`maritime_dataset.world` et le serveur TCP habituels actifs. Aucun nouveau serveur,
nouvelle connexion ROS ou caméra concurrente n'est créé. Cette évolution ne
nécessite pas de recompiler le module Gazebo.

Configuration : `Assets/Dataset/MaritimeRandomLotusim.asset`.

La caméra est fixée à hauteur de la passerelle avant, en position locale
`(30,3 ; 12,4 ; −5,5)` m. Le modèle n'ayant pas d'intérieur exploitable, l'œil est
devant les vitres opaques plutôt que dans la coque. Son transform est enfant
du visuel FREMM : il hérite de ses mouvements et n'applique pas de stabilisation
d'horizon, même après la dernière capture. Les paramètres **Observer Wave Tilt
Gain**, **Observer Max Roll Deg** et **Observer Max Pitch Deg** agissent sur
le bateau entier. Valeurs initiales : gain 1,8, limites 7° / 4°. Elles ne forcent
pas une amplitude constante et ne sont pas une calibration hydrodynamique.

- **Width / Height** : 3840 / 2160 pour la 4K ; 2560 / 1440 ou 1920 / 1080 pour
  alléger le rendu. Conserver le même rapport largeur/hauteur garde le cadrage.
- **Sensors > Thermal / Night Vision** : activer/désactiver les sorties
  supplémentaires. RGB reste toujours enregistré.
- **Thermal Min C / Max C** : fenêtre d'affichage des températures supposées ;
  **Black Hot** inverse la palette clair/chaud en sombre/chaud.
- **Thermal Classes** : température et émissivité supposées par catégorie.
- **Water / Sky / Background Temperature C** : hypothèses d'environnement.
- **Night Gain / Gamma / Noise / Vignette / Tint** : rendu de vision nocturne.

La migration initiale double une configuration Full HD en 4K et active les deux
modes supplémentaires une fois. Les réglages ultérieurs ne sont pas écrasés.
Réexporter le YAML avec le menu 8 après modification du cadrage, de la résolution
ou du plan, comme pour les autres réglages de campagne.

## Ce qui est réellement simulé

### RGB

Rendu visible Unity HDRP, océan et éclairage jour/soirée/nuit existants. Capture
à la résolution demandée, sans résolution dynamique ni agrandissement logiciel.
L'anticrénelage spatial existant est conservé ; flou de mouvement et profondeur
de champ restent désactivés pour les annotations.

La 4K double les dimensions et quadruple les pixels par rapport au Full HD. Cela
améliore l'échantillonnage d'une cible, mais ne peut pas révéler des détails absents
du modèle ou rendre reconnaissable un avion qui occupe seulement quelques pixels.
Pour davantage de détails sur une cible, réduire aussi sa distance ou le champ
de vue, puis régénérer les images et annotations.

### IR synthétique — non radiométrique

Ce mode **n'est pas une conversion du RGB en niveaux de gris**. Un rendu de la
géométrie attribue des températures et émissivités supposées aux objets, avec un
fond ciel/eau et une réflexion simplifiée de l'environnement. La luminance utilise
un proxy de corps gris en T⁴, ramené dans la fenêtre de température choisie.
La profondeur de la scène garde les occultations par les autres objets, le pont
et l'eau. La lumière visible n'est pas utilisée pour décider qu'un objet est chaud.

Valeurs initiales indicatives : eau 18 °C, bouée 20 °C, voilier 23 °C, bateaux
26–30 °C, drone 35 °C, hélicoptère 40 °C, avion 32 °C, oiseau 39 °C. Ce sont des
**hypothèses de génération**, pas des températures mesurées ni une banque de
signatures thermiques réelles.

Limites : pas de conduction thermique, de chauffage solaire, d'échappement
localisé, de refroidissement temporel, d'atmosphère radiométrique, d'intégration
spectrale LWIR 8–14 µm ni de réponse d'un capteur réel. Les PNG montrent une
apparence thermique synthétique, pas une mesure de température exploitable.
Une température homogène par catégorie ne remplace pas des matériaux thermiques
spatialisés. Ces limites doivent accompagner tout usage pour entraîner un modèle.

### Vision nocturne simulée

Intensification de la luminance HDR **avant** la transformation finale RGB,
teinte verte, bruit et vignettage configurables. Aucune lampe invisible n'est
ajoutée et la scène n'est pas déplacée. Ce n'est pas une simulation calibrée de
photocathode, de gain électronique ou de bruit photonique d'un appareil réel.
Les éclairages jour/soirée/nuit restent les mêmes pour les trois sorties.

## Fichiers et annotation commune

Chaque instant `fXXXXXX` produit :

- `rgb/`, `thermal/`, `nightvision/` : images sans texte ;
- `overlays/`, `overlays-thermal/`, `overlays-nightvision/` : aperçus annotés ;
- `masks/`, `amodal/`, `labels/` : géométrie et labels partagés ;
- `annotations.coco.json`, `annotations.thermal.coco.json`,
  `annotations.nightvision.coco.json` : mêmes boîtes/masques, chemins d'images adaptés ;
- `annotations/fXXXXXX.json` : liste des modes, chemins, dimensions, frame Unity,
  poses et hypothèses thermiques ;
- `sensor-models.json` et `requested-config.json` : modèles et paramètres archivés.

Les trois modes ont la même caméra, la même résolution, les mêmes poses et le
même rendu temporel. Aucun déplacement de la simulation n'intervient entre eux.
Une sortie manquante ou périmée provoque une erreur au lieu de produire une paire
incohérente. Les annotations sont **géométriques** : une boîte peut être exacte
alors que le contraste IR ou nocturne rend sa cible non reconnaissable. Les
seuils de validité visuelle devront être évalués séparément pour chaque mode.

## Voir les détails sans agrandir une vignette

La galerie générée propose un sélecteur RGB / IR / vision nocturne et une case
pour afficher les annotations. Cliquer une image ouvre une vue défilante en
**pixels natifs à 100 %**, avec un bouton pour l'adapter à l'écran et un lien vers
le PNG original. Les anciennes galeries et images restent conservées.

## Coût

La 4K, les masques et les deux modes supplémentaires augmentent le temps de
calcul, les lectures GPU et le stockage. Une campagne peut occuper plusieurs
gigaoctets. Les masques GPU sont monocanaux quand le périphérique le permet pour
limiter la mémoire. Commencer par quelques captures avant de lancer les 360.

## Vérification

Test isolé réel LOTUSim → ROS → Unity : trois instants jour/soirée/nuit,
neuf PNG natifs 3840 × 2160, 52 annotations sur les 12 catégories. Résolutions,
frames, masques monochromes binaires, COCO/RLE, YOLO et poses sources vérifiés.
Les coordonnées locales du montage caméra sont constantes et les angles de
roulis effectivement transmis sont enregistrés. Une seule connexion et l'arrêt
du seul scénario de test sont confirmés. Il s'agit d'un test court, pas du calcul
de toute la campagne de 360 instants.
