# Intégration LOTUSim

Les chemins sont relatifs au clone LOTUSim cible. Les modifications fonctionnelles
ci-dessous vont ensemble ; les adaptations d’environnement sont optionnelles.

## 1. Références et portée de compatibilité

| Élément | Origine relevée localement | Révision de référence |
| --- | --- | --- |
| Noyau LOTUSim | `https://github.com/naval-group/LOTUSim.git` | `803c739e4c3222cde54704e94b9f4a89d53fee89` |
| Projet Unity | `https://github.com/naval-group/LOTUSim-Unity-modules.git` | `68e56588f5b469201fcb50a90b571e357a89ad9c` |
| UI backend, verrouillée par `flake.lock` | `https://github.com/naval-group/LOTUSim-UI-backend` | `0861406e54844886f55a03479e59ffbe390bc012` |
| UI frontend, verrouillée par `flake.lock` | `https://github.com/naval-group/LOTUSim-UI-frontend` | `5f6775299aa3e9d0bf202445b82e5d5b6c832b0c` |
| xDyn, verrouillé par `flake.lock` | `https://github.com/naval-group/lxdyn` | `363668b2b1f97e3177d2d617586fee6c4a727262` |
| Environnement ROS Nix, verrouillé par `flake.lock` | `https://github.com/lopsided98/nix-ros-overlay` | `2004728f9f450421c9d44b62d6c707a5834139bb` |

Ces SHA sont les versions de base, pas les commits des extensions dataset.
Cloner ces révisions ne suffit pas : appliquer aussi les ajouts et patchs via
l’[installateur](INSTALLATION_COMPLETE.md). La compatibilité avec d’autres bases
doit être testée séparément.

Versions lues dans les fichiers : ROS 2 Jazzy, Gazebo Harmonic, Unity `2022.3.18f1` et HDRP `14.0.10`. Conserver `flake.lock`, `Packages/manifest.json` et `Packages/packages-lock.json` avec l'export ; le manifeste Unity utilise une URL Git non épinglée pour ROS-TCP-Connector, dont la résolution précise appartient au lockfile.

Installer le noyau dans un dossier `LOTUSim` et Unity dans son dossier frère `LOTUSim-Unity-modules`. Les chemins de cet inventaire sont relatifs à ces deux racines, indépendamment du poste d’origine.

## 2. Quels changements sont réellement nécessaires ?

- Dashboard de consultation, suivi des sorties RGB et préparation de campagnes manuelles : aucun nouveau service C++ n'est nécessaire au simple démarrage de l'interface. Les scripts Python/JS et l'adaptateur Unity constituent cette couche. Afficher le dashboard ne démarre pas Gazebo, xDyn ou Unity.
- Scénarios YAML classiques avec création/suppression fiable dans Unity : reprendre les correctifs de synchronisation de `ScenarioManager`, de détection des créations/suppressions de `RenderPlugin` et de déplacement initial d'`EntitySpawner` ; leurs fichiers sont précisés ci-dessous.
- Campagnes connectées où LOTUSim est l'autorité des trajectoires : reprendre l'ensemble fonctionnel de 13 fichiers C++/build ci-dessous, ainsi que le monde et les modèles/scénarios de données correspondants. Ne pas prendre uniquement `dataset_timeline.cpp` ou uniquement le nouveau service.
- Captures par capteur Gazebo avec Mesa dans un conteneur sans GPU : ajouter, si nécessaire, les adaptations d'environnement `flake.nix`/`mise.toml`. Elles ne font pas partie du protocole dataset Unity.

Le diff du noyau contient 13 fichiers déjà suivis modifiés : 10 fichiers fonctionnels sous `systems/` et 3 fichiers d'environnement à la racine. Trois nouveaux fichiers fonctionnels s'y ajoutent, soit 13 fichiers dans le groupe fonctionnel complet. Les modèles, mondes et scénarios ajoutés sont des assets, pas des modifications des interfaces C++ publiques ou des messages ROS.

## 3. Groupe fonctionnel à reprendre intégralement

### Construction : 2 fichiers modifiés

