(function() {
'use strict';

let isPaused = false;
let speedMultiplier = __INITIAL_SPEED_MULTIPLIER__;
window.__speedControlInstalled = true;
window.__gameSpeedMultiplier__ = speedMultiplier;

const OriginalDate = Date;
const originalDateNow = OriginalDate.now.bind(OriginalDate);
const originalPerfNow = performance.now.bind(performance);
window.__realDateNow = function() { return originalDateNow(); };
window.__realPerfNow = function() { return originalPerfNow(); };
const originalSetTimeout = window.setTimeout.bind(window);
const originalClearTimeout = window.clearTimeout.bind(window);
const originalClearInterval = window.clearInterval.bind(window);
const originalCancelRAF = window.cancelAnimationFrame.bind(window);

const BASE_FRAME_RATE = 60;
const pendingRAFCallbacks = [];
const scheduledRAFTimeouts = new Map();
let rafIdCounter = 1000000;
let managedTimeoutIdCounter = 2000000;
let managedIntervalIdCounter = 3000000;
const managedTimeouts = new Map();
const managedIntervals = new Map();

const startDateNow = originalDateNow();
const startPerfNow = originalPerfNow();
let totalPausedReal = 0;
let pauseStartRealPerf = 0;
let pauseScaledDate = startDateNow;
let pauseScaledPerf = startPerfNow;
const PAUSED_CLASS = '__gw_game_paused';
const PAUSE_STYLE_ID = '__gw_game_pause_style';
let pausedWebAnimations = [];

function scaledDateNow(realDate) {
    return startDateNow + (realDate - startDateNow - totalPausedReal) * speedMultiplier;
}

function scaledPerfNow(realPerf) {
    return startPerfNow + (realPerf - startPerfNow - totalPausedReal) * speedMultiplier;
}

function currentScaledDateNow() {
    if (isPaused) {
        return pauseScaledDate;
    }
    return scaledDateNow(originalDateNow());
}

function currentScaledPerfNow() {
    if (isPaused) {
        return pauseScaledPerf;
    }
    return scaledPerfNow(originalPerfNow());
}

function SpeedControlDate(...args) {
    if (!(this instanceof SpeedControlDate)) {
        return new OriginalDate(currentScaledDateNow()).toString();
    }
    if (args.length === 0) {
        return new OriginalDate(currentScaledDateNow());
    }
    return new OriginalDate(...args);
}
SpeedControlDate.prototype = OriginalDate.prototype;
Object.defineProperty(SpeedControlDate.prototype, 'constructor', {
    value: SpeedControlDate,
    writable: true,
    configurable: true,
});
Object.setPrototypeOf(SpeedControlDate, OriginalDate);
SpeedControlDate.now = function() {
    return currentScaledDateNow();
};
SpeedControlDate.parse = OriginalDate.parse.bind(OriginalDate);
SpeedControlDate.UTC = OriginalDate.UTC.bind(OriginalDate);
window.Date = SpeedControlDate;

performance.now = function() {
    return currentScaledPerfNow();
};

function normalizeSpeed(multiplier) {
    if (!Number.isFinite(multiplier) || multiplier <= 0) {
        return null;
    }
    return multiplier;
}

function ensurePauseStyle() {
    if (document.getElementById(PAUSE_STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = PAUSE_STYLE_ID;
    style.textContent = `
html.${PAUSED_CLASS} *, html.${PAUSED_CLASS} *::before, html.${PAUSED_CLASS} *::after {
    animation-play-state: paused !important;
    -webkit-animation-play-state: paused !important;
}`;
    (document.head || document.documentElement).appendChild(style);
}

function setCssAnimationPaused(paused) {
    const root = document.documentElement;
    if (!root) return;
    ensurePauseStyle();
    if (paused) {
        root.classList.add(PAUSED_CLASS);
        pausedWebAnimations = [];
        if (typeof document.getAnimations === 'function') {
            document.getAnimations().forEach((anim) => {
                try {
                    if (anim && anim.playState === 'running') {
                        pausedWebAnimations.push(anim);
                        anim.pause();
                    }
                } catch (_err) {}
            });
        }
    } else {
        root.classList.remove(PAUSED_CLASS);
        if (pausedWebAnimations.length > 0) {
            pausedWebAnimations.forEach((anim) => {
                try {
                    if (anim && anim.playState === 'paused') {
                        anim.play();
                    }
                } catch (_err) {}
            });
            pausedWebAnimations = [];
        }
    }
}

function getRAFDelayMs() {
    const normalized = normalizeSpeed(speedMultiplier);
    const effectiveSpeed = normalized || 1;
    return 1000 / (BASE_FRAME_RATE * effectiveSpeed);
}

function scheduleRAF(id, callback) {
    const timeoutId = originalSetTimeout(function() {
        if (!scheduledRAFTimeouts.has(id)) return;
        scheduledRAFTimeouts.delete(id);

        if (isPaused) {
            pendingRAFCallbacks.push({ id, callback });
            return;
        }

        callback(performance.now());
    }, getRAFDelayMs());

    scheduledRAFTimeouts.set(id, timeoutId);
}

function invokeTimerHandler(handler, args) {
    if (typeof handler === 'function') {
        handler(...args);
        return;
    }
    (0, eval)(String(handler));
}

function toTimerDelayMs(timeout) {
    const value = Number(timeout);
    const safeTimeout = Number.isFinite(value) ? Math.max(0, value) : 0;
    const normalized = normalizeSpeed(speedMultiplier);
    return normalized ? safeTimeout / normalized : safeTimeout;
}

function scheduleManagedTimeout(entry) {
    const delayMs = Math.max(0, Number(entry.remainingMs) || 0);
    entry.nextFireAtPerf = originalPerfNow() + delayMs;
    entry.nativeId = originalSetTimeout(function() {
        const current = managedTimeouts.get(entry.id);
        if (!current) return;
        managedTimeouts.delete(entry.id);
        current.nativeId = null;
        invokeTimerHandler(current.handler, current.args);
    }, delayMs);
}

function scheduleManagedInterval(entry) {
    const delayMs = Math.max(0, Number(entry.remainingMs) || 0);
    entry.nextFireAtPerf = originalPerfNow() + delayMs;
    entry.nativeId = originalSetTimeout(function tick() {
        const current = managedIntervals.get(entry.id);
        if (!current) return;
        current.nativeId = null;
        invokeTimerHandler(current.handler, current.args);

        const stillActive = managedIntervals.get(entry.id);
        if (!stillActive) return;
        stillActive.remainingMs = stillActive.intervalMs;
        scheduleManagedInterval(stillActive);
    }, delayMs);
}

window.requestAnimationFrame = function(callback) {
    const id = rafIdCounter++;
    if (isPaused) {
        pendingRAFCallbacks.push({ id, callback });
        return id;
    }
    scheduleRAF(id, callback);
    return id;
};

window.cancelAnimationFrame = function(id) {
    const idx = pendingRAFCallbacks.findIndex(p => p.id === id);
    if (idx !== -1) {
        pendingRAFCallbacks.splice(idx, 1);
        return;
    }

    const timeoutId = scheduledRAFTimeouts.get(id);
    if (timeoutId !== undefined) {
        originalClearTimeout(timeoutId);
        scheduledRAFTimeouts.delete(id);
        return;
    }

    return originalCancelRAF(id);
};

window.setTimeout = function(handler, timeout, ...args) {
    const timeoutId = managedTimeoutIdCounter++;
    const entry = {
        id: timeoutId,
        handler: handler,
        args: args,
        remainingMs: toTimerDelayMs(timeout),
        nextFireAtPerf: 0,
        nativeId: null,
    };
    managedTimeouts.set(timeoutId, entry);
    if (!isPaused) {
        scheduleManagedTimeout(entry);
    }
    return timeoutId;
};

window.setInterval = function(handler, timeout, ...args) {
    const intervalId = managedIntervalIdCounter++;
    const intervalMs = toTimerDelayMs(timeout);
    const entry = {
        id: intervalId,
        handler: handler,
        args: args,
        intervalMs: intervalMs,
        remainingMs: intervalMs,
        nextFireAtPerf: 0,
        nativeId: null,
    };
    managedIntervals.set(intervalId, entry);
    if (!isPaused) {
        scheduleManagedInterval(entry);
    }
    return intervalId;
};

window.clearTimeout = function(timeoutId) {
    const managed = managedTimeouts.get(timeoutId);
    if (managed) {
        if (managed.nativeId !== null) {
            originalClearTimeout(managed.nativeId);
        }
        managedTimeouts.delete(timeoutId);
        return;
    }
    return originalClearTimeout(timeoutId);
};

window.clearInterval = function(intervalId) {
    const managed = managedIntervals.get(intervalId);
    if (managed) {
        if (managed.nativeId !== null) {
            originalClearTimeout(managed.nativeId);
        }
        managedIntervals.delete(intervalId);
        return;
    }
    return originalClearInterval(intervalId);
};

window.__pauseGame = function() {
    if (isPaused) return;
    isPaused = true;
    pauseStartRealPerf = originalPerfNow();
    pauseScaledDate = scaledDateNow(originalDateNow());
    pauseScaledPerf = scaledPerfNow(pauseStartRealPerf);
    managedTimeouts.forEach((entry) => {
        if (entry.nativeId === null) return;
        originalClearTimeout(entry.nativeId);
        entry.nativeId = null;
        entry.remainingMs = Math.max(0, entry.nextFireAtPerf - pauseStartRealPerf);
    });
    managedIntervals.forEach((entry) => {
        if (entry.nativeId === null) return;
        originalClearTimeout(entry.nativeId);
        entry.nativeId = null;
        entry.remainingMs = Math.max(0, entry.nextFireAtPerf - pauseStartRealPerf);
    });
    setCssAnimationPaused(true);
    console.log('[SpeedControl] Game PAUSED');
};

window.__resumeGame = function() {
    if (!isPaused) return;
    const pauseDuration = originalPerfNow() - pauseStartRealPerf;
    totalPausedReal += pauseDuration;
    isPaused = false;
    setCssAnimationPaused(false);
    console.log('[SpeedControl] Game RESUMED after ' + pauseDuration + 'ms pause');

    const callbacks = pendingRAFCallbacks.splice(0);
    callbacks.forEach(({ id, callback }) => {
        scheduleRAF(id, callback);
    });

    managedTimeouts.forEach((entry) => {
        if (entry.nativeId !== null) return;
        scheduleManagedTimeout(entry);
    });
    managedIntervals.forEach((entry) => {
        if (entry.nativeId !== null) return;
        scheduleManagedInterval(entry);
    });
};

window.__setGameSpeed = function(multiplier) {
    const normalized = normalizeSpeed(multiplier);
    if (!normalized) {
        console.warn('[SpeedControl] Invalid speed multiplier, using pause instead');
        window.__pauseGame();
        return;
    }
    speedMultiplier = normalized;
    window.__gameSpeedMultiplier__ = speedMultiplier;
    console.log('[SpeedControl] Speed set to ' + speedMultiplier + 'x');
};

window.__getGameSpeedState = function() {
    const accountingRealPerfNow = isPaused ? pauseStartRealPerf : originalPerfNow();
    return {
        isPaused: isPaused,
        speedMultiplier: speedMultiplier,
        totalPausedTime: totalPausedReal,
        activeRealTimeMs: Math.max(
            0,
            accountingRealPerfNow - startPerfNow - totalPausedReal
        ),
        gameplayTimeMs: Math.max(0, currentScaledPerfNow() - startPerfNow),
        pendingCallbacks: pendingRAFCallbacks.length,
        pendingTimeouts: managedTimeouts.size,
        pendingIntervals: managedIntervals.size
    };
};

window.__isGamePaused = function() {
    return isPaused;
};

console.log('[SpeedControl] Dynamic speed control installed with initial speed: ' + speedMultiplier + 'x');
        })();
