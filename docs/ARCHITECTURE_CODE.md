# Organisation du code et guide de contribution

Le code applicatif est organisé par responsabilité. Le paquet Python se trouve
dans `components/LOTUSim/tools/lotusim_image_generator/`, le frontend dans
`components/LOTUSim/tools/ops_dashboard_ui/` et les tests dans des dossiers
distincts. Les anciens noms de lancement restent utilisables par Unity et les
installations existantes.

Cette organisation est préparée sur `refactor`. Elle ne recharge pas les projets
sous `runtime/` : le dashboard déjà ouvert continue donc d’utiliser ses sources
installées tant qu’un déploiement explicite n’a pas été validé.

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

La revue et la fusion de `refactor` restent distinctes du déploiement. Ne pas
copier automatiquement cet overlay sur un runtime déjà modifié : l’installateur
attend des clones propres et préserve les fichiers divergents.
