# Bouée marine instrumentée — prefab LOTUSim

Asset original construit pour ce projet, sans modèle ni texture tiers.

Crédit : **Gabriel Ricardon (Roi-Scub)**. Géométrie, textures et matériaux originaux
sous [CC BY 4.0](../../../ORIGINAL_ASSETS_LICENSE.md), avec attribution.

- Prefab : `Assets/Prefabs/buoy.prefab` ; adresse Addressables : `buoy`.
- Bouée générique orange instrumentée, et non reproduction d'une marque ou d'une signalisation nautique réglementaire.
- Diamètre du flotteur : 0,76 m ; bande de protection : environ 0,79 m.
- Lanterne / antenne : environ 1,54 m au-dessus de l'origine.
- Chaîne d'amarrage visible jusqu'à environ -0,50 m.
- Axe vertical Unity : Y ; origine et ligne d'eau nominale : Y=0 ; échelle : 1 unité = 1 m.
- Matériaux HDRP/Lit : peinture avec corrosion, sel et salissures de ligne d'eau ; carte de normales et masque PBR ; caoutchouc, métal, bande réfléchissante, cellules solaires et lentille ambrée.
- Les petites ferrures sont regroupées par matériau pour réduire le nombre de renderers.
- Pas de Rigidbody, de scripts de mouvement, de lumière clignotante ni de simulation d'eau. LOTUSim reste la source des poses.

L'éditeur génère les éléments à son prochain état inactif, hors Play, si le prefab ne contient pas encore son enfant `MarineBuoyVisual_v1`. Reconstruction manuelle : **LOTUSim → Models → Build realistic buoy**. La reconstruction conserve le GUID du prefab et les composants/enfants de l'utilisateur autres que cet enfant généré.

Le scénario doit demander `renderer_type: buoy`. Lancer Unity avant de relancer le scénario pour recevoir sa commande CREATE. En mode éditeur, utiliser **Use Asset Database** dans les Addressables ; si l'on utilise un catalogue construit, reconstruire le contenu Addressables après ajout du prefab.

Vérification automatique : `artifacts/buoy/validation.txt`. Aperçu réel de l'asset Unity : `artifacts/buoy/preview.png` lorsqu'AssetPreview est disponible.

Important pour le dataset : cette géométrie détaillée n'est pas identique au prototype cylindrique Gazebo `assets/models/buoy/model.sdf`. Les masques et boîtes destinés aux images Unity doivent provenir du rendu Unity. Ne pas reporter directement les boîtes Gazebo sur les images Unity ; harmoniser les géométries si une comparaison croisée est nécessaire. Le relief des vagues ne déplace pas automatiquement ce modèle statique.
