# Architecture du code

Le code applicatif est organisé par responsabilité. Le paquet Python se trouve
dans `components/LOTUSim/tools/lotusim_image_generator/`, le frontend dans
`components/LOTUSim/tools/ops_dashboard_ui/` et les tests dans des dossiers
distincts. Les anciens noms de lancement restent utilisables par Unity et les
installations existantes.

`main` contient les sources courantes. Les projets sous `runtime/` utilisent leur
copie installée : modifier le dépôt ne recharge pas le dashboard ou un moteur ouvert.

## Repères dans le dépôt

```text
scripts/                           commandes d’installation et de développement
tests/tooling/                     tests des commandes du dépôt portable
components/LOTUSim/
  tools/
    lotusim_image_generator/       logique Python, imports par nom de paquet
      assets/                     bibliothèque, conversion et intégration 3D
      campaigns/                  paramètres et calendriers des captures
      dashboard/                  serveur HTTP, collecte, état et rapports
      engines/                    contrats, préparation et adaptateurs moteurs
        templates/                scripts autonomes destinés au moteur
      telemetry/                  suivi des processus et du rendu
      traffic/                    planification, trajectoires et bibliothèque
      vision/                     analyse RGB, masques, comparaison et confiance
      paths.py                    chemins relatifs à l’installation
    ops_dashboard_ui/
      index.html                  structure de l’interface
      resources.json              correspondance URL publique vers fichier
      shell/                      navigation, journal, alertes et styles communs
      features/
        assets/                   modèles 3D et visionneuse
        settings/                 paramétrage des campagnes
        traffic/                  lecture et édition du trafic
      vendor/                     bibliothèques tierces et leurs licences
    ops_dashboard.py              ancien point de lancement, sans logique métier
    rgb_observer.py               ancien point de lancement, sans logique métier
    ...                           autres entrées de compatibilité
  scripts/
    gazebo_image_to_png.py         conversion ponctuelle d’un message image
  tests/
    python/                       régressions regroupées par domaine
      assets/ campaigns/ dashboard/ engines/ traffic/ vision/
      integration/                bancs Gazebo et ROS à lancer explicitement
    web/                          tests Node des calculs, du DOM et des contrats
      support/                    chemins et analyseurs partagés entre tests
    native/                       tests C++ des trajectoires
    qa/
      browser/                    parcours et captures de contrôle navigateur
      unity/                      contrôles de compilation ciblés
```

Les trois scripts fournis par le socle officiel, `check.sh`, `gl-wrapper.sh` et
`test_assets_path.sh`, restent à leur emplacement dans les clones complets :
Mise et la construction les appellent directement. Ils ne sont pas recopiés ou
déplacés artificiellement dans cet overlay.

## Choix d’architecture

Le paquet utilise des modules Python en `snake_case`, des classes en `PascalCase`
et des constantes en `UPPER_SNAKE_CASE`. Les chemins d’import indiquent le métier :
`lotusim_image_generator.traffic.library` désigne ainsi la bibliothèque de plans,
sans ambiguïté avec les modèles 3D de `assets.library`.

Le paquet reste sous `tools/` pour conserver l’installation par overlay dans
LOTUSim, sans imposer une installation `pip` supplémentaire. Un agencement
`src/` est utile pour une distribution Python installable, mais exigerait ici une
étape de construction et d’installation pour les clones et les workers. Cette
distinction suit les principes décrits par le
[guide PyPA](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/).

Le dashboard est une application Web locale sans framework imposé. Le serveur
HTTP traduit les requêtes vers les services des domaines ; il ne doit pas
contenir les calculs de trajectoire ou les conversions 3D. `dashboard.state` gère
le cache de supervision et `dashboard.report_assets` les chemins et liens des
rapports. La séparation par fonctionnalités du frontend évite un MVC artificiel
et conserve le comportement des scripts existants.

Les URL `/app.js`, `/settings.js`, `/traffic.js` et les autres ressources publiques
ne changent pas. `resources.json` permet de ranger les sources sans renommer les
adresses utilisées par le navigateur. Le serveur conserve une liste explicite
des routes et ses contrôles de fichiers ; ce fichier n’est pas une nouvelle API.

Les fichiers C# conservent leurs noms de types, champs sérialisés et `.meta` Unity.
Les scènes, prefabs, interfaces ROS et noms d’objets ne sont pas renommés pour
faire correspondre le rendu à une convention Python.

## Organisation des modules Unity

Les ajouts Unity sont séparés en **41 scripts d’exécution**, **29 scripts
d’outillage de l’éditeur** et **14 fichiers de vérification**. Les fichiers C# et
leurs `.meta` sont déplacés ensemble, sans changement de contenu, de type, de
namespace, de menu ou de champ sérialisé.

