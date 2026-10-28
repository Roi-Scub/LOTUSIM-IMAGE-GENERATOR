# Paramétrage des campagnes d’images

L’onglet **Paramétrage** du dashboard local permet de construire un plan d’expérience sans éditer les scripts. Cette première version prépare des **images indépendantes**, pas une vidéo continue : la composition demandée est réinitialisée pour chaque prise de vue. LOTUSim reste la source des poses ; Unity réalise le rendu, la réponse visuelle à la houle et les annotations géométriques.

## Procédure

1. Ouvrir `http://127.0.0.1:8766/#settings` et choisir **Unity** et la scène maritime connectée à la passerelle de la FREMM.
2. Définir le nom, la graine, la résolution et le total d’images. Ajouter les blocs souhaités ; la somme de leurs nombres d’images doit égaler le total.
3. Pour chaque bloc, choisir jour, crépuscule ou nuit, la couverture nuageuse, la pluie visuelle, la houle cible et sa direction. Ajouter les lignes d’objets et leurs paramètres.
4. **Vérifier la configuration**, puis **Enregistrer localement** pour conserver un brouillon ou **Préparer pour Unity** pour produire un couple immuable `campaign.json` / `manifest.json`.
5. Hors Play dans Unity, menu **LOTUSim > Dataset > Manual campaigns > Import prepared campaign**. Sélectionner **manifest.json** dans le dépôt LOTUSim : `artifacts/campaign-settings/prepared/<identifiant>/`. Garder `campaign.json` dans le même dossier ; l’empreinte du manifeste permet de détecter une modification après préparation.
6. L’import prépare une **nouvelle scène et de nouveaux assets**, sans modifier les scènes existantes. Vérifier les messages de validation, puis appuyer sur **Play** dans cette nouvelle scène. Garder les services LOTUSim et ROS habituels ouverts. Ne pas lancer le même scénario manuellement en parallèle.

La préparation dans le navigateur ne démarre aucun moteur. L’import Unity ne lance pas Play. Un scénario tiers déjà actif n’est pas arrêté pour faire de la place ; une erreur ou un nettoyage non confirmé arrête la campagne en conservant les fichiers déjà produits.

## Exemple de répartition

Une campagne peut demander 2 images de nuit contenant 3 voiliers et 1 chalutier, puis 4 images de jour contenant 1 avion, 2 oiseaux et 1 drone sous forte houle. Il faut alors définir **6 images au total**, deux blocs, et les lignes d’objets correspondantes. Une même catégorie peut avoir plusieurs lignes : par exemple un voilier à 20 m et un autre à 100 m.

Ces effectifs décrivent la **composition prévue en 3D**, pas une garantie d’objets reconnaissables dans chaque image : hors-champ, immersion, masque par un autre objet et faible taille apparente restent possibles et font partie de l’expérience. Consulter ensuite les annotations réellement rendues.

## Sens des paramètres

| Paramètre | Interprétation |
| --- | --- |
| Résolution | Largeur × hauteur des images, de 64 à 4 096 pixels par axe ; augmenter la résolution augmente le coût GPU et le stockage. |
| FOV | Champ de vision **vertical**, de 30 à 90°. Il modifie la taille apparente sans changer les dimensions physiques des modèles. |
| Vue / axe du bateau | Orientation relative au bateau : 0° vers l’avant, 90° vers tribord ; le cap de l’observateur reste une direction absolue. |
| Distance | Portée **horizontale nominale depuis la caméra de passerelle**, en mètres. La distance 3D effectivement rendue dépend aussi de l’altitude et du mouvement de houle. |
| Hauteur cible en pixels | Estimation de projection, calculée à partir de la hauteur du catalogue et du FOV. Le mode inverse ajuste la distance nominale, jamais l’échelle du modèle. |
| Relèvement | Emplacement de l’objet par rapport à la direction de vue ; 0° devant la caméra. |
| Dispersion | Écart angulaire entre les instances d’une même ligne. Une dispersion nulle avec plusieurs instances peut les superposer. |
| Cap | Direction absolue de déplacement, 0° nord, 90° est. Distinct du relèvement. |
| Vitesse | Stockée en m/s, présentée en nœuds pour les bateaux et en km/h pour les aéronefs. La borne provient du catalogue. |
| Houle cible | Paramètre de mise en scène traduit en réglages du spectre HDRP, **pas une hauteur significative effectivement mesurée et calibrée**. |
| Nuages et pluie | Proxies visuels ; la pluie n’est pas exprimée en mm/h et ses gouttes ne constituent pas une nouvelle vérité terrain d’occultation. |

Pour une petite cible centrée, l’estimation utilisée est :

`hauteur_px ≈ hauteur_objet_m × hauteur_image_px / (2 × tan(FOV_vertical / 2) × distance_horizontale_m)`

L’orientation, la perspective hors axe, l’altitude, le roulis, l’occlusion et la portion immergée limitent cette approximation. Les pixels réellement visibles et les niveaux NR / PR / R doivent être lus dans les annotations après rendu.

## Bornes et réalisme

La campagne est bornée à 2 000 images, 50 blocs, 40 objets simultanés et 12 objets par catégorie et par bloc. Le catalogue fournit les modèles disponibles, leurs dimensions et les limites de vitesse et d’altitude. Beaucoup de profils sont des **hypothèses de simulation**, pas des performances constructeur certifiées ; le drone rapide fictif reste identifié comme tel. Une bouée ne reçoit pas de vitesse propre.

Les images sont des échantillons indépendants au premier instant de chaque scène ; les vitesses et caps restent enregistrés dans le scénario et les métadonnées, mais cette campagne ne mesure pas un déplacement inter-images. Pour une trajectoire continue, conserver les scènes de trafic existantes.

Unity est le premier adaptateur. Un brouillon **Unreal Engine** peut être enregistré et exporté dans le format neutre, mais ne peut pas être préparé ou lancé tant qu’un adaptateur Unreal n’est pas installé. Le nouveau pilote manuel est limité au RGB ; les anciens pilotes conservent leurs modes IR et vision nocturne.

## Résultats et traçabilité

Les brouillons et préparations sont enregistrés dans `LOTUSim/artifacts/campaign-settings/`. Ils reçoivent des identifiants uniques et n’écrasent pas leurs versions précédentes.

Les sorties Unity sont regroupées dans `LOTUSim-Unity-modules/artifacts/manual-campaigns/`. La galerie de campagne donne accès aux images et à leur provenance. Le dossier commun `rgb/` est directement utilisable par le RGB Observer, avec des noms uniques ; les annotations géométriques sont regroupées dans `annotations/`. Chaque prise de vue conserve aussi son dossier source complet (exports COCO/YOLO, masques, paramètres et empreintes). Ne pas supposer qu’un COCO unique a été fusionné : le manifeste d’images précise les exports disponibles.

La préparation est validée par le backend ; l’import vérifie de nouveau les fichiers et les références Unity. La compilation et les tests hors rendu ne remplacent pas un essai GPU de bout en bout : commencer par **une ou deux images** avant une campagne de plusieurs centaines.
