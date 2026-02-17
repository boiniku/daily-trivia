
import React, { createContext, useContext, useEffect, useState } from 'react';
import auth, { FirebaseAuthTypes } from '@react-native-firebase/auth';
import * as AppleAuthentication from 'expo-apple-authentication';
import AsyncStorage from '@react-native-async-storage/async-storage';
import DefaultPreference from 'react-native-default-preference';
import * as Crypto from 'expo-crypto';
import { Alert } from 'react-native';
import { Config } from '../constants/Config';
import { useRevenueCat } from './RevenueCatContext';
import { reloadAllTimelines } from '../modules/widget-control';

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
        // Initial setup for existing user ID
        initializeUser();
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
            // Guest mode
            let guestId = await AsyncStorage.getItem('user_id');

            // Relaxed check: Just ensure it exists
            if (!guestId) {
                // If missing, generate new guest ID
                const newGuestId = Crypto.randomUUID();
                await syncUserIdToStorage(newGuestId);
                setUserId(newGuestId);
            } else {
                setUserId(guestId);
            }
        }
    };



    const syncUserIdToStorage = async (id: string) => {
        await AsyncStorage.setItem('user_id', id);
        // Sync with Widget
        try {
            await DefaultPreference.setName('group.com.dailytrivia.app');
            await DefaultPreference.set('user_id', id);

            // Force Widget Reload immediately
            console.log("Triggering widget timeline reload...");
            try {
                reloadAllTimelines();
                console.log("Widget reload triggered successfully.");
            } catch (wError) {
                console.warn("Failed to trigger widget reload:", wError);
            }

        } catch (e) {
            console.error('Failed to sync widget:', e);
        }
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
            const response = await fetch(`${Config.BACKEND_URL}/auth/merge`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    guest_user_id: guestId,
                    auth_user_id: authId
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
            const response = await fetch(`${Config.BACKEND_URL}/auth/user`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ user_id: userId })
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
            await AsyncStorage.removeItem('triviaState');

            try {
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

    const isGuest = !user;

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
