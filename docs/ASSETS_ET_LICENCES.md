# Assets et provenance à conserver

Inventaire documentaire local du 27 octobre 2026. Ce fichier décrit les notices
et métadonnées effectivement archivées ; il ne transfère pas la propriété des
modèles et ne remplace pas les conditions de leurs auteurs.

## Trois ensembles différents

1. **Créations procédurales et code d’intégration** : bouée, bibliothèque aérienne,
   sept familles de navires, matériaux/textures générés et scripts de réponse
   visuelle. Les constructeurs correspondants restent dans `Assets/Editor/`.
2. **Adaptations de modèles externes** : six bateaux et huit autres variantes,
   importés dans `Assets/models/open_boats/` et `open_objects/` puis assemblés en
   prefabs. Les manifestes les déclarent `CC-BY-4.0` et enregistrent leurs auteurs,
   URL sources, commits miroirs, empreintes SHA-256 et transformations.
3. **Assets du projet officiel de base** : FREMM original, HDRP/environnement,
   terrain, audio, polices, personnages, Photon/XR et autres dépendances.
   L’export d’intégration ne les transforme pas en créations nouvelles et ne leur
   attribue pas automatiquement la licence des modèles externes.

Le `LICENSE` du dépôt Unity de base est EPL-2.0. Garder ce fichier et les en-têtes
existants avec les fichiers de code repris/modifiés. Ne pas appliquer une seule
étiquette de licence à l’ensemble des médias par commodité ; conserver les
notices propres à chaque ensemble.

## Bibliothèque externe présente

Les identifiants sont les clés de modèles utilisées par les prefabs et le
catalogue LOTUSim. Les sources complètes et leurs empreintes sont dans les
manifestes, qui font foi pour retrouver les téléchargements retenus.

| Identifiant | Œuvre / auteur renseignés | Licence déclarée dans l’archive |
| --- | --- | --- |
| `speedboat_zefiro` | ZEFIRO — angelo raffaele catalano | CC BY 4.0 |
| `rib_assault` | Assault Boat — tnnv | CC BY 4.0 |
| `motor_yacht_35` | motoryacht 35 — angelo raffaele catalano | CC BY 4.0 |
| `jetski_seadoo_gti` | 2012 Sea-Doo GTI SE 130 — BoatUS Foundation | CC BY 4.0 |
| `cabin_cruiser_minnow` | SS Minnow III — gogiart | CC BY 4.0 |
| `rib_zodiac` | Zodiac boat — RedC130 | CC BY 4.0 |
| `buoy_navigation_ozzy` | Buoy — OzzyDan | CC BY 4.0 |
| `drone_amvlab` | drone amvlab — AMV Lab | CC BY 4.0 |
| `helicopter_utility_gb` | Helicopter — Gigantic Burger | CC BY 4.0 |
| `airplane_a320` | airplane a320 — AMV Lab | CC BY 4.0 |
| `airplane_c172` | Cessna 172 — Nobilis the Palaeovespa | CC BY 4.0 |
| `seagull_dayvable` | Seagull — Dayvable ; adaptation FBX/rig viniciusbarros | CC BY 4.0, avec signalement ci-dessous |
| `speedboat_smolbot` | Boat — Nicosama, selon le manifeste et la preuve créateur | CC BY 4.0 |
| `speedboat_racing` | Boat — milamila | CC BY 4.0 |

Les URL vers les œuvres et les liens de licence doivent rester dans les
`ATTRIBUTION.txt`, composants `OpenBoatAssetCredit`, manifestes et notices.
Les marques et noms commerciaux ne constituent pas une approbation du projet.
Les dimensions, masses, vitesses représentatives et réponses à la mer sont des
paramètres de simulation, pas une certification des modèles de fabricants.

## Dossier `ThirdParty` : partie indispensable de l’export

Conserver **tout le dossier sélectionné `ThirdParty/`** (67 fichiers, environ
87 Mio à l’audit), sans ajouter les dépôts miroirs complets :

