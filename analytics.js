/**
 * Lucid Website Analytics — Google Sheets Backend
 * Tracks: page views, time on page, CTA clicks, persona selection,
 *         scroll depth, FAQ opens, sound toggle, carousel nav,
 *         mobile menu, sticky CTA clicks.
 */
(function () {
  'use strict';

  // ── Config ──
  var ENDPOINT = 'https://script.google.com/macros/s/AKfycbwlpVeZOr73GGNk8z5ae0PpqprccdvDsnLUn018SX8Y1KUzTU3XZKma02aalWGRa2jSeQ/exec';
  var FLUSH_INTERVAL = 5000; // ms
  var PAGE_NAME = detectPage();
  var SESSION_ID = getSessionId();

  // ── Helpers ──
  function detectPage() {
    var path = location.pathname.replace(/\/$/, '');
    var file = path.split('/').pop().replace('.html', '') || 'router';
    var map = {
      'Base': 'base',
      'burnedout': 'burnedout',
      'Lucid-founder': 'founder',
      'systemskeptic': 'systemskeptic',
      'wall-street': 'wall-street',
      'router': 'router',
      '': 'router'
    };
    return map[file] || file;
  }

  function getSessionId() {
    var id = sessionStorage.getItem('_lucid_sid');
    if (!id) {
      id = 's_' + Math.random().toString(36).substr(2, 8);
      sessionStorage.setItem('_lucid_sid', id);
    }
    return id;
  }

  function getUTM(key) {
    try {
      return new URLSearchParams(location.search).get(key) || '';
    } catch (e) {
      return '';
    }
  }

  function getDeviceType() {
    return /Mobi|Android/i.test(navigator.userAgent) ? 'mobile' : 'desktop';
  }

  function now() {
    return new Date().toISOString();
  }

  // ── Event Queue ──
  var queue = [];

  function track(event, detail, extra) {
    var entry = {
      timestamp: now(),
      session_id: SESSION_ID,
      page: PAGE_NAME,
      event: event,
      event_detail: detail || '',
      referrer: document.referrer || '',
      utm_source: getUTM('utm_source'),
      utm_medium: getUTM('utm_medium'),
      utm_campaign: getUTM('utm_campaign'),
      utm_content: getUTM('utm_content'),
      utm_term: getUTM('utm_term'),
      device_type: getDeviceType(),
      user_agent: navigator.userAgent,
      scroll_position: extra && extra.scroll_position != null ? extra.scroll_position : '',
      duration_seconds: extra && extra.duration_seconds != null ? extra.duration_seconds : ''
    };
    queue.push(entry);
  }

  function flush() {
    if (queue.length === 0) return;
    var batch = queue.splice(0);
    var payload = JSON.stringify({ events: batch });

    // sendBeacon avoids CORS preflight (sends as text/plain)
    if (navigator.sendBeacon) {
      var sent = navigator.sendBeacon(ENDPOINT, payload);
      if (!sent) fetchFallback(payload);
    } else {
      fetchFallback(payload);
    }
  }

  function fetchFallback(payload) {
    try {
      fetch(ENDPOINT, {
        method: 'POST',
        body: payload,
        keepalive: true,
        headers: { 'Content-Type': 'text/plain' }
      });
    } catch (e) { /* silent */ }
  }

  // Periodic flush
  setInterval(flush, FLUSH_INTERVAL);

  // ── Page View ──
  track('page_view');

  // ── Time on Page ──
  var pageStart = Date.now();
  var timeSent = false;

  function sendTimeOnPage() {
    if (timeSent) return;
    timeSent = true;
    var seconds = Math.round((Date.now() - pageStart) / 1000);
    if (seconds > 0) {
      track('time_on_page', seconds + 's', { duration_seconds: seconds });
      flush();
    }
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') sendTimeOnPage();
  });
  window.addEventListener('beforeunload', sendTimeOnPage);

  // ── Scroll Depth ──
  var scrollMilestones = {};

  function checkScroll() {
    var scrollTop = window.pageYOffset || document.documentElement.scrollTop;
    var docHeight = Math.max(
      document.body.scrollHeight,
      document.documentElement.scrollHeight
    ) - window.innerHeight;
    if (docHeight <= 0) return;
    var pct = Math.round((scrollTop / docHeight) * 100);

    [25, 50, 75, 100].forEach(function (m) {
      if (pct >= m && !scrollMilestones[m]) {
        scrollMilestones[m] = true;
        track('scroll_depth', m + '%', { scroll_position: scrollTop });
      }
    });
  }

  var scrollTimer;
  window.addEventListener('scroll', function () {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(checkScroll, 200);
  }, { passive: true });

  // ── Delegated Click Handlers ──
  document.addEventListener('click', function (e) {
    var target = e.target;

    // CTA buttons (any .btn-* class)
    var btn = target.closest('[class*="btn-"]');
    if (btn) {
      var classes = Array.prototype.filter.call(btn.classList, function (c) {
        return c.indexOf('btn-') === 0;
      }).join(' ');
      var text = (btn.textContent || '').trim().substring(0, 80);
      var scrollPos = window.pageYOffset || document.documentElement.scrollTop;
      track('cta_click', classes + ': ' + text, { scroll_position: scrollPos });
    }

    // Sticky CTA
    var sticky = target.closest('.sticky-cta');
    if (sticky) {
      var stickyBtn = target.closest('[class*="btn-"]');
      var stickyText = stickyBtn ? (stickyBtn.textContent || '').trim().substring(0, 80) : 'sticky-bar';
      track('sticky_cta_click', stickyText);
    }

    // Persona card (router.html)
    var card = target.closest('.persona-card');
    if (card) {
      var headline = card.querySelector('.card-headline');
      var headlineText = headline ? headline.textContent.trim() : '';
      track('persona_select', headlineText);
    }

    // FAQ question
    var faq = target.closest('.faq-question');
    if (faq) {
      var questionText = (faq.textContent || '').trim().substring(0, 120);
      track('faq_open', questionText);
    }

    // Sound toggle
    if (target.closest('#soundToggle') || target.closest('.sound-toggle')) {
      track('sound_toggle');
    }

    // Carousel navigation
    var arrow = target.closest('.carousel-arrow');
    if (arrow) {
      var isNext = arrow.id === 'carouselNext' || arrow.textContent.indexOf('→') !== -1 ||
                   arrow.textContent.indexOf('›') !== -1;
      track('carousel_nav', isNext ? 'next' : 'prev');
    }
    var dot = target.closest('.carousel-dot');
    if (dot) {
      var dots = document.querySelectorAll('.carousel-dot');
      var idx = Array.prototype.indexOf.call(dots, dot);
      track('carousel_nav', 'dot_' + idx);
    }

    // Mobile menu toggle
    if (target.closest('#mobileToggle') || target.closest('.nav-mobile-toggle')) {
      track('mobile_menu_toggle');
    }
  });

})();
