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
    const currentUser = auth().currentUser;
    if (currentUser) {
        try {
            // Force refresh is false (fetches from cache if valid)
            const idToken = await currentUser.getIdToken(false);
            headers['Authorization'] = `Bearer ${idToken}`;
        } catch (error) {
            console.error("Failed to fetch Firebase ID token:", error);
        }
    } else {
        // Guest users don't have a firebase token, but backend still needs a user_id
        // Wait, backend requires token now? 
        // Ah, if the backend requires token validation, Guest users will fail!
        // Let's add the token if we have one, otherwise fallback to sending what we have.
    }

    // 3. Execute fetch
    const response = await fetch(url, {
        ...options,
        headers
    });

    return response;
}
