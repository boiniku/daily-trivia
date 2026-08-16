import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Location from 'expo-location';
import { Platform } from 'react-native';
import { getTriviaSpots } from '../data/triviaSpots';
import { Coordinates, TriviaSpot } from '../models/TriviaSpot';
import { TriviaLocationManager } from './TriviaLocationManager';
import { TriviaNotificationManager } from './TriviaNotificationManager';
import { TriviaSpotCache } from './TriviaSpotCache';
import { calculateDistanceMeters, TriviaUnlockManager } from './TriviaUnlockManager';

export const TRIVIA_GEOFENCE_TASK = 'TRIVIA_MAP_GEOFENCE_TASK_V1';

const ENABLED_STORAGE_KEY = 'triviaMapBackgroundNotificationsEnabled';
const REFRESH_REGION_ID = 'trivia-refresh-region';
const SPOT_REGION_PREFIX = 'trivia-spot:';
const MAX_SPOT_REGIONS = 19;
const MIN_REFRESH_RADIUS_METERS = 200;
const MAX_REFRESH_RADIUS_METERS = 3000;

export type TriviaGeofenceEnableResult =
    | 'enabled'
    | 'notification-denied'
    | 'foreground-location-denied'
    | 'background-location-denied'
    | 'unsupported';

export type TriviaGeofenceStatus =
    | 'off'
    | 'active'
    | 'notification-denied'
    | 'location-denied';

let refreshQueue: Promise<unknown> = Promise.resolve();

const runSerialized = async <T>(operation: () => Promise<T>): Promise<T> => {
    const previous = refreshQueue;
    let release: () => void = () => undefined;
    refreshQueue = new Promise<void>((resolve) => {
        release = resolve;
    });
    await previous.catch(() => undefined);
    try {
        return await operation();
    } finally {
        release();
    }
};

const boundaryDistance = (spot: TriviaSpot, location: Coordinates) => (
    calculateDistanceMeters(location, {
        latitude: spot.latitude,
        longitude: spot.longitude,
    }) - spot.unlockRadiusMeters
);

const clamp = (value: number, minimum: number, maximum: number) => (
    Math.min(maximum, Math.max(minimum, value))
);

const getRegions = async (spots: TriviaSpot[], location: Coordinates): Promise<Location.LocationRegion[]> => {
    const records = await TriviaUnlockManager.getUnlockedRecords();
    const lockedByDistance = spots
        .filter((spot) => !records[spot.id])
        .sort((a, b) => boundaryDistance(a, location) - boundaryDistance(b, location));
    const monitoredSpots = lockedByDistance.slice(0, MAX_SPOT_REGIONS);
    const firstExcludedSpot = lockedByDistance[MAX_SPOT_REGIONS];
    const firstExcludedBoundary = firstExcludedSpot
        ? boundaryDistance(firstExcludedSpot, location)
        : MAX_REFRESH_RADIUS_METERS * 2;
    const refreshRadius = clamp(
        Math.max(0, firstExcludedBoundary) / 2,
        MIN_REFRESH_RADIUS_METERS,
        MAX_REFRESH_RADIUS_METERS
    );

    const spotRegions = monitoredSpots.map((spot) => ({
            identifier: `${SPOT_REGION_PREFIX}${spot.id}`,
            latitude: spot.latitude,
            longitude: spot.longitude,
            radius: Math.max(1, spot.unlockRadiusMeters),
            notifyOnEnter: true,
            notifyOnExit: false,
        }));

    if (!firstExcludedSpot) return spotRegions;

    return [
        ...spotRegions,
        {
            identifier: REFRESH_REGION_ID,
            latitude: location.latitude,
            longitude: location.longitude,
            radius: refreshRadius,
            notifyOnEnter: false,
            notifyOnExit: true,
        },
    ];
};

const loadSpots = async () => {
    const cached = await TriviaSpotCache.read();
    if (cached.length > 0) return cached;
    return getTriviaSpots();
};

