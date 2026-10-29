# Installer le dashboard et ses outils locaux

Ce dossier exporte du code réutilisable. Le dashboard peut fonctionner seul, sans Unity, Docker, Gazebo, ROS2, compte en ligne ou dépendance Python à installer. Produire de nouvelles images exige en revanche le projet Unity complet et ses assets ; analyser leur contenu exige l’environnement vision optionnel. Un dossier d’overlay `Assets/` n’est pas à lui seul un projet Unity autonome.

## 1. Conserver cette organisation

```text
export/
├── docs/INSTALLATION_DASHBOARD.md
└── components/
    ├── LOTUSim/
    │   ├── tools/
    │   │   ├── ops_dashboard.py
    │   │   ├── ops_collector.py
    │   │   ├── campaign_settings.py
    │   │   ├── start_ops_dashboard.command
    │   │   └── ops_dashboard_ui/  (HTML, JS et CSS)
    │   ├── assets/scenarios/catalogs/traffic_assets.json
    │   ├── assets/perception/
    │   ├── docs/
    │   └── scripts/
    └── LOTUSim-Unity-modules/
        └── Assets/  (overlay des extensions Unity)
```

Les deux répertoires frères doivent exister. Aucun chemin personnel de l’ancien poste n’est requis pour démarrer le serveur. Les scripts découvrent leur racine à partir de leur propre emplacement, pas du dossier courant du terminal. Le catalogue doit rester à son chemin relatif indiqué ci-dessus.

Les projets de travail, poids du détecteur, environnements virtuels, caches Unity, conteneurs Docker et corpus complets ne sont pas recréés par le simple lancement du dashboard. Consulter l’inventaire de l’export pour savoir quels modèles et exemples sont effectivement inclus.

## 2. Démarrage minimal, sans simulation

Prérequis : Python 3.9 ou plus récent et un navigateur moderne. Le serveur et l’édition de configurations ont été vérifiés sous macOS avec Python **3.9.6**, sans paquet tiers. La copie exportée normalise les sept décimales des horodatages Unity en microsecondes pour cette version de Python. Le stockage sécurisé utilise des fonctions POSIX : macOS et Linux sont les plateformes ciblées ; l’édition de campagnes sous Windows natif n’est pas validée.

Depuis la racine du dossier exporté :

```bash
python3 components/LOTUSim/tools/ops_dashboard.py --no-docker
```

