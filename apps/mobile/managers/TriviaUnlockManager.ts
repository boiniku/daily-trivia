import AsyncStorage from '@react-native-async-storage/async-storage';
import { Coordinates, TriviaSpot, UnlockedTriviaRecord } from '../models/TriviaSpot';
import { getBackendUrl } from '../constants/Config';
import { fetchWithToken } from '../utils/apiClient';

const STORAGE_KEY = 'triviaMapUnlockedRecords';
let unlockQueue: Promise<unknown> = Promise.resolve();
const syncedUnlockCounts: Record<string, number> = {};

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

const syncRecords = async (records: UnlockedTriviaRecord[]) => {
    if (records.length === 0) return;
    try {
        const response = await fetchWithToken(`${getBackendUrl()}/trivia/map/unlocks`, {
            method: 'POST',
            body: JSON.stringify({ spot_ids: records.map((record) => record.id) }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json() as { unlockCounts?: Record<string, number> };
        Object.entries(payload.unlockCounts ?? {}).forEach(([spotId, count]) => {
            if (Number.isFinite(count)) syncedUnlockCounts[spotId] = count;
        });
    } catch (error) {
        // The local unlock remains authoritative and is retried on the next map load.
        console.warn('Map trivia unlock sync failed:', error);
    }
};

export const TriviaUnlockManager = {
    async getUnlockedRecords() {
        return readRecords();
    },

    async syncUnlockedRecords() {
        const records = Object.values(await readRecords());
        await syncRecords(records);
    },

    async hydrateSpots(spots: TriviaSpot[]) {
        const records = await readRecords();

        return spots.map((spot) => {
            const record = records[spot.id];
            return {
                ...spot,
                unlockCount: syncedUnlockCounts[spot.id] ?? spot.unlockCount ?? 0,
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
            await syncRecords([record]);

            return record;
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
                await syncRecords(newlyUnlocked);
            }

            return newlyUnlocked;
        });
    },
};
