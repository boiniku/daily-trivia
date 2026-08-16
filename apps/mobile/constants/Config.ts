import Constants from 'expo-constants';

export type AppEnvironment = 'development' | 'staging' | 'production';

const rawAppEnvironment = process.env.EXPO_PUBLIC_APP_ENV;
const appEnvironment: AppEnvironment =
    rawAppEnvironment === 'production' || rawAppEnvironment === 'staging' || rawAppEnvironment === 'development'
        ? rawAppEnvironment
        : (__DEV__ ? 'development' : 'production');

const productionBackendUrl = 'https://daily-trivia-e7ge.onrender.com';
const localBackendUrl = 'http://127.0.0.1:8000';
const configuredBackendUrl = process.env.EXPO_PUBLIC_BACKEND_URL?.trim().replace(/\/+$/, '');

if (appEnvironment !== 'production' && configuredBackendUrl === productionBackendUrl) {
    throw new Error('Safety check: a non-production build cannot use the production backend.');
}

if (appEnvironment === 'production' && configuredBackendUrl && configuredBackendUrl !== productionBackendUrl) {
    throw new Error('Safety check: a production build cannot use a non-production backend.');
}

export const Config = {
    APP_ENV: appEnvironment,
    IS_PRODUCTION: appEnvironment === 'production',
    // Available in development/staging unless explicitly disabled. Production
    // builds can never expose the virtual-location test controls.
    LOCATION_TESTING_ENABLED:
        appEnvironment !== 'production' && process.env.EXPO_PUBLIC_ENABLE_LOCATION_TESTING !== 'false',
    // Production is the only environment allowed to fall back to the production API.
    // Development intentionally falls back to localhost so an incomplete test setup
    // cannot accidentally write to production.
    BACKEND_URL: configuredBackendUrl || (appEnvironment === 'production' ? productionBackendUrl : localBackendUrl),
    API_VERSION: process.env.EXPO_PUBLIC_API_VERSION || '1',
    TRIVIA_IMAGE_R2_BASE_URL: process.env.EXPO_PUBLIC_TRIVIA_IMAGE_R2_BASE_URL || '',
    APP_VERSION: Constants.expoConfig?.version || '0.0.0',

    // API Keys (loaded from env or fallback)
    REVENUECAT_IOS_KEY: process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY || '',
    REVENUECAT_ANDROID_KEY: process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY || '',

    // AdMob Unit IDs
    // Production IDs must be set via .env; fallback is always test IDs
    BANNER_ID_IOS: process.env.EXPO_PUBLIC_ADMOB_BANNER_ID_IOS || 'ca-app-pub-3940256099942544/2934735716', // Test ID
    BANNER_ID_ANDROID: process.env.EXPO_PUBLIC_ADMOB_BANNER_ID_ANDROID || 'ca-app-pub-3940256099942544/6300978111', // Test ID
    INTERSTITIAL_ID_IOS: process.env.EXPO_PUBLIC_ADMOB_INTERSTITIAL_ID_IOS || 'ca-app-pub-3940256099942544/4411468910', // Test ID
    INTERSTITIAL_ID_ANDROID: process.env.EXPO_PUBLIC_ADMOB_INTERSTITIAL_ID_ANDROID || 'ca-app-pub-3940256099942544/1033173712', // Test ID
    REWARDED_ID_IOS: process.env.EXPO_PUBLIC_ADMOB_REWARDED_ID_IOS || 'ca-app-pub-3940256099942544/1712485313', // Test ID
    REWARDED_ID_ANDROID: process.env.EXPO_PUBLIC_ADMOB_REWARDED_ID_ANDROID || 'ca-app-pub-3940256099942544/5224354917', // Test ID


};

// Helper function if we need dynamic logic later
export const getBackendUrl = () => {
    return Config.BACKEND_URL;
};
