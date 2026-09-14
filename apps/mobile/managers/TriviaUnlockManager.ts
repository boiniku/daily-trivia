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
const syncJobs = new Map<string, Promise<boolean>>();
const suspendedUsers = new Set<string>();
const deletionKeyFor = (userId: string) => `triviaMapAccountDeletionV1:${userId}`;
const isSuspended = async (userId: string) => suspendedUsers.has(userId)
    || await AsyncStorage.getItem(deletionKeyFor(userId)) === 'true';

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
    const parsed = JSON.parse(json) as Record<string, UnlockedTriviaRecord>;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Invalid unlock storage; original data has been preserved');
    }
    return parsed;
};

const readKey = async (key: string) => parseRecords(await AsyncStorage.getItem(key));
const resolveUserId = async (explicitUserId?: string | null) => (
    explicitUserId || await AsyncStorage.getItem('user_id') || PENDING_USER_ID
);

const prepareUserStorage = async (userId: string) => {
    let records = await readKey(storageKeyFor(userId));
    if (userId === PENDING_USER_ID) return records;

    let migrationOwner = await AsyncStorage.getItem(LEGACY_MIGRATION_OWNER_KEY);
    if (!migrationOwner) {
        // Claim first; if the following write fails, only this owner can resume.
        await AsyncStorage.setItem(LEGACY_MIGRATION_OWNER_KEY, userId);
        migrationOwner = userId;
    }
    if (migrationOwner === userId) {
        const legacy = await readKey(LEGACY_STORAGE_KEY);
        records = mergeUnlockRecordMaps(records, legacy).records;
        await AsyncStorage.setItem(storageKeyFor(userId), JSON.stringify(records));
        // Retain the old key as recovery-only data. This ownership marker makes
        // sure no second account can ever claim or upload the same legacy data.
    }

    if (migrationOwner !== userId) return records;
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
    const acknowledgedIds = new Set<string>();
    const aliases: Record<string, string> = {};
    const values = Object.values(startingRecords);
    const chunks: UnlockedTriviaRecord[][] = [];
    for (let index = 0; index < values.length; index += SYNC_CHUNK_SIZE) {
        chunks.push(values.slice(index, index + SYNC_CHUNK_SIZE));
    }
    // An empty request restores an Apple account onto an empty installation.
    if (chunks.length === 0) chunks.push([]);

    for (const chunk of chunks) {
        if (await isSuspended(userId)) throw new Error('Account sync is suspended');
        const payload = await syncChunk(userId, chunk);
        if (!Array.isArray(payload.unlockedRecords)) {
            throw new Error('Server did not confirm account backup');
        }
        for (const record of payload.unlockedRecords) {
            if (typeof record.id === 'string' && Number.isFinite(Date.parse(record.unlockedAt))) {
                acknowledgedIds.add(record.id);
            }
        }
        Object.assign(aliases, payload.spotIdAliases ?? {});
        await runWithUnlockLock(async () => {
            if (await isSuspended(userId)) return;
            // Merge with the latest ledger, not the pre-request snapshot.
            const current = await readKey(storageKeyFor(userId));
            const merged = mergeUnlockRecords(current, payload);
            if (merged.changed) await writeRecords(userId, merged.records);
        });
    }
    return runWithUnlockLock(async () => {
        if (await isSuspended(userId)) return false;
        const latest = await readKey(storageKeyFor(userId));
        // HTTP 200 alone is not proof: unknown IDs may have been ignored, and
        // new local unlocks may have arrived while the request was in flight.
        return Object.values(latest).every(record => acknowledgedIds.has(record.id)
            || (typeof aliases[record.id] === 'string' && acknowledgedIds.has(aliases[record.id])));
    });
};

export const TriviaUnlockManager = {
    async getUnlockedRecords(explicitUserId?: string | null) {
        return runWithUnlockLock(async () => {
            const userId = await resolveUserId(explicitUserId);
            return await isSuspended(userId) ? readKey(storageKeyFor(userId)) : prepareUserStorage(userId);
        });
    },

    async syncUnlockedRecords(explicitUserId?: string | null) {
        const userId = await resolveUserId(explicitUserId);
        if (userId === PENDING_USER_ID || await isSuspended(userId)) return false;
        const existing = syncJobs.get(userId);
        if (existing) return existing;
        const job = (async () => {
            try {
                const records = await runWithUnlockLock(() => prepareUserStorage(userId));
                return await syncAllRecords(userId, records);
            } catch (error) {
                // The complete local ledger remains the retry queue.
                console.warn('Map trivia unlock sync failed:', error);
                return false;
            }
        })();
        syncJobs.set(userId, job);
        try { return await job; } finally { syncJobs.delete(userId); }
    },

    async suspendUser(userId: string) {
        suspendedUsers.add(userId);
        // Drain pre-existing HTTP requests before issuing account deletion.
        await syncJobs.get(userId);
    },

    resumeUser(userId: string) { suspendedUsers.delete(userId); },

    async beginAccountDeletion(userId: string) {
        // Keep the block across crashes until the account is actually deleted.
        await AsyncStorage.setItem(deletionKeyFor(userId), 'true');
        await this.suspendUser(userId);
    },

    async isAccountDeletionPending(userId: string) {
        return await AsyncStorage.getItem(deletionKeyFor(userId)) === 'true';
    },

    async transferUserRecords(fromUserId: string, toUserId: string) {
        if (!fromUserId || !toUserId || fromUserId === toUserId) return;
        await this.suspendUser(fromUserId);
        return runWithUnlockLock(async () => {
            const source = await prepareUserStorage(fromUserId);
            const target = await prepareUserStorage(toUserId);
            const merged = mergeUnlockRecordMaps(target, source);
            if (merged.changed) await writeRecords(toUserId, merged.records);
            const migrationOwner = await AsyncStorage.getItem(LEGACY_MIGRATION_OWNER_KEY);
            if (migrationOwner === fromUserId) {
                await AsyncStorage.setItem(LEGACY_MIGRATION_OWNER_KEY, toUserId);
            }
            await AsyncStorage.removeItem(storageKeyFor(fromUserId));
        });
    },

    async removeUserRecords(userId: string) {
        if (!userId) return;
        await this.suspendUser(userId);
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
        const userId = await resolveUserId(explicitUserId);
        const result = await runWithUnlockLock(async () => {
            if (await isSuspended(userId) || spot.isArchived) return null;
            const records = await prepareUserStorage(userId);
            if (records[spot.id]) return null;
            const record = { id: spot.id, unlockedAt: new Date().toISOString() };
            records[spot.id] = record;
            await writeRecords(userId, records);
            return record;
        });
        if (result) void this.syncUnlockedRecords(userId);
        return result;
    },

    async unlockNearbySpots(
        spots: TriviaSpot[],
        userLocation: Coordinates,
        explicitUserId?: string | null,
    ) {
        const userId = await resolveUserId(explicitUserId);
        const result = await runWithUnlockLock(async () => {
            if (await isSuspended(userId)) return [];
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
            }
            return newlyUnlocked;
        });
        if (result.length) void this.syncUnlockedRecords(userId);
        return result;
    },
};