- `OpenBoats/manifest.json` et `OpenObjects/manifest.json` ;
- `LICENSE-CC-BY-4.0.txt` dans chaque collection ;
- `ATTRIBUTION.txt`, `inspection.json`, preuves `sketchfab-license.json` ou
  `creator-license.json` de chaque modèle ;
- fichiers sources `source.glb` ou `source.fbx`, utiles à la reproduction et à
  la vérification des empreintes ;
- notices du miroir `MIRROR_NOTICES.md`, `water-THIRD_PARTY_NOTICES.md`, licences
  et README d’AMV/SDR/du modèle d’oiseau ; texture source d’oiseau conservée.

Ces sources ne sont pas un cache anonyme jetable. Elles permettent de distinguer
le fichier téléchargé de sa conversion Unity et de documenter les transformations
sans dépendre d’un téléchargement futur potentiellement modifié.

Les adaptations documentées incluent notamment : orientation et échelle, ligne
de flottaison artistique, regroupement des maillages, conversion HDRP des
matériaux, approximation du verre et de la transmission en surfaces opaques pour
la politique d’annotation, animations de maillage et ajout de lumières/réponse
visuelle. Garder ces listes de changements avec l’attribution.

## Points de vigilance documentaires

### Oiseau Dayvable et mention `noai`

L’archive `OpenObjects/seagull_dayvable/creator-license.json` indique une licence
« CC Attribution » vers CC BY 4.0 **et contient un tag `noai`** parmi les tags de
la page créateur. Ce constat doit rester visible et la preuve ne doit pas être
supprimée. Ce document ne tranche pas la portée de ce tag, ni sa relation avec la
licence indiquée. Avant une diffusion destinée à l’entraînement ou une
publication du corpus, faire vérifier ce cas ou utiliser une autre variante
d’oiseau dont la provenance convient à l’usage retenu. L’oiseau procédural
existant constitue une variante technique distincte.

### Informations de miroirs non équivalentes à une licence globale

Les notices des miroirs mentionnent aussi des modèles **non commerciaux** ou
**ShareAlike** présents dans ces autres dépôts : yacht Frickie, dauphin, raie,
tortue, autre mouette. Ces fichiers ne font pas partie des 14 téléchargements
retenus ci-dessus. Ne pas les ajouter par un téléchargement global du miroir.
Le nom d’auteur de `speedboat_smolbot` diffère entre une notice générale du miroir
et le manifeste/preuve créateur retenus ; conserver les deux documents, sans
écraser cette différence de provenance.

### Assets du socle

Le prefab `DatasetObserverFremm` référence le fichier original
`Assets/models/boat/fremm.dae`. Certaines scènes pilotes référencent un terrain
IslandTools et `ES_Underwater Ambience 4.mp3`. Ce sont des dépendances du projet
de base, non incluses dans les manifestes CC BY de nos variantes. Leur présence
dans une scène ne suffit pas à attribuer leurs droits. Le projet de base et ses
propres notices restent nécessaires.

## Métadonnées lors de la génération de corpus

Conserver avec les résultats les `asset-attributions.json` écrits par les
exporteurs, configurations demandées, plans/scénarios, paramètres réellement
capturés et manifestes de campagne. Pour un corpus diffusé, définir aussi une
politique d’attribution et de vérification des droits adaptée aux fichiers
effectivement utilisés. Le présent export n’est pas une validation juridique
générale de toutes les utilisations possibles.

Enfin, ne pas présenter les approximations visuelles comme des mesures validées :
la houle HDRP demandée en mètres reste un proxy non calibré ; pluie, infrarouge et
vision nocturne sont synthétiques ; la physique visuelle des modèles n’est pas
une hydrodynamique/aérodynamique certifiée. Cette provenance technique est aussi
importante que la provenance des modèles pour réutiliser les images correctement.