| Fichier | Changement exact et nécessité |
| --- | --- |
| `systems/lotusim_mas/CMakeLists.txt` | Ajouter `find_package(std_srvs REQUIRED)` et `find_package(nlohmann_json REQUIRED)` ; compiler `src/dataset_timeline.cpp` dans `multi_agent_system_plugin` ; lier `nlohmann_json::nlohmann_json` ; déclarer/exporter `std_srvs` et `nlohmann_json`. Sans cela le code ajouté n'est pas construit ou ses dépendances ne sont pas résolues. |
| `systems/lotusim_mas/package.xml` | Déclarer `<depend>std_srvs</depend>` et `<depend>nlohmann_json</depend>`. `std_srvs` était déjà employé pour l'arrêt ; sa dépendance doit néanmoins être explicite. |

Le `flake.nix` de référence contient déjà `std-srvs`, `nlohmann_json` et `yaml-cpp` dans ses dépendances. Le patch Mesa n'est donc pas requis pour trouver ces bibliothèques.

### Modèle de données et validation : 2 fichiers modifiés, 1 nouveau

| Fichier | Changement exact et nécessité |
| --- | --- |
| `systems/lotusim_mas/include/lotusim_mas/scenario_types.hpp` | Ajouter `Agent::Trajectory`, son `std::optional`, les vecteurs centre/vitesse ENU, les instants centre/début/fin, le taux de virage et les bornes du virage ; ajouter `ScenarioConfig::DatasetSequence` avec `plan_id`, `observer`, `fps`, `frames`. Les scénarios non dataset gardent ces champs optionnels absents. |
| `systems/lotusim_mas/src/scenario_parser.cpp` | Lire et valider `dataset_sequence`/`trajectory`, rejeter les écrivains concurrents physique/waypoints, les IDs invalides, doublons, valeurs non finies, vitesses/durées/virages hors limites et l'observateur absent. Refuser une trajectoire sans séquence dataset. `fromString` attrape aussi les erreurs de validation standard. Sans ce fichier, le YAML exporté n'a pas le sens attendu et pourrait être interprété comme un scénario classique. |
| `systems/lotusim_mas/include/lotusim_mas/dataset_motion.hpp` — nouveau | Fonction C++17 `sampleMotion` : trajectoire rectiligne ou à vitesse angulaire constante, orientation issue de la vitesse, et raccords tangents avant/après un virage borné. Unités : mètres, secondes, m/s, degrés/s ; yaw retourné en radians. C'est une cinématique de dataset, pas une dynamique aéronautique ou navale. |

Bornes réellement appliquées par le parseur : `fps` de 1 à 60 ; `frames` de 1 à 36 000 ; 1 à 41 agents, observateur inclus ; noms non vides limités à lettres ASCII, chiffres et `_` ; norme de vitesse au plus 350 m/s ; coordonnées centrales de module au plus 1 000 000 m ; vie dans la durée de la séquence ; observateur présent sur toute cette durée ; taux de virage de module au plus 5 degrés/s et angle total de module au plus 45 degrés. Les deux bornes d'un virage borné sont obligatoires ensemble, ordonnées et dans la vie de l'agent, avec l'instant centre à l'intérieur. Ne pas extrapoler ces bornes à la validité physique d'un scénario réel.

### Exécution dataset : 2 nouveaux fichiers

| Fichier | Changement exact et nécessité |
| --- | --- |
| `systems/lotusim_mas/include/lotusim_mas/dataset_timeline.hpp` — nouveau | Classe `DatasetTimeline`, jeton de propriété, suivi des entités de la campagne, numéro d'étape et dernier instantané JSON. API `advance`, `describe`, `clear`. Appels limités au thread `PreUpdate` Gazebo. |
| `systems/lotusim_mas/src/dataset_timeline.cpp` — nouveau | Refuser les collisions de noms avant création ; créer/supprimer selon la fenêtre `[start_seconds, end_seconds)` ; exiger un modèle SDF statique ; calculer la pose ENU, écrire la composante ECM `Pose`, la marquer changée puis relire la pose effective ; retourner poses/vitesses/IDs dans le JSON. Étapes strictement successives, réessai de la dernière étape idempotent. `clear` cible seulement les entités de cette timeline, pas toutes les entités du spawner. |

