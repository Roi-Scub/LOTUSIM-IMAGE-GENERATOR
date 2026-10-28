# LOTUSim sur macOS : guide de démarrage Docker → Unity

Ce guide reprend l’installation utilisée sur le poste de Gabriel : macOS Apple Silicon, dépôt LOTUSim monté dans le conteneur `lotusim-dev`, Nix à l’intérieur du conteneur, interface Web LOTUSim, serveur physique xDyn, ROS TCP Endpoint, puis le projet Unity `LOTUSim-Unity-modules`.

Les commandes Nix/ROS/Gazebo ci-dessous s’exécutent **dans le conteneur Linux**, pas directement dans le Terminal macOS. Le projet flake ne fournit pas `aarch64-darwin` pour toutes ses dépendances, notamment xDyn.

## Architecture et ports

```text
Navigateur Mac :8080 ──> Docker :8080       interface Web
Navigateur Mac :5001 ──> Docker :5000       API de l’interface
Unity Mac      :10000 ─> Docker :10000      ROS TCP Endpoint

Gazebo/ROS 2 et xDyn tournent dans le même conteneur :
Gazebo ── WebSocket ws://127.0.0.1:12346 ──> xDyn
```

`12346` est le WebSocket **physique xDyn**, pas l’adresse ROS de Unity. Unity se connecte à l’Endpoint TCP sur `127.0.0.1:10000`. Le backend UI sert en interne son API sur `5000`; dans la configuration Docker de ce poste, elle est publiée sur le Mac en `5001`.

Pour lancer et arrêter les scénarios YAML, il faut démarrer un monde Gazebo qui contient le plugin `MultiAgentSystem`, ici `lotusim.world`. La scène Unity `defenseScenario` est le visualiseur ; ce n’est pas le monde Gazebo à démarrer. Le fichier `assets/worlds/defenseScenario.world` de ce dépôt charge `AerialMAS` et ne contient pas le `MultiAgentSystem` qui expose les services de scénario.

**Attention à la notion d’« instance » de l’API Web :** lancer Gazebo ne crée pas automatiquement un enregistrement `lotusim` dans le backend REST. Si le terminal UI affiche `Instance 'lotusim' not found`, les routes `/instance/lotusim/...` ne peuvent pas encore contrôler le monde. Le README du backend décrit actuellement les routes de création/suppression d’instances comme des stubs ; il n’y a donc pas de commande de démarrage à ajouter à cette procédure pour créer cette instance. Pour démarrer/arrêter un scénario dans cette situation, utiliser directement les services ROS de `MultiAgentSystem` (section 9). L’interface Web/API peut rester ouverte, mais son contrôle de scénario n’est pas disponible tant que son instance n’est pas réellement enregistrée.

## 0. Démarrage du conteneur (Terminal Mac)

Démarrer Docker Desktop, puis vérifier le conteneur et les ports :

```bash
cd "/chemin/projets/LOTUSim"
docker ps -a --filter name=lotusim-dev
docker port lotusim-dev
```

Si le conteneur existe mais est arrêté :

```bash
docker start lotusim-dev
```

Les publications attendues sont `8080/tcp → 8080`, `5000/tcp → 5001` et `10000/tcp → 10000`. Si `docker port` n’affiche pas ces liaisons, le conteneur actuel n’expose pas tous les ports requis ; il faudra le recréer avec ces ports en conservant le montage du dépôt vers `/workspace`. Ne supprime pas l’ancien conteneur avant d’avoir vérifié ses volumes et ses données.

**Si le dépôt a été déplacé sur le Mac :** le conteneur existant conserve l'ancien chemin de montage, même si un terminal est encore ouvert. Vérifier le chemin réel avec :

```bash
docker inspect -f '{{range .Mounts}}{{println .Source "→" .Destination}}{{end}}' lotusim-dev
```

Le chemin source de `/workspace` doit être le dossier réel ci-dessus. Un montage devenu invalide peut provoquer `Current directory does not exist or is not accessible: /workspace`, `cannot get cwd` ou un échec de `docker exec`. Sur ce poste, ajouter un lien symbolique à l'ancien emplacement n'a pas corrigé le problème : Docker Desktop refuse le redémarrage avec `mkdir ...: file exists`. Il faut recréer le conteneur avec le vrai chemin. Sauvegarder d'abord son système de fichiers dans une image locale (`docker commit`), puis garder l'ancien conteneur arrêté en secours ; une image Nix vierge ne conserverait pas les dépendances téléchargées ni le workspace du ROS TCP Endpoint. Le dépôt monté n'est pas inclus dans cette image : ses fichiers restent dans le dossier réel sur le Mac.