```text
Assets/
  Scripts/Dataset/
    Annotations/           masques, visibilité, reconnaissance et annotations
    Campaigns/             configurations et exécution des campagnes
    Capture/               export PNG, séquences, galeries et capteurs
    Environment/           houle, mouvements, météo et éclairages
    Integration/           protocole et source de positions LOTUSim
    Models/                catalogues, modèles importés et animations
    Sensors/               caméra embarquée et passes spectrales
    Traffic/               plans coopératifs et contrôle de la trajectoire
  Editor/Dataset/
    Campaigns/             création des scènes et configurations de génération
    Import/                importeurs du dashboard et de la bibliothèque de plans
    Models/Aerial/         constructeurs et géométrie des objets aériens
    Models/Marine/         constructeurs et géométrie des objets maritimes
    Monitoring/            suivi local et outils de validation RGB
  Tests/Editor/Dataset/
    Annotations/ Campaigns/ Capture/ Environment/ Integration/ Models/ Sensors/
  Resources/Dataset/       shaders InstanceMask et SpectralCapture inchangés
```

Les fichiers partiels d’un même constructeur restent regroupés : par exemple
`AerialLibraryBuilder`, sa géométrie, ses modèles, ses exports et ses contrôles.
Les vérifications de géométrie associées à ces constructeurs restent avec eux.
Les autres fichiers `*Tests.cs` sont désormais sous `Tests/Editor/Dataset/`.

Le nom spécial `Editor` reste présent dans les chemins des outils et des tests.
Les scripts d’exécution restent dans `Assembly-CSharp` et les outils dans
`Assembly-CSharp-Editor`. Aucun `.asmdef` ou `.asmref` n’est ajouté : les ajouts
référencent encore des types du projet officiel dans ses assemblages prédéfinis.
Cette réorganisation n’est donc pas une extraction en package UPM.

