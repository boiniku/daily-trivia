import { useEffect } from 'react';
import { AppState } from 'react-native';
import { useAuth } from '../contexts/AuthContext';
import { TriviaUnlockManager } from '../managers/TriviaUnlockManager';
import { TriviaGeofenceManager } from '../managers/TriviaGeofenceManager';

/** Syncs map unlocks after auth initialization even if the map tab is never opened. */
export const MapUnlockSyncBridge = () => {
    const { userId, loading } = useAuth();

    useEffect(() => {
        if (loading || !userId) return;

        const sync = async () => {
            try {
                await TriviaUnlockManager.syncUnlockedRecords(userId);
                await TriviaGeofenceManager.syncLatestRegistration();
            } catch (error) {
                console.error('Map unlock startup sync failed:', error);
            }
        };
        void sync();

        const subscription = AppState.addEventListener('change', (state) => {
            if (state === 'active') void sync();
        });
        const timer = setInterval(() => { if (AppState.currentState === 'active') void sync(); }, 60000);
        return () => { clearInterval(timer); subscription.remove(); };
    }, [loading, userId]);

    return null;
};
