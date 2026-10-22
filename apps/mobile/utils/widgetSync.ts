import DefaultPreference from 'react-native-default-preference';
import { Platform } from 'react-native';
import { getAuth, getIdToken } from '@react-native-firebase/auth';
import { getIsWidgetInstalled } from '../modules/widget-control';
import { Config } from '../constants/Config';
import { fetchWithToken } from './apiClient';

const APP_GROUP_IDENTIFIER = 'group.com.dailytrivia.app';
const widgetRequests = new Map<string, Promise<boolean>>();

const getEffectiveDate = () => {
    const now = new Date();
    now.setHours(now.getHours() - 2);
    return now.getFullYear() + '-' +
        String(now.getMonth() + 1).padStart(2, '0') + '-' +
        String(now.getDate()).padStart(2, '0');
};

// Cache preparation does not mark trivia as read. An installed widget, or a
// card swipe in the app, must explicitly cause history registration.
export const syncTriviaToWidget = async (trivias: any[], userId?: string, date = getEffectiveDate()) => {
    if (Platform.OS !== 'ios') return;
    if (userId && getAuth().currentUser?.uid !== userId) return;

    try {
        const currentUser = getAuth().currentUser;
        let firebaseToken: string | undefined;
        if (currentUser) {
            try {
                firebaseToken = await getIdToken(currentUser, false);
            } catch (e) {
                console.error('Failed to get token for widget sync:', e);
            }
        }
        // Token refresh can outlive a sign-out or an account switch.
        if (userId && getAuth().currentUser?.uid !== userId) return;
        await DefaultPreference.setName(APP_GROUP_IDENTIFIER);
        if (userId && getAuth().currentUser?.uid !== userId) return;
        if (userId) await DefaultPreference.set('user_id', userId);
        if (firebaseToken && (!userId || getAuth().currentUser?.uid === userId)) {
            await DefaultPreference.set('firebase_token', firebaseToken);
        }

        // Keep the batch's logical date, including when a request crosses 2 AM.
        const widgetData = trivias.slice(0, 3).map(t => ({
            id: t.id ?? 0,
            title: t.title,
            content: t.content,
            date
        }));

        // 4. Save to UserDefaults
        if (userId && getAuth().currentUser?.uid !== userId) return;
        await DefaultPreference.set('daily_trivia', JSON.stringify(widgetData));

        console.log('✅ Widget data synced!', widgetData);

        // The widget consumes the cache on its next timeline update.
    } catch (error) {
        console.error('Failed to sync widget data:', error);
    }
};

export async function syncInstalledWidgetTrivia(userId: string, date = getEffectiveDate()): Promise<boolean> {
    if (Platform.OS !== 'ios' || !userId || date !== getEffectiveDate()) return false;
    if (getAuth().currentUser?.uid !== userId) return false;

    // Query the system each time; a persisted flag could remain true after the
    // user removes the widget without opening the app.
    try {
        if (!await getIsWidgetInstalled()) return false;
    } catch {
        return false;
    }
    if (getAuth().currentUser?.uid !== userId || date !== getEffectiveDate()) return false;

    const key = `${userId}:${date}`;
    const pending = widgetRequests.get(key);
    if (pending) return pending;

    const request = (async () => {
        const url = `${Config.BACKEND_URL}/trivia/widget?limit=3&date=${date}&user_id=${encodeURIComponent(userId)}&widget_installed=true`;
        const response = await fetchWithToken(url, { headers: { 'Cache-Control': 'no-cache' } }, userId);
        if (!response.ok) throw new Error(`Widget trivia request failed: ${response.status}`);
        const data = await response.json();
        if (!Array.isArray(data) || data.some(item =>
            !item || !Number.isInteger(item.id) || item.id <= 0 ||
            typeof item.title !== 'string' || typeof item.content !== 'string'
        )) throw new Error('Invalid widget trivia response');
        if (data.length === 0) return false;
        if (getAuth().currentUser?.uid !== userId) return false;
        await syncTriviaToWidget(data, userId, date);
        return true;
    })();

    widgetRequests.set(key, request);
    try {
        return await request;
    } finally {
        if (widgetRequests.get(key) === request) widgetRequests.delete(key);
    }
}
