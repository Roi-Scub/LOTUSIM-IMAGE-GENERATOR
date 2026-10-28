# Répertoire de développement actif

Le répertoire de travail est la racine du clone contenant ce fichier.
Déterminer son chemin absolu et le fournir explicitement aux commandes. Les anciens dossiers sous
`STAGE - CEMIS - LOTUSIM` sont des secours : ne plus les modifier ni y lancer de services.

## Sources exécutées

- `runtime/LOTUSim/` : clone complet avec les modifications locales, le dashboard,
  les configurations, les modèles Gazebo et le build Linux.
- `runtime/LOTUSim-Unity-modules/` : projet Unity complet, scènes, capture et annotation.
- `components/`, `patches/`, `references/` : sources et correctifs portables ; initialisés
  avant migration, puis enrichis notamment de la bibliothèque de meshes. Ne pas les
  confondre avec les projets complets exécutés sous `runtime/`. Quand un ajout local est
  modifié, reporter explicitement ses sources portables concernées dans `components/`
  et rafraîchir le manifeste. Ne jamais écraser le runtime entier depuis un ancien snapshot.
- `scripts/` et `docs/SESSION_LOCALE.md` : lanceurs et instructions de cette installation.

## Services et précautions

Le conteneur actif est `lotusim-dev`, monté sur `runtime/LOTUSim` -> `/workspace`.
L'ancien conteneur `lotusim-dev-before-export-20261027` reste arrêté pour récupération.
Lancer `python3 scripts/start_local_stack.py status` pour vérifier les chemins et ports.
Le lanceur ouvre uniquement des onglets locaux ; il ne déclenche pas Play ni de campagne.
Ne jamais lancer `lotusim.world` en même temps que `maritime_dataset.world` dans `/lotusim`.
Ne pas sonder TCP10000 avec une connexion de test (cela crée un faux client ROS TCP).
Ne pas arrêter Unity de force ni une génération active sans accord.
Ne pas publier le dashboard ou les images : fonctionnement local uniquement.
Ne pas journaliser les arguments complets de Unity, pouvant contenir des jetons.

Les résultats et dépendances lourdes sous `runtime/` et `.local/` ne sont pas à publier
automatiquement. Conserver les licences et les `.meta` Unity lors des copies.
