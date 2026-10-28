"""Local RGB audit with a single readable frame and an explicit exclusion editor.

The viewer never reads test annotations. It displays detector/review JSON and
clean RGB, while optional metrics are supplied by the separate evaluator.
Rejected hypotheses remain inspectable and no browser edit changes predictions.
"""

import html
import json
import math
from pathlib import Path
import re


def esc(value):
    return html.escape(str(value), quote=True)


def _finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _relative(path, prefix=None):
    path = Path(path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Unsafe gallery path")
    if prefix is not None and path.parts[0] != prefix:
        raise ValueError("Unexpected gallery path prefix")
    return path.as_posix()


def _prediction(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid gallery prediction")
    box = value.get("bbox")
    if (
        not isinstance(box, (tuple, list))
        or len(box) != 4
        or not all(_finite(v) for v in box)
        or box[2] <= 0
        or box[3] <= 0
    ):
        raise ValueError("Invalid gallery bounding box")
    if not _finite(value.get("score")) or not 0 <= value["score"] <= 1:
        raise ValueError("Invalid gallery prediction score")
    result = dict(value)
    evidence = dict(result.get("semanticEvidence") or {})
    neighbors = []
    for neighbor in evidence.get("neighbors", []):
        neighbor = dict(neighbor)
        neighbor["crop"] = _relative(neighbor["crop"], "crops")
        neighbors.append(neighbor)
    evidence["neighbors"] = neighbors
    result["semanticEvidence"] = evidence
    return result


def _exclusions(review):
    values = review.get("excludeRegions", review.get("exclusions", []))
    result = []
    for region in values:
        polygon = region.get("polygon")
        if not isinstance(polygon, list) or not 3 <= len(polygon) <= 128:
            raise ValueError("Invalid gallery exclusion polygon")
        if any(
            not isinstance(p, (list, tuple))
            or len(p) != 2
            or not all(_finite(v) and 0 <= v <= 1 for v in p)
            for p in polygon
        ):
            raise ValueError("Exclusion coordinates must be normalized")
        result.append({"id": str(region.get("id", "ownship")), "polygon": polygon})
    return result


def build_gallery_data(output, mapping, report=None, warnings=None):
    output = Path(output)
    frames = []
    counts = {"retained": 0, "uncertain": 0, "rejected": 0}
    for item in mapping:
        neutral = str(item["workerImage"])
        if not re.fullmatch(r"i[0-9]{6}\.png", neutral):
            raise ValueError("Gallery requires neutral RGB names")
        path = output / "predictions" / (Path(neutral).stem + ".json")
        payload = json.loads(path.read_text()) if path.is_file() else {}
        width, height = item["width"], item["height"]
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise ValueError("Invalid native gallery dimensions")
        retained = [_prediction(p) for p in payload.get("predictions", [])]
        review = payload.get("review") or {}
        rejected = []
        for entry in review.get("rejected", []):
            if "prediction" not in entry:
                raise ValueError("Rejected entry must preserve its original prediction")
            rejected.append({**entry, "prediction": _prediction(entry["prediction"])})
        counts["retained"] += len(retained)
        counts["uncertain"] += sum(
            (
                p.get("reviewStatus") == "uncertain"
                if p.get("reviewStatus") in {"retained", "uncertain"}
                else bool(p.get("semanticConflict"))
                or p.get("recognitionDecision") == "indeterminate"
                or p.get("category") == "unknown"
            )
            for p in retained
        )
        counts["rejected"] += len(rejected)
        mask = review.get("exclusionMask")
        if mask is not None:
            mask = _relative(mask, "input")
            if not mask.startswith("input/observer-exclusion/"):
                raise ValueError("Only the observer exclusion mask may enter the viewer")
        frames.append(
            {
                "sourceImage": str(item["sourceImage"]),
                "workerImage": neutral,
                "width": width,
                "height": height,
                "raw": "input/rgb/" + neutral,
                "predictionFile": "predictions/" + Path(neutral).stem + ".json",
                "retained": retained,
                "rejected": rejected,
                "exclusions": _exclusions(review),
                "exclusionMask": mask,
                "reviewCounts": review.get("counts", {}),
                "predictionAvailable": path.is_file(),
            }
        )
    metrics = None
    if report:
        fields = (
            "truePositives",
            "falsePositives",
            "falseNegatives",
            "precision",
            "recall",
            "f1",
            "iouThreshold",
            "byVisiblePixelSize",
            "reference",
        )
        metrics = {key: report.get(key) for key in fields}
    return {
        "schema": "lotusim-rgb-gallery-2",
        "frames": frames,
        "counts": counts,
        "warnings": [str(w) for w in (warnings or [])],
        "metrics": metrics,
        "inputContract": "clean RGB + detector/review outputs; no target geometry for display correction",
    }


PAGE = r'''<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LOTUSim · revue visuelle RGB</title><style>
:root{color-scheme:dark;--bg:#0c1822;--panel:#142837;--line:#355063;--text:#e9f1f5;--muted:#a6bbc7;--blue:#48c9ff;--amber:#ffbd59;--gray:#aeb7c1;--red:#ff7383}
*{box-sizing:border-box}body{font:15px/1.5 system-ui,sans-serif;margin:0;background:var(--bg);color:var(--text)}a{color:#8cdcff;text-underline-offset:3px}header{padding:24px max(24px,4vw);background:#132c3d;border-bottom:1px solid var(--line)}h1{font-size:28px;line-height:1.2;margin:5px 0 10px}h2{font-size:20px;margin:0 0 10px}h3{font-size:16px;margin:6px 0}.eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#83d4e4}.subtitle{max-width:1000px;margin:8px 0;color:#c8dbe4}.stats{color:#a8e4ee;font-variant-numeric:tabular-nums}main{max-width:1600px;padding:24px;margin:auto}.toolbar,.controls{display:flex;flex-wrap:wrap;align-items:center;gap:10px}.toolbar{margin:0 0 12px}.toolbar select{min-width:200px;max-width:400px;flex:1}.controls{gap:18px;padding:12px 16px;background:var(--panel);border:1px solid var(--line);border-radius:9px 9px 0 0}button,select,input[type=text]{font:inherit;background:#1d394b;color:var(--text);border:1px solid #527184;border-radius:5px;padding:7px 11px}button{cursor:pointer}button:hover:not(:disabled){background:#2b526b}button:disabled{opacity:.45;cursor:not-allowed}label{display:inline-flex;gap:6px;align-items:center}input[type=checkbox]{accent-color:#48c9ff}input[type=range]{max-width:140px;accent-color:#48c9ff}.legend{display:inline-block;width:12px;height:12px;margin-right:3px;border:2px solid currentColor}.blue{color:var(--blue)}.amber{color:var(--amber)}.gray{color:var(--gray)}.red{color:var(--red)}#canvasScroll{width:100%;max-height:78vh;min-height:250px;overflow:auto;background:#07111a;border:1px solid var(--line);border-top:0}#viewer{display:block;width:100%;height:auto;touch-action:pan-x pan-y}#viewer.editing{cursor:crosshair;touch-action:none}#viewer image{pointer-events:none}.box{cursor:pointer;vector-effect:non-scaling-stroke}.box.selected{stroke:#fff;stroke-width:3}#frameInfo{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:13px;padding:10px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin:20px 0}.panel{padding:18px;background:var(--panel);border:1px solid var(--line);border-radius:9px}.panel p{margin:8px 0}.muted{color:var(--muted)}.notice{padding:10px 14px;background:#3b2c19;color:#ffdfac;border-radius:5px;margin:12px 0}.small{font-size:13px}.row{padding:10px 0;border-top:1px solid var(--line)}.row:first-child{border-top:0}.rowHead{display:flex;gap:10px;justify-content:space-between;align-items:center}.rowHead button{padding:4px 8px;font-size:13px;flex-shrink:0}.row.selected{background:#25475c;border-radius:5px;padding-left:10px;padding-right:10px}details{margin:12px 0}summary{cursor:pointer;font-weight:650}summary:hover{color:#a3e4ff}.neighbors{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}.neighbor{margin:0;max-width:180px}.neighbor img{width:160px;height:110px;object-fit:contain;background:#233d4e}.neighbor figcaption{font-size:12px}.pill{display:inline-block;padding:2px 7px;border:1px solid currentColor;border-radius:20px;font-size:11px;white-space:nowrap}.editorActions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.draft{color:#e3a9ff}pre{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto;background:#0d1c27;padding:12px;border:1px solid #355063;border-radius:5px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{text-align:left;border-bottom:1px solid var(--line);padding:8px 12px}footer{padding:8px 0 25px;color:var(--muted);font-size:13px}#warningList:empty{display:none}#empty{padding:30px}.links{display:flex;gap:14px;flex-wrap:wrap}.help{max-width:1020px}.excluded-note{border-left:3px solid var(--red);padding-left:12px}#editorPoints{font-variant-numeric:tabular-nums}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}@media(max-width:850px){main{padding:14px}.grid{grid-template-columns:1fr}header{padding:20px}.controls{gap:11px}.toolbar select{min-width:150px}h1{font-size:24px}#canvasScroll{max-height:65vh}}
</style></head><body>
<header><div class="eyebrow">LOTUSim / Unity · inspection RGB</div><h1>Revue des propositions visuelles</h1>
<p class="subtitle">Une image à la fois, à partir du RGB propre. Les cadres retenus, les hypothèses ambiguës et les rejets sont séparés. Aucun objet manqué n’est ajouté à partir des annotations Unity.</p>
<p id="globalCounts" class="stats"></p><p class="subtitle small">Score brut ≠ probabilité de justesse. Masquer des cadres dans cette page ne change ni les prédictions enregistrées ni les métriques.</p>
<div id="warningList"></div><div class="links small"><a href="agent-events.json">Journal des agents</a><a href="run-manifest.json">Provenance</a><a href="status.json">État</a><a href="comparison.json" id="comparisonLink">Comparaison indépendante</a></div></header>
<main><div class="toolbar"><button id="previous" title="Image précédente">← Précédente</button><label class="sr-only" for="frameSelect">Image</label><select id="frameSelect"></select><button id="next" title="Image suivante">Suivante →</button><button id="fit">Vue entière</button><label>Zoom <input id="zoom" type="range" min="1" max="3" step=".25" value="1"><span id="zoomValue">100 %</span></label></div>
<div class="controls"><label class="blue"><input id="showRetained" type="checkbox" checked><i class="legend"></i>Retenus <span id="retainedCount"></span></label><label class="amber"><input id="showUncertain" type="checkbox"><i class="legend"></i>Ambigus <span id="uncertainCount"></span></label><label class="gray"><input id="showRejected" type="checkbox"><i class="legend" style="border-style:dashed"></i>Écartés <span id="rejectedCount"></span></label><label><input id="showLabels" type="checkbox">Noms sur l’image</label><label class="red"><input id="showExclusions" type="checkbox" checked>Zones exclues appliquées</label></div>
<div id="canvasScroll"><svg id="viewer" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="RGB et cadres du détecteur"><image id="rgbImage" preserveAspectRatio="none"></image><g id="exclusionLayer"></g><g id="boxLayer"></g><g id="draftLayer"></g></svg><p id="empty" hidden>Aucune image à afficher.</p></div>
<div id="frameInfo"><span id="frameDescription"></span><span class="links"><a id="rawLink">Ouvrir le RGB natif</a><a id="jsonLink">Prédictions JSON</a></span></div>
<p class="muted small help">Les cadres sont dessinés sur le RGB sans utiliser l’ancien PNG annoté : aucun cadre ni texte n’est donc « imprimé deux fois ». Cliquez sur un cadre ou sur « Voir » pour examiner une proposition. Les propositions ambiguës et écartées sont masquées par défaut, mais restent auditables.</p>
<div class="grid"><section class="panel"><h2>Propositions de cette image</h2><div id="predictionRows"></div><details id="rejectedDetails"><summary id="rejectedSummary">Hypothèses écartées</summary><p class="muted small">Rejets de post-traitement, conservés avec leur motif. Ils ne constituent pas des détections validées.</p><div id="rejectedRows"></div></details></section>
<section class="panel"><h2>Cartographier une zone à ne pas chercher</h2><p class="muted small">Pour une caméra fixée au bateau, dessinez le contour du pont ou de la rambarde à ignorer. Une zone générique peut masquer de vrais objets : vérifiez son emprise sur plusieurs images et après tout changement de caméra.</p><label>Nom <input id="regionName" type="text" maxlength="40" value="ownship"></label><div class="editorActions"><button id="edit">Dessiner sur le RGB</button><button id="closePolygon" disabled>Fermer le polygone</button><button id="undo" disabled>Annuler un point</button><button id="resetDraft" disabled>Effacer le dessin</button></div><p id="editorStatus" class="small draft">L’édition est un brouillon : elle ne modifie pas ce résultat.</p><p id="editorPoints" class="small muted"></p><div class="editorActions"><button id="download" disabled>Télécharger la zone JSON</button><button id="copy" disabled>Copier le JSON</button></div><p class="small excluded-note">Origine en haut à gauche ; coordonnées normalisées de 0 à 1. Ce fichier décrit uniquement la zone observateur, pas la position des cibles. Enregistrez <code>rgb-observer-regions.json</code> à la racine de la campagne (à côté de <code>rgb/</code>), puis relancez le traitement pour appliquer l’exclusion.</p><details><summary>Configuration du brouillon</summary><pre id="regionJson">Aucun polygone fermé.</pre></details></section></div>
<details id="metricsDetails" class="panel"><summary>Mesures de comparaison à la référence Unity</summary><div id="metrics"></div><p class="muted small">Ces métriques proviennent de l’évaluateur séparé. Elles ne prouvent pas la reconnaissabilité humaine et ne sont jamais recalculées par les filtres d’affichage.</p></details>
<footer>RGB inchangés · aucune bibliothèque distante · aucun envoi d’image. Les hypothèses originales et leurs motifs restent dans les JSON.</footer></main>
<script id="gallery-data" type="application/json">__DATA__</script><script>
'use strict';
const DATA=JSON.parse(document.getElementById('gallery-data').textContent), NS='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id), svg=$('viewer');
let frameIndex=0,selected=null,editing=false,draft=[],closed=false,focused=false;
const fmt=(n,d=1)=>Number(n).toLocaleString('fr-FR',{maximumFractionDigits:d});
const uncertain=p=>['retained','uncertain'].includes(p.reviewStatus)?p.reviewStatus==='uncertain':p.recognitionDecision==='indeterminate'||p.category==='unknown'||p.semanticConflict===true;
const category=p=>p.displayName||p.category||'objet';
function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
function sEl(tag,attrs={}){const node=document.createElementNS(NS,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));return node;}
function frame(){return DATA.frames[frameIndex];}
function label(p){return `${category(p)} · score brut ${fmt(100*p.score)} %`;}
function reason(code){return ({'ownship_exclusion':'Zone observateur exclue','ignoreboat':'Zone observateur exclue','excluded_region':'Zone exclue','excluded_center':'Centre du cadre dans la zone observateur exclue','excluded_overlap':'Cadre majoritairement dans la zone observateur exclue','geometric_duplicate':'Doublon géométrique','duplicate':'Doublon géométrique','duplicate_same_class':'Doublon de la même classe','duplicate_cross_class':'Classes concurrentes sur un même emplacement','duplicate_tile_fragment':'Fragment de tuile du même objet','same_object_duplicate':'Doublon du même objet','cross_class_duplicate':'Hypothèses concurrentes sur le même objet','large_weak_proposal':'Grand cadre peu étayé : proposition ambiguë','ambiguous_class_duplicates':'Plusieurs classes concurrentes regroupées : classe non résolue','ambiguous_or_unrecognizable':'Classe ambiguë ou objet non reconnaissable','insufficient_native_pixels':'Trop peu de pixels natifs pour identifier la cible','box_outside_image':'Cadre dépassant les limites de l’image','giant_low_confidence':'Cadre très grand et peu étayé','small':'Cible trop petite','low_score':'Score sous le seuil de revue','semantic_conflict':'Désaccord avec les références','oversized_box':'Cadre disproportionné','tile_boundary_fragment':'Fragment de bord de tuile'})[code]||String(code||'Rejet documenté');}
const categoryName=code=>({'buoy':'bouée','bird':'oiseau','airplane':'avion','helicopter':'hélicoptère','drone':'drone','fishing_trawler':'chalutier','container_ship':'porte-conteneurs','motor_yacht':'yacht','speedboat':'hors-bord','jetski':'jetski','ferry':'ferry','sailboat':'voilier','unknown':'indéterminé'})[code]||String(code);
function fit(){const f=frame();if(!f)return;svg.setAttribute('viewBox',`0 0 ${f.width} ${f.height}`);svg.style.width='100%';$('zoom').value=1;$('zoomValue').textContent='100 %';focused=false;}
function focusBox(p,key){const f=frame(),[x,y,w,h]=p.bbox;selected=key;const pad=Math.max(20,Math.max(w,h)*.35);let left=Math.max(0,x-pad),top=Math.max(0,y-pad),right=Math.min(f.width,x+w+pad),bottom=Math.min(f.height,y+h+pad);const ratio=f.width/f.height;let rw=right-left,rh=bottom-top;if(rw/rh<ratio){const desired=rh*ratio;left=Math.max(0,Math.min(f.width-desired,left-(desired-rw)/2));right=Math.min(f.width,left+desired);}else{const desired=rw/ratio;top=Math.max(0,Math.min(f.height-desired,top-(desired-rh)/2));bottom=Math.min(f.height,top+desired);}svg.setAttribute('viewBox',`${left} ${top} ${right-left} ${bottom-top}`);svg.style.width='100%';focused=true;render();}
function predictionRow(p,key,rejection){const row=el('div',undefined,'row'+(selected===key?' selected':'')),head=el('div',undefined,'rowHead');let text=label(p);if(!rejection&&uncertain(p))text+=' · ambigu';const heading=el('strong',text);heading.className=rejection?'gray':uncertain(p)?'amber':'blue';head.append(heading);const see=el('button','Voir');see.addEventListener('click',()=>{if(rejection)$('showRejected').checked=true;else if(uncertain(p))$('showUncertain').checked=true;else $('showRetained').checked=true;focusBox(p,key);});head.append(see);row.append(head);if(rejection){row.append(el('p',reason(rejection.reason),'small gray'));if(typeof rejection.exclusionFraction==='number')row.append(el('p',`Recouvrement avec la zone exclue : ${fmt(100*rejection.exclusionFraction)} %.`,'small muted'));}
for(const code of p.reviewReasons||[])row.append(el('p',reason(code),'small amber'));
if(Array.isArray(p.classAlternatives)&&p.classAlternatives.length>1){const alternatives=el('details'),summary=el('summary',`${p.classAlternatives.length} hypothèses regroupées au même endroit`);alternatives.append(summary,el('p','Le cadre et la classe du meilleur score sont conservés comme proposition, pas comme vérité. Les autres classes restent ci-dessous.','small muted'));const list=el('ul');for(const alternative of p.classAlternatives)list.append(el('li',`${categoryName(alternative.category)} · score brut ${fmt(100*alternative.score)} %`,'small'));alternatives.append(list);row.append(alternatives);}
const [x,y,w,h]=p.bbox;row.append(el('div',`Cadre natif : x=${fmt(x,0)}, y=${fmt(y,0)}, ${fmt(w,0)} × ${fmt(h,0)} px`,'small muted'));
const details=el('details'),summary=el('summary','Scores et références visuelles');details.append(summary);details.append(el('p','Le score brut et la similarité ne sont pas des probabilités de justesse.','small muted'));
if(p.semanticConflict)details.append(el('p','Le détecteur et les exemples visuels ne proposent pas la même classe.','small amber'));
const confidence=p.confidenceEvidence||{},percent=confidence.calibratedConfidencePercent,interval=confidence.confidenceIntervalPercent;
if(typeof percent==='number'&&Array.isArray(interval))details.append(el('p',`Précision empirique descriptive : ${fmt(percent)} %, intervalle 95 % [${fmt(interval[0])} ; ${fmt(interval[1])}], n=${confidence.support||0}. Portée : ${confidence.calibrationScope||'non précisée'}. Référence géométrique, pas jugement humain.`,'small'));
else details.append(el('p','Estimation de justesse non disponible : calibration indépendante insuffisante ou incompatible.','small muted'));
const neighbors=(p.semanticEvidence||{}).neighbors||[],list=el('div',undefined,'neighbors');for(const n of neighbors){const fig=el('figure',undefined,'neighbor'),img=el('img');img.loading='lazy';img.src='knowledge/'+n.crop;img.alt='Exemple de référence '+n.category;fig.append(img,el('figcaption',`${n.category} · cosinus ${fmt(n.similarity,3)}`));list.append(fig);}details.append(list);if(!neighbors.length)details.append(el('p','Aucun exemple de référence disponible.','small muted'));row.append(details);return row;}
function paintBox(p,key,rejected=false){const f=frame(),[x,y,w,h]=p.bbox;if(x+w<=0||y+h<=0||x>=f.width||y>=f.height)return;const color=rejected?'#aeb7c1':uncertain(p)?'#ffbd59':'#48c9ff',group=sEl('g'),rect=sEl('rect',{x:Math.max(0,x),y:Math.max(0,y),width:Math.max(0,Math.min(f.width,x+w)-Math.max(0,x)),height:Math.max(0,Math.min(f.height,y+h)-Math.max(0,y)),fill:'none',stroke:color,'stroke-width':selected===key?3:1.5,class:'box'+(selected===key?' selected':'')});if(rejected)rect.setAttribute('stroke-dasharray','5 4');rect.append(sEl('title'));rect.firstChild.textContent=label(p);rect.addEventListener('click',event=>{if(editing)return;event.stopPropagation();selected=selected===key?null:key;render();});group.append(rect);
if($('showLabels').checked||selected===key){const text=label(p),size=Math.max(14,f.width/100),width=Math.min(f.width,size*text.length*.55+12),left=Math.max(0,Math.min(f.width-width,x)),top=Math.max(size+8,Math.min(f.height-4,y-5));group.append(sEl('rect',{x:left,y:top-size-5,width,height:size+9,fill:'#08212f','fill-opacity':.94}));const node=sEl('text',{x:left+5,y:top,'font-size':size,fill:color});node.textContent=text;group.append(node);} $('boxLayer').append(group);}
function paintRegions(){const f=frame();$('exclusionLayer').replaceChildren();if($('showExclusions').checked){if(f.exclusionMask){const defs=sEl('defs'),mask=sEl('mask',{id:'observerMask',maskUnits:'userSpaceOnUse',x:0,y:0,width:f.width,height:f.height,style:'mask-type:luminance'});mask.append(sEl('image',{href:f.exclusionMask,x:0,y:0,width:f.width,height:f.height,preserveAspectRatio:'none'}));defs.append(mask);$('exclusionLayer').append(defs,sEl('rect',{x:0,y:0,width:f.width,height:f.height,fill:'#ff7383','fill-opacity':.23,mask:'url(#observerMask)','pointer-events':'none'}));}for(const r of f.exclusions){const poly=sEl('polygon',{points:r.polygon.map(p=>`${p[0]*f.width},${p[1]*f.height}`).join(' '),fill:'#ff7383','fill-opacity':.14,stroke:'#ff7383','stroke-width':1.5,'vector-effect':'non-scaling-stroke','stroke-dasharray':'8 5'});poly.append(sEl('title'));poly.firstChild.textContent='Zone exclue appliquée : '+r.id;$('exclusionLayer').append(poly);}}paintDraft();}
function paintDraft(){const f=frame(),layer=$('draftLayer');layer.replaceChildren();if(!f||!draft.length)return;const points=draft.map(p=>`${p[0]*f.width},${p[1]*f.height}`).join(' '),shape=sEl(closed?'polygon':'polyline',{points,fill:closed?'#d2a1ff':'none','fill-opacity':.18,stroke:'#e3a9ff','stroke-width':2,'vector-effect':'non-scaling-stroke'});layer.append(shape);for(const p of draft)layer.append(sEl('circle',{cx:p[0]*f.width,cy:p[1]*f.height,r:Math.max(4,f.width/350),fill:'#e3a9ff'}));}
function render(){const f=frame();if(!f)return;$('rgbImage').setAttribute('href',f.raw);$('rgbImage').setAttribute('width',f.width);$('rgbImage').setAttribute('height',f.height);svg.setAttribute('width',f.width);svg.setAttribute('height',f.height);$('boxLayer').replaceChildren();const certain=f.retained.filter(p=>!uncertain(p)).length,ambiguous=f.retained.length-certain;$('retainedCount').textContent=`(${certain})`;$('uncertainCount').textContent=`(${ambiguous})`;$('rejectedCount').textContent=`(${f.rejected.length})`;
f.retained.forEach((p,i)=>{if(uncertain(p)?$('showUncertain').checked:$('showRetained').checked)paintBox(p,'k'+i);});if($('showRejected').checked)f.rejected.forEach((r,i)=>paintBox(r.prediction,'r'+i,true));paintRegions();
const retained=$('predictionRows');retained.replaceChildren();if(!f.predictionAvailable)retained.append(el('p','Le fichier de prédictions n’est pas encore disponible.','notice'));else if(!f.retained.length)retained.append(el('p','Aucune proposition retenue. Cela ne prouve pas l’absence d’objet.','muted'));else f.retained.forEach((p,i)=>retained.append(predictionRow(p,'k'+i)));
const rejected=$('rejectedRows');rejected.replaceChildren();f.rejected.forEach((r,i)=>rejected.append(predictionRow(r.prediction,'r'+i,r)));$('rejectedSummary').textContent=`${f.rejected.length} hypothèse${f.rejected.length>1?'s':''} écartée${f.rejected.length>1?'s':''} — motifs et preuves`;$('rejectedDetails').hidden=!f.rejected.length;
$('frameDescription').textContent=`Image ${frameIndex+1}/${DATA.frames.length} · ${f.sourceImage} · ${f.width} × ${f.height} px · ${f.exclusionMask?'masque observateur + ':''}${f.exclusions.length} zone(s) polygonale(s) exclue(s)`;$('rawLink').href=f.raw;$('jsonLink').href=f.predictionFile;$('frameSelect').value=frameIndex;$('previous').disabled=frameIndex===0;$('next').disabled=frameIndex===DATA.frames.length-1;}
function changeFrame(index){frameIndex=Math.max(0,Math.min(DATA.frames.length-1,index));selected=null;fit();render();updateEditor();}
function regionId(){let value=$('regionName').value.replace(/[^a-zA-Z0-9_-]/g,'_')||'ownship';if(!/^[A-Za-z]/.test(value))value='zone_'+value;return value.slice(0,40);}
function regionConfig(){return {schema:'lotusim-rgb-search-regions-1',coordinateSystem:'normalized_image',excludeRegions:[{id:regionId(),polygon:draft.map(p=>p.map(v=>Number(v.toFixed(6))))}]};}
function polygonIssue(points){if(points.length<3||points.length>128)return'Un polygone doit comporter de 3 à 128 points.';if(new Set(points.map(p=>p.join(','))).size!==points.length)return'Deux points sont identiques : annulez le dernier point.';let area=0;for(let i=0;i<points.length;i++){const a=points[i],b=points[(i+1)%points.length];area+=a[0]*b[1]-b[0]*a[1];}if(Math.abs(area)/2<1e-8)return'Le polygone doit entourer une surface non nulle.';const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++){if(j===(i+1)%points.length||(j+1)%points.length===i)continue;const a=points[i],b=points[(i+1)%points.length],c=points[j],d=points[(j+1)%points.length];if(cross(a,b,c)*cross(a,b,d)<=0&&cross(c,d,a)*cross(c,d,b)<=0&&Math.max(Math.min(a[0],b[0]),Math.min(c[0],d[0]))<=Math.min(Math.max(a[0],b[0]),Math.max(c[0],d[0]))&&Math.max(Math.min(a[1],b[1]),Math.min(c[1],d[1]))<=Math.min(Math.max(a[1],b[1]),Math.max(c[1],d[1])))return'Le contour se croise : annulez les derniers points et redessinez le bord.';}return null;}
function updateEditor(){const ready=closed&&draft.length>=3;$('download').disabled=!ready;$('copy').disabled=!ready;$('closePolygon').disabled=closed||draft.length<3;$('undo').disabled=!draft.length;$('resetDraft').disabled=!draft.length;$('edit').textContent=editing?'Terminer le dessin':'Dessiner sur le RGB';svg.classList.toggle('editing',editing);$('editorStatus').textContent=editing?'Cliquez autour de la zone observateur, puis fermez le polygone. Les cadres ne sont pas recalculés par ce dessin.':closed?'Brouillon fermé : exportez-le, puis relancez l’analyse pour appliquer cette exclusion.':'L’édition est un brouillon : elle ne modifie pas ce résultat.';$('editorPoints').textContent=draft.length?`${draft.length} points · coordonnées normalisées · dessin commun à la caméra, à vérifier sur chaque image`:'Aucun point dessiné.';$('regionJson').textContent=ready?JSON.stringify(regionConfig(),null,2):'Aucun polygone fermé.';paintDraft();}
svg.addEventListener('click',event=>{if(!editing||closed||!frame())return;if(draft.length>=128){$('editorStatus').textContent='Maximum de 128 points atteint : fermez le polygone ou annulez un point.';return;}const point=svg.createSVGPoint();point.x=event.clientX;point.y=event.clientY;const matrix=svg.getScreenCTM();if(!matrix)return;const native=point.matrixTransform(matrix.inverse()),f=frame();draft.push([Math.max(0,Math.min(1,native.x/f.width)),Math.max(0,Math.min(1,native.y/f.height))]);updateEditor();});
$('edit').addEventListener('click',()=>{editing=!editing;if(editing){closed=false;fit();}updateEditor();});$('closePolygon').addEventListener('click',()=>{if(draft.length>=3){const issue=polygonIssue(regionConfig().excludeRegions[0].polygon);if(issue){$('editorStatus').textContent=issue;return;}closed=true;editing=false;updateEditor();}});$('undo').addEventListener('click',()=>{draft.pop();closed=false;updateEditor();});$('resetDraft').addEventListener('click',()=>{draft=[];closed=false;updateEditor();});$('regionName').addEventListener('input',updateEditor);
$('download').addEventListener('click',()=>{const blob=new Blob([JSON.stringify(regionConfig(),null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),link=el('a');link.href=url;link.download='rgb-observer-regions.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});$('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(JSON.stringify(regionConfig(),null,2));$('editorStatus').textContent='JSON copié. Enregistrez-le puis relancez le traitement pour appliquer la zone.';}catch(error){$('editorStatus').textContent='Copie indisponible dans ce navigateur : utilisez Télécharger la zone JSON.';}});
for(const id of ['showRetained','showUncertain','showRejected','showLabels','showExclusions'])$(id).addEventListener('change',render);$('previous').addEventListener('click',()=>changeFrame(frameIndex-1));$('next').addEventListener('click',()=>changeFrame(frameIndex+1));$('frameSelect').addEventListener('change',event=>changeFrame(Number(event.target.value)));$('fit').addEventListener('click',()=>{selected=null;fit();render();});$('zoom').addEventListener('input',event=>{const value=Number(event.target.value);if(focused)fit();$('zoom').value=value;svg.style.width=`${value*100}%`;$('zoomValue').textContent=`${Math.round(value*100)} %`;});
document.addEventListener('keydown',event=>{if(editing||['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName))return;if(event.key==='ArrowRight')changeFrame(frameIndex+1);else if(event.key==='ArrowLeft')changeFrame(frameIndex-1);});
DATA.frames.forEach((f,i)=>{const option=el('option',`${i+1} · ${f.sourceImage}`);option.value=i;$('frameSelect').append(option);});$('globalCounts').textContent=`${DATA.frames.length} images · ${DATA.counts.retained} propositions conservées, dont ${DATA.counts.uncertain} ambiguës · ${DATA.counts.rejected} rejets documentés`;
for(const warning of DATA.warnings)$('warningList').append(el('p',warning,'notice small'));
if(DATA.metrics){const m=DATA.metrics;const rate=value=>value===null||value===undefined?'non définie':fmt(100*value)+' %';$('metrics').append(el('p',`${m.truePositives} correspondances · ${m.falsePositives} propositions non appariées · ${m.falseNegatives} objets manqués.`));$('metrics').append(el('p',`Précision ${rate(m.precision)} · rappel ${rate(m.recall)} · F1 ${rate(m.f1)} · IoU ≥ ${m.iouThreshold}.`));const table=el('table'),head=el('tr');for(const title of ['Pixels visibles natifs','Références','Retrouvées'])head.append(el('th',title));table.append(head);for(const [name,value] of Object.entries(m.byVisiblePixelSize||{})){const row=el('tr');for(const text of [name,value.referenceObjects,value.matched])row.append(el('td',String(text)));table.append(row);}$('metrics').append(table);}else{$('metricsDetails').hidden=true;$('comparisonLink').hidden=true;}
if(DATA.frames.length){fit();render();updateEditor();}else{$('viewer').hidden=true;$('empty').hidden=false;for(const id of ['previous','next','fit','edit'])$(id).disabled=true;}
</script></body></html>'''


def render_gallery(output, mapping, report=None, warnings=None):
    output = Path(output)
    payload = build_gallery_data(output, mapping, report, warnings)
    # Prevent script-tag termination from labels, warnings or source filenames.
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    (output / "index.html").write_text(PAGE.replace("__DATA__", encoded), encoding="utf-8")