const registerFromLocation = async (spots: TriviaSpot[], location: Coordinates) => {
    const regions = await getRegions(spots, location);
    if (regions.length === 0) {
        if (await Location.hasStartedGeofencingAsync(TRIVIA_GEOFENCE_TASK)) {
            await Location.stopGeofencingAsync(TRIVIA_GEOFENCE_TASK);
        }
        return;
    }
    await Location.startGeofencingAsync(TRIVIA_GEOFENCE_TASK, regions);
};

export const TriviaGeofenceManager = {
    async isEnabled() {
        return (await AsyncStorage.getItem(ENABLED_STORAGE_KEY)) === 'true';
    },

    async enable(): Promise<TriviaGeofenceEnableResult> {
        if (Platform.OS !== 'ios') return 'unsupported';

        await AsyncStorage.setItem(ENABLED_STORAGE_KEY, 'true');

        const notificationsGranted = await TriviaNotificationManager.requestPermission();
        if (!notificationsGranted) return 'notification-denied';

        const foregroundStatus = await TriviaLocationManager.requestForegroundPermission();
        if (foregroundStatus !== 'granted') return 'foreground-location-denied';

        const backgroundStatus = await TriviaLocationManager.requestBackgroundPermission();
        if (backgroundStatus !== 'granted') return 'background-location-denied';

        await this.syncLatestRegistration();
        return 'enabled';
    },

    async getStatus(): Promise<TriviaGeofenceStatus> {
        if (!await this.isEnabled()) return 'off';
        if (!await TriviaNotificationManager.hasPermission()) return 'notification-denied';
        if (!await TriviaLocationManager.hasBackgroundPermission()) return 'location-denied';
        return 'active';
    },

    async disable() {
        await AsyncStorage.setItem(ENABLED_STORAGE_KEY, 'false');
        if (await Location.hasStartedGeofencingAsync(TRIVIA_GEOFENCE_TASK)) {
            await Location.stopGeofencingAsync(TRIVIA_GEOFENCE_TASK);
        }
    },

    async refreshRegistration(spots?: TriviaSpot[], location?: Coordinates) {
        return runSerialized(async () => {
            if (Platform.OS !== 'ios' || !await this.isEnabled()) return;
            if (!await TriviaLocationManager.hasBackgroundPermission()) return;

            const availableSpots = spots?.length ? spots : await loadSpots();
            if (availableSpots.length === 0) return;
            await TriviaSpotCache.save(availableSpots);

            const currentLocation = location ?? await TriviaLocationManager.getBackgroundLocation();
            if (!currentLocation) return;

            const newlyUnlocked = await TriviaUnlockManager.unlockNearbySpots(availableSpots, currentLocation);
            if (newlyUnlocked.length > 0) {
                const unlockedIds = new Set(newlyUnlocked.map((record) => record.id));
                const unlockedSpots = availableSpots.filter((spot) => unlockedIds.has(spot.id));
                await TriviaNotificationManager.notifyUnlockedSpots(unlockedSpots);
            }

            await registerFromLocation(availableSpots, currentLocation);
        });
    },

    async syncLatestRegistration() {
        if (Platform.OS !== 'ios' || !await this.isEnabled()) return;
        const spots = await getTriviaSpots();
        await this.refreshRegistration(spots);
    },

    async handleEvent(eventType: Location.GeofencingEventType, region: Location.LocationRegion) {
        if (!await this.isEnabled()) return;

        const isRefreshExit = region.identifier === REFRESH_REGION_ID
            && eventType === Location.GeofencingEventType.Exit;
        const isSpotEntry = region.identifier.startsWith(SPOT_REGION_PREFIX)
            && eventType === Location.GeofencingEventType.Enter;
        if (!isRefreshExit && !isSpotEntry) return;

        if (isSpotEntry) {
            const spotId = region.identifier.slice(SPOT_REGION_PREFIX.length);
            const spots = await loadSpots();
            const spot = spots.find((item) => item.id === spotId);
            if (spot) {
                const record = await TriviaUnlockManager.unlockTrivia(spot);
                if (record) await TriviaNotificationManager.notifyUnlockedSpot(spot);
            }
        }

        await this.refreshRegistration();
    },
};
