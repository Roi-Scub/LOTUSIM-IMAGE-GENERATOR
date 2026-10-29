# Installer LOTUSim et Unity

Cette procédure installe les extensions dans deux nouveaux clones compatibles.
Ne pas l’appliquer par-dessus des projets de travail déjà modifiés. Pour le
dashboard seul, voir le [démarrage local](INSTALLATION_DASHBOARD.md).

Le dépôt fournit les ajouts dans `components/`, les patchs dans `patches/`, leurs
copies complètes dans `references/` et un inventaire SHA-256 dans `manifest.json`.
Les moteurs, dépôts complets, builds, caches, poids IA, bases locales et corpus
ne sont pas inclus. Les [licences des médias](ASSETS_ET_LICENCES.md) restent distinctes.

## 1. Préparer les deux dépôts de base

Prérequis : Git, Python 3.9+, Unity Hub avec Unity **2022.3.18f1**, accès aux dépendances du socle et, pour la simulation sur Mac, Docker Desktop. La vision indépendante demande en plus Python 3.12 et ses paquets spécifiques.

Choisir un nouveau dossier de projets et garder les noms de dépôts ci-dessous. Les constructeurs Unity utilisent encore cette disposition :

```text
projets/
├── LOTUSim/
└── LOTUSim-Unity-modules/
```

Dans un terminal, en remplaçant `/chemin/projets` :

```bash
task_workspace="/chemin/projets"
mkdir -p "$task_workspace"
git clone https://github.com/naval-group/LOTUSim.git "$task_workspace/LOTUSim"
git -C "$task_workspace/LOTUSim" checkout --detach 803c739e4c3222cde54704e94b9f4a89d53fee89
git clone https://github.com/naval-group/LOTUSim-Unity-modules.git "$task_workspace/LOTUSim-Unity-modules"
git -C "$task_workspace/LOTUSim-Unity-modules" checkout --detach 68e56588f5b469201fcb50a90b571e357a89ad9c
git -C "$task_workspace/LOTUSim-Unity-modules" submodule update --init --recursive
```

Récupérer les assets Git LFS du projet de base si nécessaire avec `git lfs pull` dans le clone Unity, après installation de Git LFS. Un fichier pointeur LFS n’est pas le maillage ou la texture qu’il désigne. Garder les versions de packages et sous-modules indiquées dans [MODIFICATIONS_UNITY.md](MODIFICATIONS_UNITY.md).

## 2. Intégrer l’export

Fermer Unity dans ces nouveaux clones. Depuis la racine de l’export :

```bash
python3 scripts/verify_export.py
python3 scripts/install_integration.py \
  --core "$task_workspace/LOTUSim" \
  --unity "$task_workspace/LOTUSim-Unity-modules"
```

Cette étape ne fait qu’une vérification. Elle contrôle les commits, les patchs, les empreintes et les conflits de fichiers. Pour appliquer après un résultat positif :

```bash
python3 scripts/install_integration.py \
  --core "$task_workspace/LOTUSim" \
  --unity "$task_workspace/LOTUSim-Unity-modules" \
  --apply
```

Options à ajouter **à la vérification puis à l’application** si elles sont utiles :

- `--with-environment` : patchs Nix/Mise, rendu logiciel Mesa et tâche Gazebo `capture:buoy`. Utile pour le chemin Gazebo sans GPU et le build peu parallélisé.
- `--with-interactive` : correctifs du Launcher historique, caméra de poursuite et réglage XR local. Les scènes dédiées de dataset n’ont pas besoin du Launcher/Photon pour capturer leurs images.

L’installation de base comprend les correctifs fonctionnels LOTUSim, la compatibilité ROS Unity, les entrées Addressables et tous les nouveaux fichiers. Aucune commande Git de commit/reset, aucun téléchargement, build, lancement de conteneur ou Play n’est exécuté par l’installateur. Les modifications locales d’une cible sont refusées, pas effacées.

## 3. Construire LOTUSim dans Linux

Le socle utilise ROS 2 Jazzy, Gazebo Harmonic et Nix. Utiliser son `flake.lock`, pas une mise à jour arbitraire des dépendances. Consulter également le README du socle pour ses caches binaires Nix : sans les caches configurés, des dépendances lourdes peuvent être reconstruites.

Sur macOS Apple Silicon, la voie de référence passe par un conteneur Linux ; les scripts Nix/ROS ci-dessous ne s’exécutent pas dans le shell macOS. Pour un **nouveau conteneur uniquement**, depuis le nouveau clone LOTUSim :

```bash
cd "$task_workspace/LOTUSim"
docker run -dit --platform linux/amd64 --name lotusim-dev \
  -p 127.0.0.1:10000:10000 \
  --mount "type=bind,source=$PWD,target=/workspace" \
  -w /workspace nixos/nix:2.35.2 sh
```

Si `lotusim-dev` existe déjà, ne pas le supprimer ou le recréer aveuglément : contrôler son montage et utiliser un autre nom pour une installation parallèle. Le collecteur du dashboard observe par défaut le nom `lotusim-dev`. Les ports 8080/API5000 du Web LOTUSim ne sont pas requis par la chaîne de capture dédiée ; les publier seulement si l’interface officielle est également utilisée.

Ouvrir le shell du conteneur :

```bash
docker exec -it -w /workspace lotusim-dev sh
nix --extra-experimental-features "nix-command flakes" \
  --option filter-syscalls false develop -c bash
mise trust
CMAKE_BUILD_PARALLEL_LEVEL=1 MAKEFLAGS=-j1 \
  colcon build --merge-install --executor sequential \
  --cmake-args -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
source install/setup.bash
```

