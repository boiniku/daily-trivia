import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import { TriviaSpot } from '../models/TriviaSpot';

Notifications.setNotificationHandler({
    handleNotification: async () => ({
        shouldShowAlert: true,
        shouldPlaySound: false,
        shouldSetBadge: false,
        shouldShowBanner: true,
        shouldShowList: true,
    }),
});

export const TriviaNotificationManager = {
    async requestPermission() {
        const current = await Notifications.getPermissionsAsync();
        if (current.granted) return true;

        const requested = await Notifications.requestPermissionsAsync();
        return requested.granted;
    },

    async notifyUnlockedSpot(spot: TriviaSpot) {
        const permissions = await Notifications.getPermissionsAsync();
        if (!permissions.granted) return;

        if (Platform.OS === 'android') {
            await Notifications.setNotificationChannelAsync('trivia-map', {
                name: '雑学MAP',
                importance: Notifications.AndroidImportance.DEFAULT,
            });
        }

        await Notifications.scheduleNotificationAsync({
            content: {
                title: `「${spot.title}」が解放されました！`,
                body: 'この場所ならではの雑学を読めるようになりました。',
            },
            trigger: null,
        });
    },
};