Ouvrir [http://127.0.0.1:8766/](http://127.0.0.1:8766/). Garder le terminal ouvert. `Ctrl+C` arrête seulement ce serveur : il ne ferme ni Unity ni une simulation.

Le lanceur Bash est une alternative sur macOS/Linux :

```bash
bash components/LOTUSim/tools/start_ops_dashboard.command --no-docker
```

Il ne faut pas ouvrir directement `index.html` par `file://` : l’interface utilise les API du petit serveur Python. Sans captures ni télémétrie, les cartes indiquent « non mesuré », « aucun instantané » ou « historique ». Ce n’est pas une panne et aucune activité fictive n’est générée.

### Autre port ou autres emplacements

```bash
python3 components/LOTUSim/tools/ops_dashboard.py --no-docker --port 8767
```

Ouvrir alors `http://127.0.0.1:8767/`. Le raccourci du menu Unity conserve le port 8766 ; sur un autre port, utiliser l’adresse explicitement dans le navigateur. Un port occupé provoque un message d’erreur, jamais la fermeture du processus qui l’utilise.

Pour utiliser des dépôts déjà installés ailleurs :

```bash
python3 components/LOTUSim/tools/ops_dashboard.py \
  --core "/chemin/vers/LOTUSim" \
  --unity "/chemin/vers/LOTUSim-Unity-modules" \
  --no-docker
```

Les deux chemins doivent désigner des répertoires existants. `--core` est la racine dont on lit le catalogue et dans laquelle les configurations seront enregistrées. `--unity` est la racine des résultats Unity observés ; il ne change pas l’emplacement de l’interface Web servie par le script.

## 3. Préparer une campagne

Dans **Paramétrage** :

1. Choisir le nombre total d’images, la caméra et la graine aléatoire.
2. Répartir exactement ce total entre les blocs ; définir les objets et leurs conditions de prise de vue.
3. **Vérifier la configuration**, puis **Enregistrer localement** pour conserver une configuration rechargeable.
4. **Préparer pour Unity** produit une nouvelle paire `manifest.json` / `campaign.json`. Aucun lancement n’est déclenché.
5. Dans le projet Unity complet, utiliser **LOTUSim > Dataset > Manual campaigns > Import prepared campaign**, puis sélectionner **manifest.json**, avec **campaign.json dans le même dossier**. Le lancement de la campagne reste une action explicite dans Unity.

Le dashboard écrit uniquement ses nouveaux fichiers sous `components/LOTUSim/artifacts/campaign-settings/`, ou sous le `--core` choisi. Les fichiers préparés se trouvent dans `prepared/<identifiant>/`. Le manifeste contient l’empreinte SHA-256 du fichier campagne, contrôlée par l’importeur Unity.

La disponibilité du moteur Unity signifie que son adaptateur d’import a été trouvé dans le projet indiqué ; elle ne prouve ni qu’un éditeur tourne ni qu’une caméra rend. Sans cet adaptateur, sauvegarder et exporter du JSON reste possible, mais la préparation est indisponible. Unreal n’a pas d’adaptateur de préparation dans cet export.

Le pilote manuel produit des **images RGB indépendantes**, pas une vidéo continue. Il limite une campagne à 2 000 images et 50 blocs. Les modes thermique et vision nocturne ne sont pas implémentés par cet éditeur manuel, même si d’autres pipelines du projet proposent des rendus simulés. La houle est un proxy visuel, la hauteur apparente en pixels une approximation géométrique, et les vitesses du catalogue des hypothèses de scénario : aucune de ces valeurs n’est une garantie de visibilité ou de performance réelle.

Guide détaillé : [campagnes manuelles](../components/LOTUSim/docs/guide-campagnes-manuelles-dashboard.md).

## 4. Brancher un projet Unity et LOTUSim existants

Le projet source de ce travail utilise **Unity 2022.3.18f1**, d’après `ProjectSettings/ProjectVersion.txt`. Son manifeste déclare notamment Addressables 1.21.21, Cinemachine 2.9.7 et HDRP 14.0.10. Ce sont les versions du projet de référence, pas une promesse de compatibilité avec tout projet Unity.

Intégrer l’overlay dans une copie sauvegardée du projet Unity compatible, en conservant les fichiers `.meta` et les dépendances fournies par l’inventaire. Ne pas copier `Library/`, `Temp/`, `obj/` ou un cache de packages comme substitut aux sources. Les scènes, shaders, préfabriqués et assets du projet d’origine restent nécessaires pour le rendu ; cette doc ne garantit pas leur présence dans un export de code.

Les extensions d’éditeur découvrent généralement LOTUSim comme projet frère nommé exactement `LOTUSim`. Conserver cette disposition lors de l’intégration, ou adapter les résolveurs dans une copie du code avant utilisation. Les options `--core` / `--unity` du serveur ne reconfigurent pas automatiquement ces menus Unity.

Pour seulement observer les services existants, relancer le dashboard sans `--no-docker` :

```bash
python3 components/LOTUSim/tools/ops_dashboard.py
```

L’inspection Docker vise le conteneur nommé **lotusim-dev**. Un autre nom n’est pas configurable par une option de ce serveur ; utiliser `--no-docker` ou adapter cette convention dans une copie. Le dashboard lit des états, processus et ports déjà présents. Il ne démarre pas le conteneur, ne lance pas Gazebo et n’ouvre aucun client ROS TCP supplémentaire.

Entrées reconnues :

- `LOTUSim-Unity-modules/artifacts/operations/unity.json` et `preview.jpg` pour la télémétrie de l’éditeur et l’aperçu.
- Les campagnes avec `status.json` sous `artifacts/datasets/`, `artifacts/manual-campaigns/` ou les groupes `artifacts/dataset-*` du projet Unity.
- Les analyses `visual-observer/<analyse>/` et `visual-verification/<analyse>/` rattachées à ces campagnes.
- Les statuts de planification et autres emplacements explicitement gérés par le collecteur.

Le serveur ne parcourt pas arbitrairement tout le disque. Un rapport placé hors des deux racines `artifacts/` n’est pas automatiquement accessible. Un aperçu historique reste signalé comme tel ; un service présent n’est pas la preuve d’une image effectivement rendue.

## 5. Dépendances : séparer les trois usages

| Usage | Nécessaire | Non nécessaire |
| --- | --- | --- |
| Dashboard et paramétrage JSON | Python 3.9+, navigateur, catalogue local ; POSIX pour le stockage sécurisé | PyTorch, Unity actif, Docker, ROS2, modèle IA |
| Détection / vérification RGB locale | Python 3.12, paquets vision, poids locaux vérifiés, images RGB propres | Unity actif, client ROS, transport Gazebo obligatoire |
| Génération connectée LOTUSim → Unity | Projet Unity complet, assets et dépendances compatibles, environnement LOTUSim/Gazebo/ROS2 prévu par le projet | Hébergement du dashboard, clé d’API de vision externe |

Le relais Gazebo Transport est une option supplémentaire. Il transporte des pixels : ce n’est pas lui qui reconnaît les objets. Le détecteur indépendant est Grounding DINO. Un capteur d’annotation Gazebo natif annote sa propre scène 3D étiquetée ; il ne déduit pas une vérité terrain d’un PNG Unity importé.

## 6. Installer la vision optionnelle

Ces étapes ne servent pas au lancement du dashboard. Elles téléchargent des dépendances et éventuellement un modèle pendant la préparation du poste ; elles n’envoient aucune image du corpus à une API distante. L’inférence est ensuite locale et hors ligne.

Depuis `components/LOTUSim/`, avec **Python 3.12** installé :

```bash
python3.12 -m venv .venv-vision
.venv-vision/bin/python -m pip install -r tools/vision-requirements.txt
```

Versions directes épinglées dans le dépôt :

```text
torch==2.8.0
torchvision==0.23.0
transformers==4.57.1
Pillow==11.3.0
```

Ce fichier ne verrouille pas toutes les dépendances transitives ni toutes les variantes de roues par système. Les poids et roues Python ne font pas partie du paquet de sources ; recréer l’environnement sur la machine cible, avec une distribution adaptée à son système et à Python 3.12. Ne pas copier un ancien `.venv-vision` macOS sur Linux ou Windows.

Python 3.9 suffit au dashboard, **pas à la chaîne vision telle qu’elle est écrite** : les outils vision utilisent notamment `hashlib.file_digest`. La version validée dans les guides du projet est Python 3.12.

### Préparer les poids séparément et vérifier l’empreinte

Référence enregistrée dans `assets/perception/rgb_observer_tiled.json` :

```text
Modèle : IDEA-Research/grounding-dino-tiny
Révision : a2bb814dd30d776dcf7e30523b00659f4f141c71
SHA-256 de model.safetensors :
1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3
Répertoire local : artifacts/vision-models/grounding-dino-tiny
Licence enregistrée : Apache-2.0 ; conserver aussi les notices du fournisseur.
```

Sur le poste de préparation connecté, depuis `components/LOTUSim/` :

```bash
.venv-vision/bin/python - <<'PY'
import hashlib
import json
from pathlib import Path
from huggingface_hub import snapshot_download

root = Path.cwd()
config = json.loads((root / 'assets/perception/rgb_observer_tiled.json').read_text())
destination = root / config['modelDirectory']
snapshot_download(
    repo_id=config['model'],
    revision=config['revision'],
    local_dir=str(destination),
    allow_patterns=['model.safetensors', '*.json', '*.txt', 'LICENSE*', 'NOTICE*'],
)
with (destination / 'model.safetensors').open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
if digest != config['weightsSha256']:
    raise SystemExit('Empreinte des poids différente : ne pas lancer l’inférence.')
print('Poids locaux vérifiés :', digest)
PY
```

Cette commande est une étape d’installation optionnelle, non exécutée par le dashboard. Elle ne télécharge ni pickle `.bin` ni code distant. Les outils chargent ensuite les fichiers avec `local_files_only=True`, `trust_remote_code=False` et `use_safetensors=True`, et activent le mode hors ligne.

Pour un poste isolé, transférer **tout le répertoire du modèle préparé**, pas uniquement `model.safetensors` : processeur, tokenizer et configurations JSON/TXT sont nécessaires. Recalculer le SHA-256 après transfert. Préparer séparément les roues Python correspondant à la même plateforme/Python : `pip download -r tools/vision-requirements.txt -d /chemin/wheelhouse` sur le poste de préparation, puis `pip install --no-index --find-links /chemin/wheelhouse -r tools/vision-requirements.txt` dans le nouvel environnement. Un wheelhouse d’une autre architecture peut être inutilisable.

### Premier essai d’analyse

Remplacer le nom de campagne par une vraie sortie Unity contenant `rgb/` :

```bash
.venv-vision/bin/python tools/rgb_observer.py \
  --rgb "../LOTUSim-Unity-modules/artifacts/manual-campaigns/MA_CAMPAGNE/rgb" \
  --limit 3 --compare
```

Ne pas fournir les images avec cadres dessinés, les masques ou les overlays comme RGB d’entrée. Sans annotations de référence, omettre `--compare`. Sans base d’exemples locale, la détection seule reste possible et l’absence de base est indiquée ; le diagnostic de classification d’instances déjà localisées exige, lui, une base reconstruite avec sa provenance.

La sortie est un nouveau dossier `visual-observer/<analyse>/` à côté du RGB de la campagne. Ouvrir son `index.html` ou le retrouver dans **Campagnes & rapports** si la campagne est sous une racine reconnue. Un score de modèle n’est pas une probabilité de justesse calibrée. Consulter [validation RGB](../components/LOTUSim/docs/guide-validation-visuelle-rgb.md) avant toute interprétation scientifique.

Le transport Gazebo optionnel attend le conteneur `lotusim-dev` et le relais Linux `/workspace/artifacts/rgb-observer-gazebo/relay`, compilé avec `gz-transport13` et `gz-msgs10`. Ces conventions ne désignent pas un ancien chemin utilisateur Mac. L’analyse directe ci-dessus ne les utilise pas.

## 7. Vérifications et dépannage

Depuis `components/LOTUSim/` :

```bash
python3 -m unittest discover -s scripts -p 'test_ops_*.py'
python3 -m unittest discover -s scripts -p 'test_campaign_settings*.py'
```

Les tests du serveur ouvrent des ports locaux temporaires. Les tests de frontend nécessitant Node.js sont distincts ; Node.js n’est pas une dépendance du dashboard en utilisation normale.

| Symptôme | Contrôle |
| --- | --- |
| `FileNotFoundError` au lancement | Vérifier que les deux répertoires frères existent ou fournir `--core` et `--unity`. |
| Port indisponible | Choisir `--port 8767` ; ne pas fermer un processus inconnu. |
| Interface vide par `file://` | Lancer le serveur et ouvrir son adresse `http://127.0.0.1:...`. |
| Unity « non mesuré » | Intégrer l’overlay dans le projet complet ; vérifier `artifacts/operations/unity.json`. Ne pas interpréter la seule présence d’un dossier Unity comme un heartbeat. |
| Préparation Unity désactivée | Vérifier `Assets/Editor/Dataset/Campaigns/DatasetManualCampaignBuilder.cs` dans le projet `--unity`. L’ancien emplacement `Assets/Editor/DatasetManualCampaignBuilder.cs` reste également reconnu. |
| Docker non observé | Normal avec `--no-docker` ; sinon vérifier Docker et le nom `lotusim-dev`. |
| Analyse refusée ou poids absents | Créer l’environnement Python 3.12, préparer tous les fichiers du modèle et contrôler le SHA-256. |
| Ancien rapport introuvable | L’export de code ne contient pas nécessairement les anciens corpus ; copier volontairement les résultats autorisés sous une racine `artifacts/` reconnue. |

Le serveur écoute exclusivement sur `127.0.0.1`. Ne pas modifier cela ni ajouter de tunnel pour « résoudre » un accès depuis un autre poste : cet outil est prévu pour un usage local. Les liens servis sont bornés aux répertoires d’artifacts autorisés ; le serveur n’est pas un explorateur de fichiers généraliste.

## Validation de portabilité réalisée

Le 27 octobre 2026, les sources dashboard, leur interface et le catalogue ont été copiés dans une arborescence de test déplacée avec les deux racines frères. Avec Python 3.9.6, depuis un autre dossier courant et avec `--no-docker`, les vérifications suivantes ont réussi : démarrage CLI, API de santé et d’état, cinq ressources UI, catalogue de 27 modèles, états sans télémétrie honnêtement inconnus, puis sauvegarde/relecture d’une configuration uniquement dans les artifacts de la copie. Le serveur de test a été arrêté proprement. Ce test ne valide ni un rendu GPU Unity, ni une installation Gazebo, ni une inférence du modèle sur un autre système.
