/**
 * TimerRegistry — centralized timer management for view lifecycle cleanup.
 * Wraps setTimeout, setInterval, and requestAnimationFrame with scope tracking.
 * Call clearScope(scopeName) when leaving a view to cancel all its timers.
 */
(function () {
    'use strict';

    const _timers = {};  // id -> { scope, type, nativeId }
    let _nextId = 1;

    function _register(scope, type, nativeId) {
        const id = _nextId++;
        if (!_timers[scope]) _timers[scope] = {};
        _timers[scope][id] = { type, nativeId };
        return id;
    }

    function _remove(scope, id) {
        if (_timers[scope]) {
            delete _timers[scope][id];
            if (Object.keys(_timers[scope]).length === 0) {
                delete _timers[scope];
            }
        }
    }

    window.TimerRegistry = {
        setTimeout(scope, fn, delay) {
            const id = _nextId++;
            const nativeId = window._nativeSetTimeout(function () {
                _remove(scope, id);
                fn();
            }, delay);
            if (!_timers[scope]) _timers[scope] = {};
            _timers[scope][id] = { type: 'timeout', nativeId };
            return id;
        },

        setInterval(scope, fn, delay) {
            const nativeId = window._nativeSetInterval(fn, delay);
            return _register(scope, 'interval', nativeId);
        },

        requestAnimationFrame(scope, fn) {
            const nativeId = window._nativeRAF(fn);
            return _register(scope, 'raf', nativeId);
        },

        clear(scope, id) {
            const entry = _timers[scope] && _timers[scope][id];
            if (!entry) return;
            if (entry.type === 'timeout') window._nativeClearTimeout(entry.nativeId);
            else if (entry.type === 'interval') window._nativeClearInterval(entry.nativeId);
            else if (entry.type === 'raf') window._nativeCancelRAF(entry.nativeId);
            _remove(scope, id);
        },

        clearScope(scope) {
            const scopeTimers = _timers[scope];
            if (!scopeTimers) return;
            for (const [id, entry] of Object.entries(scopeTimers)) {
                if (entry.type === 'timeout') window._nativeClearTimeout(entry.nativeId);
                else if (entry.type === 'interval') window._nativeClearInterval(entry.nativeId);
                else if (entry.type === 'raf') window._nativeCancelRAF(entry.nativeId);
            }
            delete _timers[scope];
        },

        activeCount(scope) {
            if (scope) {
                return _timers[scope] ? Object.keys(_timers[scope]).length : 0;
            }
            let total = 0;
            for (const s of Object.keys(_timers)) {
                total += Object.keys(_timers[s]).length;
            }
            return total;
        },

        activeScopesSummary() {
            const summary = {};
            for (const [scope, entries] of Object.entries(_timers)) {
                summary[scope] = Object.keys(entries).length;
            }
            return summary;
        }
    };

    // Save native references before any wrapping
    window._nativeSetTimeout = window.setTimeout.bind(window);
    window._nativeClearTimeout = window.clearTimeout.bind(window);
    window._nativeSetInterval = window.setInterval.bind(window);
    window._nativeClearInterval = window.clearInterval.bind(window);
    window._nativeRAF = window.requestAnimationFrame.bind(window);
    window._nativeCancelRAF = window.cancelAnimationFrame.bind(window);
})();