Le premier build doit construire le workspace complet. Après une modification des seuls modules dataset, un rebuild ciblé peut employer `--packages-select lotusim_mas render_interface_plugin`. Le nom du second paquet est **render_interface_plugin**, pas `render_interface`. La simulation déjà en mémoire ne recharge pas un nouveau module : sortir de Play, arrêter seulement ce simulateur, puis le relancer après le build.

Cette procédure `colcon` lit les fichiers du dossier de travail. Pour produire ensuite un paquet pur avec `nix build .#workspace` ou `.#container`, les nouveaux fichiers doivent aussi être suivis par Git : une flake Git ne prend pas automatiquement les fichiers non suivis. Examiner les ajouts avant de les indexer ; l’installateur n’effectue volontairement ni `git add` ni commit.

## 4. Préparer le ROS TCP Endpoint

Il est séparé du build LOTUSim. Dans un shell Nix où `install/setup.bash` de LOTUSim a été sourcé, sur un conteneur neuf :

```bash
mkdir -p /root/.local/share/lotusim/ros_tcp_endpoint_ws/src
git clone https://github.com/naval-group/LOTUSim-Unity-ros-tcp-endpoint.git \
  /root/.local/share/lotusim/ros_tcp_endpoint_ws/src/ros_tcp_endpoint
git -C /root/.local/share/lotusim/ros_tcp_endpoint_ws/src/ros_tcp_endpoint \
  checkout --detach 3e3db753c916356f8e32fb602b02fc5dbc1764f1
cd /root/.local/share/lotusim/ros_tcp_endpoint_ws
colcon build --merge-install --executor sequential --packages-select ros_tcp_endpoint
```

Sur Linux hors conteneur, choisir un chemin accessible à son utilisateur. Ce commit est celui du workspace externe constaté sur le poste de travail. Aucun correctif local supplémentaire n’a été trouvé entre ses sources Git et les modules Python installés lors de l’export.

## 5. Démarrer une session connectée

**Terminal de simulation**, dans le shell Nix LOTUSim :

```bash
cd /workspace
source install/setup.bash
mise run sim maritime_dataset.world
```

**Terminal ROS TCP**, dans un autre shell du même environnement :

```bash
source /workspace/install/setup.bash
source /root/.local/share/lotusim/ros_tcp_endpoint_ws/install/setup.bash
ros2 run ros_tcp_endpoint default_server_endpoint \
  --ros-args -p ROS_IP:=0.0.0.0 -p ROS_TCP_PORT:=10000
```

Ne pas lancer un second `lotusim.world` dans le même domaine ROS en parallèle : les deux mondes utiliseraient `/lotusim`. `maritime_dataset.world` est le monde dédié à la timeline cinématique ; xDyn n’est pas nécessaire à ce chemin. Pour les scénarios de propulsion classiques, voir le guide historique et leurs besoins xDyn spécifiques.

**Unity**, sur le poste de rendu : ouvrir le nouveau clone complet dans l’éditeur prévu, attendre les imports et vérifier ROS2, espace couleur Linear et les réglages HDRP Water/CPU/Custom Pass du projet. Conserver les `.meta`. Les assets déjà convertis sont fournis : inutile de reconstruire toute la bibliothèque pour le premier essai.

**Dashboard**, sur le poste local, depuis l’export :

```bash
python3 scripts/start_dashboard.py \
  --core "$task_workspace/LOTUSim" \
  --unity "$task_workspace/LOTUSim-Unity-modules"
```

Ouvrir `http://127.0.0.1:8766/#settings`. Vérifier une petite configuration de **deux images**, préparer ses fichiers, puis hors Play dans Unity : **LOTUSim > Dataset > Manual campaigns > Import prepared campaign**, choisir **manifest.json** et lancer Play dans la nouvelle scène. Ne pas lancer le même scénario depuis une autre interface.

## 6. Voir puis analyser les résultats

Les campagnes manuelles produisent une galerie sous `LOTUSim-Unity-modules/artifacts/manual-campaigns/`, avec RGB commun, annotations et liens vers les exports de chaque image. Les pilotes historiques utilisent les groupes `artifacts/dataset-*`. Le dashboard retrouve ces sorties sous les racines installées.

Installer la vision optionnelle comme indiqué dans [INSTALLATION_DASHBOARD.md](INSTALLATION_DASHBOARD.md) pour analyser des pixels RGB locaux, sans cadres dessinés. Le relais Gazebo Transport n’est pas nécessaire à l’inférence directe ; il ne remplace pas le détecteur visuel. Les poids ne sont pas inclus dans l’export.

## 7. Contrôles avant une grande campagne

- Les deux dépôts sont à la version de base attendue, patchs appliqués, modules C++ reconstruits et chargés par le processus de simulation actuel.
- Un seul monde `/lotusim`, un seul ROS TCP Endpoint, une seule source de poses dans la scène dédiée.
- Le protocole annonce `ownedStop`, `steppedTimeline`, les capacités de virage et la vitesse nécessaire au plan ; le pilote refuse une version incompatible.
- Les deux premières images sont lisibles, leurs masques alignés et le bateau observateur exclu ; le scénario possédé s’arrête correctement avant le suivant.
- Les conditions visuelles et les tailles apparentes ont été contrôlées sur ces images avant d’augmenter le nombre de captures.

Les tests du paquet vérifient la portabilité des sources et l’application des patchs. Ils ne certifient pas le rendu GPU, les performances ni la validité scientifique des seuils sur toute machine. Les campagnes manuelles doivent commencer par ce petit essai réel.
