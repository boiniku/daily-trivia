
import React, { createContext, useContext, useEffect, useState } from 'react';
import auth, { FirebaseAuthTypes } from '@react-native-firebase/auth';
import { appleAuth } from '@expo/apple-authentication';
import AsyncStorage from '@react-native-async-storage/async-storage';
import DefaultPreference from 'react-native-default-preference';
import * as Crypto from 'expo-crypto';
import { Alert } from 'react-native';
import { Config } from '../constants/Config';
import { useRevenueCat } from './RevenueCatContext';

interface AuthContextType {
    user: FirebaseAuthTypes.User | null;
    userId: string | null; // Current effective user ID (Guest or Auth)
    loading: boolean;
    signInWithApple: () => Promise<void>;
    signOut: () => Promise<void>;
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

            // Check if existing ID is valid guest ID (UUID)
            // Firebase UIDs are usually 28 chars alphanumeric. UUIDs are 36 chars with hyphens.
            const isGuestUuid = guestId && guestId.includes('-');

            if (!guestId || !isGuestUuid) {
                // If missing or it looks like an old Auth ID (after logout), generate new guest ID
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
        } catch (e) {
            console.error('Failed to sync widget:', e);
        }
    };

    const signInWithApple = async () => {
        try {
            // start a login request
            const appleAuthRequestResponse = await appleAuth.performRequest({
                requestedOperation: appleAuth.Operation.LOGIN,
                requestedScopes: [appleAuth.Scope.FULL_NAME, appleAuth.Scope.EMAIL],
            });

            const { identityToken, nonce } = appleAuthRequestResponse;

            if (!identityToken) {
                throw new Error('Apple Sign-In failed - no identify token returned');
            }

            // create a Firebase credential with the token
            const credential = auth.AppleAuthProvider.credential(identityToken, nonce);

            // Save guest ID before signing in
            const guestUserId = await AsyncStorage.getItem('user_id');

            // sign the node in with the credential
            const userCredential = await auth().signInWithCredential(credential);
            const authUser = userCredential.user;

            console.log("Apple Sign-In success:", authUser.uid);

            // Merge Data if coming from a valid guest session
            if (guestUserId && guestUserId !== authUser.uid && guestUserId.includes('-')) {
                await mergeData(guestUserId, authUser.uid);
            }

            // Force update user ID immediately
            setUserId(authUser.uid);
            await syncUserIdToStorage(authUser.uid);

            // Sync with RevenueCat (Transfer subscription)
            await logIn(authUser.uid);

        } catch (error: any) {
            if (error.code === appleAuth.Error.CANCELED) {
                console.log("User canceled Apple Sign-In");
                return;
            }
            console.error(error);
            Alert.alert("Error", "Failed to sign in with Apple.");
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
            } else {
                const text = await response.text();
                console.error("Merge failed", text);
            }
        } catch (e) {
            console.error("Merge network error", e);
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

    const isGuest = !user;

    return (
        <AuthContext.Provider value={{
            user,
            userId,
            loading,
            signInWithApple,
            signOut,
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
