import * as Notifications from 'expo-notifications';
import { AppState, Platform } from 'react-native';
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
    async hasPermission() {
        const permission = await Notifications.getPermissionsAsync();
        return permission.granted;
    },

    async requestPermission() {
        const current = await Notifications.getPermissionsAsync();
        if (current.granted) return true;

        const requested = await Notifications.requestPermissionsAsync();
        return requested.granted;
    },

    async notifyUnlockedSpots(spots: TriviaSpot[]) {
        if (spots.length === 0 || AppState.currentState === 'active') return;

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
                title: spots.length === 1
                    ? `「${spots[0].title}」が解放されました！`
                    : `${spots.length}件の雑学が解放されました！`,
                body: spots.length === 1
                    ? 'この場所ならではの雑学を読めるようになりました。'
                    : '近くで見つけた新しい雑学を確認してみましょう。',
                data: {
                    type: 'trivia-map-unlock',
                    spotId: spots[0].id,
                },
            },
            trigger: null,
        });
    },

    async notifyUnlockedSpot(spot: TriviaSpot) {
        return this.notifyUnlockedSpots([spot]);
    },
};
