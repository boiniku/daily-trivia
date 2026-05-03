import { Platform } from 'react-native';
import Constants from 'expo-constants';

export const Config = {
    // Backend URL
    // Use Render URL for production/testing on device
    // If you want to use local backend, change this to your local IP or localhost logic
    BACKEND_URL: 'https://daily-trivia-e7ge.onrender.com',
    TRIVIA_IMAGE_R2_BASE_URL: process.env.EXPO_PUBLIC_TRIVIA_IMAGE_R2_BASE_URL || '',
    APP_VERSION: '1.0.5',

    // API Keys (loaded from env or fallback)
    REVENUECAT_IOS_KEY: process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY || '',
    REVENUECAT_ANDROID_KEY: process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY || '',

    // AdMob Unit IDs
    // Production IDs must be set via .env; fallback is always test IDs
    BANNER_ID_IOS: process.env.EXPO_PUBLIC_ADMOB_BANNER_ID_IOS || 'ca-app-pub-3940256099942544/2934735716', // Test ID
    BANNER_ID_ANDROID: process.env.EXPO_PUBLIC_ADMOB_BANNER_ID_ANDROID || 'ca-app-pub-3940256099942544/6300978111', // Test ID
    INTERSTITIAL_ID_IOS: process.env.EXPO_PUBLIC_ADMOB_INTERSTITIAL_ID_IOS || 'ca-app-pub-3940256099942544/4411468910', // Test ID
    INTERSTITIAL_ID_ANDROID: process.env.EXPO_PUBLIC_ADMOB_INTERSTITIAL_ID_ANDROID || 'ca-app-pub-3940256099942544/1033173712', // Test ID


};

// Helper function if we need dynamic logic later
export const getBackendUrl = () => {
    return Config.BACKEND_URL;
};
