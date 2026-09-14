import { getAuth, getIdToken, signInAnonymously } from '@react-native-firebase/auth';
import { Config } from '../constants/Config';

const firebaseAuth = getAuth();

const withTimeout = async <T,>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> => {
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const timeoutPromise = new Promise<never>((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs);
    });

    try {
        return await Promise.race([promise, timeoutPromise]);
    } finally {
        if (timeoutId) clearTimeout(timeoutId);
    }
};

/**
 * A wrapper around the standard `fetch` that automatically attaches the
 * Firebase ID token to the Authorization header if a user is logged in.
 */
export async function fetchWithToken(
    url: string,
    options: RequestInit = {},
    expectedUserId?: string,
) {
    // 1. Prepare headers
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        'X-Daily-Trivia-App-Version': Config.APP_VERSION,
        'X-Daily-Trivia-App-Environment': Config.APP_ENV,
        'X-Daily-Trivia-API-Version': Config.API_VERSION,
        ...(options.headers as Record<string, string> || {})
    };

    // 2. Try to get token from Firebase Auth
    let currentUser = firebaseAuth.currentUser;
    if (expectedUserId && currentUser?.uid !== expectedUserId) {
        throw new Error('Authenticated user changed before the request was sent');
    }

    // If there's no current user, it might be a fresh install that hasn't finished anon auth
    // Let's force an anonymous sign-in here just in case, to ensure we have a token
    if (!currentUser) {
        try {
            console.log("fetchWithToken: No currentUser found, attempting anonymous sign-in...");
            const userCred = await withTimeout(signInAnonymously(firebaseAuth), 2500, 'Anonymous sign-in');
            currentUser = userCred.user;
        } catch (error) {
            console.error("fetchWithToken: Failed to sign in anonymously:", error);
        }
    }

    if (currentUser) {
        if (expectedUserId && currentUser.uid !== expectedUserId) {
            throw new Error('Authenticated user changed before the request was sent');
        }
        try {
            // Force refresh is false (fetches from cache if valid)
            const idToken = await withTimeout(getIdToken(currentUser, false), 2000, 'Firebase token fetch');
            if (idToken) {
                headers['Authorization'] = `Bearer ${idToken}`;
            } else {
                console.warn("fetchWithToken: getIdToken returned empty.");
            }
        } catch (error) {
            if (expectedUserId) throw error;
            console.error("fetchWithToken: Failed to fetch Firebase ID token:", error);
        }
    } else {
        console.warn("fetchWithToken: Still no currentUser, sending request without Authorization header.");
    }

    // 3. Execute fetch
    if (expectedUserId && (!headers.Authorization || firebaseAuth.currentUser?.uid !== expectedUserId)) {
        throw new Error('Authenticated user changed or token is unavailable');
    }
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (options.signal?.aborted) abort();
    options.signal?.addEventListener('abort', abort);
    const timer = setTimeout(abort, 15000);
    try {
        // Also bound response-body reads (React Native fetch can resolve headers
        // before the body). Buffer once so callers cannot hang outside the timeout.
        return await withTimeout((async () => {
            const response = await fetch(url, { ...options, headers, signal: controller.signal });
            const body = await response.text();
            return {
                ok: response.ok, status: response.status, statusText: response.statusText, headers: response.headers,
                text: async () => body,
                json: async () => JSON.parse(body),
            };
        })(), 15000, 'API request');
    } finally {
        clearTimeout(timer);
        options.signal?.removeEventListener('abort', abort);
        controller.abort();
    }
}
