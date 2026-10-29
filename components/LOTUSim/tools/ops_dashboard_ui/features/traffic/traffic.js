'use strict';
(() => {
  const list = (value) => (Array.isArray(value) ? value : []),
    finite = (value) => typeof value === 'number' && Number.isFinite(value);
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  function position(actor, time, change = null) {
    const center = change?.centerENU || actor.centerENU,
      speed = change?.speedMps ?? actor.speedMps,
      heading = change?.headingDeg ?? actor.headingDeg;
    if (
      !center ||
      ![center.eastM, center.northM, center.altitudeM, speed, heading, time].every(finite)
    )
      return null;
    const focus = finite(actor.centerSeconds)
      ? actor.centerSeconds
      : (actor.startSeconds + actor.endSeconds) / 2;
    const angle = (heading * Math.PI) / 180,
      vE = Math.sin(angle) * speed,
      vN = Math.cos(angle) * speed,
      w = ((actor.yawRateDegS || 0) * Math.PI) / 180;
    let east, north;
    if (Math.abs(w) < 1e-9) {
      east = vE * (time - focus);
      north = vN * (time - focus);
    } else {
      const bounded = actor.boundedTurn === true;
      const q =
          (bounded ? clamp(time, actor.turnStartSeconds, actor.turnEndSeconds) : time) - focus,
        a = w * q;
      east = (vE * Math.sin(a) + vN * (1 - Math.cos(a))) / w;
      north = (vE * (Math.cos(a) - 1) + vN * Math.sin(a)) / w;
      if (bounded)
        for (const [at, extra] of [
          [actor.turnStartSeconds, Math.min(0, time - actor.turnStartSeconds)],
          [actor.turnEndSeconds, Math.max(0, time - actor.turnEndSeconds)],
        ]) {
          const b = w * (at - focus);
          east += (Math.cos(b) * vE + Math.sin(b) * vN) * extra;
          north += (-Math.sin(b) * vE + Math.cos(b) * vN) * extra;
        }
    }
    return {
      timeSeconds: time,
      eastM: center.eastM + east,
      northM: center.northM + north,
      altitudeM: center.altitudeM,
    };
  }
  function interpolate(points, time) {
    const values = list(points).filter((p) =>
      [p.timeSeconds, p.eastM, p.northM, p.altitudeM].every(finite),
    );
    if (!values.length) return null;
    if (time <= values[0].timeSeconds) return { ...values[0] };
    for (let i = 1; i < values.length; i++)
      if (time <= values[i].timeSeconds) {
        const a = values[i - 1],
          b = values[i],
          span = b.timeSeconds - a.timeSeconds,
          f = span > 0 ? (time - a.timeSeconds) / span : 0;
        return {
          timeSeconds: time,
          ...Object.fromEntries(
            ['eastM', 'northM', 'altitudeM'].map((key) => [key, a[key] + (b[key] - a[key]) * f]),
          ),
        };
      }
    return { ...values[values.length - 1] };
  }
  function validateChange(actor, change) {
    if (actor.editable !== true) throw Error('Cet objet ne peut pas être modifié.');
    if (
      ![
        change.centerENU?.eastM,
        change.centerENU?.northM,
        change.centerENU?.altitudeM,
        change.speedMps,
        change.headingDeg,
      ].every(finite)
    )
      throw Error('Renseigner des valeurs numériques finies.');
    if (Math.abs(change.centerENU.eastM) > 100000 || Math.abs(change.centerENU.northM) > 100000)
      throw Error('Les coordonnées Est/Nord doivent rester entre −100 000 et 100 000 m.');
    if (!finite(actor.maxSpeedMps) || change.speedMps < 0 || change.speedMps > actor.maxSpeedMps)
      throw Error(
        'La vitesse dépasse la capacité déclarée du modèle, ou sa limite n’est pas connue.',
      );
    if (change.headingDeg < 0 || change.headingDeg > 360)
      throw Error('Le cap doit être compris entre 0° et 360°.');
    if (actor.domain === 'air') {
      if (change.centerENU.altitudeM <= 0 || change.centerENU.altitudeM > actor.maxAltitudeM)
        throw Error('L’altitude aérienne doit être positive et respecter le maximum du modèle.');
    } else if (change.centerENU.altitudeM !== 0)
      throw Error('Les objets marins doivent rester à l’altitude de référence 0 m.');
    if (actor.domain === 'moored' && change.speedMps !== 0)
      throw Error('Un objet amarré doit rester immobile.');
    return { ...change, headingDeg: change.headingDeg === 360 ? 0 : change.headingDeg };
  }

  function captureCadence(durationSeconds, capture) {
    if (
      typeof durationSeconds !== 'number' ||
      !Number.isFinite(durationSeconds) ||
      durationSeconds < 4 ||
      durationSeconds > 600
    )
      throw Error('La durée doit être comprise entre 4 et 600 secondes simulées.');
    if (!capture || capture.mode === 'legacy')
      return { mode: 'legacy', capture: null, count: null };
    const fraction = (value) => {
      const parts = String(value).toLowerCase().split('e'),
        mantissa = parts[0],
        decimals = (mantissa.split('.')[1] || '').length,
        scale = decimals - Number(parts[1] || 0),
        digits = BigInt(mantissa.replace('.', ''));
      return scale < 0
        ? { n: digits * 10n ** BigInt(-scale), d: 1n }
        : { n: digits, d: 10n ** BigInt(scale) };
    };
    const duration = fraction(durationSeconds),
      fps = 30,
      simulationFrames = Math.ceil(durationSeconds * fps);
    let count,
      interval = null;
    if (capture.mode === 'count') {
      count = capture.count;
      if (!Number.isInteger(count) || count < 1 || count > 2000 || count > simulationFrames)
        throw Error(
          'Choisir de 1 à 2 000 images, sans dépasser le nombre de frames moteur disponibles.',
        );
    } else if (capture.mode === 'interval') {
      if (
        typeof capture.intervalSeconds !== 'number' ||
        !Number.isFinite(capture.intervalSeconds) ||
        capture.intervalSeconds < 1 / 30
      )
        throw Error('L’intervalle minimum est 1/30 seconde simulée (0,033333… s).');
      interval = fraction(capture.intervalSeconds);
      const numerator = duration.n * interval.d,
        denominator = duration.d * interval.n;
      count = Number((numerator + denominator - 1n) / denominator);
      if (count > 2001)
        throw Error(
          'Cette cadence dépasse la limite de 2 000 photos ; augmenter l’intervalle ou réduire la durée.',
        );
    } else throw Error('Mode de capture non pris en charge.');
    const frames = [],
      requestedTimesSeconds = [],
      effectiveTimesSeconds = [];
    let maxQuantizationErrorSeconds = 0,
      discardedAtOrAfterEndCount = 0;
    for (let index = 0; index < count; index++) {
      const numerator = interval ? BigInt(index) * interval.n : BigInt(index) * duration.n,
        denominator = interval ? interval.d : duration.d * BigInt(count),
        frame = Number((2n * numerator * 30n + denominator) / (2n * denominator));
      if (frame >= simulationFrames) {
        discardedAtOrAfterEndCount++;
        continue;
      }
      if (frames.at(-1) === frame)
        throw Error(
          'Plusieurs prises se confondent sur la grille de 30 images/s : réduire le nombre demandé.',
        );
      const requested = Number(numerator) / Number(denominator),
        effective = frame / fps;
      frames.push(frame);
      requestedTimesSeconds.push(requested);
      effectiveTimesSeconds.push(effective);
      maxQuantizationErrorSeconds = Math.max(
        maxQuantizationErrorSeconds,
        Math.abs(effective - requested),
      );
    }
    if (capture.mode === 'count' && frames.length !== count)
      throw Error(
        'Ce nombre de prises ne tient pas sur la grille temporelle ; choisir un nombre inférieur.',
      );
    if (frames.length > 2000)
      throw Error(
        'Cette cadence dépasse la limite de 2 000 photos ; augmenter l’intervalle ou réduire la durée.',
      );
    return {
      mode: capture.mode,
      capture: { ...capture },
      count: frames.length,
      fps,
      simulationFrames,
      frames,
      requestedTimesSeconds,
      effectiveTimesSeconds,
      maxQuantizationErrorSeconds,
      discardedAtOrAfterEndCount,
    };
  }
  const math = { position, interpolate, validateChange, captureCadence };
  if (typeof module !== 'undefined' && module.exports) module.exports = math;
  if (typeof document === 'undefined') return;
  const $ = (id) => document.getElementById(id),
    NS = 'http://www.w3.org/2000/svg';
  const fmt = (value, digits = 1) =>
    finite(value)
      ? new Intl.NumberFormat('fr-FR', { maximumFractionDigits: digits }).format(value)
      : '—';
  const node = (tag, text, className) => {
    const result = document.createElement(tag);
    if (text !== undefined && text !== null) result.textContent = String(text);
    if (className) result.className = className;
    return result;
  };
  const svg = (tag, attributes = {}) => {
    const result = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attributes)) result.setAttribute(key, String(value));
    return result;
  };
  let plan = null,
    selected = null,
    time = 0,
    loaded = false,
    loading = false,
    saving = false,
    playing = false,
    lastTick = 0,
    animationHandle = null,
    dirty = false,
    saved = null;
  let selectedPlanId = 'source',
    library = [],
    libraryLoading = false,
    generating = false,
    revalidating = false,
    pendingPlanId = null;
  let auditDetailsKey = null,
    warningsDetailsKey = null;
  const changes = new Map();
  const colors = { air: '#baa8ed', sea: '#6bd8c5', moored: '#efbd79', observer: '#e6f2fb' };
  function notice(message, kind = '') {
    const target = $('trafficNotice');
    target.className = 'notice traffic-notice' + (kind ? ' ' + kind : '');
    if (typeof window.LotusimAlerts?.notify === 'function')
      return window.LotusimAlerts.notify(target, message, kind, {
        source: 'Trafic',
        route: 'traffic',
        label: 'Plan coopératif',
      });
    target.textContent = message;
    target.hidden = !message;
  }
  const uuid = (value) =>
    typeof value === 'string' &&
    /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
  function errorText(result, fallback) {
    return (
      result?.message ||
      result?.error ||
      list(result?.errors)
        .slice(0, 5)
        .map((issue) =>
          [issue.path, issue.message].filter((value) => typeof value === 'string').join(' : '),
        )
        .join(' ; ') ||
      fallback
    );
  }
  function auditLabel(record) {
    const status = record?.auditStatus || record?.status;
    return record?.ready === true && (status === 'approved' || status === 'ready')
      ? 'Contrôles limités satisfaits'
      : status === 'requires_revalidation' || status === 'needs_revalidation'
        ? 'Révalidation nécessaire'
        : status === 'failed' || status === 'refused'
          ? 'Refusé par les contrôles'
          : status === 'unsupported'
            ? 'Contrôles non pris en charge'
            : 'État des contrôles non confirmé';
  }
  function libraryBundle(id) {
    return uuid(id) ? '/api/traffic/plans/' + id + '/bundle.zip' : null;
  }
  function trafficCapture() {
    const mode = $('trafficCaptureMode').value || 'legacy';
    return mode === 'legacy'
      ? null
      : mode === 'interval'
        ? { mode, intervalSeconds: Number($('trafficCaptureInterval').value) }
        : { mode, count: Number($('trafficCaptureCount').value) };
  }
  function renderCapturePreview() {
    const mode = $('trafficCaptureMode');
    if (!mode.value) mode.value = 'legacy';
    if (!$('trafficCaptureCount').value) $('trafficCaptureCount').value = '360';
    if (!$('trafficCaptureInterval').value) $('trafficCaptureInterval').value = '2';
    const busy = loading || saving || generating || revalidating;
    mode.disabled = busy;
    $('trafficCaptureCountField').hidden = mode.value !== 'count';
    $('trafficCaptureIntervalField').hidden = mode.value !== 'interval';
    $('trafficCaptureCount').disabled = busy || mode.value !== 'count';
    $('trafficCaptureInterval').disabled = busy || mode.value !== 'interval';
    const target = $('trafficCapturePreview');
    target.className = 'traffic-help traffic-capture-preview';
    if (mode.value === 'legacy') {
      target.textContent =
        'Calendrier hérité conservé, avec les rafales éventuelles. Le nombre exact sera fourni par le planificateur ; aucun nouveau choix de cadence n’est envoyé.';
      return;
    }
    try {
      const schedule = captureCadence(Number($('trafficGenerateDuration').value), trafficCapture());
      target.textContent =
        fmt(schedule.count, 0) +
        ' photos prévues · de 0 à ' +
        fmt(schedule.effectiveTimesSeconds.at(-1), 6) +
        ' s simulées (fin de l’épisode exclue). Grille moteur : 30 images/s.' +
        (schedule.maxQuantizationErrorSeconds > 1e-9
          ? ' Écart maximal de quantification : ' +
            fmt(schedule.maxQuantizationErrorSeconds, 6) +
            ' s.'
          : ' Aucun décalage de quantification.') +
        (schedule.discardedAtOrAfterEndCount
          ? ' ' + schedule.discardedAtOrAfterEndCount + ' prise hors grille finale exclue.'
          : '');
    } catch (error) {
      target.textContent = error.message;
      target.className += ' error';
    }
  }
  function renderCaptureSchedule(result) {
    const schedule = result.captureSchedule || result.plan?.captureSchedule,
      target = $('trafficCaptureSchedule');
    if (
      schedule?.schema !== 'lotusim-capture-schedule-1' ||
      !Number.isInteger(schedule.count) ||
      schedule.count < 1 ||
      schedule.count > 2000 ||
      !Array.isArray(schedule.effectiveTimesSeconds) ||
      schedule.effectiveTimesSeconds.length !== schedule.count ||
      !schedule.effectiveTimesSeconds.every(finite)
    ) {
      target.textContent = 'Calendrier de capture non documenté dans ce plan historique.';
      return;
    }
    const mode =
      {
        interval:
          'intervalle demandé : ' + fmt(schedule.requestedIntervalSeconds, 6) + ' s simulées',
        count: 'nombre d’images choisi',
        legacy: 'calendrier hérité',
      }[schedule.mode] || 'mode non documenté';
    target.textContent =
      'Captures planifiées (non exécutées) : ' +
      fmt(schedule.count, 0) +
      ' photos · ' +
      mode +
      ' · de ' +
      fmt(schedule.effectiveTimesSeconds[0], 6) +
      ' à ' +
      fmt(schedule.effectiveTimesSeconds.at(-1), 6) +
      ' s simulées · grille ' +
      fmt(schedule.fps, 0) +
      ' images/s.' +
      (schedule.maxQuantizationErrorSeconds > 1e-9
        ? ' Écart de quantification maximal : ' +
          fmt(schedule.maxQuantizationErrorSeconds, 6) +
          ' s.'
        : '');
  }
  function renderLibrary(preferred = null) {
    const target = $('trafficPlanChoice'),
      previous = preferred || target.value || selectedPlanId,
      values = library.slice();
    if (uuid(plan?.record?.id) && !values.some((record) => record.id === plan.record.id))
      values.unshift(plan.record);
    target.replaceChildren();
    const source = node('option', 'Source historique · plan existant');
    source.value = 'source';
    target.append(source);
    for (const record of values) {
      if (!uuid(record?.id)) continue;
      const option = node(
        'option',
        (record.name || record.id) +
          ' · ' +
          auditLabel(record) +
          ' · ' +
          fmt(record.actorCount, 0) +
          ' objets',
      );
      option.value = record.id;
      target.append(option);
    }
    target.value =
      previous === 'source' || values.some((record) => record.id === previous)
        ? previous
        : 'source';
    $('trafficLibraryCount').textContent = fmt(values.length, 0) + ' plans / révisions enregistrés';
  }
  async function refreshLibrary(preferred = null) {
    if (libraryLoading) return;
    libraryLoading = true;
    $('trafficLibraryRefresh').disabled = true;
    try {
      const response = await fetch('/api/traffic/plans', { cache: 'no-store' }),
        result = await response.json();
      if (
        !response.ok ||
        result.schema !== 'lotusim-traffic-library-1' ||
        !Array.isArray(result.plans)
      )
        throw Error(errorText(result, 'Bibliothèque indisponible.'));
      library = result.plans;
      renderLibrary(preferred);
    } catch (error) {
      $('trafficLibraryCount').textContent =
        'Bibliothèque non actualisée · la source historique reste disponible.';
      if (preferred) notice(error.message, 'error');
    } finally {
      libraryLoading = false;
      $('trafficLibraryRefresh').disabled = false;
    }
  }
  function renderRecord() {
    const record = plan?.record,
      known = uuid(selectedPlanId);
    $('trafficAuditBadge').textContent = record
      ? auditLabel(record)
      : 'Source historique · non réévaluée';
    $('trafficAuditBadge').className =
      'badge ' + (record?.ready === true ? 'complete' : known ? 'warning' : 'neutral');
    $('trafficAuditDetail').textContent = record
      ? [
          record.name || record.id,
          record.parentId ? 'Révision de ' + record.parentId : null,
          record.createdAt
            ? 'Enregistré le ' + new Date(record.createdAt).toLocaleString('fr-FR')
            : null,
        ]
          .filter(Boolean)
          .join(' · ')
      : 'La source historique reste intacte et ne devient pas active en lisant ce plan.';
    const reasons = $('trafficAuditReasons');
    reasons.replaceChildren();
    const audit = plan?.audit,
      separations = list(audit?.checks),
      colreg = list(audit?.limitedColreg?.checks),
      excluded = list(audit?.limitedColreg?.excludedPairs);
    if (audit && (finite(audit.pairChecks) || separations.length || audit.limitedColreg))
      reasons.append(
        node(
          'li',
          fmt(finite(audit.pairChecks) ? audit.pairChecks : separations.length, 0) +
            ' séparations contrôlées · ' +
            fmt(colreg.length, 0) +
            ' rencontres COLREG contrôlées (périmètre limité) · ' +
            fmt(excluded.length, 0) +
            ' paires hors périmètre COLREG. Les séparations géométriques ne constituent pas une conformité COLREG complète.',
        ),
      );
    for (const text of list(audit?.errors)
      .filter((value) => typeof value === 'string')
      .slice(0, 8))
      reasons.append(node('li', 'Échec : ' + text.slice(0, 1500)));
    for (const item of separations
      .filter((item) => item?.safe === false || item?.approved === false)
      .slice(0, 8)) {
      const text = [
        'Séparation non satisfaite',
        item.a,
        item.b,
        item.rule || item.id,
        item.reason || item.message,
        finite(item.marginM) ? 'Marge : ' + fmt(item.marginM, 2) + ' m' : null,
      ]
        .filter((value) => typeof value === 'string')
        .join(' · ');
      reasons.append(node('li', text.slice(0, 1500)));
    }
    for (const item of colreg.filter((item) => item?.passed === false).slice(0, 8)) {
      const text = [
        'Contrôle COLREG limité non satisfait',
        item.rule ? 'Règle ' + item.rule : null,
        item.a,
        item.b,
        item.control,
        item.detail,
      ]
        .filter((value) => typeof value === 'string')
        .join(' · ');
      reasons.append(node('li', text.slice(0, 1500)));
    }
    for (const text of [audit?.reason, ...list(audit?.limitations)]
      .filter((value) => typeof value === 'string')
      .slice(0, 10))
      reasons.append(node('li', text.slice(0, 1500)));
    const details = $('trafficAuditDetails'),
      summary = $('trafficAuditSummary');
    const failed =
      list(audit?.errors).some((value) => typeof value === 'string') ||
      separations.some((item) => item?.safe === false || item?.approved === false) ||
      colreg.some((item) => item?.passed === false) ||
      ['failed', 'refused', 'unsupported'].includes(record?.auditStatus || record?.status);
    if (summary)
      summary.textContent =
        (failed ? 'Contrôles à examiner' : 'Détail des contrôles et limites') +
        ' · ' +
        reasons.children.length +
        ' point' +
        (reasons.children.length > 1 ? 's' : '');
    if (details) {
      details.hidden = !reasons.children.length;
      const key =
        selectedPlanId +
        '|' +
        (plan?.baseSha256 || '') +
        '|' +
        JSON.stringify([
          audit?.errors,
          separations.filter((item) => item?.safe === false || item?.approved === false),
          colreg.filter((item) => item?.passed === false),
          failed,
        ]);
      if (key !== auditDetailsKey) {
        details.open = failed;
        auditDetailsKey = key;
      }
    }
    const bundle = libraryBundle(selectedPlanId);
    $('trafficPlanExport').hidden = !bundle;
    if (bundle) {
      $('trafficPlanExport').href = bundle;
      $('trafficPlanExport').textContent =
        record?.ready === true
          ? 'Télécharger scénario + audit'
          : 'Télécharger JSON + audit (sans YAML validé)';
    }
    $('trafficRevalidate').disabled = !known || dirty || saving || revalidating || generating;
  }
  function actorFor(id) {
    return list(plan?.actors).find((actor) => actor.id === id);
  }
  function edited(actor) {
    return changes.get(actor.id);
  }
  function working() {
    return $('trafficVersion').value !== 'original';
  }
  function currentActor(actor) {
    const edit = working() ? edited(actor) : null;
    return edit ? { ...actor, ...edit, centerENU: { ...edit.centerENU } } : actor;
  }
  function actorPoints(actor) {
    const edit = working() ? edited(actor) : null;
    return edit
      ? list(actor.points)
          .map((point) => position(actor, point.timeSeconds, edit))
          .filter(Boolean)
      : list(actor.points);
  }
  function actorPosition(actor) {
    return working() && edited(actor)
      ? position(actor, time, edited(actor))
      : interpolate(actor.points, time);
  }
  function isActive(actor) {
    return (
      finite(actor.startSeconds) &&
      finite(actor.endSeconds) &&
      time >= actor.startSeconds &&
      time <= actor.endSeconds
    );
  }
  function speedText(actor) {
    const speed = currentActor(actor).speedMps;
    return (
      fmt(speed, 2) +
      ' m/s · ' +
      fmt(actor.domain === 'air' ? speed * 3.6 : (speed * 3600) / 1852, 1) +
      (actor.domain === 'air' ? ' km/h' : ' nœuds')
    );
  }
  function setPlayback(next) {
    if (animationHandle !== null) {
      cancelAnimationFrame(animationHandle);
      animationHandle = null;
    }
    playing = next && !!plan;
    lastTick = 0;
    $('trafficPlay').textContent = playing ? 'Pause de l’aperçu' : 'Lire l’aperçu';
    $('trafficPlay').setAttribute('aria-pressed', String(playing));
    if (playing) animationHandle = requestAnimationFrame(tick);
  }
  function tick(now) {
    animationHandle = null;
    if (!playing) return;
    if (lastTick) time = Math.min(plan.timeline.endSeconds, time + (now - lastTick) / 1000);
    lastTick = now;
    renderFrame();
    if (time >= plan.timeline.endSeconds) {
      setPlayback(false);
      return;
    }
    animationHandle = requestAnimationFrame(tick);
  }
  function safeExport(value, id) {
    if (
      typeof value !== 'string' ||
      value.includes('\\') ||
      typeof id !== 'string' ||
      !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(id)
    )
      return null;
    try {
      const url = new URL(value, location.origin);
      return url.origin === location.origin &&
        url.pathname === '/api/traffic/drafts/' + id + '/draft.json' &&
        !url.search &&
        !url.hash
        ? url.pathname
        : null;
    } catch (_) {
      return null;
    }
  }
  function updateStatus() {
    const count = changes.size,
      busy = loading || saving || generating || revalidating;
    $('trafficDraftCount').textContent =
      fmt(count, 0) + ' objet' + (count > 1 ? 's' : '') + ' modifié' + (count > 1 ? 's' : '');
    $('trafficDraftBadge').textContent = count
      ? dirty
        ? 'Brouillon non enregistré'
        : 'Brouillon enregistré · non appliqué'
      : uuid(selectedPlanId)
        ? 'Plan de bibliothèque · hors ligne'
        : 'Plan source · lecture seule';
    $('trafficDraftBadge').className = 'badge ' + (count ? 'warning' : 'neutral');
    $('trafficSave').disabled = busy || !loaded || !count;
    $('trafficResetAll').disabled = busy || !count;
    $('trafficGenerate').disabled = busy;
    $('trafficPlanChoice').disabled = busy;
    $('trafficRevalidate').disabled = !loaded || !uuid(selectedPlanId) || dirty || busy;
    renderCapturePreview();
    $('trafficSaved').hidden = !saved;
    if (saved) {
      $('trafficSavedLabel').textContent =
        'Brouillon immuable ' +
        saved.id +
        (dirty
          ? ' · les dernières modifications locales ne sont pas encore enregistrées.'
          : ' · révalidation nécessaire avant toute utilisation.');
      const href = safeExport(saved.downloadUrl || saved.exportUrl, saved.id);
      $('trafficExport').hidden = !href;
      if (href) $('trafficExport').href = href;
    }
  }
  function acceptPlan(result, identifier = 'source') {
    if (
      !Array.isArray(result.actors) ||
      !result.timeline ||
      !finite(result.timeline.startSeconds) ||
      !finite(result.timeline.endSeconds) ||
      result.timeline.endSeconds <= result.timeline.startSeconds ||
      typeof result.baseSha256 !== 'string'
    )
      throw Error('Le plan est incomplet.');
    plan = result;
    selectedPlanId = uuid(result.planId) ? result.planId : identifier;
    changes.clear();
    saved = null;
    dirty = false;
    time = result.timeline.startSeconds;
    selected =
      result.actors.find((actor) => actor.editable === true)?.id || result.actors[0]?.id || null;
    loaded = true;
    $('trafficWorkspace').hidden = false;
    $('trafficEmpty').hidden = true;
    $('trafficVersion').value = 'original';
    $('trafficTime').min = String(result.timeline.startSeconds);
    $('trafficTime').max = String(result.timeline.endSeconds);
    $('trafficSource').textContent = [
      result.source?.label || result.record?.name || 'Plan coopératif existant',
      result.source?.engineId ? 'Source : ' + result.source.engineId : null,
      result.source?.relativePath,
    ]
      .filter(Boolean)
      .join(' · ');
    $('trafficSourceHash').textContent = 'SHA-256 ' + result.baseSha256.slice(0, 16) + '…';
    $('trafficSourceHash').title = result.baseSha256;
    renderCaptureSchedule(result);
    const auditLimitations = new Set(
      list(result.audit?.limitations).filter((value) => typeof value === 'string'),
    );
    const warnings = list(result.warnings).filter(
      (value) => typeof value === 'string' && !auditLimitations.has(value),
    );
    $('trafficWarnings').replaceChildren(
      ...warnings.slice(0, 12).map((message) => node('li', message)),
    );
    const warningsDetails = $('trafficWarningsDetails'),
      warningsSummary = $('trafficWarningsSummary');
    if (warningsSummary)
      warningsSummary.textContent =
        'Points de vigilance · ' +
        Math.min(12, warnings.length) +
        (warnings.length > 12 ? ' sur ' + warnings.length : '');
    if (warningsDetails) {
      warningsDetails.hidden = !warnings.length;
      const key = selectedPlanId + '|' + result.baseSha256;
      if (key !== warningsDetailsKey) {
        warningsDetails.open = false;
        warningsDetailsKey = key;
      }
    }
    renderList();
    renderSelection();
    renderFrame();
    updateStatus();
    renderRecord();
    renderLibrary(selectedPlanId);
  }
  async function load(identifier = selectedPlanId) {
    if (typeof identifier !== 'string') identifier = selectedPlanId;
    if (identifier !== 'source' && !uuid(identifier)) return;
    if (loading || saving || generating || revalidating) return;
    if (
      dirty &&
      !window.confirm('Charger ce plan et abandonner les modifications locales non enregistrées ?')
    ) {
      $('trafficPlanChoice').value = selectedPlanId;
      return;
    }
    setPlayback(false);
    loading = true;
    $('trafficReload').disabled = true;
    updateStatus();
    renderSelection();
    notice('Lecture du plan coopératif local…');
    try {
      const response = await fetch(
          '/api/traffic/plan' +
            (identifier === 'source' ? '' : '?planId=' + encodeURIComponent(identifier)),
          { cache: 'no-store' },
        ),
        result = await response.json();
      if (!response.ok) throw Error(errorText(result, 'Plan local indisponible.'));
      if (result.schema !== 'lotusim-traffic-editor-1') throw Error('Format de plan incompatible.');
      if (!result.available) {
        loaded = false;
        plan = null;
        $('trafficWorkspace').hidden = true;
        $('trafficEmpty').hidden = false;
        $('trafficEmptyDetail').textContent =
          list(result.warnings).join(' ') ||
          'Aucun plan coopératif existant n’a été trouvé. Aucun scénario n’est généré ou lancé par cette page.';
        notice('');
        return;
      }
      acceptPlan(result, identifier);
      notice(
        'Plan lu depuis ses sources. Prévisualisation locale uniquement ; aucune connexion à un moteur ni simulation en cours.',
      );
    } catch (error) {
      $('trafficPlanChoice').value = selectedPlanId;
      notice(error.message || 'Le plan local n’est pas accessible.', 'error');
      if (!plan) {
        $('trafficWorkspace').hidden = true;
        $('trafficEmpty').hidden = false;
      }
    } finally {
      loading = false;
      $('trafficReload').disabled = false;
      updateStatus();
      renderSelection();
      openPending();
    }
  }
  async function generate(event) {
    event.preventDefault();
    if (generating || saving || revalidating || loading) return;
    if (
      dirty &&
      !window.confirm(
        'Générer un nouveau plan et quitter les modifications locales non enregistrées ?',
      )
    )
      return;
    const name = $('trafficGenerateName').value.trim(),
      seed = Number($('trafficGenerateSeed').value),
      durationSeconds = Number($('trafficGenerateDuration').value),
      actionProfile = $('trafficGenerateProfile').value;
    if (
      !name ||
      name.length > 80 ||
      !Number.isInteger(seed) ||
      seed < 0 ||
      seed > 2147483647 ||
      !finite(durationSeconds) ||
      durationSeconds < 4 ||
      durationSeconds > 600 ||
      !['open_water', 'crossing', 'parallel'].includes(actionProfile)
    ) {
      notice(
        'Vérifier le nom (80 caractères), la graine entière et la durée de 4 à 600 secondes.',
        'error',
      );
      return;
    }
    let capture;
    try {
      capture = captureCadence(durationSeconds, trafficCapture()).capture;
    } catch (error) {
      notice(error.message, 'error');
      return;
    }
    setPlayback(false);
    generating = true;
    updateStatus();
    renderSelection();
    notice('Génération des trajectoires et contrôles coopératifs limités…');
    try {
      const response = await fetch('/api/traffic/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-LOTUSim-Traffic': '1' },
          body: JSON.stringify({
            name,
            seed,
            durationSeconds,
            actionProfile,
            ...(capture ? { capture } : {}),
          }),
        }),
        result = await response.json();
      if (!response.ok) throw Error(errorText(result, 'La génération a été refusée.'));
      if (!uuid(result.planId || result.id) || result.applied !== false || !result.preview)
        throw Error('Réponse de génération incompatible.');
      await refreshLibrary(result.planId || result.id);
      acceptPlan(result.preview, result.planId || result.id);
      notice(
        'Nouveau scénario enregistré dans la bibliothèque et affiché : ' +
          auditLabel(plan.record) +
          '. Les contrôles sont limités, non certifiants ; aucun moteur ni génération d’images lancé.',
        plan.record?.ready === true ? 'success' : 'warning',
      );
    } catch (error) {
      notice(error.message, 'error');
    } finally {
      generating = false;
      updateStatus();
      renderRecord();
      renderSelection();
      openPending();
    }
  }
  async function revalidate() {
    if (!uuid(selectedPlanId) || dirty || loading || saving || generating || revalidating) return;
    setPlayback(false);
    revalidating = true;
    updateStatus();
    renderSelection();
    notice('Contrôles limités des trajectoires courantes ; une nouvelle révision sera conservée…');
    try {
      const response = await fetch('/api/traffic/plans/' + selectedPlanId + '/revalidate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-LOTUSim-Traffic': '1' },
          body: '{}',
        }),
        result = await response.json();
      if (!response.ok) throw Error(errorText(result, 'Réévaluation refusée.'));
      if (!uuid(result.planId || result.id) || result.applied !== false || !result.preview)
        throw Error('Réponse de contrôle incompatible.');
      await refreshLibrary(result.planId || result.id);
      acceptPlan(result.preview, result.planId || result.id);
      notice(
        'Nouvelle révision des contrôles affichée : ' +
          auditLabel(plan.record) +
          '. Cela ne constitue pas une conformité COLREG complète ni une application en simulation.',
        plan.record?.ready === true ? 'success' : 'warning',
      );
    } catch (error) {
      notice(error.message, 'error');
    } finally {
      revalidating = false;
      updateStatus();
      renderRecord();
      renderSelection();
      openPending();
    }
  }
  function select(id) {
    selected = id;
    renderList();
    renderSelection();
    renderMap();
  }
  function renderList() {
    const target = $('trafficObjects'),
      query = $('trafficSearch').value.trim().toLocaleLowerCase('fr-FR');
    target.replaceChildren();
    const actors = list(plan?.actors).filter(
      (actor) =>
        !query ||
        [actor.id, actor.model, actor.category]
          .join(' ')
          .toLocaleLowerCase('fr-FR')
          .includes(query),
    );
    $('trafficObjectCount').textContent =
      fmt(actors.length, 0) + ' / ' + fmt(list(plan?.actors).length, 0) + ' objets';
    for (const actor of actors) {
      const button = node(
        'button',
        null,
        'traffic-object' + (actor.id === selected ? ' selected' : ''),
      );
      button.type = 'button';
      button.dataset.actorId = actor.id;
      button.setAttribute('aria-pressed', String(actor.id === selected));
      const mark = node('span', null, 'traffic-domain-dot');
      mark.style.backgroundColor = colors[actor.domain] || colors.sea;
      const content = node('span', null, 'traffic-object-copy');
      content.append(
        node('strong', actor.id),
        node(
          'small',
          [actor.model, actor.category, edited(actor) ? 'modifié' : null]
            .filter(Boolean)
            .join(' · '),
        ),
      );
      button.append(
        mark,
        content,
        node(
          'span',
          actor.domain === 'air' ? 'Air' : actor.domain === 'moored' ? 'Amarré' : 'Mer',
          'traffic-object-domain',
        ),
      );
      button.addEventListener('click', () => select(actor.id));
      target.append(button);
    }
    if (!actors.length) target.append(node('p', 'Aucun objet pour ce filtre.', 'traffic-help'));
  }
  function renderSelection() {
    const actor = actorFor(selected),
      form = $('trafficActorForm'),
      busy = loading || saving || generating || revalidating;
    form.hidden = !actor;
    $('trafficSelectionEmpty').hidden = !!actor;
    if (!actor) return;
    const value = { ...actor, ...edited(actor) },
      center = edited(actor)?.centerENU || actor.centerENU;
    $('trafficSelectedTitle').textContent = actor.id;
    $('trafficSelectedModel').textContent = [actor.model, actor.category, actor.domain]
      .filter(Boolean)
      .join(' · ');
    $('trafficSchedule').textContent =
      'Présent de ' +
      fmt(actor.startSeconds, 2) +
      ' à ' +
      fmt(actor.endSeconds, 2) +
      ' s · centre temporel ' +
      fmt(actor.centerSeconds, 2) +
      ' s';
    $('trafficTrajectoryKind').textContent =
      {
        bounded_turn: 'Virage borné conservé',
        constant_turn: 'Virage à taux constant conservé',
        linear: 'Trajectoire linéaire',
        piecewise_linear: 'Trajectoire à points de passage',
      }[actor.trajectoryKind] || 'Type de trajectoire non renseigné';
    for (const [id, key] of [
      ['trafficEast', 'eastM'],
      ['trafficNorth', 'northM'],
      ['trafficAltitude', 'altitudeM'],
    ])
      $(id).value = String(center?.[key] ?? 0);
    $('trafficSpeed').value = String(value.speedMps);
    $('trafficSpeed').max = String(actor.maxSpeedMps);
    $('trafficHeading').value = String(value.headingDeg);
    $('trafficAltitude').max = String(actor.domain === 'air' ? actor.maxAltitudeM : 0);
    $('trafficAltitude').min = actor.domain === 'air' ? '0.01' : '0';
    $('trafficAltitude').disabled = busy || actor.domain !== 'air' || !actor.editable;
    $('trafficSpeed').disabled = busy || actor.domain === 'moored' || !actor.editable;
    for (const id of [
      'trafficEast',
      'trafficNorth',
      'trafficHeading',
      'trafficPreviewEdit',
      'trafficResetActor',
    ])
      $(id).disabled = !actor.editable || busy;
    $('trafficCapability').textContent =
      'Limite déclarée : ' +
      fmt(actor.maxSpeedMps, 2) +
      ' m/s' +
      (actor.domain === 'air'
        ? ' · altitude max. ' + fmt(actor.maxAltitudeM, 0) + ' m'
        : ' · altitude de référence 0 m') +
      '. Ces limites ne constituent pas une certification.';
    $('trafficPreviewEdit').disabled = !actor.editable || busy;
    renderSelectionPosition();
  }
  function renderSelectionPosition() {
    const actor = actorFor(selected);
    if (!actor) return;
    const value = actorPosition(actor);
    $('trafficSelectedPosition').textContent = value
      ? 'À ' +
        fmt(time, 2) +
        ' s : Est ' +
        fmt(value.eastM, 1) +
        ' m · Nord ' +
        fmt(value.northM, 1) +
        ' m · altitude ' +
        fmt(value.altitudeM, 1) +
        ' m · ' +
        speedText(actor)
      : 'Position non disponible.';
  }
  function renderFrame() {
    if (!plan) return;
    $('trafficTime').value = String(time);
    $('trafficClock').textContent = fmt(time, 2) + ' / ' + fmt(plan.timeline.endSeconds, 2) + ' s';
    $('trafficActiveCount').textContent =
      fmt(plan.actors.filter(isActive).length, 0) + ' objets présents';
    renderMap();
    renderSelectionPosition();
  }
  function renderMap() {
    if (!plan) return;
    const target = $('trafficMap');
    target.replaceChildren();
    const all = plan.actors
      .flatMap((actor) => actorPoints(actor))
      .concat(list(plan.observer?.points))
      .filter((point) => finite(point.eastM) && finite(point.northM));
    let centerE = 0,
      centerN = 0,
      halfN = 1000,
      halfE = 1500;
    const view = $('trafficMapView').value,
      observer = interpolate(plan.observer?.points, time),
      chosen = actorFor(selected),
      chosenPoint = chosen ? actorPosition(chosen) : null;
    if (view === 'all' && all.length) {
      const east = all.map((point) => point.eastM),
        north = all.map((point) => point.northM),
        lowE = Math.min(...east),
        highE = Math.max(...east),
        lowN = Math.min(...north),
        highN = Math.max(...north);
      centerE = (lowE + highE) / 2;
      centerN = (lowN + highN) / 2;
      halfN = Math.max(100, (highN - lowN) * 0.57, (highE - lowE) * 0.38);
      halfE = halfN * 1.5;
    } else {
      const focus = view === 'selected' ? chosenPoint : observer;
      if (focus) {
        centerE = focus.eastM;
        centerN = focus.northM;
      }
      halfN = view === 'observer_1km' ? 1000 : view === 'observer_5km' ? 5000 : 1000;
      halfE = halfN * 1.5;
    }
    const project = (point) => [
      450 + ((point.eastM - centerE) / halfE) * 405,
      300 - ((point.northM - centerN) / halfN) * 255,
    ];
    const defs = svg('defs'),
      clip = svg('clipPath', { id: 'trafficPlotClip' });
    clip.append(svg('rect', { x: 35, y: 35, width: 830, height: 530 }));
    defs.append(clip);
    target.append(defs);
    for (let i = 0; i <= 8; i++) {
      const x = 45 + i * 101.25;
      target.append(
        svg('path', { d: 'M' + x + ' 45V555', stroke: '#28465a', 'stroke-width': 0.7 }),
      );
    }
    for (let i = 0; i <= 6; i++) {
      const y = 45 + i * 85;
      target.append(
        svg('path', { d: 'M45 ' + y + 'H855', stroke: '#28465a', 'stroke-width': 0.7 }),
      );
    }
    for (const [label, x, y] of [
      ['N', 450, 23],
      ['E', 879, 302],
    ]) {
      const text = svg('text', { x, y, fill: '#8cb1c7', 'font-size': 12, 'text-anchor': 'middle' });
      text.textContent = label;
      target.append(text);
    }
    const layer = svg('g', { 'clip-path': 'url(#trafficPlotClip)' });
    let outside = 0;
    for (const actor of plan.actors) {
      const points = actorPoints(actor),
        color = edited(actor) && working() ? '#efbd79' : colors[actor.domain] || colors.sea,
        active = isActive(actor),
        chosen = actor.id === selected;
      const track = svg('polyline', {
        points: points.map((point) => project(point).join(',')).join(' '),
        fill: 'none',
        stroke: color,
        'stroke-width': chosen ? 2.7 : 1.1,
        opacity: chosen ? 0.95 : active ? 0.55 : 0.2,
        'stroke-dasharray': edited(actor) && working() ? '7 4' : 'none',
      });
      track.dataset.actorId = actor.id;
      track.style.cursor = 'pointer';
      track.addEventListener('click', () => select(actor.id));
      layer.append(track);
      const value = actorPosition(actor);
      if (!value || (!active && !chosen)) continue;
      const [x, y] = project(value);
      if (x < 35 || x > 865 || y < 35 || y > 565) {
        outside++;
        continue;
      }
      const marker = svg(
        actor.domain === 'air' ? 'path' : 'circle',
        actor.domain === 'air'
          ? {
              d: `M${x} ${y - 6}L${x + 5} ${y + 4}L${x - 5} ${y + 4}Z`,
              fill: color,
              opacity: active ? 1 : 0.35,
            }
          : { cx: x, cy: y, r: chosen ? 5.5 : 3.8, fill: color, opacity: active ? 1 : 0.35 },
      );
      marker.style.cursor = 'pointer';
      marker.addEventListener('click', () => select(actor.id));
      const title = svg('title');
      title.textContent = actor.id + ' · ' + actor.model + ' · ' + fmt(value.altitudeM, 1) + ' m';
      marker.append(title);
      layer.append(marker);
      if (chosen) {
        layer.append(
          svg('circle', { cx: x, cy: y, r: 11, stroke: color, fill: 'none', 'stroke-width': 1.3 }),
        );
        const label = svg('text', { x: x + 14, y: y - 9, fill: '#e1edf5', 'font-size': 10 });
        label.textContent = actor.id + (active ? '' : ' · hors créneau');
        layer.append(label);
      }
    }
    if (plan.observer) {
      const points = list(plan.observer.points),
        line = svg('polyline', {
          points: points.map((point) => project(point).join(',')).join(' '),
          fill: 'none',
          stroke: colors.observer,
          'stroke-width': 2,
          opacity: 0.65,
        });
      layer.append(line);
      if (observer) {
        const [x, y] = project(observer);
        layer.append(
          svg('circle', {
            cx: x,
            cy: y,
            r: 6,
            fill: colors.observer,
            stroke: '#102435',
            'stroke-width': 2,
          }),
        );
        const title = svg('text', { x: x + 12, y: y + 4, fill: colors.observer, 'font-size': 10 });
        title.textContent = plan.observer.model || 'Observateur FREMM';
        layer.append(title);
      }
    }
    target.append(layer);
    $('trafficMapScale').textContent =
      'Largeur ' +
      fmt((2 * halfE) / 1000, 2) +
      ' km · ENU en mètres' +
      (outside ? ' · ' + outside + ' hors cadre' : '');
  }
  function previewEdit(event) {
    event.preventDefault();
    const actor = actorFor(selected);
    if (!actor || loading || saving || generating || revalidating) return;
    try {
      const change = validateChange(actor, {
        actorId: actor.id,
        centerENU: {
          eastM: Number($('trafficEast').value),
          northM: Number($('trafficNorth').value),
          altitudeM: Number($('trafficAltitude').value),
        },
        speedMps: Number($('trafficSpeed').value),
        headingDeg: Number($('trafficHeading').value),
      });
      changes.set(actor.id, change);
      dirty = true;
      $('trafficVersion').value = 'working';
      if ($('trafficMapView').value === 'all') $('trafficMapView').value = 'selected';
      renderList();
      renderSelection();
      renderFrame();
      updateStatus();
      notice(
        'Modification prévisualisée localement, avec l’objet sélectionné comme repère. L’évitement des collisions et la sécurité doivent être réévalués ; aucun plan n’a été appliqué à un moteur.',
        'warning',
      );
    } catch (error) {
      notice(error.message, 'error');
    }
  }
  async function save() {
    if (loading || saving || generating || revalidating || !plan || !changes.size) return;
    const name = $('trafficDraftName').value.trim();
    if (!name || name.length > 120) {
      notice('Nommer le brouillon avec 1 à 120 caractères.', 'error');
      return;
    }
    setPlayback(false);
    saving = true;
    updateStatus();
    renderSelection();
    notice('Vérification des capacités et enregistrement d’un brouillon immuable…');
    try {
      const response = await fetch('/api/traffic/drafts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-LOTUSim-Traffic': '1' },
          body: JSON.stringify({
            planId: selectedPlanId,
            baseSha256: plan.baseSha256,
            name,
            changes: [...changes.values()],
          }),
        }),
        result = await response.json();
      if (!response.ok)
        throw Error(
          result.message ||
            result.error ||
            list(result.errors)
              .slice(0, 5)
              .map((issue) =>
                [issue.path, issue.message]
                  .filter((value) => typeof value === 'string')
                  .join(' : '),
              )
              .join(' ; ') ||
            'Le brouillon a été refusé.',
        );
      if (typeof result.id !== 'string' || result.applied !== false || !result.preview)
        throw Error(
          'Réponse de brouillon incompatible : aucune application à un moteur n’est autorisée.',
        );
      if (result.record && uuid(result.planId || result.preview.planId)) {
        const id = result.planId || result.preview.planId;
        await refreshLibrary(id);
        acceptPlan(result.preview, id);
      } else {
        saved = result;
        dirty = false;
        updateStatus();
      }
      notice(
        'Nouvelle révision enregistrée, sélectionnée et non appliquée. Les capacités ont été vérifiées ; la coopération et les collisions nécessitent une nouvelle validation avant utilisation.',
        'success',
      );
    } catch (error) {
      notice(error.message + ' Les modifications locales sont conservées.', 'error');
    } finally {
      saving = false;
      updateStatus();
      renderSelection();
      openPending();
    }
  }
  $('trafficReload').addEventListener('click', () => load());
  $('trafficPlay').addEventListener('click', () => {
    if (time >= plan?.timeline.endSeconds) time = plan.timeline.startSeconds;
    setPlayback(!playing);
  });
  $('trafficPlanChoice').addEventListener('change', () => load($('trafficPlanChoice').value));
  $('trafficLibraryRefresh').addEventListener('click', () => refreshLibrary());
  $('trafficGenerateForm').addEventListener('submit', generate);
  $('trafficRevalidate').addEventListener('click', revalidate);
  $('trafficCaptureMode').addEventListener('change', renderCapturePreview);
  for (const id of ['trafficGenerateDuration', 'trafficCaptureCount', 'trafficCaptureInterval'])
    $(id).addEventListener('input', renderCapturePreview);
  renderCapturePreview();
  $('trafficTime').addEventListener('input', () => {
    if (!plan) return;
    time = clamp(
      Number($('trafficTime').value),
      plan.timeline.startSeconds,
      plan.timeline.endSeconds,
    );
    renderFrame();
  });
  $('trafficMapView').addEventListener('change', renderMap);
  $('trafficVersion').addEventListener('change', () => {
    renderFrame();
    renderList();
  });
  $('trafficSearch').addEventListener('input', renderList);
  $('trafficActorForm').addEventListener('submit', previewEdit);
  $('trafficSave').addEventListener('click', save);
  $('trafficResetActor').addEventListener('click', () => {
    if (!selected || saving) return;
    changes.delete(selected);
    dirty = changes.size > 0;
    saved = null;
    renderList();
    renderSelection();
    renderFrame();
    updateStatus();
    notice(
      'Modifications de cet objet retirées du brouillon local. Le plan source n’a pas changé.',
    );
  });
  $('trafficResetAll').addEventListener('click', () => {
    if (
      saving ||
      !window.confirm(
        'Revenir au plan source et retirer les modifications locales ? Les brouillons enregistrés restent conservés.',
      )
    )
      return;
    changes.clear();
    saved = null;
    dirty = false;
    $('trafficVersion').value = 'original';
    renderList();
    renderSelection();
    renderFrame();
    updateStatus();
    notice('Plan source réaffiché ; aucun fichier de brouillon supprimé.');
  });
  function openPending() {
    if (
      pendingPlanId &&
      location.hash === '#traffic' &&
      !loading &&
      !saving &&
      !generating &&
      !revalidating
    ) {
      const id = pendingPlanId;
      pendingPlanId = null;
      load(id);
    }
  }
  const enter = () => {
    if (location.hash === '#traffic') {
      refreshLibrary(pendingPlanId);
      if (pendingPlanId) openPending();
      else if (!loaded) load();
    } else setPlayback(false);
  };
  window.addEventListener('hashchange', enter);
  window.addEventListener('lotusim-traffic-plan-selected', (event) => {
    if (uuid(event.detail?.planId)) {
      pendingPlanId = event.detail.planId;
      if (location.hash === '#traffic') enter();
    }
  });
  window.addEventListener('pagehide', () => setPlayback(false));
  enter();
})();
