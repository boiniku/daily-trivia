import { Config } from '../constants/Config';
import { fetchWithToken } from '../utils/apiClient';
import { TriviaUnlockManager } from './TriviaUnlockManager';

const pending = new Map<string, Promise<void>>();

export async function prepareAppleMigration(guestId: string, appleSubject: string) {
    // Save/claim old-format records under the source before auth listeners run.
    await TriviaUnlockManager.getUnlockedRecords(guestId);
    if (!await TriviaUnlockManager.syncUnlockedRecords(guestId)) {
        throw new Error('履歴を保護するため、通信が回復してからApple連携を再試行してください。');
    }
    await TriviaUnlockManager.suspendUser(guestId);
    try {
        const response = await fetchWithToken(`${Config.BACKEND_URL}/auth/merge/prepare`, {
            method: 'POST', body: JSON.stringify({ apple_subject: appleSubject }),
        }, guestId);
        if (!response.ok) throw new Error('引き継ぎの準備に失敗しました。元の履歴は保持されています。');
    } catch (error) {
        TriviaUnlockManager.resumeUser(guestId);
        throw error;
    }
}

export async function finishAppleMigration(userId: string): Promise<void> {
    if (await TriviaUnlockManager.isAccountDeletionPending(userId)) return;
    const existing = pending.get(userId);
    if (existing) return existing;
    const job = (async () => {
        const response = await fetchWithToken(`${Config.BACKEND_URL}/auth/merge/pending`, {
            method: 'POST',
        }, userId);
        if (!response.ok) throw new Error('履歴の引き継ぎが未完了です。通信回復後に自動で再試行します。');
        const payload = await response.json();
        if (!Array.isArray(payload.merged_guest_ids) ||
            !payload.merged_guest_ids.every((id: unknown) => typeof id === 'string')) {
            throw new Error('Invalid migration response');
        }
        for (const sourceId of payload.merged_guest_ids) {
            await TriviaUnlockManager.transferUserRecords(sourceId, userId);
        }
        await TriviaUnlockManager.syncUnlockedRecords(userId);
    })();
    pending.set(userId, job);
    try { await job; } finally { pending.delete(userId); }
}
