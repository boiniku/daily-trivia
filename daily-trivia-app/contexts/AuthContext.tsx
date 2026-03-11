
import React, { createContext, useContext, useEffect, useState } from 'react';
import auth, { FirebaseAuthTypes } from '@react-native-firebase/auth';
import * as AppleAuthentication from 'expo-apple-authentication';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
import { Alert } from 'react-native';
import { Config } from '../constants/Config';
import { useRevenueCat } from './RevenueCatContext';
import { fetchWithToken } from '../utils/apiClient';

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

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<FirebaseAuthTypes.User | null>(null);
    const [userId, setUserId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const { logIn, logOut: rcLogOut } = useRevenueCat(); // Destructure logIn/logOut

    // Handle user state changes
    function onAuthStateChanged(user: FirebaseAuthTypes.User | null) {
        setUser(user);
        if (loading) setLoading(false);
    }

    useEffect(() => {
        const subscriber = auth().onAuthStateChanged(onAuthStateChanged);
        // We wait for Firebase's initial onAuthStateChanged event instead of manually calling initializeUser().
        // This prevents an unnecessary anonymous signin from taking place before the cached user is parsed.
        return subscriber; // unsubscribe on unmount
    }, []);

    // Effect to update detailed user ID when auth state changes
    useEffect(() => {
        if (!loading) {
            updateEffectiveUserId();
        }
    }, [user, loading]);

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
            setUserId(user.uid);
            await syncUserIdToStorage(user.uid);
        } else {
            // Guest mode: We need a Firebase Token for the backend, so use Anonymous Auth
            if (!auth().currentUser) {
                try {
                    const anonCred = await auth().signInAnonymously();
                    setUserId(anonCred.user.uid);
                    await syncUserIdToStorage(anonCred.user.uid);
                } catch (e) {
                    console.error("Failed to sign in anonymously:", e);
                    // Fallback to locally generated id if anonymous auth fails
                    let guestId = await AsyncStorage.getItem('user_id');
                    if (!guestId) {
                        const newGuestId = Crypto.randomUUID();
                        await syncUserIdToStorage(newGuestId);
                        setUserId(newGuestId);
                    } else {
                        setUserId(guestId);
                    }
                }
            } else {
                // If currentUser exists but `user` state was null (race condition or weird state),
                // just use the current anonymous user's uid
                setUserId(auth().currentUser!.uid);
            }
        }
    };



    const syncUserIdToStorage = async (id: string) => {
        try {
            await AsyncStorage.setItem('user_id', id);
        } catch (e) {
            console.error('Failed to save user_id to AsyncStorage:', e);
        }
        // Widget sync is handled by syncTriviaToWidget() in index.tsx (after trivia fetch)
        // and by backgroundFetch.ts — no direct DefaultPreference calls here to avoid crash
    };

    const signInWithApple = async (): Promise<boolean> => {
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

            if (!identityToken) {
                throw new Error('Apple Sign-In failed - no identify token returned');
            }

            // Create a Firebase credential with the token
            // Pass the RAW nonce to Firebase (it will verify against the hash in the token)
            const firebaseCredential = auth.AppleAuthProvider.credential(identityToken, rawNonce);

            // Save guest ID before signing in
            const guestUserId = await AsyncStorage.getItem('user_id');

            // sign the node in with the credential
            const userCredential = await auth().signInWithCredential(firebaseCredential);
            const authUser = userCredential.user;

            console.log("Apple Sign-In success:", authUser.uid);

            // Merge Data if coming from a valid guest session
            // Relaxed check: Allow any non-empty guest ID
            if (guestUserId && guestUserId !== authUser.uid) {
                await mergeData(guestUserId, authUser.uid);
            }

            // Force update user ID immediately
            setUserId(authUser.uid);
            await syncUserIdToStorage(authUser.uid);

            // Sync with RevenueCat (Transfer subscription)
            await logIn(authUser.uid);

            return true;
        } catch (error: any) {
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

    const mergeData = async (guestId: string, authId: string) => {
        try {
            console.log(`Merging guest ${guestId} to auth ${authId}...`);
            const response = await fetchWithToken(`${Config.BACKEND_URL}/auth/merge`, {
                method: 'POST',
                body: JSON.stringify({
                    guest_user_id: guestId
                })
            });

            if (response.ok) {
                console.log("Merge successful");
                // Optional: Alert success for debugging, or kept silent for smooth UX
                // Alert.alert("データ連携", "過去のデータを引き継ぎました。");
            } else {
                const text = await response.text();
                console.error("Merge failed", text);
                Alert.alert("データ連携エラー", "過去のデータの引き継ぎに失敗しました。\n開発者に連絡してください。");
            }
        } catch (e) {
            console.error("Merge network error", e);
            Alert.alert("データ連携エラー", "通信エラーが発生しました。");
        }
    };

    const signOut = async () => {
        try {
            await AsyncStorage.removeItem('triviaState');
            await auth().signOut();
            await rcLogOut(); // Sync RevenueCat logout
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
            console.log("Sending DELETE request to backend...");
            const response = await fetchWithToken(`${Config.BACKEND_URL}/auth/user`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                const text = await response.text();
                console.error("Backend delete failed:", response.status, text);
                throw new Error(`Backend Error: ${text}`);
            }

            console.log("Backend delete success. Cleaning up local data...");

            // 2. Sign out & Cleanup
            await AsyncStorage.removeItem('user_id');
            await AsyncStorage.removeItem('hasSeenTutorial');
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
