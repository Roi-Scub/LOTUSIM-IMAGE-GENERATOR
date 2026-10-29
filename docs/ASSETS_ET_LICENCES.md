# Assets et licences

Les [crédits du README](../README.md#modèles-3d-et-crédits) recensent les modèles
et leurs auteurs. La licence du code ne s’applique pas automatiquement à tous
les médias utilisés par une scène.

| Ensemble | Licence et provenance |
| --- | --- |
| Créations procédurales de Gabriel Ricardon | [CC BY 4.0, périmètre explicite](LICENCE_ASSETS.md) |
| 14 modèles externes | CC BY 4.0 déclarée dans les manifestes, notices et preuves archivées ; réserves ci-dessous |
| Modèles et environnement du socle | Notices du projet officiel et de leurs fournisseurs ; pas de nouvelle attribution à Gabriel |
| Code et générateurs | [EPL-2.0](../LICENSE), avec conservation des en-têtes existants |
| Packages et bibliothèques tierces | Licences propres, notamment Three.js MIT dans le visualiseur |

## Sources externes

Les deux manifestes sont la référence pour retrouver les fichiers effectivement
intégrés, leurs auteurs, les pages sources, les commits miroirs, les SHA-256 et
les changements de conversion :

- [OpenBoats](../components/LOTUSim-Unity-modules/ThirdParty/OpenBoats/manifest.json) : six bateaux.
- [OpenObjects](../components/LOTUSim-Unity-modules/ThirdParty/OpenObjects/manifest.json) : huit variantes maritimes et aériennes.

Conserver `ThirdParty/` avec les sources GLB/FBX sélectionnées, `ATTRIBUTION.txt`,
preuves `creator-license.json` ou `sketchfab-license.json`, inspections et textes
de licence. Les dossiers `Assets/models/open_boats/`, `open_objects/` et les modèles
Gazebo associés restent des adaptations de ces œuvres, pas des créations originales.

Les conversions comprennent selon le modèle : orientation, échelle, ligne d’eau
artistique, regroupement des meshes, matériaux HDRP opaques, animation et lumières.
Elles ne conservent pas nécessairement la transmission du verre ou tous les effets
du matériau source. Les listes détaillées restent dans les notices locales.

Les dimensions, masses, vitesses et réponses aux vagues sont des paramètres de
simulation. Les noms commerciaux et les crédits n’impliquent aucun soutien des auteurs
ou fabricants.

## Cas à vérifier avant diffusion

### Goéland Dayvable

La preuve `OpenObjects/seagull_dayvable/creator-license.json` contient à la fois
une licence CC Attribution et un tag `noai`. Ne pas supprimer ce signalement.
Faire clarifier les droits avant entraînement ou diffusion d’un corpus utilisant
ce modèle. Le goéland procédural `seagull` est une autre géométrie, couverte par
la licence des créations originales.

### Noms d’auteur dans les miroirs

Pour `speedboat_smolbot`, la notice générale du miroir diffère du manifeste et
de la preuve créateur retenus, qui créditent **Nicosama**. Garder les deux pièces.
Le Cessna 172 est crédité **Nobilis the Palaeovespa** dans notre archive et **e737**
dans la notice du miroir gods-eye-view ; la page source reste la même.

Les miroirs contiennent aussi d’autres modèles NC ou ShareAlike non retenus ici,
notamment yacht Frickie, dauphin, raie, tortue et autre mouette. Ne pas importer
le miroir complet en lui attribuant la licence de notre sélection.

### Ressources du socle

`DatasetObserverFremm` référence `Assets/models/boat/fremm.dae`. Certaines scènes
référencent IslandTools et `ES_Underwater Ambience 4.mp3`. Ces ressources ne sont
pas couvertes par notre licence CC BY et ne sont pas redistribuées comme des
créations de Gabriel. LRAUV, x500, HDRP, Photon, XR, polices et autres dépendances
gardent aussi leurs propres notices.

## Corpus et nouveaux imports

Garder les crédits des modèles effectivement utilisés avec les données diffusées.
Conserver aussi les `asset-attributions.json` produits par les pilotes qui les
exportent, les configurations et les manifestes de campagne. La licence d’un mesh
ajouté depuis le dashboard reste celle déclarée pour cet import ; le formulaire
ne vérifie pas les droits à la place de l’utilisateur.

La licence d’un modèle ne suffit pas à fixer celle de tous les éléments d’une
image. Vérifier aussi les textures, sons ou environnements inclus dans le corpus
avant sa publication.
