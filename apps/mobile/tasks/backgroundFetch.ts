import * as BackgroundFetch from 'expo-background-fetch';
import * as TaskManager from 'expo-task-manager';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { syncInstalledWidgetTrivia } from '../utils/widgetSync';

const BACKGROUND_FETCH_TASK = 'BACKGROUND_TRIVIA_FETCH';

// Define the task — wrapped in try-catch to prevent crash at import time
// if native TaskManager module isn't ready
try {
    TaskManager.defineTask(BACKGROUND_FETCH_TASK, async () => {
        try {
            const now = new Date();
            console.log(`[BackgroundFetch] Task running at: ${now.toISOString()}`);

            // Maximum 30 seconds to execute
            // 1. Get User ID from Storage
            const userId = await AsyncStorage.getItem('user_id');
            if (!userId) {
                console.log('[BackgroundFetch] No user ID, skipping fetch.');
                return BackgroundFetch.BackgroundFetchResult.NoData;
            }

            // Only an installed widget can register the daily batch as read.
            // The app's regular fetch prepares cards without adding history.
            const synced = await syncInstalledWidgetTrivia(userId);
            if (!synced) {
                console.log('[BackgroundFetch] No installed widget or no new data.');
                return BackgroundFetch.BackgroundFetchResult.NoData;
            }
            console.log('[BackgroundFetch] Widget synced successfully.');

            return BackgroundFetch.BackgroundFetchResult.NewData;
        } catch (error) {
            console.error('[BackgroundFetch] Error:', error);
            return BackgroundFetch.BackgroundFetchResult.Failed;
        }
    });
} catch (e) {
    console.warn('[BackgroundFetch] Failed to define task (native module may not be ready):', e);
}

// Register the task
export async function registerBackgroundFetchAsync() {
    try {
        console.log('[BackgroundFetch] Registering task...');
        await BackgroundFetch.registerTaskAsync(BACKGROUND_FETCH_TASK, {
            minimumInterval: 60 * 60 * 6, // 6 hours (minimum allowed by iOS is usually 15-20 min, but for battery let's say 6h. Widget requests updates on its own too)
            stopOnTerminate: false, // Keep running after app close
            startOnBoot: true, // Android only
        });
        console.log('[BackgroundFetch] Task registered');
    } catch (err) {
        console.log('[BackgroundFetch] Register failed:', err);
    }
}
