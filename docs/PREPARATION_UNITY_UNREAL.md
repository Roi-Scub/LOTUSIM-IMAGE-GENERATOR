# Préparer une scène Unity ou Unreal

Le même formulaire prépare un paquet propre au moteur choisi. Unity conserve la
chaîne LOTUSim de capture et d'annotation existante. Le préparateur Unreal produit
un projet et un script d'aperçu RGB statique, sans parité ROS, houle ou annotations.

Ce guide décrit ces deux adaptateurs natifs. Le cœur permet aussi de choisir Godot,
Blender, O3DE ou un nom personnalisé ; ces profils exportent un contrat de scène
neutre, sans prétendre disposer d'un adaptateur de rendu. Voir
[l'architecture multi-moteurs](ARCHITECTURE_MULTI_MOTEURS.md).

## Utilisation

1. Ouvrir [Paramétrage](http://127.0.0.1:8766/#settings) et choisir **Unity** ou
   **Unreal Engine** dans « Moteur de rendu ».
2. Définir objets, distances, résolution et blocs d'images. Changer de moteur
   conserve les paramètres ; leur application dépend des capacités de l'adaptateur.
3. Vérifier la configuration puis cliquer **Préparer pour le moteur choisi**.
4. Lire les instructions et limites, puis télécharger le **bundle ZIP** ou utiliser
   `runtime/LOTUSim/artifacts/campaign-settings/prepared/<id>/`.
5. Importer explicitement dans l'éditeur. Le dashboard ne démarre aucun moteur,
   Play ou scénario, et n'exécute pas les scripts produits.

Les badges séparent disponibilité du préparateur, présence détectée de l'exécutable
et validation native. Une préparation réussie ne prouve ni l'éligibilité de licence
ni la production d'une image.

## Agent de préparation

L'orchestrateur applique trois rôles déterministes : le **planificateur** lit la
configuration validée ; le **constructeur de script** choisit le modèle de code du
moteur ; le **validateur** contrôle les fichiers et leurs empreintes SHA-256.
La trace `engine-agent.json` est affichée dans le dashboard. Aucun LLM n'invente
du code ni ne répare seul des scripts dans l'éditeur.

Chaque préparation est une révision immuable. `manifest.json` référence les fichiers
et révisions des modèles importés. Les téléchargements vérifient tailles et empreintes ;
les scripts sont servis en pièces jointes, jamais exécutés par le navigateur.

## Unity

Dans `runtime/LOTUSim-Unity-modules`, hors Play, utiliser **LOTUSim > Dataset > Manual
campaigns > Import prepared campaign** et choisir `manifest.json`, avec `campaign.json`
dans le même dossier. L'adaptateur crée une nouvelle scène et ses scénarios LOTUSim.
Lancer ensuite Play explicitement lorsque les services LOTUSim et ROS habituels sont prêts.

Le paquet contient aussi `scene_unity.cs`, une entrée Editor optionnelle. La copier
dans `Assets/Editor` ajoute un menu propre à cette préparation, qui appelle le même
importeur. Ce script n'est pas requis avec le menu standard et ne s'exécute pas au démarrage.

## Unreal

Le paquet contient `LOTUSimPrepared.uproject`, `scene_unreal.py`, `scene-plan.json`
et `unreal-instructions.txt`. Installer séparément un Unreal Editor compatible et
vérifier les droits de l'organisme ; Epic Games Launcher seul n'est pas un éditeur.
Le prototype vise les API Unreal 5.5/5.6 et doit être validé dans la version installée.

Ouvrir le projet préparé. Dans la console Python de l'éditeur, suivre la commande
exacte de `unreal-instructions.txt`, qui conserve l'espace de fonctions dans `scene` :

```python
import runpy
scene = runpy.run_path("/chemin/du/paquet/scene_unreal.py")
scene["build"]()
scene["sample"](0)
scene["capture_rgb"](0)  # attendre la fin
# ou scene["capture_all"]() pour toute la campagne
```

Le script vérifie les sources, importe les meshes compatibles et crée un nouveau
niveau sous `/Game/LOTUSim/Campaigns/`, avec caméra et éclairages. PNG et reçus
techniques vont dans `Saved/LOTUSim/<id>/`. Le ZIP référence la bibliothèque LOTUSim
locale sans l'embarquer ; une source modifiée, manquante ou incompatible bloque
sa construction. Les fichiers existants ne sont pas écrasés.

Cet aperçu utilise une **mer plane**, les éclairages jour, crépuscule et nuit et des
échantillons indépendants. Il n'applique pas houle, pluie, nuages, vent physique,
trajectoires continues ou ROS. La coque FREMM est absente. Il ne produit pas de
masques ni d'annotations de vérité terrain. Les vitesses restent déclaratives,
sans animation temporelle. La bouée issue des primitives SDF diffère du prefab
Unity détaillé. Ces limites figurent aussi dans le dashboard et les reçus.

Le Python Unreal automatise l'éditeur ; il ne constitue pas un langage de gameplay
dans une application packagée. [Documentation Epic](https://dev.epicgames.com/documentation/en-us/unreal-engine/scripting-the-unreal-editor-using-python).

## Validation et suite

Les tests couvrent préparation, fichiers, repères, code C# généré et interface.
Les tests Unreal utilisent des fixtures et doublures d'API, pas un rendu GPU.
Commencer dans Unreal Editor par une bouée et un bateau pour contrôler caméra,
matériaux et captures avant de porter océan, synchronisation LOTUSim et masques.
