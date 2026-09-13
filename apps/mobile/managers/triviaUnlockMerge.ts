import type { UnlockedTriviaRecord } from '../models/TriviaSpot';

export type UnlockMergePayload = {
    spotIdAliases?: Record<string, string>;
    unlockedRecords?: UnlockedTriviaRecord[];
};

type UnlockRecordMap = Record<string, UnlockedTriviaRecord>;

const isValidRecord = (record: UnlockedTriviaRecord | null | undefined) => (
    Boolean(record) &&
    typeof record?.id === 'string' &&
    typeof record?.unlockedAt === 'string' &&
    !Number.isNaN(new Date(record.unlockedAt).getTime())
);

/**
 * Merges aliases and server backups into local unlock history without removing
 * or replacing any record already stored on the device.
 */
export const mergeUnlockRecords = (
    current: UnlockRecordMap,
    payload: UnlockMergePayload | null | undefined,
) => {
    const records = { ...current };
    let changed = false;

    Object.entries(payload?.spotIdAliases ?? {}).forEach(([legacyId, canonicalId]) => {
        const legacyRecord = records[legacyId];
        if (!legacyRecord || !canonicalId || records[canonicalId]) return;

        // Retain the legacy record as a backup and add its current API alias.
        records[canonicalId] = {
            id: canonicalId,
            unlockedAt: legacyRecord.unlockedAt,
        };
        changed = true;
    });

    (payload?.unlockedRecords ?? []).forEach((record) => {
        if (!isValidRecord(record) || records[record.id]) return;

        records[record.id] = record;
        changed = true;
    });

    return { records, changed };
};

export const mergeUnlockRecordMaps = (
    target: UnlockRecordMap,
    source: UnlockRecordMap,
) => {
    const records = { ...target };
    let changed = false;

    Object.values(source).forEach((record) => {
        if (!isValidRecord(record)) return;
        const existing = records[record.id];
        if (!existing || new Date(record.unlockedAt) < new Date(existing.unlockedAt)) {
            records[record.id] = record;
            changed = true;
        }
    });

    return { records, changed };
};
