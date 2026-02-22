import auth from '@react-native-firebase/auth';
import { Config } from '../constants/Config';
import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * A wrapper around the standard `fetch` that automatically attaches the
 * Firebase ID token to the Authorization header if a user is logged in.
 */
export async function fetchWithToken(url: string, options: RequestInit = {}) {
    // 1. Prepare headers
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> || {})
    };

    // 2. Try to get token from Firebase Auth
    let currentUser = auth().currentUser;

    // If there's no current user, it might be a fresh install that hasn't finished anon auth
    // Let's force an anonymous sign-in here just in case, to ensure we have a token
    if (!currentUser) {
        try {
            console.log("fetchWithToken: No currentUser found, attempting anonymous sign-in...");
            const userCred = await auth().signInAnonymously();
            currentUser = userCred.user;
        } catch (error) {
            console.error("fetchWithToken: Failed to sign in anonymously:", error);
        }
    }

    if (currentUser) {
        try {
            // Force refresh is false (fetches from cache if valid)
            const idToken = await currentUser.getIdToken(false);
            if (idToken) {
                headers['Authorization'] = `Bearer ${idToken}`;
            } else {
                console.warn("fetchWithToken: getIdToken returned empty.");
            }
        } catch (error) {
            console.error("fetchWithToken: Failed to fetch Firebase ID token:", error);
        }
    } else {
        console.warn("fetchWithToken: Still no currentUser, sending request without Authorization header.");
    }

    // 3. Execute fetch
    const response = await fetch(url, {
        ...options,
        headers
    });

    return response;
}
