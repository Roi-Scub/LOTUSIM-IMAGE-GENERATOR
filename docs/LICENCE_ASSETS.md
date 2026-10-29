# Licence des modèles originaux

Copyright © 2026 Gabriel Ricardon (Roi-Scub).

Les médias originaux listés ci-dessous sont mis à disposition sous
[Creative Commons Attribution 4.0 International — CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Le [texte juridique](https://creativecommons.org/licenses/by/4.0/legalcode.fr)
définit les conditions complètes.

Les deux overlays conservent aussi une notice locale `ORIGINAL_ASSETS_LICENSE.md`
pour que l’attribution accompagne les modèles après installation.

Vous pouvez les partager et les modifier, y compris pour un usage commercial,
avec attribution à Gabriel Ricardon, un lien vers la licence et l’indication des
modifications éventuelles. Cette autorisation ne change pas la visibilité du dépôt.

## Fichiers concernés

Les chemins sont relatifs à la racine de ce dépôt. La licence porte sur la
géométrie et les textures/matériaux originaux, pas sur les logiciels et ressources
tiers référencés par un prefab.

| Ensemble | Chemins |
| --- | --- |
| Bouée Unity | `components/LOTUSim-Unity-modules/Assets/models/buoy/` |
| Quatre modèles aériens | `components/LOTUSim-Unity-modules/Assets/models/aerial_library/` |
| Sept modèles maritimes | `components/LOTUSim-Unity-modules/Assets/models/marine_library/` |
| Prefabs correspondants | `components/LOTUSim-Unity-modules/Assets/Prefabs/` : `buoy`, `small_drone`, `drone_racer_sim`, `helicopter`, `airplane`, `seagull`, `fishing_trawler`, `container_ship`, `motor_yacht`, `speedboat`, `jetski`, `ferry`, `sailboat`, `DatasetObserverBoat` |
| Exports et primitives Gazebo | `components/LOTUSim/assets/models/` : `buoy`, `small_drone`, `drone_racer_sim`, `helicopter`, `airplane`, `seagull`, `fishing_trawler`, `container_ship`, `motor_yacht`, `speedboat`, `jetski`, `ferry`, `sailboat`, `dataset_observer` |

`drone_racer_sim` réutilise la géométrie du drone original. `DatasetObserverBoat`
est le bateau simplifié, pas la FREMM. Les scripts de génération et les composants
C# restent sous la licence de code EPL-2.0 ; les shaders Unity référencés gardent
leur propre licence. Les droits déjà accordés sous d’autres licences ne sont pas retirés.

## Attribution proposée

> Modèle « nom du modèle » — Gabriel Ricardon (Roi-Scub), LOTUSIM Image Generator,
> https://github.com/Roi-Scub/LOTUSIM-IMAGE-GENERATOR — CC BY 4.0,
> https://creativecommons.org/licenses/by/4.0/. Modifications : préciser, le cas échéant.

Conserver ce crédit avec les modèles redistribués et dans les crédits des corpus
qui les utilisent. Une citation ne doit pas laisser entendre que Gabriel approuve
le produit ou les résultats obtenus.

## Exclusions

Cette licence ne couvre pas `open_boats/`, `open_objects/`, `ThirdParty/`, les modèles
historiques du socle, `fremm_observer` ou `DatasetObserverFremm`. Elle ne couvre pas
non plus les ressources Unity/HDRP, terrains, polices, sons, packages, poids IA ou
modèles ajoutés ensuite par un utilisateur. Consulter les
[notices des assets tiers](ASSETS_ET_LICENCES.md).
