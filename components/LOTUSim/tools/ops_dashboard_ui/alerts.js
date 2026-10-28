'use strict';

/* Local presentation only: no network, system notification or stored dismissal. */
(() => {
  const routes = new Set([
    'overview',
    'agents',
    'traffic',
    'journal',
    'reports',
    'settings',
    'assets',
  ]);
  const text = (value) => (typeof value === 'string' ? value.trim() : '');
  const array = (value) => (Array.isArray(value) ? value : []);
  const status = (value) => text(value?.state || value?.status).toLowerCase();
  const errors = new Set(['error', 'failed', 'offline']);
  function item(key, source, level, message, route, at = null) {
    return {
      key,
      source,
      level,
      message: text(message),
      route: routes.has(route) ? route : 'overview',
      at,
    };
  }
  function collect(data) {
    if (!data || typeof data !== 'object') return [];
    const result = [];
    if (text(data.health?.error))
      result.push(
        item(
          'collector-error',
          'Collecteur',
          'error',
          data.health.error,
          'overview',
          data.generatedAt,
        ),
      );
    for (const warning of array(data.health?.warnings)) {
      if (text(warning))
        result.push(
          item(
            'health:' + warning,
            'Diagnostic de la chaîne',
            'warning',
            warning,
            'overview',
            data.generatedAt,
          ),
        );
    }
    for (const service of array(data.services)) {
      if (
        !service ||
        !['error', 'failed', 'offline', 'stale', 'degraded'].includes(status(service))
      )
        continue;
      result.push(
        item(
          'service:' + text(service.id || service.label),
          'Services',
          errors.has(status(service)) ? 'error' : 'warning',
          [text(service.label) || 'Composant', text(service.detail) || 'État à vérifier'].join(
            ' — ',
          ),
          'overview',
          service.updatedAt,
        ),
      );
    }
    // Archived jobs are results, not fresh incidents. Their complete history stays in Reports/Journal.
    for (const [key, label] of [
      ['capture', 'Capture'],
      ['vision', 'Analyse RGB'],
      ['preparation', 'Préparation'],
    ]) {
      const job = data[key];
      if (
        !job ||
        job.historical === true ||
        job.fresh === false ||
        status(job) === 'stale' ||
        !(errors.has(status(job)) || errors.has(text(job.status).toLowerCase()))
      )
        continue;
      const at = Date.parse(job.updatedAt || '');
      const snapshot = Date.parse(data.generatedAt || '');
      if (
        job.live !== true &&
        !(
          Number.isFinite(at) &&
          Number.isFinite(snapshot) &&
          snapshot >= at &&
          snapshot - at <= 15000
        )
      )
        continue;
      result.push(
        item(
          'job:' + key,
          label,
          'error',
          text(job.error) || text(job.detail) || label + ' en échec',
          'agents',
          job.updatedAt,
        ),
      );
    }
    return result;
  }
  function deduplicate(values) {
    const unique = new Map();
    for (const value of values) {
      if (!value || !['warning', 'error'].includes(value.level) || !text(value.message)) continue;
      const signature = [value.source, value.level, value.message].join('\u0000');
      if (!unique.has(signature)) unique.set(signature, value);
    }
    return [...unique.values()].sort(
      (a, b) =>
        (a.level === 'error' ? 0 : 1) - (b.level === 'error' ? 0 : 1) ||
        a.source.localeCompare(b.source, 'fr') ||
        a.message.localeCompare(b.message, 'fr'),
    );
  }
  function createStore() {
    let snapshot = null,
      transport = null;
    const local = new Map();
    return {
      update(data) {
        snapshot = data;
      },
      transport(value) {
        transport = value;
      },
      publish(key, value) {
        if (value && ['warning', 'error'].includes(value.level) && text(value.message))
          local.set(key, value);
        else local.delete(key);
      },
      items() {
        return deduplicate([
          ...collect(snapshot),
          ...(transport ? [transport] : []),
          ...local.values(),
        ]);
      },
      snapshot() {
        return snapshot;
      },
    };
  }
  function mount(win) {
    const document = win.document,
      $ = (id) => document.getElementById(id),
      store = createStore();
    const center = $('alertCenter');
    if (!center) return null;
    let signature = '',
      transportState = '';
    const inlineState = new WeakMap();
    function node(tag, content, className) {
      const target = document.createElement(tag);
      if (content !== undefined) target.textContent = content;
      if (className) target.className = className;
      return target;
    }
    function close(focus = false) {
      center.open = false;
      if (focus) $('alertToggle').focus();
    }
    function position() {
      const bounds = $('alertToggle').getBoundingClientRect?.();
      if (!bounds || !center.style?.setProperty) return;
      const height = Number.isFinite(win.innerHeight) ? win.innerHeight : 700;
      center.style.setProperty(
        '--alerts-top',
        Math.min(Math.max(12, bounds.bottom + 10), Math.max(12, height - 210)) + 'px',
      );
    }
    function draw() {
      const values = store.items(),
        errorCount = values.filter((value) => value.level === 'error').length;
      const label = values.length + ' point' + (values.length > 1 ? 's' : '') + ' à vérifier';
      if ($('alertCount').textContent !== String(values.length))
        $('alertCount').textContent = String(values.length);
      $('alertToggle').setAttribute('aria-label', 'Centre d’alertes : ' + label);
      center.classList.toggle('has-errors', errorCount > 0);
      center.classList.toggle('has-warnings', values.length > 0 && !errorCount);
      const summary = values.length
        ? errorCount +
          ' erreur' +
          (errorCount > 1 ? 's' : '') +
          ' · ' +
          (values.length - errorCount) +
          ' avertissement' +
          (values.length - errorCount > 1 ? 's' : '')
        : 'Aucun point signalé';
      if ($('alertStatus').textContent !== summary) $('alertStatus').textContent = summary;
      const snapshot = store.snapshot();
      const date = Date.parse(snapshot?.generatedAt || '');
      $('alertFreshness').textContent = transportState
        ? 'Liaison non actualisée : les derniers états reçus sont conservés.'
        : Number.isFinite(date)
          ? 'Dernier état reçu · ' +
            new Intl.DateTimeFormat('fr-FR', {
              timeZone: 'Europe/Paris',
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            }).format(new Date(date))
          : 'Date du dernier état non mesurée.';
      const filter = $('alertFilter').value;
      const filtered = values.filter((value) => filter === 'all' || value.level === filter);
      const next = JSON.stringify([
        filtered.map(({ source, level, message, route }) => [source, level, message, route]),
        filter,
        !!snapshot,
      ]);
      if (next === signature) return;
      signature = next;
      const opened = new Map(
        [...$('alertItems').querySelectorAll('details[data-source]')].map((element) => [
          element.dataset.source,
          element.open,
        ]),
      );
      const scroll = $('alertItems').scrollTop;
      $('alertItems').replaceChildren();
      if (!filtered.length)
        $('alertItems').append(
          node(
            'p',
            !snapshot && !values.length
              ? 'Aucun état reçu. Cela ne confirme pas la disponibilité de la chaîne.'
              : values.length
                ? 'Aucun point de ce niveau.'
                : 'Aucune alerte dans le dernier état reçu. Les résultats anciens restent dans le journal et les rapports.',
            'alerts-empty',
          ),
        );
      const groups = new Map();
      for (const value of filtered) {
        if (!groups.has(value.source)) groups.set(value.source, []);
        groups.get(value.source).push(value);
      }
      for (const [source, entries] of groups) {
        const group = node('details', undefined, 'alert-group');
        group.dataset.source = source;
        group.open = opened.has(source) ? opened.get(source) : true;
        const title = node('summary', source);
        title.append(node('span', entries.length, 'alert-group-count'));
        group.append(title);
        for (const value of entries) {
          const row = node('article', undefined, 'alert-entry ' + value.level);
          row.append(
            node('span', value.level === 'error' ? 'Erreur' : 'Avertissement', 'alert-level'),
            node('p', value.message),
          );
          const link = node('a', 'Voir la section', 'text-link');
          link.href = '#' + value.route;
          link.addEventListener('click', () => close());
          row.append(link);
          group.append(row);
        }
        $('alertItems').append(group);
      }
      $('alertItems').scrollTop = scroll;
    }
    const api = {
      update(data) {
        store.update(data);
        draw();
      },
      setTransport(value) {
        transportState = value?.level || '';
        store.transport(
          value
            ? item('transport', 'Liaison du dashboard', value.level, value.message, 'overview')
            : null,
        );
        draw();
      },
      notify(target, message, kind = '', options = {}) {
        if (!target) return;
        message = text(message);
        const source = text(options.source) || 'Interface',
          route = routes.has(options.route) ? options.route : 'overview';
        const key = target.id || source + ':' + route;
        store.publish(
          key,
          message && ['error', 'warning'].includes(kind)
            ? item('action:' + key, source, kind, message, route)
            : null,
        );
        const previous = inlineState.get(target),
          identity = JSON.stringify([message, kind, options.label]);
        if (identity !== previous) {
          inlineState.set(target, identity);
          target.replaceChildren();
          target.hidden = !message;
          if (message && ['error', 'warning'].includes(kind)) {
            const details = node('details', undefined, 'feedback-details');
            const heading = node('summary');
            heading.append(
              node(
                'strong',
                (kind === 'error' ? 'Erreur' : 'Attention') +
                  (text(options.label) ? ' · ' + text(options.label) : ''),
              ),
              node(
                'span',
                message.length > 155 ? message.slice(0, 152) + '…' : message,
                'feedback-excerpt',
              ),
              node('span', 'Détails', 'feedback-hint'),
            );
            details.append(heading, node('p', message));
            target.append(details);
          } else target.textContent = message;
        }
        draw();
      },
    };
    $('alertFilter').addEventListener('change', draw);
    center.addEventListener('toggle', position);
    win.addEventListener?.('resize', position);
    win.addEventListener?.(
      'scroll',
      () => {
        if (center.open) position();
      },
      { passive: true },
    );
    $('alertClose').addEventListener('click', () => close(true));
    $('alertJournal').addEventListener('click', () => close());
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && center.open) {
        event.preventDefault();
        close(true);
      }
    });
    document.addEventListener('click', (event) => {
      if (center.open && !center.contains(event.target)) close();
    });
    draw();
    return api;
  }
  const exported = { collect, deduplicate, createStore, mount };
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  if (typeof window !== 'undefined' && window.document) window.LotusimAlerts = mount(window);
})();
