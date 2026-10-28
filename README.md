# LOTUSIM Image Generator

Ce dossier contient les développements locaux ajoutés autour de LOTUSim et Unity, leurs assets, leurs correctifs et les instructions pour les réinstaller. Il peut être copié dans un dépôt séparé. Ce n’est ni un nouveau simulateur autonome ni une version officielle de LOTUSim : les moteurs de base restent des dépendances identifiées.

Version portable actuelle : **0.2.0**. Voir le [journal des versions](CHANGELOG.md)
et le [guide de versionnement](docs/VERSIONNEMENT.md).

## Démarrer depuis le dépôt privé

Avec un compte autorisé sur le dépôt :

```bash
git clone https://github.com/Roi-Scub/LOTUSIM-IMAGE-GENERATOR.git
cd LOTUSIM-IMAGE-GENERATOR
python3 scripts/verify_export.py
python3 scripts/start_dashboard.py --no-docker
```

Le dashboard ouvre les sources portables sans lancer de moteur. Pour réinstaller
la chaîne complète dans des clones LOTUSim et Unity, suivre
[l'installation complète](docs/INSTALLATION_COMPLETE.md).

## Répertoire de travail actuel sur ce Mac

Depuis le déplacement du 27 octobre, ce dossier est aussi la racine de développement.
Les projets complets utilisés par les services sont maintenant sous `runtime/LOTUSim`
et `runtime/LOTUSim-Unity-modules`. `components/` reste le snapshot portable des ajouts.
Les caches, builds et résultats du runtime sont exclus du dépôt et du manifeste portable.

```bash
python3 scripts/start_local_stack.py
```

Ce lanceur ouvre les terminaux dédiés et, si le profil Unity est choisi, Unity
**sans lancer Play**. Il ne devine pas de commande de démarrage pour un autre moteur.
Dashboard : **http://127.0.0.1:8766/#settings**.
Voir [la session locale et le pilote de deux images](docs/SESSION_LOCALE.md).

La section [Modèles 3D](http://127.0.0.1:8766/#assets) permet de consulter les meshes
et d'importer des meshes statiques GLB, glTF, OBJ ou STL dans une bibliothèque locale.
Unity ouvert hors Play, le prefab/Addressable et le modèle LOTUSim sont préparés
automatiquement ; le modèle apparaît dans Paramétrage après confirmation des deux côtés.
[Guide de la bibliothèque](docs/BIBLIOTHEQUE_MESHES.md) ·
[Import automatique](docs/IMPORTS_AUTOMATIQUES_UNITY.md) ·
[Comparatif des moteurs 3D et licences](docs/ETUDE_MOTEURS_3D.md).

Le choix Unity / Unreal est disponible dans Paramétrage. L'agent de préparation
génère les fichiers adaptés au moteur et un bundle vérifié. Unity conserve sa chaîne
existante ; Unreal dispose d'un préparateur d'aperçu RGB statique, sans parité ROS,
houle ou annotations pour l'instant. [Préparation des scènes](docs/PREPARATION_UNITY_UNREAL.md).

Le cœur utilise un registre de moteurs et un contrat de scène commun : profils Unity,
Unreal, Godot, Blender, O3DE ou nom personnalisé. Les profils sans adaptateur natif
exportent un contrat neutre, sans prétendre produire un rendu.
[Architecture et ajout d'un moteur](docs/ARCHITECTURE_MULTI_MOTEURS.md).

La section [Trafic coopératif](http://127.0.0.1:8766/#traffic) permet de générer des
scénarios et de choisir leurs plans dans une bibliothèque SQLite locale, puis de
modifier position, vitesse ou cap dans de nouvelles révisions. Les contrôles de
séparation et de rencontre COLREG sont partiels et non certifiants. Aucun plan n'est
appliqué à une simulation active. [Guide des plans](docs/PLANS_COOPERATIFS.md).

Les scénarios continus peuvent demander un nombre de photos ou une prise toutes
les X secondes simulées, avec aperçu du calendrier et import explicite du bundle
dans Unity. Le mode d'images indépendantes reste disponible.

## Lancer seulement le dashboard

Depuis ce dossier, avec Python 3.9 ou plus récent, sous macOS ou Linux :

```bash
python3 scripts/start_dashboard.py --no-docker
```

Ouvrir **http://127.0.0.1:8766/**. Si le dashboard de travail utilise déjà ce port :

```bash
python3 scripts/start_dashboard.py --no-docker --port 8767
```

Aucun paquet Python tiers, compte, Unity actif, ROS ou Docker n’est requis pour le dashboard et son éditeur de configurations. Si les projets complets sont présents sous `runtime/`, le lanceur les sélectionne ; sinon il utilise `components/`. Sans télémétrie ni captures, il affiche des états non mesurés. Il ne lance aucune simulation. [Installation et utilisation du dashboard](docs/INSTALLATION_DASHBOARD.md).

## Contenu

| Dossier | Contenu et rôle |
| --- | --- |
| `components/LOTUSim/` | Outils Python/C++, dashboard HTML/JS/CSS, planification, analyse RGB, configurations, scénarios, modèles Gazebo, tests et guides |
| `components/LOTUSim-Unity-modules/` | Nouveaux scripts, shaders, scènes, prefabs, maillages, matériaux, textures et preuves de provenance ; fichiers `.meta` conservés |
| `patches/` | Modifications des fichiers déjà présents dans les dépôts de base, réparties en sept groupes |
| `references/` | Sources modifiées complètes, verrous de dépendances et versions de référence, pour inspection |
| `scripts/` | Lanceur du dashboard, vérification des empreintes et installateur avec simulation par défaut |
| `examples/` | Configuration JSON d’un petit pilote de deux images |
| `docs/` | Synthèse, installation, inventaires techniques, dépendances, crédits et limites |
| `manifest.json` | Inventaire des fichiers exportés avec taille et SHA-256 |
| `provenance.json` | Commits de base, origines et groupes de correctifs |

`components/` contient des **ajouts à intégrer**, pas deux clones complets des projets officiels. Ne pas ouvrir son sous-dossier Unity comme s’il s’agissait déjà d’un projet complet. Les images générées, rapports historiques, poids IA, environnements virtuels, caches Unity, binaires compilés et conteneurs ne sont pas inclus.

## Réinstaller la chaîne complète

Suivre [INSTALLATION_COMPLETE.md](docs/INSTALLATION_COMPLETE.md). L’installateur exige des clones propres aux commits indiqués et ne télécharge, ne compile et ne démarre rien automatiquement :

```bash
python3 scripts/install_integration.py \
  --core "/chemin/projets/LOTUSim" \
  --unity "/chemin/projets/LOTUSim-Unity-modules"
```

Cette commande vérifie uniquement. Ajouter `--apply` après avoir contrôlé les chemins et fermé Unity dans ces clones. **Ne pas la pointer vers les projets actuels déjà modifiés** : ils n’ont pas besoin d’une réinstallation et seront refusés.

## Lire les travaux et les modifications

- [Synthèse du projet](docs/SYNTHESE_TRAVAUX.md).
- [Modifications nécessaires du cœur LOTUSim](docs/MODIFICATIONS_LOTUSIM.md).
- [Ajouts et modifications Unity](docs/MODIFICATIONS_UNITY.md).
- [Assets, licences et points à clarifier](docs/ASSETS_ET_LICENCES.md).
- [Périmètre et exclusions de l’export](docs/PERIMETRE_EXPORT.md).

Les notices existantes sont conservées ; ce dossier n’attribue pas une licence unique à tous les médias. Le modèle d’oiseau `seagull_dayvable` comporte notamment une mention `noai` à clarifier avant un usage destiné à l’entraînement ou une diffusion du corpus. Voir le guide de provenance.

## Vérifier la copie

```bash
python3 scripts/verify_export.py
```

Le manifeste porte sur le snapshot de sources et d’assets. Les nouveaux résultats enregistrés ultérieurement dans `artifacts/` ne font pas partie de ses empreintes.
