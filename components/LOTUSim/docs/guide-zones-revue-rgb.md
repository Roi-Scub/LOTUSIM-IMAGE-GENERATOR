# Revue RGB : exclusion du bateau et cadres concurrents

## Ce qui change

Le rapport affiche une grande image RGB propre, avec des cadres SVG plutôt que
des étiquettes déjà imprimées dans le PNG. Les flèches changent d’image ; « Voir »
cadre une proposition à sa résolution native. Les cadres ambigus et les
propositions rejetées sont masqués au départ mais restent consultables.

« Retenue » signifie **hypothèse affichable**, jamais objet vérifié. Un cadre
géant peu étayé devient ambigu ; il n’est pas effacé de l’audit. Les propositions
ambiguës participent encore aux métriques, même si elles sont masquées à l’écran.
Changer un filtre d’affichage ne recalcule donc jamais les performances.

Les cadres presque identiques, y compris de classes différentes, sont regroupés.
Les classes concurrentes et les boîtes originales restent dans les JSON et dans
les motifs de revue. Une simple inclusion ne suffit pas à supprimer une petite
cible devant une grande : la fusion de fragments nécessite une provenance de
tuilage concordante. Les anciennes prédictions sans cette provenance restent
traitées plus prudemment.

Le signal de désaccord avec la petite base visuelle n’est pas, à lui seul, une
preuve d’erreur : plusieurs classes ne sont pas encore couvertes par cette base.
Les scores et les coordonnées du modèle ne sont pas corrigés à partir des
annotations Unity. Les cadres sur montagnes ou vagues sont de fausses hypothèses,
pas un décalage général de coordonnées.

## Exclure le propre bateau

Priorité, à chaque analyse d’une campagne :

1. **Masque visible de l’observateur**, s’il est exporté par Unity. Le fichier
   `observer-exclusion.json` associe chaque RGB à un PNG monochrome du seul
   observateur, avec hashes des fichiers et numéro de frame. Les dimensions et
   hashes sont vérifiés avant toute inférence. Les masques des cibles ne sont
   jamais fournis au détecteur.
2. **Polygone explicite** dans `rgb-observer-regions.json`, placé à la racine de
   la campagne, à côté de `rgb/`. Il peut aussi être passé avec `--regions`.
   Un polygone explicite peut compléter un masque visible.
3. **Profil de caméra connu**, pour les anciennes campagnes sans masque. Le
   registre `assets/perception/rgb_region_profiles.json` ne sélectionne le contour
   de la FREMM que si station, FOV, rapport d’image, montage et angles correspondent.
   Une autre caméra n’hérite pas automatiquement de cette zone.

Les pixels exclus sont remplacés par un gris neutre **avant l’entrée dans le
modèle** et avant la comparaison visuelle de crops. Les RGB originaux ne sont
pas modifiés. Pour les polygones, les cadres centrés dans la zone ou majoritairement
couverts sont écartés avec leur motif. Avec le seul masque visible exact, seule
une boîte entièrement ignorée est rejetée : un objet de premier plan ne doit pas
être éliminé parce que son rectangle contient aussi du pont en arrière-plan.
Les autres cadres gardent leurs
coordonnées natives : aucun rectangle n’est déplacé pour correspondre à une cible.

Le contrat devient donc **RGB + exclusion déclarée de l’observateur**, pas RGB
strictement seul. Cette information de périmètre ne transmet aucune catégorie,
pose ou boîte des cibles. Une modification des zones ou du post-traitement change
la signature et invalide les anciennes estimations de confiance.
Les hashes prouvent l’appariement et l’intégrité des fichiers, pas leur origine
authentique : le caractère « observateur seulement » reste un contrat déclaré
par l’exporteur local.

## Dessiner une zone

Dans le rapport : « Cartographier une zone à ne pas chercher » → « Dessiner sur
le RGB » → cliquer autour du pont → « Fermer le polygone » → télécharger le JSON.
Enregistrer le fichier sous `rgb-observer-regions.json` dans la campagne, puis
relancer l’analyse. Le dessin seul est un brouillon : il ne modifie pas le rapport.

Les points sont normalisés entre 0 et 1, avec l’origine en haut à gauche. Vérifier
le contour sur plusieurs images. Un polygone reste une approximation et peut
masquer une vraie cible passant devant le bateau ; le masque visible par frame
est préférable. Si la caméra change, il faut refaire le polygone.

## Vérifier une ancienne analyse sans refaire le modèle

```sh
.venv-vision/bin/python tools/rgb_validate.py review \
  --run-folder "/chemin/ancienne-analyse" \
  --source "/chemin/campagne" --output "/chemin/nouvelle-revue"
```

Cette commande conserve l’ancienne analyse et produit une nouvelle revue. Elle
filtre les propositions déjà existantes ; elle ne prétend pas que l’ancienne
inférence avait ignoré le pont si ce n’était pas déjà le cas. Le JSON conserve
explicitement ce fait lorsque le profil d’exclusion est inchangé. Elle ne peut
pas servir à calibrer le nouveau
détecteur masqué. Pour tester réellement le masquage en entrée, relancer l’analyse
normale depuis Unity ou `tools/rgb_observer.py`.

## Validation du masque Unity

Le masque observateur utilise les seuls MeshRenderer opaques de la FREMM, la
profondeur de la caméra RGB et la même frame. Il reste séparé des objets annotés
et n’ajoute pas l’observateur au COCO. Sans observateur, aucun fichier additionnel
n’est produit. Les observateurs transparents, alpha-clippés ou skinnés sont refusés.

L’implémentation a été compilée avec les références Unity du projet. Une nouvelle
capture GPU doit encore confirmer visuellement l’alignement et le comportement
avec une cible passant devant le bateau. Le surcoût GPU d’une texture 4K est
d’environ 8,3 Mo en R8, ou 33,2 Mo avec le fallback RGBA.
