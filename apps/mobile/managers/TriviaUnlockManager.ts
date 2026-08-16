import AsyncStorage from '@react-native-async-storage/async-storage';
import { Coordinates, TriviaSpot, UnlockedTriviaRecord } from '../models/TriviaSpot';

const STORAGE_KEY = 'triviaMapUnlockedRecords';
let unlockQueue: Promise<unknown> = Promise.resolve();

const runWithUnlockLock = async <T>(operation: () => Promise<T>): Promise<T> => {
    const previous = unlockQueue;
    let release: () => void = () => undefined;
    unlockQueue = new Promise<void>((resolve) => {
        release = resolve;
    });

    await previous.catch(() => undefined);
    try {
        return await operation();
    } finally {
        release();
    }
};

const toRadians = (value: number) => (value * Math.PI) / 180;

export const calculateDistanceMeters = (from: Coordinates, to: Coordinates) => {
    const earthRadiusMeters = 6371000;
    const dLat = toRadians(to.latitude - from.latitude);
    const dLon = toRadians(to.longitude - from.longitude);
    const lat1 = toRadians(from.latitude);
    const lat2 = toRadians(to.latitude);

    const a =
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));

    return earthRadiusMeters * c;
};

const readRecords = async (): Promise<Record<string, UnlockedTriviaRecord>> => {
    const json = await AsyncStorage.getItem(STORAGE_KEY);
    if (!json) return {};

    try {
        const parsed = JSON.parse(json) as Record<string, UnlockedTriviaRecord>;
        return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
        return {};
    }
};

const writeRecords = async (records: Record<string, UnlockedTriviaRecord>) => {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(records));
};

export const TriviaUnlockManager = {
    async getUnlockedRecords() {
        return readRecords();
    },

    async hydrateSpots(spots: TriviaSpot[]) {
        const records = await readRecords();

        return spots.map((spot) => {
            const record = records[spot.id];
            return {
                ...spot,
                isUnlocked: Boolean(record),
                unlockedAt: record ? new Date(record.unlockedAt) : null,
            };
        });
    },

    async unlockTrivia(spot: TriviaSpot) {
        return runWithUnlockLock(async () => {
            const records = await readRecords();
            if (records[spot.id]) return null;

            const record = {
                id: spot.id,
                unlockedAt: new Date().toISOString(),
            };
            records[spot.id] = record;
            await writeRecords(records);

            return record;
        });
    },

    async resetTrivia(spotId: string) {
        return runWithUnlockLock(async () => {
            const records = await readRecords();
            if (!records[spotId]) return false;

            delete records[spotId];
            await writeRecords(records);
            return true;
        });
    },

    async unlockNearbySpots(spots: TriviaSpot[], userLocation: Coordinates) {
        return runWithUnlockLock(async () => {
            const records = await readRecords();
            const newlyUnlocked: UnlockedTriviaRecord[] = [];

            spots.forEach((spot) => {
                if (records[spot.id]) return;

                const distance = calculateDistanceMeters(userLocation, {
                    latitude: spot.latitude,
                    longitude: spot.longitude,
                });

                if (distance <= spot.unlockRadiusMeters) {
                    const record = {
                        id: spot.id,
                        unlockedAt: new Date().toISOString(),
                    };
                    records[spot.id] = record;
                    newlyUnlocked.push(record);
                }
            });

            if (newlyUnlocked.length > 0) {
                await writeRecords(records);
            }

            return newlyUnlocked;
        });
    },
};
