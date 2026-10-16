const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const load = require('./loadTypescript.cjs');
const profiles = require('../eas.json').build;
const production = 'https://daily-trivia-e7ge.onrender.com';

function config(environment, backend) {
    const previous = { environment: process.env.EXPO_PUBLIC_APP_ENV, backend: process.env.EXPO_PUBLIC_BACKEND_URL, dev: global.__DEV__ };
    process.env.EXPO_PUBLIC_APP_ENV = environment;
    if (backend === undefined) delete process.env.EXPO_PUBLIC_BACKEND_URL;
    else process.env.EXPO_PUBLIC_BACKEND_URL = backend;
    global.__DEV__ = environment !== 'production';
    try {
        return load(path.resolve(__dirname, '../constants/Config.ts'), {
            'expo-constants': { default: { expoConfig: { version: '1.1.2' } } },
        }).Config;
    } finally {
        for (const [key, value] of [['EXPO_PUBLIC_APP_ENV', previous.environment], ['EXPO_PUBLIC_BACKEND_URL', previous.backend]]) {
            if (value === undefined) delete process.env[key]; else process.env[key] = value;
        }
        if (previous.dev === undefined) delete global.__DEV__; else global.__DEV__ = previous.dev;
    }
}

test('development and preview builds share production data while retaining their build mode', () => {
    for (const name of ['development', 'preview', 'testflight', 'production']) {
        const profile = profiles[name];
        assert.equal(profile.env.EXPO_PUBLIC_BACKEND_URL, production);
        const actual = config(profile.env.EXPO_PUBLIC_APP_ENV, profile.env.EXPO_PUBLIC_BACKEND_URL);
        assert.equal(actual.BACKEND_URL, production);
        assert.equal(actual.IS_PRODUCTION, name === 'production');
    }
});

test('a missing development endpoint keeps the local fallback', () => {
    assert.equal(config('development').BACKEND_URL, 'http://127.0.0.1:8000');
});

test('production builds reject a test API endpoint', () => {
    assert.throws(() => config('production', 'https://example.test'), /production build/);
});
