const assert = require('node:assert/strict');
const test = require('node:test');
const { validateStoreAds } = require('../scripts/verify-build-ads');
const app = require('../app.json').expo;
const profiles = require('../eas.json').build;
const env = {
  EXPO_PUBLIC_APP_ENV: 'production',
  EXPO_PUBLIC_ADMOB_BANNER_ID_IOS: 'ca-app-pub-4541342273103383/1111111111',
  EXPO_PUBLIC_ADMOB_INTERSTITIAL_ID_IOS: 'ca-app-pub-4541342273103383/2222222222',
  EXPO_PUBLIC_ADMOB_REWARDED_ID_IOS: 'ca-app-pub-4541342273103383/3333333333',
  EXPO_PUBLIC_REVENUECAT_IOS_API_KEY: 'appl_fixture',
};
const check = (overrides = {}, profile = profiles.production) => validateStoreAds({ app, profile, env: { ...env, ...overrides }, platform: 'ios' });

test('both store profiles use production advertising and update settings', () => {
  assert.deepEqual(check(), []);
  assert.deepEqual(check({}, profiles.testflight), []);
  assert.notEqual(profiles.preview.channel, 'staging');
});

test('missing ad IDs and Google sample IDs block a store build', () => {
  for (const value of [undefined, '', 'ca-app-pub-3940256099942544/2934735716']) {
    assert.ok(check({ EXPO_PUBLIC_ADMOB_BANNER_ID_IOS: value }).some(error => error.includes('BANNER_ID_IOS')));
  }
});

test('an ad unit belonging to another publisher blocks a store build', () => {
  assert.ok(check({ EXPO_PUBLIC_ADMOB_INTERSTITIAL_ID_IOS: 'ca-app-pub-1111111111111111/2222222222' }).some(error => error.includes('INTERSTITIAL_ID_IOS')));
});

test('preview environment, staging channel and sandbox SDK keys cannot enter a store build', () => {
  assert.ok(check({ EXPO_PUBLIC_APP_ENV: 'staging' }).length);
  assert.ok(check({}, { ...profiles.production, environment: 'preview' }).length);
  assert.ok(check({}, { ...profiles.production, channel: 'staging' }).length);
  assert.ok(check({ EXPO_PUBLIC_REVENUECAT_IOS_API_KEY: 'test_fixture' }).length);
});
