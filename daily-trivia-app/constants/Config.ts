import { Platform } from 'react-native';
import Constants from 'expo-constants';

export const Config = {
    // Backend URL
    // Use Render URL for production/testing on device
    // If you want to use local backend, change this to your local IP or localhost logic
    BACKEND_URL: 'https://daily-trivia-e7ge.onrender.com',

    // API Keys (loaded from env or fallback)
    REVENUECAT_IOS_KEY: process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY || '',
    REVENUECAT_ANDROID_KEY: process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY || '',

    // AdMob Unit IDs
    // Fallback to Test IDs if not set in env
    // Production IDs provided by user:
    BANNER_ID_IOS: process.env.EXPO_PUBLIC_ADMOB_BANNER_ID_IOS || 'ca-app-pub-4541342273103383/2981957640',
    BANNER_ID_ANDROID: process.env.EXPO_PUBLIC_ADMOB_BANNER_ID_ANDROID || 'ca-app-pub-3940256099942544/6300978111', // Test ID

    REWARDED_ID_IOS: process.env.EXPO_PUBLIC_ADMOB_REWARDED_ID_IOS || 'ca-app-pub-4541342273103383/2404099493',
    REWARDED_ID_ANDROID: process.env.EXPO_PUBLIC_ADMOB_REWARDED_ID_ANDROID || 'ca-app-pub-3940256099942544/5224354917', // Test ID
};

// Helper function if we need dynamic logic later
export const getBackendUrl = () => {
    return Config.BACKEND_URL;
};