Le moteur maintient la pose entre deux demandes du client. L'instant dataset est `frame / fps`, distinct du temps global Gazebo transmis dans `worldTimeSeconds`. La gravité nulle ne remplace pas l'exigence de modèles SDF `<static>true</static>` ; une entité dynamique est refusée.

### Services ROS et accès ECM : 3 fichiers modifiés

| Fichier | Changement exact et nécessité |
| --- | --- |
| `systems/lotusim_mas/include/lotusim_mas/scenario_manager.hpp` | Inclure la timeline et ajouter le mutex, la file d'opérations, le temps monde, `processPendingRequests`, `enqueueRequest`, `handleDataset`, la timeline active et le service `dataset_control`. Interdire aussi le déplacement de l'objet qui possède les callbacks et le mutex. |
| `systems/lotusim_mas/src/scenario_manager.cpp` | Transformer les callbacks de `launch_scenario`/`stop_scenario` en demandes différées avec réponse envoyée après exécution. Ajouter `dataset_control`, la file protégée et son drainage dans l'ordre. Au lancement d'un YAML dataset, créer la timeline et l'étape 0, retourner le descriptif JSON au lieu du texte ancien. Au stop, nettoyer seulement la timeline active. Exposer les capacités avant tout lancement et protéger `step`/`stop` par le jeton `runId`. |
| `systems/lotusim_mas/src/multi_agent_system.cpp` | Dans `PreUpdate`, appeler `m_scenario_manager->processPendingRequests(std::chrono::duration<double>(_info.simTime).count())` avant le traitement MAS existant. Sans cet appel, la file n'est jamais exécutée et les services différés ne répondent pas. |

Pourquoi ces trois fichiers vont ensemble : le nœud ROS tourne dans un `MultiThreadedExecutor` séparé. Les callbacks ne doivent pas créer, déplacer ou supprimer les entités ECM depuis ce thread ROS ; ils déposent une opération exécutée dans `PreUpdate`. Le verrou est relâché avant l'exécution. Les réponses de service sont donc retardées jusqu'au passage de Gazebo dans cette phase. Si la boucle de mise à jour Gazebo ne tourne plus, le client peut expirer même si le service est découvert.

### Fiabilité spawn et représentation Unity : 3 fichiers modifiés

| Fichier | Changement exact et nécessité |
| --- | --- |
| `systems/lotusim_mas/src/entity_spawner.cpp` | Dans `moveEntity`, vérifier explicitement la présence de la composante `Pose`, retourner `false` si absente, puis appeler `SetComponentData` sans traiter une pose inchangée comme un échec. Le booléen retourné par Gazebo n'implique pas une erreur lorsque la valeur demandée est identique ; la position initiale `(0,0,0)` est donc valide. |
| `systems/render_interface/include/render_interface/render_plugin.hpp` | Ajouter l'interface `gz::sim::ISystemUpdate` et la méthode `Update`. |
| `systems/render_interface/src/render_plugin.cpp` | Garder `customPreUpdates` dans `PreUpdate`, déplacer les parcours `EachNew`/`EachRemoved` vers `Update`, ajouter la garde `Name` absent lors d'une suppression et enregistrer `ISystemUpdate` dans `GZ_ADD_PLUGIN`. Cela place la découverte des créations après les créateurs `PreUpdate` ; les nouveaux modèles ne sont plus ratés selon l'ordre des plugins. Les commandes CREATE/DELETE et les poses de rendu demeurent disponibles aux clients classiques. |

L'exclusion de l'observateur du rendu standard ne nécessite pas une modification C++ supplémentaire : `DatasetLotusimScenario.cs` exporte déjà `render_interface: {enabled: false, ...}` pour `ObserverBoat`, et `RenderPlugin` respecte `publish_render`. La source dataset Unity reçoit néanmoins cet observateur dans l'instantané ECM et instancie sa représentation dédiée. Les masques d'exclusion de la coque/caméra et les annotations visibles sont des fonctions Unity, pas des sorties du noyau Gazebo.

## 4. Contrat de service requis à l'exécution

Le type existant `interfaces/lotusim_msgs/srv/String.srv` reste inchangé : requête `string data`, réponse `bool success` puis `string message`. Les commandes dataset sont du JSON dans `data` ; les résultats JSON sont dans `message`. Aucun nouveau `.msg`/`.srv` n'est nécessaire côté noyau pour la timeline.

