import DefaultPreference from 'react-native-default-preference';
import { Platform } from 'react-native';

const APP_GROUP_IDENTIFIER = 'group.com.dailytrivia.app';

export const syncTriviaToWidget = async (trivias: any[], userId?: string) => {
    if (Platform.OS !== 'ios') return;

    try {
        // 1. Configure the App Group
        await DefaultPreference.setName(APP_GROUP_IDENTIFIER);

        // 2. Save User ID for widget API calls
        if (userId) {
            await DefaultPreference.set('user_id', userId);
        }

        // 3. Format data for Swift
        // Swift expects: [{ title: string, content: string, date: string }]
        const today = new Date().toISOString().split('T')[0];
        const widgetData = trivias.slice(0, 3).map(t => ({
            title: t.title,
            content: t.content,
            date: today
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
