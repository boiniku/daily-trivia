import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { Platform, Alert, AppState } from 'react-native';
import Purchases, { CustomerInfo, PurchasesOfferings, PurchasesPackage } from 'react-native-purchases';
import { getAuth, onAuthStateChanged } from '@react-native-firebase/auth';
import { createRevenueCatIdentity } from '../managers/revenueCatIdentity';
import { hasProEntitlement, purchaseRestoreNotice } from '../managers/purchaseRestoreResult';

interface RevenueCatContextType {
    isPro: boolean;
    currentOffering: PurchasesOfferings | null;
    purchasePackage: (pack: PurchasesPackage) => Promise<void>;
    restorePurchases: () => Promise<void>;
    loading: boolean;
    retryLoadOfferings: () => Promise<void>;
    logIn: (userId: string) => Promise<void>;
    logOut: () => Promise<void>;
}
const RevenueCatContext = createContext<RevenueCatContextType | undefined>(undefined);

export const RevenueCatProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [isPro, setIsPro] = useState(false);
    const [currentOffering, setCurrentOffering] = useState<PurchasesOfferings | null>(null);
    const [loading, setLoading] = useState(true);
    const identity = useMemo(() => createRevenueCatIdentity<CustomerInfo>(Purchases,
        Platform.OS === 'ios' ? process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY || ''
            : process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY || '',
        (info) => {
            setIsPro(hasProEntitlement(info));
            setLoading(info === null);
        }), []);

    const loadOfferings = async () => {
        const offerings = await identity.run(() => Purchases.getOfferings());
        setCurrentOffering(offerings);
    };

    useEffect(() => {
        let active = true;
        let initialized = false;
        let listenerAdded = false;
        let generation = 0;
        const auth = getAuth();
        const listener = (_info: CustomerInfo) => {
            // Notifications carry no request identity; read through the barrier.
            void identity.run(() => Purchases.getCustomerInfo()).then((info) => {
                if (active) identity.accept(info);
            }).catch(() => undefined);
        };
        const synchronize = async (id: string | null) => {
            const current = ++generation;
            try {
                await identity.setIdentity(id);
                if (!active || current !== generation) return;
                if (!listenerAdded) {
                    Purchases.addCustomerInfoUpdateListener(listener);
                    listenerAdded = true;
                }
                await loadOfferings();
            } catch (error) {
                console.warn('RevenueCat identity sync failed:', error);
            } finally {
                if (active && current === generation) setLoading(false);
            }
        };
        // Includes the restored Firebase identity at startup.
        const unsubscribe = onAuthStateChanged(auth, (user) => {
            initialized = true;
            void synchronize(user?.uid ?? null);
        });
        const subscription = AppState.addEventListener('change', (state) => {
            if (state === 'active' && initialized) void synchronize(auth.currentUser?.uid ?? null);
        });
        return () => {
            active = false;
            unsubscribe();
            subscription.remove();
            if (listenerAdded) Purchases.removeCustomerInfoUpdateListener(listener);
        };
    }, [identity]);

    const purchasePackage = async (pack: PurchasesPackage) => {
        try {
            const { customerInfo } = await identity.run(() => Purchases.purchasePackage(pack));
            identity.accept(customerInfo);
        } catch (error: any) {
            if (!error.userCancelled) Alert.alert('購入エラー', error.message);
        }
    };
    const restorePurchases = async () => {
        try {
            const info = await identity.run(() => Purchases.restorePurchases());
            identity.accept(info);
            const notice = purchaseRestoreNotice(info);
            Alert.alert(notice.title, notice.message);
        } catch (error: any) { Alert.alert('復元エラー', error.message); }
    };
    const retryLoadOfferings = async () => {
        try {
            await identity.setIdentity(getAuth().currentUser?.uid ?? null);
            await loadOfferings();
        } catch (error: any) { setLoading(false); Alert.alert('通信エラー', error.message); }
    };

    return <RevenueCatContext.Provider value={{
        isPro, currentOffering, loading, purchasePackage, restorePurchases, retryLoadOfferings,
        logIn: (id) => identity.setIdentity(id), logOut: () => identity.setIdentity(null),
    }}>{children}</RevenueCatContext.Provider>;
};

export const useRevenueCat = () => {
    const context = useContext(RevenueCatContext);
    if (!context) throw new Error('useRevenueCat must be used within a RevenueCatProvider');
    return context;
};
