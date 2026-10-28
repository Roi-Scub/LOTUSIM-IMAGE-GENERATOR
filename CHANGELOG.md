# Journal des versions

## 0.1.0 du 28 octobre 2026

Première version portable de LOTUSIM Image Generator. Le code existant est importé
dans des commits thématiques à la date d'import. Ces commits ne reconstituent pas
artificiellement les dates ou les états intermédiaires du développement précédent.

### Fonctionnalités

- Raccord LOTUSim et ROS2, corrections de connexion Unity et timeline cinématique.
- Capture RGB Unity, annotations, visibilité, occultation, statuts NR, PR et R.
- Bibliothèques de bouées, aéronefs et navires, réponses visuelles à la houle,
  éclairages et notices de provenance.
- Chaîne indépendante d'analyse RGB, exclusions de l'observateur et rapports.
- Dashboard local, télémétrie, prévisualisation, paramètres des campagnes et galerie
  de meshes avec import automatique dans Unity.
- Registre de moteurs, contrat de scène commun et préparateurs Unity et Unreal.
- Scénarios coopératifs, contrôles de séparation et de rencontres limités,
  bibliothèque SQLite, édition et réaudit de révisions immuables.
- Installateur d'intégration avec dépendances épinglées, correctifs séparés,
  lanceurs locaux, tests, guides et manifeste SHA-256.

### Périmètre

Le dépôt contient les sources portables et les assets sélectionnés, pas les clones
complets des moteurs, caches, conteneurs, résultats ni bases SQLite de travail.
Les licences et attributions des composants restent distinctes.

Unity conserve sa chaîne existante. Unreal est un prototype d'aperçu statique ; les
autres profils exportent un contrat neutre et nécessitent un adaptateur natif.
Les contrôles COLREG sont partiels, non certifiants, sans navigation réactive.
Les rendus météo, thermiques et les réponses visuelles à la mer restent des
approximations de simulation, pas des mesures calibrées.
