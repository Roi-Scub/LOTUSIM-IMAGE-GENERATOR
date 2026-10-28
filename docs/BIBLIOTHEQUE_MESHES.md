# Bibliothèque locale de modèles 3D

Ouvrir <http://127.0.0.1:8766/#assets>, ou choisir **Modèles 3D** dans le dashboard.
Cette section inspecte les fichiers géométriques et conserve les nouveaux imports sur
ce Mac. Elle ne lance pas de simulation, ne modifie pas une scène et ne publie rien.

## Consulter un modèle

Rechercher un nom, filtrer par catégorie ou par état, puis sélectionner une carte.
Glisser dans l'aperçu pour tourner, utiliser la molette pour zoomer, **Recentrer** pour
rétablir le cadrage, et **Maillage** pour le fil de fer.

La bibliothèque détecte les modèles du catalogue de génération, les meshes historiques
(par exemple FREMM et LRAUV) et les imports locaux. Les états sont distingués :

- **Intégré au pipeline** : modèle déjà connu du catalogue des campagnes existantes.
- **Source historique** : géométrie disponible ; son intégration actuelle au pipeline reste à vérifier.
- **Importé / en préparation / attente Unity** : conversion en cours ou prefab non encore confirmé.
- **Échec** : une étape a refusé le modèle ; ouvrir ses réglages et relancer après correction.
- **Prêt** : prefab Unity et modèle LOTUSim confirmés ; disponible dans Paramétrage.

Les nombres de triangles proviennent du fichier chargé. Les dimensions de catalogue,
lorsqu'elles existent, ne sont pas une certification des unités du fichier importé.
L'aperçu montre la géométrie et ses matériaux disponibles, pas le rendu de l'océan Unity.
La bouée `buoy` a un aperçu simplifié reconstruit depuis ses primitives Gazebo ; son
prefab Unity détaillé est différent. Les meshes lourds nécessitent un chargement explicite.

## Ajouter un fichier

Cliquer **Ajouter un modèle**, renseigner nom, catégorie, licence ou droits déclarés,
et éventuellement la page source. Choisir le mesh et ses fichiers associés, sélectionner
le fichier principal, confirmer les droits nécessaires, puis **Importer dans la bibliothèque**.
Si le modèle utilise des sous-dossiers de textures, choisir **Choisir un dossier avec
ses textures** : les chemins relatifs sont conservés. Utiliser des noms de fichiers
simples en lettres ASCII, chiffres, espaces, tirets ou underscores.

Formats d'import : **GLB 2.0**, **glTF 2.0**, **OBJ** et **STL**. Pour un OBJ, joindre
le `.mtl` et les textures référencées ; pour un glTF séparé, joindre les `.bin` et images.
Un GLB non compressé avec textures embarquées est généralement le plus simple.
Les références relatives doivent correspondre aux fichiers joints ; les URI externes
et chemins absolus sont refusés. Les DAE déjà présents sont consultables, mais ne font
pas partie des formats d'import de ce premier écran. Les FBX, ZIP et scripts ne sont pas acceptés.

Limites : **64 Mio au total**, **100 fichiers** par import ; Draco, Meshopt et KTX2
ne sont pas décodés dans cette version. En cas de référence de texture manquante,
le formulaire refuse l'import plutôt que de télécharger une ressource externe.

Les fichiers sont conservés sous :

```text
runtime/LOTUSim/artifacts/mesh-library/imports/import-<uuid>/
  asset.json       # métadonnées et empreintes SHA-256
  files/          # originaux importés
```

Les fichiers et la licence déclarée restent consultables après rechargement du dashboard.
Un enregistrement ne vaut pas vérification juridique de la licence. La provenance
`seagull_dayvable` porte une mention NoAI : son usage pour entraînement/dataset reste à clarifier.

## Passer d'un import à un objet simulé

L'intégration est maintenant **automatique**, avec le projet Unity ouvert **hors Play**.
Déclarer la catégorie, l'échelle, l'axe avant et les limites de vitesse/altitude dans le
formulaire. Le convertisseur prépare le mesh ; Unity crée son prefab et son Addressable ;
le backend confirme les fichiers et ajoute le modèle LOTUSim au catalogue complémentaire.
Il apparaît alors dans Paramétrage, sans effacer le brouillon en cours.

Les capacités déclarées ne sont pas déduites ni certifiées par le mesh. Le collider est
simple et la réponse à la houle est visuelle, pas une hydrodynamique validée. Les animations
et les feux de navigation ne sont pas inventés. Les formats statiques non pris en charge
sont refusés explicitement. Lire [le guide de l'import automatique](IMPORTS_AUTOMATIQUES_UNITY.md).

## Technique et tests

Le serveur du dashboard utilise la bibliothèque standard Python ; le worker de conversion
utilise le Python `.venv-vision` avec NumPy et Pillow. Le visualiseur emploie
Three.js 0.180.0, livré localement avec sa licence MIT et un inventaire d'empreintes sous
`tools/ops_dashboard_ui/vendor/three/`. Il n'y a ni CDN ni appel à un modèle distant.

Les imports sont stockés séparément des modèles existants. Le serveur impose une origine
locale, un en-tête d'intention, des limites de taille, une liste de formats, des références
de fichiers locales et un stockage sans suivi de symlink. Les fichiers ne sont jamais exécutés.

Tests Python, depuis `runtime/LOTUSim` :

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_mesh_*.py'
```

Les tests d'API ouvrent des ports temporaires sur le loopback. Les tests de navigateur
interceptent les écritures dans des fixtures isolées. Un cuboïde original CC0, nommé
« Validation import automatique », est conservé dans la bibliothèque locale pour le
test réel de création du prefab et de disponibilité au paramétrage ; il ne représente
pas un navire réaliste. Ce test ne lance ni Play ni génération d'images.