| Service / opération | Requête utile | Réponse / garanties |
| --- | --- | --- |
| `/lotusim/dataset_control`, `capabilities` | `{"operation":"capabilities"}` | Lecture seule, avant ou pendant un autre scénario ; `success=true` et capacités JSON. Ne crée aucun acteur. |
| `/lotusim/launch_scenario` | Nom d'un YAML, par exemple `MaritimeRandomLotusim.yaml`, en texte dans `data` | Refus si un scénario tourne déjà ; pour un YAML dataset, création de l'étape 0 et retour du descriptif avec `runId`. Le texte `Scenario launched: …` est réservé au chemin classique, pas un instantané dataset. |
| `/lotusim/dataset_control`, `inspect` | `{"operation":"inspect"}` | Descriptif de la timeline active, sans jeton requis ; ne contient pas nécessairement les objets du dernier instantané. Refus s'il n'existe pas de dataset actif. |
| `/lotusim/dataset_control`, `step` | `{"operation":"step","runId":"JETON_RECU","frame":0}` | Première requête `frame=0` : renvoie l'instantané mis en cache du lancement. Puis `1, 2, …, frames-1`, successivement. Dernière étape répétée : exactement le même instantané ; sauts, retours en arrière ou frame non entière refusés. |
| `/lotusim/dataset_control`, `stop` | `{"operation":"stop","runId":"JETON_RECU"}` | Nettoie seulement la campagne propriétaire ; un jeton ancien ou incorrect est refusé avant mutation. |

Capacités du module exporté :

```json
{
  "schema": "lotusim-dataset-capabilities-1",
  "snapshotSchema": "lotusim-dataset-step-1",
  "ownedStop": true,
  "steppedTimeline": true,
  "constantTurnTrajectories": true,
  "maxDatasetSpeedMps": 350,
  "boundedTurnTrajectories": true
}
```

Unity vérifie d'abord les schémas, `ownedStop` et `steppedTimeline`, puis, selon le plan, les virages constants/bornés et la vitesse maximale. Un module ancien est refusé avant le lancement. Le client demande une étape, valide les IDs/poses, réalise le rendu et les écritures, puis demande la suivante. Ne pas remplacer l'arrêt propriétaire par `/lotusim/stop_scenario` : cet ancien service reste disponible mais n'applique pas le contrôle `runId` et peut arrêter le scénario actif.

Un instantané `lotusim-dataset-step-1` contient `scenario`, `runId`, `planId`, `observer`, `fps`, `frames`, `frame`, `motionSource`, puis, pour une étape complète, `timeSeconds`, `worldTimeSeconds`, `objects`. Chaque objet contient `instance`, `model`, `entity`, `position {x,y,z}`, `rotation {x,y,z,w}`, `velocity {x,y,z}`. Les coordonnées sont ENU (est, nord, haut) ; Unity effectue la conversion vers son repère. Un `describe` de lancement ne remplace pas la requête `step(0)`.

## 5. Assets nécessaires et choix du monde

Pour la campagne connectée, fournir aussi :

- `assets/worlds/maritime_dataset.world` : monde nommé `lotusim`, MAS, RenderPlugin en ROS2, SceneBroadcaster et UserCommands ; gravité nulle, pas de plugin physique xDyn ni contrôleur de vol.
- Le YAML correspondant dans `assets/scenarios/`, exporté à partir du même plan/configuration Unity : `plan_id`, nombre d'étapes, fps, observateur et catalogue doivent correspondre. Exemples livrés localement : `MaritimeRandomLotusim.yaml`, `MaritimeTrafficAgents.yaml` et catalogues/scopes associés.
- Tous les dossiers `assets/models/<model>` référencés dans le YAML, dont `fremm_observer`. Leurs modèles dataset doivent être statiques ; les variantes visuelles Unity et leurs `.meta` sont à conserver côté Unity.

Ne pas lancer `lotusim.world` et `maritime_dataset.world` simultanément dans le même domaine ROS : ils portent volontairement le même nom de monde et le namespace `/lotusim`.

