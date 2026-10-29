# Bibliothèque aérienne pour LOTUSim / Unity

Quatre modèles originaux, génériques et sans marque, construits pour le rendu dans le projet HDRP. Aucun mesh ni texture téléchargé.

Crédit : **Gabriel Ricardon (Roi-Scub)**. Géométries, textures et matériaux originaux
sous [CC BY 4.0](../../../ORIGINAL_ASSETS_LICENSE.md), avec attribution.

| Modèle | Prefab / adresse Addressables | Catégorie | Identifiant Gazebo |
| --- | --- | --- | --- |
| Petit quadricoptère avec caméra sur nacelle | `small_drone` | `drone` | 2 |
| Hélicoptère léger sur patins | `helicopter` | `helicopter` | 3 |
| Avion léger monomoteur à aile haute | `airplane` | `airplane` | 4 |
| Oiseau marin de type goéland, ailes déployées | `seagull` | `bird` | 5 |

La bouée préexistante reste la classe Gazebo 1. Ces identifiants sont une convention de cette bibliothèque ; harmoniser la table des classes avant de les fusionner avec un autre corpus.

## Utilisation

1. Hors Play, laisser Unity importer les scripts et générer les assets. Au besoin : **Assets → Refresh**, puis **LOTUSim → Models → Build aerial library**.
2. Les prefabs sont sous `Assets/Prefabs/`. Leurs adresses sont enregistrées dans le groupe Addressables existant `SpawnInterface`, sans remplacer `x500`, `lrauv` ou `buoy`.
3. Les modèles visuels correspondants sont exportés vers le dépôt LOTUSim voisin : `assets/models/small_drone`, `helicopter`, `airplane`, `seagull`. Recharger la liste de modèles dans l'interface LOTUSim après leur création.
4. Choisir le modèle et activer le rendu ; le champ **Model name in Renderer** doit reprendre son adresse. Donner une altitude positive pour les voir au-dessus de l'eau.
5. Lancer Unity avant de démarrer le scénario, afin de recevoir les commandes CREATE. En éditeur, utiliser **Use Asset Database** dans les Addressables ; reconstruire le catalogue si **Use Existing Build** est sélectionné.

Un scénario de démonstration à quatre objets est fourni séparément sous `assets/scenarios/AerialLibraryDemo.yaml`. Il ne se lance pas automatiquement et ne modifie pas les scénarios de l'utilisateur.

## Conventions et vérifications

- Une unité = un mètre. Racine au centre du modèle, pas au niveau du sol.
- Prefabs : vertical +Y, nez +X ; Gazebo : vertical +Z, nez +X. Conversion utilisée : celle du projet (`GzPoseToUnityPose`), qui échange Y et Z. L'export OBJ inverse également l'ordre des triangles pour conserver des faces orientées vers l'extérieur.
- Les dimensions mesurées, catégories, nombres de triangles et renderers sont enregistrés dans `model-info.json` pour chaque modèle, et sous `artifacts/aerial-library/*-validation.json`.
- Avant chaque génération, 16 tests contrôlent les indices, les attributs et l'orientation des faces, notamment les extrémités fermées et les ailes gauche/droite. Ils peuvent aussi être lancés seuls avec **LOTUSim → Models → Validate aerial geometry**, sans modifier les assets. Tous les sommets sont créés avant les faces qui doivent lire leurs coordonnées.
- Matériaux HDRP/Lit : peintures micro-texturées, composite tressé, caoutchouc, métal, vitrages teintés et plumage. Les vitrages sont des surfaces opaques réfléchissantes : pas d'intérieur de cabine ni de transmission optique à travers les fenêtres.
- Les petites pièces sont regroupées par matériau pour limiter le nombre de renderers. Les silhouettes ne reposent pas sur des images planes transparentes.
- **LOTUSim → Models → Preview aerial library** exporte les aperçus réels de l'éditeur Unity sous `artifacts/aerial-library/`.
- Une reconstruction remplace uniquement l'enfant généré `AerialModel_v1`, les meshes/matériaux générés et les fichiers d'export identifiés par `aerial-library-origin.txt`. Elle conserve les GUID des prefabs, leurs autres composants et les autres modèles du projet.

## Limites importantes

Il s'agit de modèles visuels, pas de véhicules simulés en vol. Les modèles Gazebo sont statiques ; les prefabs n'ont ni Rigidbody, ni autopilote, ni moteurs physiques. Les rotors et les ailes sont figés dans cette version. Les mouvements / trajectoires / animations nécessiteront une étape distincte, synchronisée avec la capture des images et des annotations.

Les OBJ Gazebo reproduisent la géométrie Unity. Leurs matériaux diffus OBJ/MTL ne reproduisent cependant pas la photométrie HDRP. Les annotations des images Unity doivent toujours provenir de la même caméra et du même rendu Unity ; ne pas reporter des boîtes Gazebo sur une autre projection sans calibration.

Cette bibliothèque ajoute les objets et leurs identifiants, mais n'implémente pas à elle seule la chaîne d'annotation ou le filtre de validité du dataset.
