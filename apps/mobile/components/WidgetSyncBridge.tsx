import { useEffect } from 'react';
import { AppState, Platform } from 'react-native';
import { getAuth, onIdTokenChanged } from '@react-native-firebase/auth';
import { useAuth } from '../contexts/AuthContext';
import { clearSignedOutWidgetIdentity, syncInstalledWidgetTrivia, syncWidgetIdentity } from '../utils/widgetSync';

/** Widget initialization must not depend on Home successfully fetching cards. */
export function WidgetSyncBridge() {
    const { userId, loading } = useAuth();
    useEffect(() => {
        if (loading || Platform.OS !== 'ios') return;
        if (!userId) {
            void clearSignedOutWidgetIdentity().catch(error => console.warn('Widget sign-out cleanup failed:', error));
            return;
        }
        let disposed = false;
        let pending: Promise<void> | null = null;
        const sync = () => {
            if (disposed || pending) return;
            pending = (async () => {
                if (!await syncWidgetIdentity(userId) || disposed) return;
                await syncInstalledWidgetTrivia(userId);
            })().catch(error => console.warn('Widget startup sync failed:', error))
                .finally(() => { pending = null; });
        };
        sync();
        const subscription = AppState.addEventListener('change', state => { if (state === 'active') sync(); });
        const unsubscribe = onIdTokenChanged(getAuth(), user => { if (user?.uid === userId) sync(); });
        return () => { disposed = true; subscription.remove(); unsubscribe(); };
    }, [loading, userId]);
    return null;
}
