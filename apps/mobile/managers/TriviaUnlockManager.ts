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

type UnlockSyncPayload = {
    unlockCounts?: Record<string, number>;
    spotIdAliases?: Record<string, string>;
    unlockedRecords?: UnlockedTriviaRecord[];
};

const syncRecords = async (records: UnlockedTriviaRecord[]): Promise<UnlockSyncPayload | null> => {
    try {
        const response = await fetchWithToken(`${getBackendUrl()}/trivia/map/unlocks`, {
            method: 'POST',
            body: JSON.stringify({ spot_ids: records.map((record) => record.id) }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json() as UnlockSyncPayload;
        Object.entries(payload.unlockCounts ?? {}).forEach(([spotId, count]) => {
            if (Number.isFinite(count)) syncedUnlockCounts[spotId] = count;
        });
        return payload;
    } catch (error) {
        // The local unlock remains authoritative and is retried on the next map load.
        console.warn('Map trivia unlock sync failed:', error);
        return null;
    }
};

const addCanonicalAliases = (
    records: Record<string, UnlockedTriviaRecord>,
    aliases: Record<string, string>,
) => {
    let changed = false;
    Object.entries(aliases).forEach(([legacyId, canonicalId]) => {
        const legacyRecord = records[legacyId];
        if (!legacyRecord || records[canonicalId]) return;

        // Keep the legacy entry as a non-destructive backup. The canonical
        // entry makes the same unlock visible under the current API ID.
        records[canonicalId] = {
            id: canonicalId,
            unlockedAt: legacyRecord.unlockedAt,
        };
        changed = true;
    });
    return changed;
};

const mergeServerRecords = (
    records: Record<string, UnlockedTriviaRecord>,
    serverRecords: UnlockedTriviaRecord[],
) => {
    let changed = false;
    serverRecords.forEach((record) => {
        if (
            !record ||
            typeof record.id !== 'string' ||
            typeof record.unlockedAt !== 'string' ||
            records[record.id] ||
            Number.isNaN(new Date(record.unlockedAt).getTime())
        ) return;

        records[record.id] = record;
        changed = true;
    });
    return changed;
};

export const TriviaUnlockManager = {
    async getUnlockedRecords() {
        return readRecords();
    },

    async syncUnlockedRecords() {
        return runWithUnlockLock(async () => {
            const records = await readRecords();
            const payload = await syncRecords(Object.values(records));
            const aliasesChanged = payload?.spotIdAliases
                ? addCanonicalAliases(records, payload.spotIdAliases)
                : false;
            const serverRecordsChanged = payload?.unlockedRecords
                ? mergeServerRecords(records, payload.unlockedRecords)
                : false;
            if (aliasesChanged || serverRecordsChanged) {
                await writeRecords(records);
            }
        });
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
                if (spot.isArchived) return;
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