Pour un conteneur neuf uniquement, depuis la racine du dépôt, une configuration minimale est :

```bash
docker run -dit --name lotusim-dev \
  -p 8080:8080 \
  -p 5001:5000 \
  -p 10000:10000 \
  --mount "type=bind,source=$PWD,target=/workspace" \
  -w /workspace \
  nixos/nix:2.35.2 sh
```

## 1. Construire le workspace si nécessaire

Chaque terminal de travail utilise son propre `docker exec` et son propre shell Nix. Dans le **Terminal 1 — Gazebo**, ouvrir le shell :

```bash
docker exec -it -w /workspace lotusim-dev sh
nix --extra-experimental-features "nix-command flakes" \
  --option filter-syscalls false develop -c bash
```

Le message `LOTUSim devShell — ROS 2 jazzy / Gazebo Harmonic` confirme qu’on est dans le bon environnement. Dans ce shell, vérifier le build existant :

```bash
test -f /workspace/install/setup.bash && echo "Workspace déjà construit"
```

Si le dépôt vient d’être cloné ou si du code C++ a changé, compiler une fois :

```bash
CMAKE_BUILD_PARALLEL_LEVEL=1 MAKEFLAGS=-j1 mise run build
```

La compilation complète consomme beaucoup de mémoire. Sur ce Mac, les builds parallèles ont déjà été arrêtés par le système (`cc1plus: Killed`). Ne relance pas une compilation si `install/setup.bash` existe et que les sources n’ont pas changé.

## 2. Terminal 1 — lancer le serveur Gazebo

Dans le shell Nix déjà ouvert (sinon refaire les deux commandes `docker exec` et `nix develop`), lancer le monde standard :

```bash
mise run sim lotusim.world
```

Laisser le terminal ouvert : Gazebo est le serveur de simulation. Cette commande tourne sans GUI, ce qui convient quand Unity fournit l’affichage 3D.

Vérifier dans le log de démarrage que Gazebo charge `multi_agent_system_plugin`, `physics_interface_plugin` et `render_plugin`. Si l’on utilise l’interface Web pour démarrer un scénario, `lotusim.world` est essentiel : c’est lui qui expose `launch_scenario` et `stop_scenario`.

`mise run sim --debug lotusim.world` peut n’afficher au départ que le chemin du monde et `GPU driver bridge: none`. Cet avertissement GPU est attendu ici et ne confirme ni n’infirme à lui seul que Gazebo a démarré. Laisser le Terminal 1 ouvert et vérifier depuis le Terminal 5 :

```bash
ps -ef | grep -E '[g]z sim|[g]z-sim'
ros2 node list
ros2 service list | grep -E 'launch_scenario|stop_scenario'
```

Le processus doit rester actif ; la liste ROS doit contenir les nœuds/plugins du monde et les services MAS (normalement `/lotusim/launch_scenario` et `/lotusim/stop_scenario`). Si le processus a disparu ou si ces nœuds/services sont absents, ne lance pas un second `gz sim` tout de suite : récupère les logs Gazebo dans `/tmp/lotus_logs` pour trouver l’erreur de chargement.

## 3. Terminal 2 — lancer le serveur physique xDyn

Dans un nouvel onglet Terminal macOS :

```bash
docker exec -it -w /workspace lotusim-dev sh
nix --extra-experimental-features "nix-command flakes" \
  --option filter-syscalls false develop -c bash
```

Puis démarrer xDyn et laisser ce terminal ouvert :

```bash
xdyn-for-cs /workspace/assets/models/lrauv/lrauv.yml \
  --verbose \
  --websocket-debug \
  --address 127.0.0.1 \
  --dt 0.2 \
  --port 12346
```

Le message `Starting websocket server on 127.0.0.1:12346` est attendu. Si `Address in use` apparaît, un xDyn écoute déjà sur ce port : ne démarre pas un deuxième serveur. Vérifier les terminaux ouverts avant d’arrêter le processus existant.

