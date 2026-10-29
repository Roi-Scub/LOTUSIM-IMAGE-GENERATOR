# Modèles 3D

La vue **Modèles 3D** du [dashboard](http://127.0.0.1:8766/#assets) regroupe le
catalogue, les modèles historiques et les imports locaux. L’aperçu permet de
tourner, zoomer, recentrer et afficher le fil de fer. Il montre la géométrie,
pas le rendu final avec l’océan et les éclairages Unity.

Les états distinguent un modèle du catalogue, une source historique non intégrée,
un import en préparation, un échec et un modèle **prêt**. Seul ce dernier état
confirme le prefab Unity et le modèle LOTUSim d’un nouvel import.

## Importer un modèle

1. Ouvrir le projet Unity complet et garder Play arrêté.
2. Dans **Ajouter un modèle**, choisir les fichiers, renseigner la catégorie,
   la source et les droits de réutilisation.
3. Vérifier l’axe vertical, l’axe avant et les mètres par unité : `0,01` pour
   un fichier en centimètres. Le mesh seul ne permet pas de déduire l’unité réelle.
4. Déclarer le tirant d’eau, la vitesse et l’altitude limites si nécessaire.
   La vitesse maximale vaut zéro par défaut ; ces valeurs ne sont pas mesurées.
5. Importer et attendre l’état **prêt**. Le modèle devient sélectionnable dans
   **Paramétrage**, sans effacer le brouillon de campagne.

Si Unity est fermé, en Play ou en compilation, l’import attend sa disponibilité.
Le menu **LOTUSim > Models > Dashboard imports > Process pending imports now**
permet de traiter manuellement la file. Aucun scénario ni client ROS n’est lancé.

## Formats acceptés

Meshes statiques **GLB 2.0**, **glTF 2.0**, **OBJ/MTL** et **STL ASCII/binaire**.
Joindre les `.bin`, matériaux et textures référencés. Pour garder les sous-dossiers,
utiliser le sélecteur de dossier. Un GLB non compressé avec textures embarquées
reste le chemin le plus simple.

Limites d’entrée : **64 Mio**, **100 fichiers**, noms simples. Les références
externes, chemins absolus et scripts sont refusés. Draco, Meshopt, KTX2, animations,
squelettes et morph targets ne sont pas pris en charge par ce convertisseur.
DAE reste consultable pour les anciens modèles, mais n’est pas un format d’import.
FBX et ZIP ne sont pas acceptés par le formulaire.

Les dimensions normalisées doivent rester entre 1 mm et 1 000 m ; le tirant ne
doit dépasser ni 25 m ni la hauteur du modèle. Des budgets supplémentaires limitent
géométrie et textures. Un fichier trop lourd doit être réexporté : le convertisseur
ne le simplifie pas silencieusement.

## Intégration Unity et LOTUSim

Les originaux et le reçu `asset.json` sont conservés sous :

```text
runtime/LOTUSim/artifacts/mesh-library/imports/import-<uuid>/
```

Le worker prépare un bundle et `unity-request.json`. Unity importe les meshes et
matériaux, crée `Assets/Prefabs/import_<uuid>.prefab`, son Addressable et un reçu
`unity-result.json`. Le backend vérifie ce reçu avant d’ajouter le SDF dans
`assets/models/import_<uuid>/` et l’entrée du catalogue `imported_assets.json`.
Le catalogue de base, les scènes et les sources des autres modèles sont conservés.

Les matériaux utilisent une politique HDRP opaque pour les masques. Le verre peut
donc différer du fichier source. Le collider est simple ; la houle est une réponse
visuelle approximative, ajoutée uniquement si les dimensions conviennent. Un tirant
nul peut employer un proxy de 5 cm sans changer la valeur déclarée. Les feux de
navigation ne sont pas inventés. Les classes existantes gardent leur numéro ;
la classe générique `other` porte le numéro 13.

Chaque campagne référence la révision, le prefab et son GUID. Reconstruire un
modèle exige une nouvelle préparation de campagne ; une ancienne révision n’est
pas remplacée silencieusement. Pour une application Unity compilée, il faut aussi
construire les bundles Addressables : cette opération n’est pas automatique.

## Dépendances et diagnostic

Le dashboard utilise Python standard ; le worker de conversion attend NumPy et
Pillow dans le `.venv-vision` du clone LOTUSim. Sur une nouvelle installation :

```bash
python3.12 -m venv runtime/LOTUSim/.venv-vision
runtime/LOTUSim/.venv-vision/bin/python -m pip install numpy==2.2.6 Pillow==11.3.0
```

Si cet environnement sert aussi au détecteur RGB, le créer avec Python 3.12 et
suivre l’[installation de la vision](INSTALLATION_DASHBOARD.md#validation-rgb-optionnelle).
Ne pas écraser un environnement existant pour réinstaller le convertisseur.

| Symptôme | À vérifier |
| --- | --- |
| Attente Unity | Bon projet ouvert, Play arrêté, compilation terminée, projets frères LOTUSim/LOTUSim-Unity-modules |
| Conversion refusée | Ressources jointes, format statique, unités, budgets et message du worker |
| Préparation refusée après reconstruction | Préparer une nouvelle campagne pour la nouvelle révision |
| Modèle visible dans la bibliothèque mais absent des paramètres | Distinguer source historique et import confirmé prêt |

Three.js est livré localement avec sa licence MIT sous `tools/ops_dashboard_ui/vendor/three/`.
Le visualiseur n’utilise ni CDN ni modèle distant. Consulter les
[crédits et restrictions](ASSETS_ET_LICENCES.md) avant d’importer ou diffuser un modèle.
