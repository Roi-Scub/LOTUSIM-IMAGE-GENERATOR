# Conventions de code et branche de refactorisation

La branche `refactor` améliore la lisibilité des sources sans changer les règles
de simulation, les contrats ROS, les champs Unity sérialisés ou les formats de
données. Elle reste séparée de `main` jusqu’à sa revue. Les projets complets sous
`runtime/` ne sont pas reformatés ni rechargés pendant cette revue.

## Conventions retenues

| Langage | Convention | Outil |
| --- | --- | --- |
| Python | Quatre espaces, largeur cible de 100 caractères, syntaxe compatible Python 3.9 | [Black 26.10.1](https://black.readthedocs.io/en/stable/usage_and_configuration/the_basics.html), mode sûr, chaînes conservées |
| JavaScript et CJS | Deux espaces, points-virgules, largeur cible de 100 caractères | [Prettier 3.6.2](https://prettier.io/docs/options) |
| HTML et CSS | Structure dépliée, deux espaces, espaces HTML significatifs préservés | Prettier 3.6.2 |
| C# | Quatre espaces, accolades Allman, blocs dépliés | Roslyn et [dotnet format whitespace](https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-format), SDK 10.0.102 |
| C++ | Style LLVM, quatre espaces, largeur cible de 100 caractères, ordre des includes conservé | [clang-format 21.1.8](https://clang.llvm.org/docs/ClangFormatStyleOptions.html) |
| HLSL | Régions de code formatées séparément, enveloppe ShaderLab conservée | clang-format 21.1.8 |
| Bash | Lanceurs existants conservés, vérification de syntaxe | `bash -n` |

`.editorconfig`, `.prettierrc.json`, `.clang-format` et `pyproject.toml` définissent
les réglages. La largeur est une cible de lisibilité : les chaînes et directives
qui ne peuvent pas être coupées sans changer leur contenu restent longues.

Le formatage ne renomme pas les API, clés JSON, identifiants de modèles ou champs
Unity. Les messages ROS générés, bibliothèques tierces, données JSON/YAML, assets
Unity sérialisés, modèles 3D, textures, fichiers de verrouillage existants et
configurations de base épinglées ne font pas partie du nettoyage automatique.
Les sources C++ et C# modifiées fournies par patch sont, elles, synchronisées avec
leurs copies de référence et leurs correctifs d’installation.

## Installer les outils de développement

Les outils de formatage sont distincts des dépendances de l’application. Black
exige un Python de développement 3.10 ou plus récent ; le code applicatif conserve
sa compatibilité Python 3.9. Le contrôle C# exige le SDK .NET 10.0.102 avec son pack
local de références 10.0.2. Aucun outil n’installe ni ne démarre Unity.

Depuis la racine du dépôt, avec un Python de développement compatible :

```bash
python3 -m venv .venv-format
source .venv-format/bin/activate
python -m pip install -r requirements-dev.txt -r requirements-test.txt
npm ci --ignore-scripts
```

Node.js 24.1.0 a servi aux vérifications de cette branche. Les versions des paquets
Node sont figées dans `package-lock.json` ; les dépendances Python de formatage
sont déclarées dans `requirements-dev.txt`.

## Vérifier ou appliquer le style

```bash
python scripts/format_sources.py --check
python scripts/format_sources.py --language python --check
python scripts/format_sources.py --language web --write
```

Sans option, la commande vérifie seulement. `--write` est nécessaire pour modifier
les sources sélectionnées. Les fichiers sous `runtime/`, les données et les
bibliothèques tierces ne sont jamais sélectionnés. Le contrôle C# utilise un
répertoire temporaire, sans projet Unity, restauration de paquet ou connexion ROS.
Il compare tokens, directives et commentaires avant de publier un candidat.

Après modification d’une source fournie par patch, synchroniser les correctifs
depuis les dépôts de base locaux contenant les commits épinglés :

```bash
python scripts/sync_source_patches.py \
  --core runtime/LOTUSim \
  --unity runtime/LOTUSim-Unity-modules \
  --write
```

Cette commande lit les historiques des deux dépôts, mais travaille dans des
répertoires temporaires et n’y applique aucun changement de source. Sans `--write`,
elle vérifie les correctifs au lieu de les remplacer.

## Organisation des sources

Le [guide d’architecture](ARCHITECTURE_CODE.md) décrit les domaines Python, les fonctionnalités Web, les modules Unity, les entrées de compatibilité et les dossiers de tests. Les scripts Unity sont déplacés avec leur `.meta`, sans renommer les classes sérialisées ni changer les assemblages. `scripts/` ne contient plus les suites de tests. Les contrôles QA sont des sources versionnées sous `tests/qa/`, tandis que leurs résultats restent sous `artifacts/qa/`.

## Valider les changements

```bash
python scripts/check_architecture.py
python scripts/run_tests.py
python scripts/refresh_manifest.py --write
python scripts/verify_export.py
```

Les tests Web utilisent désormais des analyseurs de développement pour extraire
les fonctions et contrôler les sources indépendamment de leur indentation. Il
faut donc installer les dépendances Node avant ces suites. L’application Web ne
charge pas ces analyseurs.

Pour tester un clone installé hors de ce dépôt, définir `NODE_PATH` vers le
`node_modules` de cet environnement de développement pour les seules commandes
de test. Les dépendances de formatage ne sont pas nécessaires pour lancer le
dashboard ou produire les images.

Les vérifications de la branche couvrent l’équivalence des structures Python et
JavaScript, des tokens natifs, du DOM et du CSS. La comparaison navigateur porte
sur quatre vues en deux résolutions. La compilation C# utilise les références
Unity locales ; elle ne constitue pas un test de rendu GPU.

Les empreintes des sources changent naturellement avec leur mise en forme : un
nouveau plan pourra donc porter une nouvelle provenance du planificateur. Les
plans archivés, catalogues et corpus ne sont pas réécrits pour masquer ce changement.

## Relire la branche avant fusion

```bash
git diff main...refactor --stat
git diff --ignore-all-space main...refactor
```

Relire séparément les nouveaux outils, les adaptations de tests et les correctifs
d’installation. La fusion et le déploiement vers les projets exécutés restent des
actions explicites après validation.

Le fichier `.git-blame-ignore-revs` identifie le gros commit de mise en forme.
Pour remonter à l’auteur des changements fonctionnels sans ce bruit :

```bash
git -c blame.ignoreRevsFile=.git-blame-ignore-revs blame chemin/du/fichier
```