| Usage | Monde à lancer |
| --- | --- |
| Timeline connectée / trafic / campagnes dataset pilotées par LOTUSim | `mise run sim maritime_dataset.world` |
| Scénarios LOTUSim classiques avec les plugins physiques et capteurs habituels | `mise run sim lotusim.world` |
| Démonstration de capteur Gazebo annoté | `mise run sim --debug annotated_buoy.world`, ou `mise run capture:buoy` si la tâche optionnelle a été reprise |

La scène Unity `defenseScenario` n'est pas le monde Gazebo à choisir. Le fichier `assets/worlds/defenseScenario.world` du noyau charge `AerialMAS`, pas `MultiAgentSystem`, et n'expose donc pas les services de scénario attendus ici.

Le ROS TCP Endpoint est un paquet/workspace séparé du noyau : `mise run build` ne l'installe pas. Le client Unity connecté utilise un seul `ROSConnection` vers le port TCP 10000 usuel et les services ci-dessus ; il n'a pas besoin d'un deuxième socket ou de démarrer les bancs de test. `tests/python/integration/test_dataset_bridge_server.py` est un outil de test isolé, pas le serveur de production.

## 6. Changements optionnels d'installation : 3 fichiers modifiés

| Fichier | Diff local | Quand le reprendre |
| --- | --- | --- |
| `.gitignore` | Ignorer `/artifacts/annotated-buoy/`, `/.venv-vision/`, `/artifacts/vision-models/` ; normaliser la fin de fichier. | Hygiène Git uniquement ; sans effet fonctionnel sur les services ou le dataset. Cela n'ignore pas tous les autres artifacts/cache. |
| `flake.nix` | Dans la dérivation workspace, définir `CMAKE_BUILD_PARALLEL_LEVEL=1`, `MAKEFLAGS=-j1` et `colcon --executor sequential` ; ajouter le wrapper `lotusim-software-render`, sa sortie package et `devShells.software-rendering` avec Mesa llvmpipe/EGL. | Mémoire limitée sous Docker/Rosetta et rendu de capteurs Gazebo sans GPU. Le shell logiciel est optionnel ; le shell par défaut reste inchangé sur ce point. Le dataset Unity rend ses images côté Unity, donc Mesa n'y est pas une exigence. |
| `mise.toml` | Adapter les messages de pilote GL, indiquer le shell CPU et ajouter la tâche `capture:buoy`, qui maintient un abonné `gz topic -e -t /dataset/buoy/boxes`, lance le monde annoté et ne nettoie que son abonné. | Aide au diagnostic / capture Gazebo. Ne fournit pas le service `dataset_control`. |

Attention : la limitation séquentielle ajoutée dans `flake.nix` concerne la construction de la dérivation Nix, pas automatiquement `mise run build`. Le `[tasks.build]` réel exécute `colcon build --merge-install` et les options compile commands ; `--debug` ajoute `--symlink-install` et `-DDEBUG=ON`. Aucune tâche `build:dataset`, `build:mas` ou `dashboard` n'est définie dans ce fichier. Pour sérialiser réellement un build colcon interactif, utiliser explicitement `--executor sequential`, comme ci-dessous.

## 7. Application, construction et vérification

Appliquer les fichiers fonctionnels ensemble sur le clone de base, avec les assets.
Un patch seul ne contient pas les trois nouveaux fichiers de la timeline : ils
sont fournis dans `components/LOTUSim/`. L’installateur contrôle les deux ensembles.
En cas de conflit, comparer les fichiers sans écraser les modifications locales.

Commandes dans le devShell Linux/Nix du dépôt cible, et non directement dans un terminal macOS :

```bash
# Premier build, ou dépendances non encore construites :
CMAKE_BUILD_PARALLEL_LEVEL=1 MAKEFLAGS=-j1 \
  colcon build --merge-install --executor sequential \
  --event-handlers compile_commands+ \
  --cmake-args -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
source install/setup.bash

# Recompilation ciblée une fois le workspace existant :
CMAKE_BUILD_PARALLEL_LEVEL=1 MAKEFLAGS=-j1 \
  colcon build --merge-install --executor sequential \
  --packages-select lotusim_mas render_interface_plugin
source install/setup.bash
```

