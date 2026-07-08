import * as Location from 'expo-location';
import { Coordinates } from '../models/TriviaSpot';

export type TriviaLocationStatus = 'unknown' | 'granted' | 'denied';

export const TriviaLocationManager = {
    async requestForegroundPermission(): Promise<TriviaLocationStatus> {
        const current = await Location.getForegroundPermissionsAsync();
        if (current.status === Location.PermissionStatus.GRANTED) return 'granted';

        const requested = await Location.requestForegroundPermissionsAsync();
        return requested.status === Location.PermissionStatus.GRANTED ? 'granted' : 'denied';
    },

    async getCurrentLocation(): Promise<Coordinates | null> {
        const position = await Location.getCurrentPositionAsync({
            accuracy: Location.Accuracy.Balanced,
        });

        return {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
        };
    },

    async watchLocation(onChange: (location: Coordinates) => void) {
        return Location.watchPositionAsync(
            {
                accuracy: Location.Accuracy.Balanced,
                distanceInterval: 25,
                timeInterval: 15000,
            },
            (position) => {
                onChange({
                    latitude: position.coords.latitude,
                    longitude: position.coords.longitude,
                });
            }
        );
    },
};
