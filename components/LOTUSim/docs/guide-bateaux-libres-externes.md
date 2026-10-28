# Bateaux externes libres — premier lot de variantes réalistes

Ajout du 15 octobre 2026. Six modèles externes viennent compléter les sept
bateaux procéduraux existants ; aucun ancien modèle n'est remplacé.

## Modèles et droits

| Préfab / clé du renderer | Modèle original et auteur | Catégorie existante | Triangles importés | Textures sources |
| --- | --- | --- | ---: | --- |
| `speedboat_zefiro` | [ZEFIRO](https://sketchfab.com/3d-models/zefiro-5c29921a556346f09684eadfbc51a91d), angelo raffaele catalano | hors-bord, ID 9 | 84 524 | matériaux de couleur |
| `rib_assault` | [Assault Boat](https://sketchfab.com/3d-models/assault-boat-0d4fca4f2e014cd7b6aefd4653b1508c), tnnv | hors-bord, ID 9 | 40 036 | PBR jusqu'à 4K |
| `motor_yacht_35` | [motoryacht 35](https://sketchfab.com/3d-models/motoryacht-35-0bdd7a0de7254426890bb5745bb7da6d), angelo raffaele catalano | yacht, ID 8 | 772 782 | matériaux de couleur |
| `jetski_seadoo_gti` | [2012 Sea-Doo GTI SE 130](https://sketchfab.com/3d-models/2012-sea-doo-gti-se-130-d7b3e903d7dc43a694720bd347f4fadf), BoatUS Foundation | jetski, ID 10 | 107 848 | PBR jusqu'à 4K |
| `cabin_cruiser_minnow` | [SS Minnow III](https://sketchfab.com/3d-models/ss-minnow-iii-a2aa3f9dc66446a4b2c275b9380fc41e), gogiart | yacht, ID 8 | 186 622 | textures jusqu'à 1K |
| `rib_zodiac` | [Zodiac boat](https://sketchfab.com/3d-models/zodiac-boat-a10b7997f1514bd7829ece74f68c681c), RedC130 | hors-bord, ID 9 | 121 490 | matériaux de couleur |

Les six pages des créateurs, recoupées avec leur API publique le 15/10/2026,
déclarent **CC BY 4.0**. Cette licence permet le partage, la modification et
l'usage commercial sous réserve de conserver le crédit, la licence et
l'indication des modifications : [conditions officielles](https://creativecommons.org/licenses/by/4.0/).

Il s'agit d'**assets sous licence libre**, pas d'un passage de leurs droits sous
EPL-2.0. Les GLB modifiables sont conservés ; les fichiers de travail natifs
Blender/Maya ne sont pas fournis lorsqu'ils n'existent pas dans la distribution.
La licence ne garantit pas les droits sur les marques ou les personnes et
n'implique aucun soutien du créateur au projet.

Les fichiers ont été obtenus dans la redistribution publique
[Open Water](https://github.com/bob6664569/open-water/blob/285b6ce32057c70191a7fe16c31d979fa383ac64/THIRD_PARTY_NOTICES.md),
à la version figée `285b6ce32057c70191a7fe16c31d979fa383ac64`.
Les crédits présents dans chaque GLB concordent avec ceux des créateurs.
Les modèles **CC BY-NC**, même gratuits, ont été exclus de ce lot.

## Où les trouver

Dans le projet Unity :

- `Assets/Prefabs/<clé>.prefab` : six prefabs prêts à instancier.
- `Assets/models/open_boats/<clé>/` : géométrie, matériaux HDRP, textures et
  `ATTRIBUTION.txt` ; Addressables utilise exactement la clé du prefab.
- `ThirdParty/OpenBoats/<clé>/` : GLB source inchangé, copie de la déclaration
  de licence du créateur, empreinte SHA-256 et modifications documentées.
- `ThirdParty/OpenBoats/manifest.json` : inventaire complet, provenance figée.
- `artifacts/marine-library/open-boats/index.html` : douze vues Unity natives 4K,
  deux angles par bateau, avec liens vers les masques et annotations.

Dans LOTUSim : `assets/models/<clé>/` contient les équivalents SDF / OBJ,
l'ID de catégorie et les mêmes crédits. Ces modèles sont des visuels dont les
trajectoires sont pilotées par le scénario ; ils ne fournissent pas de nouveau
modèle de propulsion ou d'hydrodynamique Gazebo.

## Les inspecter dans l'océan

Quitter Play, puis :

1. `LOTUSim > Models > External CC-BY boats > 2 - Open wave inspection scene`.
2. Passer en Play et choisir le bateau, l'angle, le zoom et le vent.

La scène est indépendante : elle n'ouvre aucune connexion ROS. Le mode par
défaut utilise la réponse amortie à neuf points de notre bibliothèque.
La racine reste réservée aux poses ROS dans un scénario connecté ; seule
l'apparence suit le pilonnement, le roulis et le tangage de l'océan HDRP.
L'option Rigidbody est une approximation indépendante, non une validation navale.

## Variantes dans le dataset connecté

Les variantes sont des **apparences d'une catégorie existante** : elles ne
créent ni nouvelle classe COCO/YOLO ni nouvelle connexion ROS.
La configuration reste `Assets/Dataset/MaritimeRandomLotusim.asset`.

Les listes `Classes > Prefab Variants` sont activées pour `speedboat`,
`motor_yacht` et `jetski`. Le prefab d'origine reste candidat. Le choix dépend
de la graine et du track, dans un tirage indépendant : il ne modifie pas les
distances, vitesses, horaires de rencontre, météo ou identifiants des classes.
Un seul prefab est retenu par objet pendant toute la séquence ; il ne change
pas d'apparence entre deux captures. Un lot donné ne contient pas nécessairement
les six variantes ; changer la graine permet d'en faire varier la composition.

Pour réactiver les listes après une modification manuelle :
`LOTUSim > Models > External CC-BY boats > 3 - Enable variants in connected dataset`.
Ce menu réexporte le YAML. Après tout changement de graine ou de prefab,
réexporter avec `LOTUSim > Dataset > 8`, puis lancer comme d'habitude le mode 7.
Ne pas remplacer à chaud un scénario en cours : terminer ou arrêter la campagne.

Avec la graine livrée `20261014`, les rencontres marines concernées sélectionnent
le yacht `motor_yacht_35`, le semi-rigide `rib_zodiac` et le jetski procédural
d'origine. Les autres rencontres et le bateau observateur FREMM sont conservés.

`events.json`, les états d'objets par image et le YAML contiennent le modèle
réel retenu. `asset-attributions.json` est ajouté automatiquement aux campagnes
qui utilisent ces assets. Conserver ce fichier avec les images lors du partage.
Les masques, boîtes et noms d'annotation utilisent toujours la catégorie, pas le
nom commercial du bateau.

## Limites du réalisme et coût

Le détail varie selon le modèle : certains ont des textures PBR 4K, d'autres
s'appuient sur une géométrie détaillée et des matériaux simples. Une géométrie
plus dense n'est pas à elle seule une garantie de photoréalisme. Le yacht est
lourd : éviter de multiplier ses instances proches sans mesurer la mémoire et
le temps de rendu. Ce premier import ne fournit pas de LOD simplifiés.

Les transformations et la pose de repos des articulations sont figées ; les
animations originales des gouvernes/propulseurs ne sont pas importées.
Les vitrages sont rendus opaques teintés afin de respecter la politique actuelle
de masques à profondeur opaque. Les extensions transmission/IOR/specular ne sont
pas reproduites à l'identique. Le petit décalque alpha d'immatriculation du
jet-ski et les traits de construction non surfaciques ont été omis.
Les fichiers sources restent intacts et les adaptations sont listées.

Les longueurs et les lignes de flottaison sont des réglages de simulation
artistiques, non des cotes certifiées du constructeur. Les coques ouvertes ne
possèdent pas de volume d'exclusion de l'eau : une forte vague peut traverser
le cockpit ; il n'y a pas de simulation d'envahissement ou de flottabilité après
embarquement d'eau. Ne pas interpréter cela comme de la physique navale validée.

L'IR et la vision nocturne restent les approximations déjà documentées dans
[le guide des capteurs](guide-capteurs-rgb-ir-vision-nocturne.md).

## Reconstruction et contrôles

Les originaux étant livrés, aucun compte Sketchfab n'est nécessaire pour
reconstruire les prefabs. `tools/prepare_open_boats.py` (Python, NumPy, Pillow)
prépare les géométries et matériaux depuis `ThirdParty/OpenBoats` ; le menu
`External CC-BY boats > 1 - Build or refresh audited prefabs` reconstruit les
assets Unity. `tools/fetch_open_boats.py` permet de retélécharger la version figée
depuis le manifeste, en vérifiant à nouveau la licence et les SHA-256.

Les commandes de validation Unity contrôlent les références, dimensions,
normales, indices, matériaux opaques, crédits et sélection reproductible sur
40 graines. Le test natif isolé produit deux vues par bateau en 3840 × 2160,
leurs masques/boîtes et une vérification de la réponse à la houle sans mouvement
de la racine externe. Cela ne remplace pas une validation physique ni une
campagne complète du dataset.

Validation connectée complémentaire : trois instants réels LOTUSim / ROS / Unity,
neuf images 4K RGB/IR/nocturnes, 53 annotations communes, douze catégories,
une seule connexion et arrêt confirmé du scénario de test. Les modèles
`motor_yacht_35` et `rib_zodiac` des snapshots Gazebo correspondent aux états
Unity et à `asset-attributions.json`. La galerie `open-boats/connected/`
contient ces captures et leur vérification indépendante.

Ce test a aussi révélé une recherche de correspondances très lente dans
l'encodeur PNG natif Unity 2022 pour une sortie synthétique 4K. Les PNG IR et
nocturnes utilisent désormais un encodage RGB24 sans perte, filtre PNG 0 et
compression rapide ; dimensions, pixels, orientation et annotations sont
inchangés. Le décodage pixel par pixel est testé en petite taille et en 4K.
Les PNG RGB et les masques gardent leur chemin existant. Les tailles de fichiers
des modalités synthétiques peuvent augmenter ; prévoir une marge de stockage.
