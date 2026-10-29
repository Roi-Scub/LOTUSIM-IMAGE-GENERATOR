# Cœur indépendant du moteur graphique

Le cœur gère les configurations, objets, unités, contrats de scène, paquets et
observations sans imposer Unity. Les particularités de génération et de rendu restent
dans des adaptateurs. Déclarer un nom ajoute un profil et un export neutre, pas un
moteur installé ni une chaîne native fonctionnelle.

| Profil | État de notre intégration |
| --- | --- |
| Unity | Chaîne LOTUSim, rendu et annotations existants |
| Unreal | Préparation et aperçu RGB statique ; exécution native à valider |
| Godot, Blender, O3DE, nom personnalisé | Export du contrat neutre, adaptateur natif à développer |

Unity reste le chemin pour les campagnes actuelles. Pour évaluer Unreal, commencer
par le [prototype de préparation](PREPARATION_UNITY_UNREAL.md#unreal). Les licences
des moteurs, leur version et le matériel doivent être vérifiés séparément ; choisir
un nom dans le registre n’installe pas le moteur et ne donne pas de droits d’usage.

## Choisir un moteur

Dans [Paramétrage](http://127.0.0.1:8766/#settings), choisir le moteur du projet et
appliquer explicitement ce choix. Unity, Unreal Engine, Godot, Blender et O3DE sont
proposés. Le champ de nom personnalisé crée un profil d'export pour un autre moteur.

Le profil est conservé dans `artifacts/render-engines/profile.json`, dans le clone
LOTUSim actif. Les nouvelles configurations utilisent ce choix par défaut. Un
brouillon déjà saisi garde son moteur tant qu'on ne le change pas explicitement.
Le profil ne contient aucun chemin d'exécutable, module Python ou commande shell.

Les textes généraux et les capacités suivent le registre. La provenance reste
indépendante : choisir Godot ne transforme pas une ancienne capture Unity en capture
Godot. Le dashboard affiche séparément profil configuré et source réellement observée.

## Responsabilités des modules

| Module | Rôle |
| --- | --- |
| `engine_registry.py` | Profils, noms, capacités déclarées, adaptateurs autorisés et inventaire des fichiers |
| `campaign_settings.py` | Validation de la campagne et paquets immuables |
| `neutral_scene_adapter.py` | Contrat commun de scène et exigences d'un nouvel adaptateur |
| `unity_scene_adapter.py` | Entrée de préparation propre à Unity |
| `unreal_scene_adapter.py` | Préparation du prototype d'aperçu Unreal |
| `render_engine_agents.py` | Orchestration des adaptateurs de confiance et trace des trois rôles |
| `renderer_telemetry.py` | Protocole d'observation commun et traduction de l'ancien signal Unity |

Les capacités décrivent le code disponible, pas une validation GPU ou de licence.
Les profils génériques n'ont pas d'adaptateur natif : ils exportent uniquement le
contrat et indiquent explicitement les fonctions à implémenter. Le prototype Unreal
conserve ses limites de mer plane, sans ROS ni annotations. La chaîne Unity existante
reste disponible quand son adaptateur est installé.

## Contrat commun de scène

Tous les nouveaux paquets comprennent `scene-contract.json`, de schéma
`lotusim-neutral-scene-contract-1`. Il contient les classes et identifiants, références
des modèles, dimensions, caméra pinhole et intrinsèques, observateur, graine aléatoire,
blocs d'images et paramètres demandés de placement et d'environnement.

Le monde est exprimé en **ENU** : X est, Y nord, Z vertical, mètres et mètres par
seconde. Le cap est en degrés dans le sens horaire depuis le nord. Les meshes
normalisés ont leur repère local distinct : X avant, Y bâbord, Z haut. L'adaptateur
convertit unités, axes et rotations vers son moteur.

Les blocs décrivent des images indépendantes. Les valeurs météo sont des demandes,
pas des effets appliqués ou une physique calibrée. Une même graine ne garantit pas
des tirages ou pixels identiques entre moteurs ; les recettes natives existantes
ne sont pas modifiées silencieusement.

Les profils génériques ajoutent `adapter-requirements.json` et `engine-instructions.txt`.
Unity et Unreal conservent leurs fichiers spécifiques. Les anciens paquets Unity
et Unreal restent lisibles sans réécriture.

La géométrie convertie d'un import peut être référencée sans prefab ni projet Unity.
Ses fichiers, empreintes, licence et provenance sont conservés. La confirmation d'un
prefab reste une exigence de l'adaptateur Unity, pas du catalogue géométrique neutre.

## Brancher un nouvel adaptateur

1. Lire le contrat et résoudre modèles, droits et repères, sans modifier leur taille
   pour améliorer artificiellement leur visibilité.
2. Implémenter l'import de scène, la caméra, les effets effectivement pris en charge
   et la capture RGB dans le moteur cible.
3. Si nécessaire, relier les poses LOTUSim au temps simulé. L'export seul ne crée
   aucun client ROS ni contrôleur physique.
4. Pour les annotations, produire profondeur ou masques d'instance, occultation et
   exclusions du bateau observateur. Valider les seuils NR/PR/R avec le nouveau rendu.
5. Déclarer le nouvel adaptateur de confiance dans le registre et l'orchestrateur,
   avec son inventaire de fichiers et uniquement les capacités implémentées.

Un profil utilisateur ne charge pas de plugin ou de code arbitraire. L'ajout d'un
adaptateur est une modification de sources révisée et testée, pas une commande saisie
dans un champ du dashboard.

## Publier les observations d'un moteur

Un adaptateur peut produire `artifacts/operations/renderer.json` avec le schéma
`lotusim-renderer-state-1`. Le module `renderer_telemetry.py` fournit le contrat et
un écrivain optionnel, sans dépendance à un SDK graphique :

```python
from renderer_telemetry import publish_renderer_state

publish_renderer_state(core_root, "godot", {
    "updatedAt": "2026-10-28T12:00:00Z",  # remplacer par le temps UTC réel
    "isPlaying": True,
    "isPaused": False,
    "sceneName": "MaScene",
    "capture": {"status": "capturing", "captured": 1, "expected": 10,
                "outputDirectory": "captures/run_01"},
    "preview": {"file": "operations/preview.jpg", "live": True,
                "updatedAt": "2026-10-28T12:00:00Z"}
})
```

Le moteur doit réellement écrire son RGB avant de publier le signal. Ses chemins
sont confinés à `artifacts/renderers/<id-moteur>/`. Les signaux anciens ne sont pas
présentés comme actifs. L'ancienne télémétrie Unity est lue par son adaptateur de
compatibilité et garde son identité réelle.

## API et démarrage

`GET /api/engines` lit le registre. `POST /api/engines/select`, de même origine avec
`X-LOTUSim-Engines: 1`, sélectionne un moteur enregistré ou un nom personnalisé.
Cette opération ne démarre rien. Les voies de génération restent explicites.

Le dashboard et les exports neutres peuvent démarrer sans Unity ni Docker :

```bash
python3 scripts/start_dashboard.py --no-docker
```

Le lanceur complet conserve les services LOTUSim habituels ; il n'ouvre plus Unity
si un autre profil est choisi et ne devine pas une commande d'exécution pour ce moteur.

## Scénarios continus

Le registre de moteurs ne lance pas les plans de trafic. Les trajectoires, leur
édition et leur calendrier sont décrits dans le [guide des plans coopératifs](PLANS_COOPERATIFS.md).
