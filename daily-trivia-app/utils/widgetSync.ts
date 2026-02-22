import DefaultPreference from 'react-native-default-preference';
import { Platform } from 'react-native';
import auth from '@react-native-firebase/auth';

const APP_GROUP_IDENTIFIER = 'group.com.dailytrivia.app';

export const syncTriviaToWidget = async (trivias: any[], userId?: string) => {
    if (Platform.OS !== 'ios') return;

    try {
        // 1. Configure the App Group
        await DefaultPreference.setName(APP_GROUP_IDENTIFIER);

        // 2. Save User ID and Token for widget API calls
        if (userId) {
            await DefaultPreference.set('user_id', userId);
        }

        // Extract Firebase token
        const currentUser = auth().currentUser;
        if (currentUser) {
            try {
                const idToken = await currentUser.getIdToken(false);
                if (idToken) {
                    await DefaultPreference.set('firebase_token', idToken);
                }
            } catch (e) {
                console.error('Failed to get token for widget sync:', e);
            }
        }

        // 3. Format data for Swift
        // Swift expects: [{ title: string, content: string, date: string }]
        // Use local date string (YYYY-MM-DD) respecting the 2:00 AM boundary
        const now = new Date();
        now.setHours(now.getHours() - 2);
        const todayLocal = now.getFullYear() + '-' +
            String(now.getMonth() + 1).padStart(2, '0') + '-' +
            String(now.getDate()).padStart(2, '0');

        const widgetData = trivias.slice(0, 3).map(t => ({
            id: t.id ?? 0,
            title: t.title,
            content: t.content,
            date: todayLocal
        }));

        // 4. Save to UserDefaults
        await DefaultPreference.set('daily_trivia', JSON.stringify(widgetData));

        console.log('✅ Widget data synced!', widgetData);

        // Note: To force reload the widget timeline immediately, 
        // we would need a native module exposure of `WidgetCenter.shared.reloadAllTimelines()`.
        // For now, the widget will update on its next scheduled timeline policy or system event.
    } catch (error) {
        console.error('Failed to sync widget data:', error);
    }
};
