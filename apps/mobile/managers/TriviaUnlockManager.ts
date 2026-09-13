import AsyncStorage from '@react-native-async-storage/async-storage';
import { Coordinates, TriviaSpot, UnlockedTriviaRecord } from '../models/TriviaSpot';
import { getBackendUrl } from '../constants/Config';
import { fetchWithToken } from '../utils/apiClient';
import {
    mergeUnlockRecordMaps,
    mergeUnlockRecords,
    type UnlockMergePayload,
} from './triviaUnlockMerge';

const LEGACY_STORAGE_KEY = 'triviaMapUnlockedRecords';
const STORAGE_KEY_PREFIX = 'triviaMapUnlockedRecordsByUserV2:';
const LEGACY_MIGRATION_OWNER_KEY = 'triviaMapUnlockedRecordsLegacyOwnerV2';
const PENDING_USER_ID = '__pending_auth__';
const SYNC_CHUNK_SIZE = 500;

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
    const a = Math.sin(dLat / 2) ** 2
        + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
    return earthRadiusMeters * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
};

const storageKeyFor = (userId: string) => `${STORAGE_KEY_PREFIX}${userId}`;

const parseRecords = (json: string | null): Record<string, UnlockedTriviaRecord> => {
    if (!json) return {};
    try {
        const parsed = JSON.parse(json) as Record<string, UnlockedTriviaRecord>;
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch {
        return {};
    }
};

const readKey = async (key: string) => parseRecords(await AsyncStorage.getItem(key));
const resolveUserId = async (explicitUserId?: string | null) => (
    explicitUserId || await AsyncStorage.getItem('user_id') || PENDING_USER_ID
);

const prepareUserStorage = async (userId: string) => {
    let records = await readKey(storageKeyFor(userId));
    if (userId === PENDING_USER_ID) return records;

    const migrationOwner = await AsyncStorage.getItem(LEGACY_MIGRATION_OWNER_KEY);
    if (!migrationOwner) {
        const legacy = await readKey(LEGACY_STORAGE_KEY);
        records = mergeUnlockRecordMaps(records, legacy).records;
        await AsyncStorage.setItem(storageKeyFor(userId), JSON.stringify(records));
        // Retain the old key as recovery-only data. This ownership marker makes
        // sure no second account can ever claim or upload the same legacy data.
        await AsyncStorage.setItem(LEGACY_MIGRATION_OWNER_KEY, userId);
    }

    const pending = await readKey(storageKeyFor(PENDING_USER_ID));
    const pendingMerge = mergeUnlockRecordMaps(records, pending);
    if (pendingMerge.changed) {
        records = pendingMerge.records;
        await AsyncStorage.setItem(storageKeyFor(userId), JSON.stringify(records));
        await AsyncStorage.removeItem(storageKeyFor(PENDING_USER_ID));
    }
    return records;
};

const writeRecords = async (userId: string, records: Record<string, UnlockedTriviaRecord>) => {
    await AsyncStorage.setItem(storageKeyFor(userId), JSON.stringify(records));
};

type UnlockSyncPayload = UnlockMergePayload & { unlockCounts?: Record<string, number> };

const syncChunk = async (userId: string, records: UnlockedTriviaRecord[]): Promise<UnlockSyncPayload> => {
    const response = await fetchWithToken(`${getBackendUrl()}/trivia/map/unlocks`, {
        method: 'POST',
        body: JSON.stringify({
            spot_ids: records.map((record) => record.id),
            records,
        }),
    }, userId);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json() as UnlockSyncPayload;
    Object.entries(payload.unlockCounts ?? {}).forEach(([spotId, count]) => {
        if (Number.isFinite(count)) syncedUnlockCounts[spotId] = count;
    });
    return payload;
};

const syncAllRecords = async (
    userId: string,
    startingRecords: Record<string, UnlockedTriviaRecord>,
) => {
    let records = startingRecords;
    const values = Object.values(records);
    const chunks: UnlockedTriviaRecord[][] = [];
    for (let index = 0; index < values.length; index += SYNC_CHUNK_SIZE) {
        chunks.push(values.slice(index, index + SYNC_CHUNK_SIZE));
    }
    // An empty request restores an Apple account onto an empty installation.
    if (chunks.length === 0) chunks.push([]);

    for (const chunk of chunks) {
        const merged = mergeUnlockRecords(records, await syncChunk(userId, chunk));
        if (merged.changed) {
            records = merged.records;
            await writeRecords(userId, records);
        }
    }
    return records;
};

export const TriviaUnlockManager = {
    async getUnlockedRecords(explicitUserId?: string | null) {
        return prepareUserStorage(await resolveUserId(explicitUserId));
    },

    async syncUnlockedRecords(explicitUserId?: string | null) {
        return runWithUnlockLock(async () => {
            const userId = await resolveUserId(explicitUserId);
            const records = await prepareUserStorage(userId);
            if (userId === PENDING_USER_ID) return false;
            try {
                await syncAllRecords(userId, records);
                return true;
            } catch (error) {
                // The complete local ledger remains the retry queue.
                console.warn('Map trivia unlock sync failed:', error);
                return false;
            }
        });
    },

    async transferUserRecords(fromUserId: string, toUserId: string) {
        if (!fromUserId || !toUserId || fromUserId === toUserId) return;
        return runWithUnlockLock(async () => {
            const source = await prepareUserStorage(fromUserId);
            const target = await prepareUserStorage(toUserId);
            const merged = mergeUnlockRecordMaps(target, source);
            if (merged.changed) await writeRecords(toUserId, merged.records);
            await AsyncStorage.removeItem(storageKeyFor(fromUserId));
            const migrationOwner = await AsyncStorage.getItem(LEGACY_MIGRATION_OWNER_KEY);
            if (migrationOwner === fromUserId) {
                await AsyncStorage.setItem(LEGACY_MIGRATION_OWNER_KEY, toUserId);
            }
        });
    },

    async removeUserRecords(userId: string) {
        if (!userId) return;
        return runWithUnlockLock(async () => {
            await AsyncStorage.removeItem(storageKeyFor(userId));
            const migrationOwner = await AsyncStorage.getItem(LEGACY_MIGRATION_OWNER_KEY);
            if (migrationOwner === userId) {
                await AsyncStorage.removeItem(LEGACY_STORAGE_KEY);
                await AsyncStorage.removeItem(LEGACY_MIGRATION_OWNER_KEY);
            }
        });
    },

    async hydrateSpots(spots: TriviaSpot[], explicitUserId?: string | null) {
        const records = await this.getUnlockedRecords(explicitUserId);
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

    async unlockTrivia(spot: TriviaSpot, explicitUserId?: string | null) {
        return runWithUnlockLock(async () => {
            const userId = await resolveUserId(explicitUserId);
            const records = await prepareUserStorage(userId);
            if (records[spot.id]) return null;
            const record = { id: spot.id, unlockedAt: new Date().toISOString() };
            records[spot.id] = record;
            await writeRecords(userId, records);
            if (userId !== PENDING_USER_ID) {
                try {
                    await syncAllRecords(userId, records);
                } catch (error) {
                    console.warn('Map trivia unlock sync failed:', error);
                }
            }
            return record;
        });
    },

    async unlockNearbySpots(
        spots: TriviaSpot[],
        userLocation: Coordinates,
        explicitUserId?: string | null,
    ) {
        return runWithUnlockLock(async () => {
            const userId = await resolveUserId(explicitUserId);
            const records = await prepareUserStorage(userId);
            const newlyUnlocked: UnlockedTriviaRecord[] = [];
            spots.forEach((spot) => {
                if (spot.isArchived || records[spot.id]) return;
                const distance = calculateDistanceMeters(userLocation, {
                    latitude: spot.latitude,
                    longitude: spot.longitude,
                });
                if (distance <= spot.unlockRadiusMeters) {
                    const record = { id: spot.id, unlockedAt: new Date().toISOString() };
                    records[spot.id] = record;
                    newlyUnlocked.push(record);
                }
            });
            if (newlyUnlocked.length > 0) {
                await writeRecords(userId, records);
                if (userId !== PENDING_USER_ID) {
                    try {
                        await syncAllRecords(userId, records);
                    } catch (error) {
                        console.warn('Map trivia unlock sync failed:', error);
                    }
                }
            }
            return newlyUnlocked;
        });
    },
};
