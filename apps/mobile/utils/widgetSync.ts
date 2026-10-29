import DefaultPreference from 'react-native-default-preference';
import { Platform } from 'react-native';
import { getAuth, getIdToken } from '@react-native-firebase/auth';
import { getIsWidgetInstalled, reloadAllTimelines } from '../modules/widget-control';
import { Config } from '../constants/Config';
import { fetchWithToken } from './apiClient';

const APP_GROUP_IDENTIFIER = 'group.com.dailytrivia.app';
const widgetRequests = new Map<string, Promise<boolean>>();
const TOKEN_TIMEOUT_MS = 5000;
let widgetWriteQueue: Promise<unknown> = Promise.resolve();
const serializeWidgetWrite = <T,>(operation: () => Promise<T>): Promise<T> => {
    const pending = widgetWriteQueue.catch(() => undefined).then(operation);
    widgetWriteQueue = pending.catch(() => undefined);
    return pending;
};

const readWidgetToken = async (user: NonNullable<ReturnType<typeof getAuth>['currentUser']>): Promise<string | undefined> => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
        return await Promise.race([
            getIdToken(user, false),
            new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Widget token request timed out')), TOKEN_TIMEOUT_MS); }),
        ]);
    } catch (error) {
        console.warn('Could not refresh widget authentication:', error);
        return undefined;
    } finally {
        if (timer) clearTimeout(timer);
    }
};

async function prepareWidgetIdentity(userId: string): Promise<boolean> {
    if (Platform.OS !== 'ios' || !userId || getAuth().currentUser?.uid !== userId) return false;
    const currentUser = getAuth().currentUser!;
    const token = await readWidgetToken(currentUser);
    if (getAuth().currentUser?.uid !== userId) return false;
    await DefaultPreference.setName(APP_GROUP_IDENTIFIER);
    if (getAuth().currentUser?.uid !== userId) return false;
    const previousId = await DefaultPreference.get('user_id');
    if (getAuth().currentUser?.uid !== userId) return false;
    if (previousId !== userId) {
        await DefaultPreference.set('daily_trivia', '[]');
        if (getAuth().currentUser?.uid !== userId) return false;
        await DefaultPreference.set('firebase_token', '');
        if (getAuth().currentUser?.uid !== userId) return false;
    }
    await DefaultPreference.set('user_id', userId);
    if (getAuth().currentUser?.uid !== userId) return false;
    if (token) await DefaultPreference.set('firebase_token', token);
    return getAuth().currentUser?.uid === userId;
}

/** Prime credentials even when Home has no cards or a network request fails. */
export const syncWidgetIdentity = (userId: string): Promise<boolean> => serializeWidgetWrite(async () => {
    try {
        if (!await prepareWidgetIdentity(userId)) return false;
        reloadAllTimelines();
        return true;
    } catch (error) {
        console.error('Failed to prepare widget authentication:', error);
        return false;
    }
});

export const clearSignedOutWidgetIdentity = (): Promise<void> => serializeWidgetWrite(async () => {
    if (Platform.OS !== 'ios' || getAuth().currentUser) return;
    await DefaultPreference.setName(APP_GROUP_IDENTIFIER);
    for (const [key, value] of [['user_id', ''], ['firebase_token', ''], ['daily_trivia', '[]']]) {
        if (getAuth().currentUser) return;
        await DefaultPreference.set(key, value);
    }
    if (!getAuth().currentUser) reloadAllTimelines();
});

const getEffectiveDate = () => {
    const now = new Date();
    now.setHours(now.getHours() - 2);
    return now.getFullYear() + '-' +
        String(now.getMonth() + 1).padStart(2, '0') + '-' +
        String(now.getDate()).padStart(2, '0');
};

// Cache preparation does not mark trivia as read. An installed widget, or a
// card swipe in the app, must explicitly cause history registration.
export const syncTriviaToWidget = (trivias: any[], userId?: string, date = getEffectiveDate()): Promise<boolean> => serializeWidgetWrite(async () => {
    if (Platform.OS !== 'ios' || !userId || getAuth().currentUser?.uid !== userId) return false;
    const batch = trivias.slice(0, 3);
    if (!batch.length || batch.some(item => !item || !Number.isInteger(item.id) || item.id <= 0 || typeof item.title !== 'string' || typeof item.content !== 'string')) return false;

    try {
        if (!await prepareWidgetIdentity(userId)) return false;

        // Keep the batch's logical date, including when a request crosses 2 AM.
        const widgetData = batch.map(t => ({
            id: t.id ?? 0,
            title: t.title,
            content: t.content,
            date
        }));

        // 4. Save to UserDefaults
        if (getAuth().currentUser?.uid !== userId) return false;
        await DefaultPreference.set('daily_trivia', JSON.stringify(widgetData));
        if (getAuth().currentUser?.uid !== userId) return false;
        // Saving UserDefaults does not tell an already visible widget to reload.
        reloadAllTimelines();
        return true;
    } catch (error) {
        console.error('Failed to sync widget data:', error);
        return false;
    }
});

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
        return await syncTriviaToWidget(data, userId, date);
    })();

    widgetRequests.set(key, request);
    try {
        return await request;
    } finally {
        if (widgetRequests.get(key) === request) widgetRequests.delete(key);
    }
}
