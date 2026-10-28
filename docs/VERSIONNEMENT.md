# Versionnement du projet

Le dépôt privé `Roi-Scub/LOTUSIM-IMAGE-GENERATOR` versionne l'export portable des
développements, des modèles sélectionnés et des correctifs. La version initiale
est `0.1.0`. Les sources exécutées sur ce poste restent sous `runtime/`, qui est
exclu de Git : reporter chaque évolution réutilisable dans `components/` ou dans
son correctif avant de la committer.

## Historique initial

Le dépôt conserve son commit de licence initial. Les développements existants sont
ajoutés dans de vrais commits thématiques datés de l'import, sans antidatage et
sans inventer d'anciens états fonctionnels. Ils séparent intégration, modèles,
captures, validation RGB, dashboard, moteurs, imports et trafic coopératif.

Les commits d'import constituent ensemble le premier snapshot complet ; chacun
n'est pas une livraison autonome. Le tag annoté `v0.1.0` désigne ce snapshot.

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
   git add components/LOTUSim/tools/traffic_plan_library.py manifest.json
   git diff --cached --stat
   git commit -m "fix(traffic): corriger la validation des revisions"
   git push origin main
   ```

Pour une évolution conséquente, utiliser une branche `feature/...` ou `fix/...`
et une pull request. Ne pas forcer l'envoi sur `main` et ne pas antidater les commits.

## Marquer une version

`VERSION` et `CHANGELOG.md` identifient le contenu livré. Pendant la série `0.x`,
incrémenter le correctif pour une correction compatible et la version mineure pour
une nouvelle fonctionnalité ou un changement d'intégration important. Documenter
toute rupture de format ou d'API dans le journal.

Après les tests, mettre à jour le manifeste et committer les trois fichiers, puis
créer un tag annoté. Par exemple, pour une future correction `0.1.1` :

```bash
git tag -a v0.1.1 -m "LOTUSIM Image Generator 0.1.1"
git push --atomic origin main refs/tags/v0.1.1
```

Ne jamais déplacer un tag déjà partagé vers un autre commit. Un tag Git n'est ni
un binaire compilé ni une validation de rendu ou de conformité réglementaire.

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
