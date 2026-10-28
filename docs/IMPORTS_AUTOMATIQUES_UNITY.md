# Intégrer automatiquement un modèle du dashboard à Unity

Le dashboard prépare les nouveaux meshes locaux ; l'éditeur Unity crée leur prefab
et leur Addressable, puis LOTUSim enregistre le modèle et le paramétrage le propose.
Un simple dépôt de fichier ne suffit plus à déclarer un modèle prêt : les deux côtés
échangent un reçu vérifié. Aucune simulation et aucun Play ne sont lancés automatiquement.

## Utilisation

1. Ouvrir le projet Unity `runtime/LOTUSim-Unity-modules` avec une licence adaptée à
   l'organisme et laisser **Play arrêté**. Garder le dashboard actif.
2. Dans [Modèles 3D](http://127.0.0.1:8766/#assets), choisir **Ajouter un modèle**,
   sélectionner le fichier et ses textures, puis renseigner sa catégorie et ses droits.
3. Vérifier l'axe vertical, l'axe avant et les **mètres par unité du fichier**.
   Par exemple, un modèle exprimé en centimètres demande `0,01` m par unité.
   La taille réelle ne peut pas être déduite de façon fiable de la géométrie seule.
4. Renseigner si besoin le tirant d'eau et les limites de vitesse/altitude.
   Ce sont des **capacités déclarées**, pas des performances mesurées par le système.
   La vitesse maximale vaut zéro par défaut ; les catégories fixes restent immobiles.
5. Importer et suivre les étapes de préparation et d'attente Unity. Une fois l'état
   **prêt** confirmé, le modèle devient sélectionnable dans
   [Paramétrage](http://127.0.0.1:8766/#settings), sans ressaisir la campagne en cours.

Si Unity est fermé, en Play, en compilation ou en rafraîchissement, l'import reste
en attente. Il reprend lorsque l'éditeur est disponible. En cas d'échec, corriger
les options et relancer depuis la fiche du modèle. Aucun autre moteur n'est démarré.

## Formats et limites

La conversion automatique couvre les **meshes statiques** OBJ/MTL, STL ASCII/binaire,
GLB 2.0 et glTF 2.0 pris en charge. Joindre les ressources locales référencées ; GLB
avec textures embarquées est souvent le plus simple. Les animations, squelettes,
morph targets, compressions ou attributs non implémentés sont refusés explicitement.
Il n'y a pas de téléchargement de textures et aucun script contenu dans un asset n'est exécuté.

Les matériaux sont convertis vers HDRP avec une politique opaque adaptée aux masques
d'instance. Cela peut modifier l'apparence du verre ou de matériaux transparents ;
ce n'est pas une conversion physiquement équivalente de tous les shaders.

Les limites d'entrée restent 64 Mio et 100 fichiers. Les budgets de géométrie, textures
et bundle préparé peuvent aussi refuser un objet trop lourd ; il faut alors exporter
un modèle statique plus léger, sans simplification silencieuse par le système.
Chaque dimension normalisée doit être comprise entre 1 mm et 1 000 m. Le tirant d'eau
est limité à 25 m et ne peut dépasser la hauteur du mesh ; une échelle erronée doit
être corrigée, pas compensée automatiquement.

## Ce qui est créé

Le reçu original et les fichiers importés restent sous
`runtime/LOTUSim/artifacts/mesh-library/imports/import-<uuid>/`.
Le traitement ajoute un bundle préparé, `unity-request.json`, `unity-result.json`
et les états de progression. Les fichiers et les révisions sont liés par SHA-256.

Unity crée un dossier de meshes et matériaux pour la révision, un prefab
`Assets/Prefabs/import_<uuid>.prefab`, une clé Addressable du même nom et une entrée
dans le registre des imports autorisés. Le prefab reçoit une racine cinématique,
un collider simple et les métadonnées de provenance. Les sources existantes et
les scènes en cours ne sont pas remplacées.

Après confirmation Unity, le backend crée le modèle SDF et son visuel sous
`runtime/LOTUSim/assets/models/import_<uuid>/`, puis met à jour le catalogue séparé
`assets/scenarios/catalogs/imported_assets.json`. Le catalogue de base reste inchangé.
Les classes existantes conservent leurs numéros ; la classe générique `other` utilise
le numéro 13.

L'enregistrement Addressables vise ici le travail dans l'éditeur et les captures
existantes. Une application Unity autonome nécessiterait aussi une construction de
ses bundles Addressables, non déclenchée par ce service.

## Houle et physique

La trajectoire cinématique reste pilotée par LOTUSim. La réaction à la houle est
visuelle et approximative, pas un calcul hydrodynamique validé. Pour les dimensions
marines compatibles, un tirant déclaré nul peut utiliser un proxy minimal de 5 cm
dans la réponse visuelle, sans modifier le tirant déclaré ni la géométrie enregistrée.
Si les dimensions ne conviennent pas à ce composant, le prefab reste utilisable mais
ce comportement n'est pas ajouté. Les feux de navigation ne sont pas inventés.

## Révisions et reproductibilité

Une campagne préparée référence les révisions des imports utilisés. Si le modèle
est reconstruit entre-temps, il faut préparer/importer une nouvelle campagne : le
système refuse de substituer silencieusement une nouvelle géométrie dans un ancien plan.
Le contrôle porte également sur le prefab et son GUID, pas seulement sur un état
« prêt » enregistré dans un JSON.

La licence déclarée et la page source sont conservées ; leur vérification juridique
et les obligations d'attribution restent à la charge de l'utilisateur et de l'organisme.

## Installation et diagnostic

Le dashboard demeure utilisable avec Python standard. La conversion tourne dans le
Python du projet LOTUSim, `.venv-vision/bin/python`, avec NumPy et Pillow. Si ces
dépendances manquent, l'import affiche un échec explicite au lieu de devenir disponible.

Sur une nouvelle installation, depuis la racine de cet export, créer ce venv s'il
n'existe pas puis installer les deux dépendances du convertisseur :

```bash
python3 -m venv runtime/LOTUSim/.venv-vision
runtime/LOTUSim/.venv-vision/bin/python -m pip install numpy Pillow
```

Sans les projets complets sous `runtime/`, utiliser le même venv dans le clone LOTUSim
installé. Le dashboard seul n'installe pas ces dépendances et ne démarre pas Unity.

Le récepteur Unity est installé dans les scripts Editor du projet et surveille le
dossier frère LOTUSim. Après mise à jour initiale, laisser Unity recompiler les scripts.
Le menu **LOTUSim > Models > Dashboard imports > Process pending imports now** permet
un contrôle manuel exceptionnel de la file, sans lancer Play ni créer un client ROS.

Les tests de convertisseur, de coordination, d'API et d'interface utilisent des
fixtures isolées. Une réussite de ces tests n'est pas, à elle seule, une preuve de
rendu GPU ou de stabilité physique d'un modèle nouvellement téléchargé.

Validation locale du 27 octobre 2026 : un cuboïde original CC0 a été déposé par l'API
du dashboard, converti, réellement importé par l'éditeur Unity et confirmé par son reçu.
Le prefab, sa clé Addressable, le SDF et l'entrée sélectionnable dans Paramétrage ont
été vérifiés. Ce modèle de test reste dans la bibliothèque sous « Validation import
automatique — cuboïde CC0 ». Ce test n'a lancé ni Play ni génération RGB : il valide
l'intégration, pas la qualité de rendu ou la physique d'un futur asset.

Pour un autre moteur, lire [le comparatif et le périmètre de l'adaptateur](ETUDE_MOTEURS_3D.md).
