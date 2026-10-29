# Contribuer

`main` contient la version courante. Pour une évolution, ouvrir une branche courte
`feature/...`, `fix/...` ou `docs/...`, puis une pull request. Les tags publiés sont
immuables ; `v1.0.0` reste le point de départ de la première version majeure.

## Installer les outils

Depuis la racine, avec Python 3.10+ et Node.js :

```bash
python3 -m venv .venv-dev
source .venv-dev/bin/activate
python -m pip install -r requirements-dev.txt -r requirements-test.txt
npm ci --ignore-scripts
```

Ce sont des dépendances de développement, pas des prérequis du dashboard.
Voir les [conventions](CONVENTIONS_CODE.md) pour le formatage natif C#/C++.

## Modifier et tester

La logique Python est dans `components/LOTUSim/tools/lotusim_image_generator/`,
le frontend dans `components/LOTUSim/tools/ops_dashboard_ui/`. Les ajouts Unity
sont dans `components/LOTUSim-Unity-modules/Assets/`. Ne pas changer les GUID `.meta`,
champs sérialisés ou messages ROS pour un simple renommage.

Les fichiers déjà présents dans les dépôts officiels sont fournis par correctifs
sous `patches/`, avec leurs copies complètes dans `references/modified-sources/`.
Après modification d’une copie, vérifier et synchroniser les correctifs :

```bash
python scripts/sync_source_patches.py \
  --core runtime/LOTUSim --unity runtime/LOTUSim-Unity-modules --write
python scripts/check_architecture.py
python scripts/run_tests.py
python scripts/format_sources.py --check
```

Les contrôles courants ne lancent ni Unity ni Gazebo. Les bancs natifs et les
parcours navigateur sont séparés : voir l’[architecture](ARCHITECTURE_CODE.md).
Pour les modèles, vérifier aussi leur licence et le rendu dans le moteur cible.

## Préparer un commit

```bash
python scripts/refresh_manifest.py --write
python scripts/verify_export.py
git diff --check
git status --short
```

Après une suppression ou un déplacement volontaire, ajouter `--prune-missing`
à la première commande. Ajouter seulement les fichiers concernés, relire le diff
indexé, puis créer un commit ciblé : `fix(traffic): ...`, `feat(assets): ...`,
`docs: ...`. Ne pas committer `runtime/`, `.local/`, corpus, poids, caches, bases
SQLite ou identifiants. Les notices des médias font partie des sources à conserver.

Une modification du dépôt ne met pas à jour les projets en cours d’exécution.
L’installateur attend des clones propres ; un runtime déjà modifié demande une
migration explicite, pas une copie récursive de l’overlay.

## Publier une version

Appliquer le versionnement sémantique : correctif compatible, fonctionnalité
compatible, puis version majeure pour une rupture documentée. Mettre à jour
`VERSION`, les versions racines de `package.json` et `package-lock.json`, le README
et le changelog, sans modifier les versions des dépendances par défaut.

Après les tests, l’inventaire et le commit, créer un tag annoté depuis le commit
de livraison sur `main`. Exemple pour une future correction :

```bash
git tag -a v1.0.1 -m "LOTUSIM Image Generator 1.0.1"
git -c http.version=HTTP/1.1 -c http.postBuffer=8388608 \
  push --atomic origin main refs/tags/v1.0.1
```

Créer ensuite la release GitHub sur ce tag avec ses notes. Ne jamais déplacer un
tag partagé, publier les données locales ou modifier la confidentialité du dépôt
dans le cadre d’une release. Un numéro de version ne certifie pas le rendu GPU,
les seuils scientifiques ou la conformité COLREG.
