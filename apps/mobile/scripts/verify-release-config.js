const fs = require('node:fs');
const path = require('node:path');

const EXPECTED_VERSION = process.env.RELEASE_VERSION || '1.1.0';
const EXPECTED_PRODUCTION_API = 'https://daily-trivia-e7ge.onrender.com';

const readJson = (relativePath) => JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', relativePath), 'utf8')
);

const appJson = readJson('app.json');
const easJson = readJson('eas.json');
const packageJson = readJson('package.json');
const app = appJson.expo;
const production = easJson.build?.production;
const pluginOptions = (name) => {
  const entry = app?.plugins?.find((plugin) => (
    Array.isArray(plugin) ? plugin[0] === name : plugin === name
  ));
  return Array.isArray(entry) ? entry[1] || {} : {};
};

const errors = [];
const expectEqual = (label, actual, expected) => {
  if (actual !== expected) errors.push(`${label}: expected ${expected}, got ${actual}`);
};

expectEqual('app version', app?.version, EXPECTED_VERSION);
expectEqual('package version', packageJson.version, EXPECTED_VERSION);
expectEqual('iOS bundle identifier', app?.ios?.bundleIdentifier, 'com.dailytrivia.app');
expectEqual('EAS production environment', production?.environment, 'production');
expectEqual('production app environment', production?.env?.EXPO_PUBLIC_APP_ENV, 'production');
expectEqual('production API', production?.env?.EXPO_PUBLIC_BACKEND_URL, EXPECTED_PRODUCTION_API);
expectEqual('production API version', production?.env?.EXPO_PUBLIC_API_VERSION, '1');
expectEqual('production channel', production?.channel, 'production');
expectEqual('runtime version policy', app?.runtimeVersion?.policy, 'appVersion');

const imagePicker = pluginOptions('expo-image-picker');
expectEqual('image picker camera permission', imagePicker.cameraPermission, false);
expectEqual('image picker microphone permission', imagePicker.microphonePermission, false);

const location = pluginOptions('expo-location');
expectEqual('legacy iOS location permission', location.locationAlwaysPermission, false);
expectEqual(
  'nonstandard notification usage description',
  app?.ios?.infoPlist?.NSUserNotificationUsageDescription,
  undefined
);

const purposeStrings = {
  ...app?.ios?.infoPlist,
  NSPhotoLibraryUsageDescription: imagePicker.photosPermission,
  NSLocationWhenInUseUsageDescription: location.locationWhenInUsePermission,
  NSLocationAlwaysAndWhenInUseUsageDescription: location.locationAlwaysAndWhenInUsePermission,
};
const placeholderPattern = /\b(?:allow|needs?|would like).{0,40}\baccess\b|\baccess your\b/i;
Object.entries(purposeStrings)
  .filter(([key, value]) => key.endsWith('UsageDescription') && typeof value === 'string')
  .forEach(([key, value]) => {
    if (!value.trim()) errors.push(`${key}: purpose string must not be empty`);
    if (placeholderPattern.test(value)) errors.push(`${key}: placeholder-like purpose string: ${value}`);
  });

if (!/^\d+$/.test(String(app?.ios?.buildNumber || ''))) {
  errors.push(`iOS build number must be numeric, got ${app?.ios?.buildNumber}`);
}

if (errors.length) {
  console.error('Release configuration is invalid:\n- ' + errors.join('\n- '));
  process.exit(1);
}

console.log(`Release configuration OK: iOS ${app.version} (${app.ios.buildNumber}) -> ${EXPECTED_PRODUCTION_API}`);
