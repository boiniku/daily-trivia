
import React, { createContext, useContext, useEffect, useState } from 'react';
import {
    AppleAuthProvider,
    FirebaseAuthTypes,
    getAuth,
    onAuthStateChanged,
    signInAnonymously,
    signInWithCredential,
    signOut as firebaseSignOut,
} from '@react-native-firebase/auth';
import * as AppleAuthentication from 'expo-apple-authentication';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
import { Alert, AppState } from 'react-native';
import { Config } from '../constants/Config';
import { fetchWithToken } from '../utils/apiClient';
import { TriviaUnlockManager } from '../managers/TriviaUnlockManager';
import { prepareAppleMigration, finishAppleMigration } from '../managers/AccountMigration';
import { authorizeAppleDeletion } from '../managers/appleAccountDeletion';

interface AuthContextType {
    user: FirebaseAuthTypes.User | null;
    userId: string | null; // Current effective user ID (Guest or Auth)
    loading: boolean;
    signInWithApple: () => Promise<boolean>;
    signOut: () => Promise<void>;
    deleteAccount: () => Promise<void>;
    isGuest: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);
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

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<FirebaseAuthTypes.User | null>(null);
    const [userId, setUserId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);

    // Handle user state changes
    function handleAuthStateChanged(user: FirebaseAuthTypes.User | null) {
        setUser(user);
        // Hide the previous identity immediately. Its map collection must never
        // remain active while a new Firebase identity is being established.
        setUserId((current) => current === user?.uid ? current : null);
        if (loading) setLoading(false);
    }

    useEffect(() => {
        const subscriber = onAuthStateChanged(firebaseAuth, handleAuthStateChanged);
        // We wait for Firebase's initial onAuthStateChanged event instead of manually calling initializeUser().
        // This prevents an unnecessary anonymous signin from taking place before the cached user is parsed.
        return subscriber; // unsubscribe on unmount
    }, []);

    // Effect to update detailed user ID when auth state changes
    useEffect(() => {
        if (!loading) {
            void updateEffectiveUserId().catch((error) => console.error('Auth initialization failed:', error));
        }
    }, [user, loading]);

    useEffect(() => {
        if (!user || user.isAnonymous) return;
        let disposed = false;
        const retry = () => {
            if (!disposed && firebaseAuth.currentUser?.uid === user.uid) {
                void finishAppleMigration(user.uid).catch((error) => console.warn('Migration pending:', error));
            }
        };
        retry();
        const subscription = AppState.addEventListener('change', (state) => { if (state === 'active') retry(); });
        const timer = setInterval(() => { if (AppState.currentState === 'active') retry(); }, 60000);
        return () => { disposed = true; clearInterval(timer); subscription.remove(); };
    }, [user]);

    const initializeUser = async () => {
        try {
            await updateEffectiveUserId();
        } catch (e) {
            console.error("Failed to initialize user:", e);
        } finally {
            setLoading(false);
        }
    };

    const updateEffectiveUserId = async () => {
        if (user) {
            // Logged in
            if (firebaseAuth.currentUser?.uid !== user.uid) return;
            await syncUserIdToStorage(user.uid);
            if (firebaseAuth.currentUser?.uid === user.uid) setUserId(user.uid);
        } else {
            // Guest mode: We need a Firebase Token for the backend, so use Anonymous Auth
            if (!firebaseAuth.currentUser) {
                try {
                    const anonCred = await withTimeout(signInAnonymously(firebaseAuth), 2500, 'Anonymous sign-in');
                    if (firebaseAuth.currentUser?.uid !== anonCred.user.uid) return;
                    setUserId(anonCred.user.uid);
                    await syncUserIdToStorage(anonCred.user.uid);
                } catch (e) {
                    console.error("Failed to sign in anonymously:", e);
                    // Fallback to locally generated id if anonymous auth fails
                    let guestId = await AsyncStorage.getItem('user_id');
                    if (!guestId) {
                        const newGuestId = Crypto.randomUUID();
                        await syncUserIdToStorage(newGuestId, true);
                        setUserId(newGuestId);
                    } else {
                        setUserId(guestId);
                    }
                }
            } else {
                // If currentUser exists but `user` state was null (race condition or weird state),
                // just use the current anonymous user's uid
                const currentUid = firebaseAuth.currentUser.uid;
                setUserId(currentUid);
                await syncUserIdToStorage(currentUid);
            }
        }
    };



    const syncUserIdToStorage = async (id: string, isLocalFallback = false) => {
        try {
            const previousId = await AsyncStorage.getItem('user_id');
            const previousWasFallback = await AsyncStorage.getItem('user_id_is_local_fallback') === 'true';
            if (!isLocalFallback && previousWasFallback && previousId && previousId !== id) {
                await TriviaUnlockManager.transferUserRecords(previousId, id);
            }
            await AsyncStorage.setItem('user_id', id);
            if (isLocalFallback) {
                await AsyncStorage.setItem('user_id_is_local_fallback', 'true');
            } else {
                await AsyncStorage.removeItem('user_id_is_local_fallback');
            }
        } catch (e) {
            console.error('Failed to save user_id to AsyncStorage:', e);
            throw e;
        }
        // Widget sync is handled by syncTriviaToWidget() in index.tsx (after trivia fetch)
        // and by backgroundFetch.ts — no direct DefaultPreference calls here to avoid crash
    };

    const signInWithApple = async (): Promise<boolean> => {
        let preparedGuestId: string | null = null;
        try {
            const rawNonce = Crypto.randomUUID();
            const state = Crypto.randomUUID();

            const hashedNonce = await Crypto.digestStringAsync(
                Crypto.CryptoDigestAlgorithm.SHA256,
                rawNonce
            );

            const credential = await AppleAuthentication.signInAsync({
                requestedScopes: [
                    AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
                    AppleAuthentication.AppleAuthenticationScope.EMAIL,
                ],
                state,
                nonce: hashedNonce,
            });

            const { identityToken } = credential;

            if (credential.state !== state) throw new Error('Apple Sign-In state mismatch');

            if (!identityToken) {
                throw new Error('Apple Sign-In failed - no identify token returned');
            }

            // Create a Firebase credential with the token
            // Pass the RAW nonce to Firebase (it will verify against the hash in the token)
            const firebaseCredential = AppleAuthProvider.credential(identityToken, rawNonce);

            // Save guest ID before signing in
            const guestUser = firebaseAuth.currentUser;
            if (guestUser?.isAnonymous) {
                await prepareAppleMigration(guestUser.uid, credential.user);
                preparedGuestId = guestUser.uid;
            }

            // sign the node in with the credential
            const userCredential = await signInWithCredential(firebaseAuth, firebaseCredential);
            const authUser = userCredential.user;

            console.log("Apple Sign-In success:", authUser.uid);

            // The server verifies the destination's Apple subject. A failed
            // response is retried on startup/resume without the expired guest token.
            try { await finishAppleMigration(authUser.uid); }
            catch (error: any) { Alert.alert('データ連携待ち', error.message); }

            // Force update user ID immediately
            setUserId(authUser.uid);
            await syncUserIdToStorage(authUser.uid);
            await TriviaUnlockManager.syncUnlockedRecords(authUser.uid);


            return true;
        } catch (error: any) {
            if (preparedGuestId && firebaseAuth.currentUser?.uid === preparedGuestId) {
                TriviaUnlockManager.resumeUser(preparedGuestId);
            }
            // Note: If linking fails because the Apple account is already tied to another Firebase
            // account, you might want to handle `auth/credential-already-in-use` specifically.
            if (error.code === 'ERR_CANCELED') {
                console.log("User canceled Apple Sign-In");
                return false;
            }
            console.error(error);
            Alert.alert("Error", `Failed to sign in with Apple.\n${error.message}`);
            return false;
        }
    };

    const signOut = async () => {
        try {
            // Prevent background work from writing the outgoing account's local
            // ledger under the next anonymous identity during auth transition.
            await AsyncStorage.removeItem('user_id');
            await AsyncStorage.removeItem('user_id_is_local_fallback');
            await AsyncStorage.removeItem('triviaState');
            await firebaseSignOut(firebaseAuth);
            // User state becomes null -> useEffect triggers updateEffectiveUserId -> Generates new Guest ID
        } catch (e) {
            console.error(e);
        }
    };

    const deleteAccount = async () => {
        try {
            console.log("Attempting to delete account for userId:", userId);
            if (!userId) {
                console.error("Delete failed: No userId found");
                Alert.alert("エラー", "ユーザーIDが見つかりません。再ログインしてください。");
                return;
            }

            // 1. Delete user data on backend
            if (!await TriviaUnlockManager.isAccountDeletionPending(userId)) {
                await authorizeAppleDeletion(userId);
            }
            await TriviaUnlockManager.beginAccountDeletion(userId);
            console.log("Sending DELETE request to backend...");
            const response = await fetchWithToken(`${Config.BACKEND_URL}/auth/user`, {
                method: 'DELETE'
            }, userId);

            if (!response.ok) {
                const text = await response.text();
                console.error("Backend delete failed:", response.status, text);
                throw new Error(`Backend Error: ${text}`);
            }

            console.log("Backend delete success. Cleaning up local data...");

            // 2. Sign out & Cleanup
            await TriviaUnlockManager.removeUserRecords(userId);
            await AsyncStorage.removeItem('user_id');
            await AsyncStorage.removeItem('user_id_is_local_fallback');
            await AsyncStorage.removeItem('hasSeenTutorial');
            await AsyncStorage.removeItem('hasSeenTutorialRevision');
            await AsyncStorage.removeItem('hasSeenWidgetGuide');
            await AsyncStorage.removeItem('triviaState');

            // Clean up widget data (lazy import to avoid loading native module at startup)
            try {
                const DefaultPreference = require('react-native-default-preference').default;
                await DefaultPreference.setName('group.com.dailytrivia.app');
                await DefaultPreference.set('user_id', '');
                await DefaultPreference.set('daily_trivia', '[]');
            } catch (e) {
                console.error("Widget cleanup warning:", e);
            }

            await signOut();

            setUserId(null);
            console.log("Account deletion complete.");
            Alert.alert("完了", "アカウントを削除しました。初期状態に戻ります。");

        } catch (e: any) {
            if (e.code === 'ERR_CANCELED') return;
            console.error("Delete account exception:", e);
            Alert.alert("エラー", "アカウントの削除に失敗しました。\n" + e.message);
        }
    };

    // A user is a "Guest" if they are only signed in anonymously
    const isGuest = !user || user.isAnonymous;

    return (
        <AuthContext.Provider value={{
            user,
            userId,
            loading,
            signInWithApple,
            signOut,
            deleteAccount,
            isGuest
        }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};
