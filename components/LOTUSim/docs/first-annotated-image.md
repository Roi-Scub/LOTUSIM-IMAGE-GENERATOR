# Première image annotée : bouée

Ce prototype valide le chemin minimal entre un objet Gazebo étiqueté, le capteur
`boundingbox_camera` et les fichiers image/annotation. La scène est volontairement
contrôlée : une bouée, une caméra fixe, lumière constante et mer calme. Le modèle est
une géométrie SDF procédurale de validation, pas encore un modèle 3D final.

Pour le rendu maritime Unity et la génération automatique complète, voir
[Pipeline LOTUSim, Gazebo et Unity](<pipeline-dataset-lotusim-unity.md>).
Cette procédure distingue le prototype existant des modules encore à développer
et précise la correspondance avec le sujet de stage.

## Lancer sur macOS + Docker Desktop

Le conteneur ne reçoit pas directement le GPU du Mac. Ce test fonctionne néanmoins
avec **Mesa llvmpipe**, qui effectue le rendu sur le CPU. Le shell Nix dédié configure
le pilote EGL nécessaire ; le shell par défaut et la connexion Unity restent
inchangés. Il ne faut pas reconstruire le workspace si `install/setup.bash` existe.

Un seul terminal suffit. Depuis un terminal macOS :

```sh
docker exec -it -w /workspace lotusim-dev sh
```

Puis, dans le conteneur :

```sh
nix --extra-experimental-features 'nix-command flakes' --option filter-syscalls false develop .#software-rendering -c bash
mise run capture:buoy
```

Le premier lancement peut télécharger Mesa depuis le cache Nix. Attendre que les
premiers fichiers apparaissent (le démarrage du moteur de rendu peut prendre
quelques dizaines de secondes), puis arrêter avec `Ctrl-C`. Le lancement doit
afficher `Rendering driver: Mesa llvmpipe (CPU)`.

Cette scène de validation ne nécessite **ni Unity, ni le serveur ROS-TCP, ni XDyn,
ni le lancement d'un scénario dans l'UI**. Elle utilise directement le capteur
Gazebo. Le plan bleu représente l'eau : ce n'est pas encore une mer avec vagues.

Les fichiers sont écrits dans `/workspace/artifacts/annotated-buoy/`, donc dans le
dossier `artifacts/annotated-buoy/` du dépôt monté sur le Mac. Les relancements
continuent la numérotation des captures déjà présentes. Ces fichiers générés sont
ignorés par Git.

### Pourquoi ne pas lancer uniquement `mise run sim` ?

Dans la version Harmonic utilisée ici, le système de capteurs attend un abonné pour
actualiser cette caméra, même avec `<save enabled="true">`. `capture:buoy` ouvre
automatiquement un abonné à `/dataset/buoy/boxes`, lance la scène et ferme cet
abonné à l'arrêt. Sans lui, la caméra peut démarrer sans écrire de fichier.

Pour un diagnostic manuel, lancer `mise run sim --debug annotated_buoy.world` dans
le shell de rendu logiciel, puis, dans un second terminal du conteneur avec le shell
Nix activé, `gz topic -e -t /dataset/buoy/boxes`.

## Vérification

Après l'arrêt, dans le même terminal :

```sh
find /workspace/artifacts/annotated-buoy -maxdepth 2 -type f | sort
sed -n '1,5p' /workspace/artifacts/annotated-buoy/boxes/boxes_0000000.csv
```

Un échantillon est composé d'une image RGB brute et de son annotation séparée,
appariées par leur numéro : `images/image_0000000.png` et
`boxes/boxes_0000000.csv`. L'image d'entraînement ne contient pas de rectangle dessiné.
Le CSV contient des coordonnées **en pixels**, pas normalisées :

```text
label,x_center,y_center,width,height
1,639.500000,418.500000,45.000000,95.000000
```

Ce résultat a été obtenu sur ce conteneur : image 1280 × 720, classe `1 = buoy`,
boîte allant de `(617, 371)` à `(662, 466)`. Le capteur utilise `visible_2d` :
l'annotation encadre la partie visible de la bouée.

Gazebo expose aussi les boîtes sur `/dataset/buoy/boxes` et une image avec les
rectangles dessinés sur `/dataset/buoy/boxes_image` pour la visualisation. Ces topics
sont des topics **Gazebo Transport**, pas ROS 2 : utiliser `gz topic`, pas
`ros2 topic`, pour les inspecter. Une passerelle ROS n'est pas requise pour la
sauvegarde native.

### Conserver un aperçu avec le rectangle natif

Pendant que `capture:buoy` tourne, ouvrir un second terminal dans le conteneur et
activer le shell Nix. Puis :

```sh
gz topic -e -t /dataset/buoy/boxes_image --json-output -n 1 > /workspace/artifacts/annotated-buoy/preview-message.json
python3 /workspace/scripts/gazebo_image_to_png.py /workspace/artifacts/annotated-buoy/preview-message.json /workspace/artifacts/annotated-buoy/preview.png
```

Le PNG reprend **sans modification** les pixels de l'image publiée par Gazebo,
rectangle vert inclus. Cet aperçu n'est pas l'image d'entraînement. Le convertisseur
utilise uniquement la bibliothèque standard Python et refuse d'écraser un PNG
existant : choisir un autre nom pour les prochains aperçus.

## Si le moteur de rendu plante

`Unable to load Ogre Plugin ... RenderSystem_GL3Plus` suivi de
`unable to find OpenGL 3+ Rendering Subsystem` ne prouve pas que le plugin est
absent. Dans notre conteneur, la bibliothèque existe mais EGL ne trouvait aucun
pilote Mesa enregistré. Le détail est dans `/root/.gz/rendering/ogre2.log`.

Vérifier que le shell a été ouvert avec `.#software-rendering` et que
`echo "$LOTUSIM_GL_WRAPPER"` affiche `lotusim-software-render`. Ce mode configure
le pilote pour Gazebo ; il ne donne pas accès au GPU Metal du Mac. Le warning
`GPU driver bridge: none` indique un pilote non configuré par le lanceur, pas une
impossibilité générale de produire des images sans GPU physique.

Références : [rendu headless Gazebo](https://gazebosim.org/api/sim/8/headless_rendering.html),
[variables Mesa](https://docs.mesa3d.org/envvars.html),
[implémentation du capteur BoundingBoxCameraSensor](https://github.com/gazebosim/gz-sensors/blob/gz-sensors8/src/BoundingBoxCameraSensor.cc).

Les avertissements Mesa `Not allowed to force software rendering when API explicitly
selects a hardware device` et Ogre sur l'anti-aliasing ont été observés pendant le
test réussi : ils n'ont pas empêché la capture. Vérifier la présence effective des
paires PNG/CSV plutôt que de considérer tout warning comme un arrêt du rendu.
Un message `task failed` juste après `Ctrl-C` peut correspondre au code
d'interruption du processus ; il ne signifie pas que les fichiers déjà écrits sont
invalides.

## Règle provisoire pour ce test

La boîte est une vérité terrain géométrique, pas encore une garantie de détectabilité.
On ne filtre rien dans cette première étape : l'objectif est seulement de prouver que
l'image et son annotation sont générées ensemble. Les seuils de taille apparente,
d'occultation et de contraste viendront ensuite, après comparaison avec une
annotation manuelle.
