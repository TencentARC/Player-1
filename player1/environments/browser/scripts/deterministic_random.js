(function() {
    'use strict';

    function mulberry32(seed) {
        return function() {
            seed |= 0;
            seed = seed + 0x6D2B79F5 | 0;
            var t = Math.imul(seed ^ seed >>> 15, 1 | seed);
            t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
            return ((t ^ t >>> 14) >>> 0) / 4294967296;
        };
    }

    const originalRandom = Math.random;
    const SEED = __RANDOM_SEED__;
    const seededRandom = mulberry32(SEED);

    Math.random = seededRandom;

    window.__getRandomSeed = function() { return SEED; };
    window.__resetRandomSeed = function() {
        Math.random = mulberry32(SEED);
        console.log('[DeterministicRandom] Reset to seed:', SEED);
    };
    window.__restoreOriginalRandom = function() {
        Math.random = originalRandom;
        console.log('[DeterministicRandom] Restored original Math.random');
    };

    console.log('[DeterministicRandom] Math.random seeded with:', SEED);
})();
