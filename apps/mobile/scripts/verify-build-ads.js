const fs = require('node:fs');
const path = require('node:path');

function validateStoreAds({ app, profile, env, platform }) {
  const errors = [];
  if (profile.environment !== 'production') errors.push('store builds must use the production EAS environment');
  if (profile.env?.EXPO_PUBLIC_APP_ENV !== 'production') errors.push('store builds must use EXPO_PUBLIC_APP_ENV=production');
  if (profile.channel !== 'production') errors.push('store builds must use the production update channel');
  if (env.EXPO_PUBLIC_APP_ENV !== 'production') errors.push('the build environment must contain EXPO_PUBLIC_APP_ENV=production');
  if (!['ios', 'android'].includes(platform)) errors.push('the build platform must be ios or android');

  const plugin = app.plugins.find(entry => Array.isArray(entry) && entry[0] === 'react-native-google-mobile-ads');
  const appId = plugin?.[1]?.[platform === 'ios' ? 'iosAppId' : 'androidAppId'];
  const publisher = /^(ca-app-pub-\d{16})~\d{10}$/.exec(appId || '')?.[1];
  if (!publisher || publisher === 'ca-app-pub-3940256099942544') errors.push('a production AdMob app ID is required');
  const suffix = platform.toUpperCase();
  for (const format of ['BANNER', 'INTERSTITIAL', 'REWARDED']) {
    const name = `EXPO_PUBLIC_ADMOB_${format}_ID_${suffix}`;
    const value = env[name];
    if (!/^ca-app-pub-\d{16}\/\d{10}$/.test(value || '') || !publisher || !value.startsWith(publisher + '/') || value.startsWith('ca-app-pub-3940256099942544/')) {
      errors.push(`${name}: a production ad unit for this app's publisher is required`);
    }
  }
  const purchasesKey = `EXPO_PUBLIC_REVENUECAT_${suffix}_API_KEY`;
  const prefix = platform === 'ios' ? 'appl_' : 'goog_';
  if (!env[purchasesKey]?.startsWith(prefix)) errors.push(`${purchasesKey}: a store SDK key is required`);
  return errors;
}

if (require.main === module) {
  const root = path.join(__dirname, '..');
  const app = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8')).expo;
  const eas = JSON.parse(fs.readFileSync(path.join(root, 'eas.json'), 'utf8'));
  const name = process.env.EAS_BUILD_PROFILE || 'production';
  const profile = eas.build[name];
  if (!profile) throw new Error(`Unknown EAS build profile: ${name}`);
  if (profile.distribution === 'store' || name === 'production' || name === 'testflight') {
    const errors = validateStoreAds({ app, profile, env: process.env, platform: process.env.EAS_BUILD_PLATFORM || 'ios' });
    if (errors.length) {
      console.error('Store build configuration is invalid:\n- ' + errors.join('\n- '));
      process.exit(1);
    }
    console.log('Store build verified: production environment, update channel, advertising IDs and purchases key.');
  } else {
    console.log(`Advertising release checks skipped for ${name}.`);
  }
}

module.exports = { validateStoreAds };