Le scénario doit demander le même URI xDyn, par exemple `ws://127.0.0.1:12346`, et le nom d’interface/propulseur attendu. Pour le scénario LRAUV déjà corrigé, la section de domaine doit utiliser `surface` en minuscules (pas `SURFACE`) et `renderer_type: lrauv` :

### Corriger `SURFACE` dans `TestScenario.yaml`

Le parser LOTUSim attend que la valeur de `domain` soit exactement `surface` en minuscules. `init_domain: surface` ne suffit pas : si la ligne reste `domain: SURFACE`, le domaine n’est pas trouvé et le chargement de la physique échoue. Dans le conteneur, corriger le fichier du dépôt avant de relancer le scénario :

```bash
sed -i 's/SURFACE/surface/g' /workspace/assets/scenarios/TestScenario.yaml
grep -nE 'init_domain:|domain:' /workspace/assets/scenarios/TestScenario.yaml
```

Vérifier que les deux lignes affichent `surface`. Si le scénario est déjà lancé, l’arrêter puis le relancer pour que Gazebo recharge le YAML ; une modification du fichier ne change pas un bateau déjà créé.

```yaml
physics_interface:
  init_domain: surface
  domains:
    - domain: surface
      interface_type: XDynWebsocket
      interface_params:
        uri: ws://127.0.0.1:12346
        thrusters:
          - name: propeller
render_interface:
  enabled: true
  renderer_type: lrauv
```

Ne remplace pas `lrauv` par `TestVessel` : Unity charge ses prefabs de rendu à partir de `renderer_type`.

## 4. Terminal 3 — lancer l’interface Web et son API

Dans un troisième onglet, entrer dans le même shell Nix, puis lancer ensemble le backend et le frontend :

```bash
docker exec -it -w /workspace lotusim-dev sh
nix --extra-experimental-features "nix-command flakes" \
  --option filter-syscalls false develop -c bash
nix --extra-experimental-features "nix-command flakes" \
  --option filter-syscalls false run .#ui
```

