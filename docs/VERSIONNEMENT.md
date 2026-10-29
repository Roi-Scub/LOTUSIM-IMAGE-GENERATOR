# Versionnement du projet

Le dépôt privé `Roi-Scub/LOTUSIM-IMAGE-GENERATOR` versionne l'export portable des
développements, des modèles sélectionnés et des correctifs. La version majeure
actuelle est **1.0.0 — Official Release** ; la version initiale était `0.1.0`.
Les sources exécutées sur ce poste restent sous `runtime/`, qui est
exclu de Git : reporter chaque évolution réutilisable dans `components/` ou dans
son correctif avant de la committer.

## Historique initial

Le dépôt conserve son commit de licence initial. Les développements existants sont
ajoutés dans de vrais commits thématiques datés de l'import, sans antidatage et
sans inventer d'anciens états fonctionnels. Ils séparent intégration, modèles,
captures, validation RGB, dashboard, moteurs, imports et trafic coopératif.

Les commits d'import constituent ensemble le premier snapshot complet ; chacun
n'est pas une livraison autonome. Le tag annoté `v0.1.0` désigne ce snapshot.

## Version majeure officielle

Le tag annoté `v1.0.0` désigne la livraison de **LOTUSIM Image Generator** publiée
sous le titre **v1.0.0 — Official Release** dans le dépôt privé. Il ne désigne
pas une version officielle du simulateur LOTUSim de Naval Group.

Cette livraison est préparée depuis `refactor`, dont le code a déjà été fusionné
dans `main` avant la publication. Le commit de version et le tag n’effectuent
aucune fusion supplémentaire et ne déploient pas les sources sous `runtime/`.
Pour obtenir exactement cette livraison, cloner ou sélectionner le tag `v1.0.0`
plutôt que supposer que la branche par défaut pointe dessus.

## Enregistrer une évolution

1. Modifier les sources actives, tester puis reporter explicitement les fichiers
   réutilisables dans les sources portables. Ne pas recopier les caches ni les
   projets complets sous `components/`.
2. Mettre à jour le guide ou le journal des changements si le comportement change.
3. Rafraîchir et vérifier les empreintes depuis la racine :

   ```bash
   python3 scripts/refresh_manifest.py --write
   python3 scripts/verify_export.py
   git status --short
   git diff --stat
   ```

4. Ajouter uniquement les chemins concernés, vérifier ce qui est préparé et créer
   un commit avec un sujet explicite :

   ```bash
   git add components/LOTUSim/tools/lotusim_image_generator/traffic/library.py manifest.json
   git diff --cached --stat
   git commit -m "fix(traffic): corriger la validation des revisions"
   git push origin refactor
   ```

Pour une évolution conséquente, utiliser une branche `feature/...` ou `fix/...`
et une pull request. Ne pas forcer l'envoi sur `main` et ne pas antidater les commits.

## Marquer une version

`VERSION`, la version racine de `package.json` et les deux versions racines de
`package-lock.json` doivent être identiques. `README.md` et `CHANGELOG.md`
présentent le contenu livré. Les versions des dépendances ne changent pas lors
d’une simple publication du projet.

À partir de `1.0.0`, incrémenter le correctif pour une correction compatible, la
version mineure pour une fonctionnalité compatible et la version majeure pour
une rupture du périmètre public documenté. Les prototypes et limites de validation
restent explicités ; un numéro majeur ne certifie pas les moteurs ou les images.

Après les tests, mettre à jour le manifeste et committer les fichiers de version,
puis créer un tag annoté et le pousser avec la branche autorisée. Par exemple,
pour une future correction `1.0.1` préparée sur `refactor` :

```bash
git tag -a v1.0.1 -m "LOTUSIM Image Generator 1.0.1"
git -c http.version=HTTP/1.1 -c http.postBuffer=8388608 \
  push --atomic origin refactor refs/tags/v1.0.1
```

Ne jamais déplacer un tag déjà partagé vers un autre commit. Un tag Git n'est ni
un binaire compilé ni une validation de rendu ou de conformité réglementaire.

Créer ensuite la release GitHub sur ce tag avec ses notes, sans la marquer comme
brouillon ni préversion lorsqu’il s’agit d’une livraison officielle. Vérifier le
commit visé, la confidentialité du dépôt et le statut de dernière version. La
publication d’une release ne change pas la branche par défaut ni les sources
actuellement exécutées sur un poste.

## Données exclues et fichiers volumineux

`runtime/`, `.local/`, les images générées, rapports, conteneurs, poids IA,
environnements Python, caches Unity, identifiants et bases SQLite de travail ne
font pas partie des commits. L'état local du dashboard et les fichiers existants
restent sur ce poste. Ne jamais ajouter ces dossiers avec `git add --force`.

Les modèles et textures sélectionnés restent versionnés avec leurs notices.
Les gros fichiers existants sont inclus dans Git sans dépendance à Git LFS ;
contrôler les limites du serveur avant d'ajouter de nouveaux fichiers volumineux.
`.gitattributes` conserve les octets exacts pour que le manifeste soit vérifiable
après un clone, et masque les diffs de géométrie les plus volumineux.