Les identifiants des scripts et leurs paramètres d’import restent dans leurs
`.meta` d’origine. Seuls les nouveaux dossiers reçoivent de nouveaux identifiants.
Les scènes, prefabs, configurations, shaders, modèles et messages ROS ne changent
pas. Cette précaution suit les règles Unity sur les
[métadonnées des assets](https://docs.unity3d.com/2022.3/Documentation/Manual/AssetMetadata.html)
et les [dossiers de compilation](https://docs.unity3d.com/2022.3/Documentation/Manual/ScriptCompileOrderFolders.html).

### Contrôler les déplacements

`references/unity-code-layout.json` conserve l’ancien chemin, le nouveau chemin,
le GUID et l’assemblage de chaque script déplacé. Le contrôle refuse un GUID
modifié ou dupliqué, une copie obsolète, des métadonnées manquantes, un changement
d’assemblage ou des scripts hors des groupes déclarés. Il fait partie du contrôle
général d’architecture :

```bash
python scripts/check_unity_layout.py
python scripts/check_architecture.py
```

Le compilateur hors éditeur utilise cette table pour rapprocher les anciens
chemins présents dans les caches des nouveaux fichiers, après vérification des
GUID. Il ne remplace pas un fichier simplement parce que son nom ressemble à un
autre. Les réponses de compilation du projet ouvert restent en lecture seule.

```bash
python scripts/check_unity_refactor.py \
  --unity runtime/LOTUSim-Unity-modules \
  --editor /Applications/Unity/Hub/Editor/2022.3.18f1/Unity.app/Contents
```

Cette commande compile les sources d’exécution et de l’éditeur avec les
références déjà installées. Elle ne lance pas Unity, n’importe aucune scène et
ne valide pas le rendu GPU. Les vérifications exposées par les menus restent des
actions manuelles ; le fichier NUnit conditionnel n’est pas exécuté par ce
contrôle de compilation.

### Conserver la compatibilité du dashboard

L’importeur principal est désormais
`Assets/Editor/Dataset/Campaigns/DatasetManualCampaignBuilder.cs`. Le registre
moteur accepte aussi son ancien emplacement
`Assets/Editor/DatasetManualCampaignBuilder.cs`, pour ne pas désactiver une
installation encore organisée comme avant. Les nouveaux paquets de préparation
indiquent le chemin réellement détecté. Les noms des classes et menus d’import
restent identiques.

Pour déployer cette organisation, utiliser des clones propres et l’installateur.
Ne pas recopier les nouveaux dossiers sur
une ancienne installation en conservant les anciennes sources : cela créerait
des classes et des GUID en double. Les projets modifiés de l’utilisateur doivent
faire l’objet d’une migration explicite, pas d’un écrasement récursif.


## Dépendances entre domaines

Le dashboard assemble les domaines. Les paramètres de campagne utilisent les
contrats moteurs et le catalogue d’objets. Le trafic utilise ces paramètres et
la télémétrie. L’analyse RGB reste séparée du serveur Web et accède seulement à
ses modules de vision et à la télémétrie. Les modules métier n’importent ni les
tests ni les commandes du dépôt.

`scripts/check_architecture.py` contrôle ces frontières sur les imports, y
compris les imports différés à l’intérieur des fonctions. Il contrôle également
les noms des modules, les initialiseurs de paquets, les fichiers statiques et
l’absence de nouvelles suites de tests dans `scripts/`.

Les anciens fichiers Python directement sous `tools/` ne contiennent plus de
classes ou fonctions métier. Ils délèguent au paquet et conservent l’identité du
module importé, y compris pour les anciennes intégrations et les mocks de test.
Le nouveau code métier doit importer le paquet, pas ces entrées historiques.

## Trajectoires et provenance

`traffic.kinematics` est la source commune des équations utilisées par le
planificateur et l’éditeur de plans. Ce module pur travaille en mètres et secondes,
sans stockage, interface Web ou connexion au simulateur. Les axes internes sont
X est, Y haut, Z nord ; l’éditeur expose les coordonnées ENU explicitement.

L’empreinte `plannerSha256` des nouveaux plans couvre `planner.py` **et**
`kinematics.py`, indépendamment du chemin d’installation. Un changement des
équations ne peut donc pas conserver la même provenance. Les plans déjà archivés
ne sont pas réécrits : leur revalidation reste une action explicite. Cette
réorganisation ne transforme pas les trajectoires planifiées en navigation
réactive ou en conformité COLREG certifiée.

## Tests et assurance qualité

QA signifie **Quality Assurance**, ou **assurance qualité**. Les tests automatisés
vérifient des résultats et des contrats ; les parcours QA vérifient aussi la
présentation et l’usage dans un vrai navigateur. Les scripts QA sont versionnés
dans `tests/qa/`, mais leurs PNG et rapports vont dans `artifacts/qa/`, ignoré par Git.

Depuis la racine du dépôt, utiliser un environnement de développement Python
3.10 ou plus récent, puis installer les dépendances des tests :

```bash
python3 -m venv .venv-dev
source .venv-dev/bin/activate
python -m pip install -r requirements-dev.txt -r requirements-test.txt
npm ci --ignore-scripts
python scripts/check_architecture.py
python scripts/run_tests.py
```

Le lanceur exécute les tests applicatifs et les tests du dépôt dans des processus
séparés pour éviter que leurs paquets `tests` se masquent. Il ne lance ni moteur,
ni navigateur, ni simulateur. Les tests HTTP créent seulement leurs propres
serveurs éphémères avec des données de fixture.

Pour travailler sur une partie seulement :

```bash
python scripts/run_tests.py --suite python --pattern 'test_traffic_*.py'
python scripts/run_tests.py --suite web
python scripts/run_tests.py --suite tooling
```

Depuis un clone LOTUSim installé, sans le lanceur du dépôt exporté :

```bash
PYTHONPATH=tools:. python -m unittest discover -s tests/python -t . -p 'test_*.py'
node tests/web/test_capture_cadence_ui.cjs
```

Les bancs sous `tests/python/integration/` ne démarrent leurs processus que si
leur commande est appelée explicitement. Ils utilisent des domaines ROS, ports
et partitions isolés. Les contrôles navigateur sont également manuels ; par
exemple, depuis le clone LOTUSim sur un Mac disposant de Chrome et du dashboard :

```bash
node tests/qa/browser/operations_ux.cjs
```

Ce parcours charge les sources locales déplacées, utilise des états de fixture
et bloque les écritures vers le dashboard. Il ne valide pas le rendu GPU Unity.

## Ajouter ou déplacer un fichier

Placer une règle métier dans son domaine, un test dans `tests/` et une commande
d’exploitation dans `scripts/` ou dans un point de lancement `tools/`. Ne pas
introduire un module `utils` généraliste pour mélanger des responsabilités sans
lien. Partager une fonction dans le domaine qui en possède la règle, comme les
équations de trajectoire, plutôt que la copier.

Après une modification, lancer les tests et les contrôles de style décrits dans
[CONVENTIONS_CODE.md](CONVENTIONS_CODE.md). Après un déplacement, vérifier aussi
les imports, chemins de workers, ressources Web, exemples de commandes et
installations depuis des clones propres. Rafraîchir l’inventaire avant commit :

```bash
python scripts/refresh_manifest.py --write
python scripts/verify_export.py
git diff --check
```

Après un renommage ou une suppression volontaire, ajouter `--prune-missing` à
`refresh_manifest.py --write` pour retirer les anciens chemins absents. Sans
cette option, un fichier inventorié manquant reste une erreur. Les chemins
dangereux et les liens symboliques restent refusés même avec cette option.

Pour les commits et les versions, suivre le [guide de contribution](CONTRIBUTION.md).
Ne pas copier automatiquement l’overlay sur un runtime déjà modifié :
l’installateur attend des clones propres et préserve les fichiers divergents.