Laisser le terminal ouvert. Ouvrir ensuite [http://localhost:8080](http://localhost:8080) dans le navigateur Mac. Le flake indique que l’API écoute en interne sur le port `5000`; la liaison Docker `5001:5000` rend cette API accessible à l’interface via `http://localhost:5001`.

Test rapide depuis un **Terminal macOS** (pas le shell Docker) :

```bash
curl -i --max-time 5 http://localhost:5001/health
```

Une réponse HTTP de l’API confirme que le backend répond. Si ça expire ou refuse la connexion, vérifier les ports avec `docker port lotusim-dev` et les erreurs dans le Terminal 3. Ne reclique pas plusieurs fois sur « Lancer » si une requête reste en attente : elle a pu être reçue même si l’interface n’a pas reçu sa réponse.

Pour inspecter l’instance que le frontend demande, depuis un Terminal macOS :

```bash
curl -i --max-time 5 http://localhost:5001/instances
curl -i --max-time 5 http://localhost:5001/instance/lotusim
```

Si le terminal UI affiche `Instance 'lotusim' not found` ou si `/instances` ne contient pas `lotusim`, ne considère pas le lancement Web comme opérationnel ; passe au contrôle ROS direct de la section 9.

## 5. Terminal 4 — ROS TCP Endpoint pour Unity

Dans un quatrième onglet, entrer dans le shell Nix puis sourcer le workspace LOTUSim :

```bash
docker exec -it -w /workspace lotusim-dev sh
nix --extra-experimental-features "nix-command flakes" \
  --option filter-syscalls false develop -c bash
source /workspace/install/setup.bash
```

`ros_tcp_endpoint` est un paquet séparé : `mise run build` ne l’installe pas. Chercher d’abord si son workspace existe déjà ailleurs :

```bash
find /root/.local/share/lotusim /workspace \
  -path '*/install/share/ros_tcp_endpoint/package.xml' -print 2>/dev/null
```

S’il n’existe pas, le cloner et le construire dans un workspace séparé :

```bash
mkdir -p /root/.local/share/lotusim/ros_tcp_endpoint_ws/src
cd /root/.local/share/lotusim/ros_tcp_endpoint_ws/src
if [ ! -d ros_tcp_endpoint ]; then
  git clone https://github.com/naval-group/LOTUSim-Unity-ros-tcp-endpoint.git ros_tcp_endpoint
fi
cd /root/.local/share/lotusim/ros_tcp_endpoint_ws
colcon build --merge-install --packages-select ros_tcp_endpoint
```

Sourcer ensuite le résultat (qu’il ait déjà été présent ou que tu viennes de le compiler) :

```bash
source /root/.local/share/lotusim/ros_tcp_endpoint_ws/install/setup.bash
ros2 pkg prefix ros_tcp_endpoint
```

`ros2 pkg prefix` doit afficher un chemin. Si `colcon build` échoue, conserver et transmettre la première erreur de compilation ; ne pas sourcer un dossier `install/` vide ou un ancien clone qui ne contient pas le paquet.

Démarrer ensuite le serveur, et laisser ce terminal ouvert :

```bash
ros2 run ros_tcp_endpoint default_server_endpoint \
  --ros-args -p ROS_IP:=0.0.0.0 -p ROS_TCP_PORT:=10000
```

Le log attendu est `Starting server on 0.0.0.0:10000`. `0.0.0.0` est l’adresse d’écoute dans le conteneur ; dans Unity sur le Mac, l’adresse de destination reste `127.0.0.1`, port `10000`.

## 6. Unity — se connecter avant de lancer le scénario

1. Ouvrir le projet `LOTUSim-Unity-modules` dans Unity Hub.
2. Ouvrir la scène `defenseScenario` et passer en Play.
3. Utiliser la connexion spectateur avec ROS IP `127.0.0.1` et port `10000` (si ces champs sont visibles). Le namespace utilisé par le monde LOTUSim est `lotusim` ; ne mets pas `defenseScenario` simplement parce que c’est le nom de la scène Unity.
4. Vérifier que le Terminal 4 affiche `Connection from ...` et des abonnements à `lotusim/renderer_poses` et `lotusim/renderer_cmd`.
5. **Après la connexion Unity**, lancer le scénario. Si le backend UI connaît l’instance, tu peux utiliser l’interface Web. Si elle affiche `Instance 'lotusim' not found`, utiliser le service ROS direct décrit en section 9 ; dans les deux cas, lancer le scénario seulement après la connexion Unity. L’ordre est important : l’événement de création du modèle doit être publié quand Unity est déjà abonné.

Les avertissements sur `tf2_msgs` ou les noms de publishers dupliqués ne prouvent pas à eux seuls que le rendu a échoué. Vérifier d’abord l’arrivée d’un `renderer_cmd` de création, son `renderer_obj_name: lrauv`, puis la présence de l’objet dans la Hierarchy Unity pendant Play.

## 7. Terminal 5 — vérifier les topics et envoyer une commande de propulsion

Ouvrir un cinquième onglet et entrer dans le shell Nix comme précédemment. Puis :

```bash
source /workspace/install/setup.bash
source "$(nix --extra-experimental-features "nix-command flakes" \
  --option filter-syscalls false build .#messages --no-link --print-out-paths)/setup.bash"
```

Vérifier les interfaces :

```bash
ros2 node list
ros2 service list | grep -E 'launch_scenario|stop_scenario'
ros2 topic list -t | grep -E 'vessel_cmd_array|renderer_cmd|renderer_poses'
ros2 topic info --verbose /lotusim/vessel_cmd_array
```

Ne passe pas le type `lotusim_msgs/msg/RendererCmd` à `ros2 topic info` : cette commande attend un **nom de topic**, par exemple `/lotusim/renderer_cmd`. De même, `ros2 topic echo ... --once` attend indéfiniment s’il n’y a aucun publisher/message ; démarre d’abord la simulation et le scénario, ou lance l’écho sans `--once` avant le lancement.

Si `/lotusim/vessel_cmd_array` est `Unknown topic` et que les topics renderer indiquent `Publisher count: 0`, les sorties montrent que le plugin Gazebo n’est pas actuellement visible dans le graphe ROS. Les abonnés `renderer_cmd_RosSubscriber` sont Unity via le TCP Endpoint ; ils ne prouvent pas que Gazebo tourne. Vérifier que le Terminal 1 garde bien le processus `gz sim` actif et que `ros2 node list` contient les plugins de `lotusim.world` avant d’envoyer une commande de propulseur.

Pour observer la commande de création en direct, lancer aussi `ros2 topic echo /lotusim/renderer_cmd` **avant** de (re)lancer le scénario. Unity doit être connectée avant ce lancement pour recevoir l’événement de création.

Le nom observé dans les poses doit correspondre à celui de la commande. Dans ton scénario actuel, le nom observé était `CommandoVessel_0`. Envoyer une commande :

```bash
ros2 topic pub --once \
  /lotusim/vessel_cmd_array \
  lotusim_msgs/msg/VesselCmdArray \
  "{cmds: [{vessel_name: 'CommandoVessel', entity: 0, cmd_string: '{\"propeller(rpm)\":200.0,\"propeller(P/D)\":0.88}'}]}"
```

L’écho du topic peut confirmer la réception ROS, mais ce n’est pas à lui seul la preuve que la physique est chargée. Vérifier également les logs du plugin physique et du serveur xDyn.

## 8. Terminal 6 — suivre les logs de scénario, physique et rendu

Dans un onglet macOS séparé, suivre les derniers logs LOTUSim du conteneur :

```bash
docker exec -it lotusim-dev sh -lc '
  logdir=$(find /tmp/lotus_logs -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)
  echo "Logs suivis dans : $logdir"
  tail -F \
    "$logdir/lotusim_mas_plugin.txt" \
    "$logdir/lotusim_physics_interface_plugin.txt" \
    "$logdir/lotusim_render_plugin.txt"
'
```

Les fichiers peuvent varier selon les plugins réellement chargés. Pour lister ceux du dernier répertoire :

```bash
docker exec -it lotusim-dev sh -lc 'find /tmp/lotus_logs -maxdepth 2 -type f | sort | tail -n 40'
```

Interprétation utile :

- `ScenarioManager::handleLaunch ... started` : l’appel a atteint le gestionnaire de scénario.
- `1/1 agents spawned` : l’agent a été créé dans Gazebo.
- `Failed transition to surface` ou `Loading failed` : problème de configuration ou de connexion au serveur physique xDyn.
- `No known entity` : le nom de vaisseau ou l’entité ne correspond pas à un modèle actuellement chargé.
- `renderer_obj_name: lrauv` dans `/lotusim/renderer_cmd` : Unity doit avoir un prefab adressable nommé `lrauv` et avoir été connecté avant l’émission de la commande de création.

## 9. Contrôle direct ROS si l’interface Web ne lance pas le scénario

Le lancement normal de scénario se fait dans l’interface Web **si son instance est connue**. Dans la session décrite ici, le Terminal 3 affiche `Instance 'lotusim' not found`, donc cette voie n’est pas encore opérationnelle. Les services ROS du monde `lotusim.world` permettent de tester et contrôler le scénario indépendamment du registre d’instances de l’API :

```bash
ros2 service list | grep -E 'launch_scenario|stop_scenario'
```

Quand Gazebo a correctement chargé `lotusim.world`, les services devraient être `/lotusim/launch_scenario` et `/lotusim/stop_scenario`. Vérifier d’abord le dossier et le fichier du scénario **dans le même shell Nix** :

```bash
echo "$LOTUSIM_SCENARIOS_PATH"
ls -l "$LOTUSIM_SCENARIOS_PATH"
```

Si `New Scenario.yaml` s’y trouve, lancer un écho des poses dans un second shell ROS (ou utiliser `/demo.yaml` pour un test initial si ce fichier est présent), puis appeler le service :

```bash
ros2 topic echo /lotusim/renderer_poses
```

Dans le Terminal 5, lancer le scénario :

```bash
ros2 service call /lotusim/launch_scenario lotusim_msgs/srv/String \
  "{data: 'New Scenario.yaml'}"
```

Le shell de développement de ce dépôt configure par défaut `LOTUSIM_SCENARIOS_PATH` sur `/workspace/assets/scenarios`. Si `New Scenario.yaml` est uniquement dans `/root/.local/share/lotusim/scenarios`, la commande directe ci-dessus ne le trouvera pas avec cette valeur : utilise le lanceur UI, ou place/configure le fichier dans le répertoire de scénarios effectivement utilisé avant de démarrer Gazebo.

Arrêt direct :

```bash
ros2 service call /lotusim/stop_scenario std_srvs/srv/Trigger "{}"
```

N’utilise pas le lancement Web et le lancement ROS direct en même temps : le gestionnaire refuse de démarrer un second scénario tant que le premier n’est pas arrêté.

## Ordre de démarrage résumé

Garder ces terminaux ouverts pendant toute la simulation :

| Terminal | Processus | Vérification de démarrage |
|---|---|---|
| 1 | Gazebo : `mise run sim lotusim.world` | plugins MAS, physique et render chargés |
| 2 | xDyn port `12346` | `Starting websocket server` |
| 3 | UI/API : `nix ... run .#ui` | UI sur `8080`, API interne `5000` / Mac `5001` |
| 4 | ROS TCP Endpoint port `10000` | `Starting server on 0.0.0.0:10000` |
| 5 | ROS diagnostics / propulsion | topics `/lotusim/...` visibles |
| 6 | `tail -F` des logs LOTUSim | logs scénario, physique et rendu |
| Unity | Play → spectateur → connexion ROS | `Connection from ...` au Terminal 4 |

**Séquence d’une session :** démarrer les terminaux 1 à 4, ouvrir Unity et attendre sa connexion, puis lancer le scénario depuis l’interface Web. Le Terminal 5 sert au diagnostic et aux commandes de propulsion ; le Terminal 6 reste en suivi des logs.

## Arrêter proprement

1. Arrêter le scénario depuis l’interface Web (ou le service ROS, mais pas les deux).
2. Arrêter Unity Play.
3. Dans les terminaux 4, 3, 2 puis 1, faire `Ctrl+C`.
4. Quitter les shells conteneur avec `exit` si nécessaire. Le conteneur peut rester démarré pour la prochaine session.

## Premier test d'image annotée Gazebo

Ce test est indépendant de la session Unity et du scénario naval. Pour une première
bouée avec une image RGB et sa boîte 2D automatique, suivre
[Première image annotée : bouée](first-annotated-image.md). Sur Docker Desktop macOS,
utiliser le shell `.#software-rendering`, puis `mise run capture:buoy` : Mesa rend
sur le CPU, et le lanceur maintient l'abonné nécessaire à la caméra. Les images et
annotations sont enregistrées dans le dépôt, sous `artifacts/annotated-buoy/`.

## Dépannage rapide

Pour construire une chaîne automatique d'images annotées avec l'eau Unity, voir
[Pipeline LOTUSim, Gazebo et Unity](<pipeline-dataset-lotusim-unity.md>).
Le démarrage interactif décrit ici n'est pas encore ce générateur automatique.

| Symptôme | Vérification prioritaire |
|---|---|
| `ros2: command not found` | La commande doit être dans le shell `nix ... develop -c bash`, pas dans le shell `sh` externe. |
| UI : `Instance 'lotusim' not found` | Le serveur UI existe mais son registre ne connaît pas `lotusim`. Démarrer via `/lotusim/launch_scenario` et `/lotusim/stop_scenario` ROS, ou corriger/mettre à jour l’enregistrement d’instance du backend. |
| Topics renderer avec publisher count 0 ; `vessel_cmd_array` inconnu | Gazebo/plugin ROS n’est pas actif ou n’a pas rejoint le même ROS graph. Contrôler `ros2 node list`, les services MAS et la sortie du Terminal 1. |
| Nix indique que `nix-command` ou `flakes` est désactivé | Ajouter `--extra-experimental-features "nix-command flakes"` à la commande Nix. |
| Nix `unable to load seccomp BPF program` | Ajouter `--option filter-syscalls false` à `nix develop`, `nix run` et aux appels Nix de build. |
| UI accessible mais API `localhost:5001` en attente | Tester `curl -i --max-time 5 http://localhost:5001/health`, vérifier `docker port lotusim-dev`, puis lire les logs du Terminal 3. |
| Unity ne reçoit aucune scène/vaisseau | Vérifier port `10000`, connexion de Unity avant le lancement du scénario, puis `renderer_cmd`/`renderer_poses` sous `/lotusim`. |
| `Address in use` sur `12346` | Un serveur xDyn écoute déjà ; ne pas en démarrer un doublon. |
| Le propulseur ne bouge pas | Vérifier `surface` en minuscules, l’URI xDyn `ws://127.0.0.1:12346`, les logs physiques, puis le nom exact dans `/lotusim/renderer_poses`. |
| Scénario non trouvé par l’appel ROS | Vérifier `LOTUSIM_SCENARIOS_PATH` et que `New Scenario.yaml` s’y trouve dans le conteneur. |

Pour le modèle d’architecture du backend et ses routes, voir [LOTUSim UI Backend](https://github.com/naval-group/LOTUSim-UI-backend). Le README LOTUSim documente aussi le démarrage Nix et l’interface Web.