Le paquet colcon s'appelle bien `render_interface_plugin` (son dossier est `systems/render_interface`) ; il est à recompiler avec MAS puisque son cycle de détection des créations/suppressions a changé. Arrêter volontairement le processus Gazebo à remplacer avant de le relancer : une bibliothèque compilée ne remplace pas celle déjà chargée en mémoire. Ne pas arrêter globalement Docker, Unity ou des sessions non concernées. Aucun redémarrage n'a été effectué pour préparer cet export.

Après démarrage du monde dédié dans le même domaine ROS que l'Endpoint :

```bash
mise run sim maritime_dataset.world

# Depuis un autre shell du même environnement :
ros2 service type /lotusim/dataset_control
ros2 service call /lotusim/dataset_control lotusim_msgs/srv/String \
  '{data: "{\"operation\":\"capabilities\"}"}'
```

Attendre les capacités ci-dessus avant de lancer la campagne Unity. L'absence du service signale un mauvais monde, un module ancien, un chemin de plugin erroné ou un problème de découverte ; l'existence de l'Endpoint TCP seul ne prouve pas que Gazebo tourne. L'absence d'abonnement `renderer_poses` n'est pas une panne du mode dataset, puisque les poses autoritatives y transitent dans les réponses de service.

Tests fournis à rejouer dans un environnement adapté :

```bash
# Test C++ autonome ; produit son exécutable hors des sources.
clang++ -std=c++17 -I systems/lotusim_mas/include \
  tests/native/test_dataset_motion.cpp -o /tmp/test_dataset_motion
/tmp/test_dataset_motion

# Tests natifs ROS/Gazebo ; démarrent leur propre monde isolé.
PYTHONPATH=tools:. python3 tests/python/integration/test_dataset_scenario_lifecycle.py \
  --plugin-dir "$PWD/install/lib" --cycles 8
PYTHONPATH=tools:. python3 tests/python/integration/test_dataset_connected.py \
  --plugin-dir "$PWD/install/lib" --world assets/worlds/maritime_dataset.world
```

Les tests natifs utilisent le domaine ROS 96 et une partition Gazebo propre ; réserver ce domaine aux tests. Ils vérifient notamment CREATE/DELETE, propriété de la campagne, trajectoires ECM réelles, étapes idempotentes et redémarrage. Le test bridge Unity isolé utilise séparément le domaine 97 et le port 10001.

Vérification effectivement exécutée pour cet audit : compilation avec Clang C++17 de `tests/native/test_dataset_motion.cpp` dans un dossier temporaire et succès des assertions de continuité position/vitesse aux raccords, conversion 400 km/h et trajectoire rectiligne historique. Les services live, le build complet Nix/colcon et les captures Unity n'ont pas été relancés lors de cet audit. Les comptes de captures et validations rapportés dans d'anciens guides sont des résultats historiques, pas une nouvelle validation de l'export.

## 8. Hors périmètre et limites importantes

- Ce groupe ne modifie ni les schémas ROS existants, ni la physique xDyn, ni l'API officielle de gestion d'instances UI. L'API classique peut signaler une instance inconnue même quand Gazebo tourne ; le dashboard local d'opérations est un outil distinct.
- Les poses racines sont pilotées par LOTUSim. Vagues, houle, éclairage, capteurs synthétiques IR/vision nocturne, oscillations visuelles et annotation géométrique sont rendus/produits dans Unity. Aucun océan physique Gazebo ou capteur IR calibré n'est ajouté par ces changements.
- L'arrêt propriétaire protège `dataset_control`, pas tous les clients du système : un opérateur utilisant explicitement `stop_scenario` ou des commandes MAS reste capable de modifier la session. Ne pas faire fonctionner plusieurs écrivains de poses sur les acteurs dataset.
- `inspect` n'est pas une opération de lancement et `capabilities` ne doit jamais être remplacé par un lancement spéculatif. En cas de coupure pendant le lancement, la propriété peut être inconnue : faire diagnostiquer la session avant d'envoyer un arrêt générique.
- Les états, modèles volumineux, bibliothèques compilées et caches du poste d'origine ne remplacent pas des sources/versionnements et ne doivent pas être copiés comme une installation portable.
