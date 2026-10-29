# Dashboard et validation RGB

Le dashboard fonctionne sur macOS ou Linux avec Python 3.9+ et un navigateur.
Pas de paquet Python à installer pour l’interface, les configurations ou la lecture
des rapports. La génération et le détecteur RGB ont des dépendances distinctes.

## Lancer le dashboard

Depuis la racine du dépôt :

```bash
python3 scripts/start_dashboard.py --no-docker
```

Ouvrir <http://127.0.0.1:8766/> et garder le terminal ouvert. Ctrl+C arrête
seulement le serveur. Si le port est occupé, utiliser `--port 8767` ; ne pas fermer
un processus inconnu. Ne pas ouvrir l’interface par `file://`.

Le lanceur choisit les projets de `runtime/` s’ils existent, sinon `components/`.
Pour désigner des clones installés ailleurs :

```bash
python3 scripts/start_dashboard.py \
  --core /chemin/projets/LOTUSim \
  --unity /chemin/projets/LOTUSim-Unity-modules
```

Sans `--no-docker`, le collecteur observe le conteneur `lotusim-dev`. Il ne le
démarre pas et ne crée pas de connexion ROS TCP. Le serveur reste sur `127.0.0.1` :
pas de tunnel ou d’exposition réseau pour cet outil local. Le stockage sécurisé
utilise des fonctions POSIX ; Windows natif n’est pas validé.

## Préparer et suivre une campagne

Dans **Paramétrage**, répartir le total d’images entre les blocs, puis définir
objets, distances, environnement et caméra. Préparer le bundle du moteur choisi
et suivre ses instructions d’import. Changer de moteur conserve les demandes,
pas une garantie que chaque effet soit appliqué par cet adaptateur.

Pour une séquence animée et une photo toutes les X secondes simulées, utiliser
les [plans coopératifs](PLANS_COOPERATIFS.md). Pour ajouter un modèle, voir la
[bibliothèque 3D](BIBLIOTHEQUE_MESHES.md).

Le dashboard lit la télémétrie `artifacts/operations/unity.json` et les sorties
`artifacts/datasets/`, `manual-campaigns/` ou `dataset-*` du projet de rendu.
Les analyses sont rattachées aux campagnes sous `visual-observer/` ou
`visual-verification/`. Les rapports hors des racines autorisées ne sont pas
servis arbitrairement. Un aperçu ancien est marqué historique ; sans télémétrie,
l’état reste non mesuré.

## Validation RGB optionnelle

Le détecteur analyse les pixels RGB localement avec Grounding DINO. Il ne reçoit
pas les cadres de vérité terrain comme entrée de détection. Gazebo Transport
peut relayer ces pixels, mais ne reconnaît pas leur contenu. Les capteurs Gazebo
natifs annotent, eux, leur propre scène 3D.

Avec Python 3.12, depuis le clone LOTUSim installé — ou `components/LOTUSim/`
pour une analyse sans simulation :

```bash
python3.12 -m venv .venv-vision
.venv-vision/bin/python -m pip install -r tools/vision-requirements.txt
```

Les dépendances directes sont épinglées ; les poids ne sont pas inclus. Le fichier
`assets/perception/rgb_observer_tiled.json` définit modèle, révision et empreinte.
Sur un poste connecté, préparer les poids avec leurs notices :

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
    raise SystemExit('Empreinte des poids différente : arrêter ici.')
print('Poids vérifiés :', digest)
PY
```

L’inférence utilise ensuite les fichiers locaux, sans code distant ni envoi
d’image. Sur un poste isolé, transférer le dossier complet du modèle, recalculer
l’empreinte et préparer séparément les roues Python de la bonne plateforme.
Ne pas copier un venv d’un autre poste.

Pour analyser les premières images d’une vraie campagne :

```bash
.venv-vision/bin/python tools/rgb_observer.py \
  --rgb ../LOTUSim-Unity-modules/artifacts/manual-campaigns/MA_CAMPAGNE/rgb \
  --limit 3 --compare
```

Remplacer `MA_CAMPAGNE`. Fournir les RGB sans cadres, pas les masques ou overlays.
Sans annotations de référence, omettre `--compare`. Ouvrir le nouveau
`visual-observer/<analyse>/index.html` ou retrouver le rapport dans le dashboard.
Un score de modèle n’est pas une probabilité de justesse ; voir le
[protocole de validation RGB](../components/LOTUSim/docs/guide-validation-visuelle-rgb.md).

## Dépannage

| Symptôme | Contrôle |
| --- | --- |
| Port occupé | Autre instance connue ou `--port 8767` |
| État du moteur non mesuré | Bon clone `--unity`, télémétrie récente et projet complet installé |
| Préparation Unity indisponible | Présence de `Assets/Editor/Dataset/Campaigns/DatasetManualCampaignBuilder.cs` ; ancien chemin plat également reconnu |
| Aucun rapport | Sorties réelles présentes sous une racine `artifacts/` reconnue |
| Analyse impossible | Python 3.12, dépendances, tous les fichiers du modèle et empreinte des poids |
| Docker non observé | Normal avec `--no-docker`, sinon vérifier le conteneur `lotusim-dev` |

Pour les services de simulation, suivre la [session locale](SESSION_LOCALE.md).
Les tests de l’interface et du serveur sont décrits dans le
[guide de contribution](CONTRIBUTION.md).
