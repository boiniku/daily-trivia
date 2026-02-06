import React, { createContext, useContext, useEffect, useState } from 'react';
import { Platform, Alert } from 'react-native';
import Purchases, { CustomerInfo, PurchasesOffering } from 'react-native-purchases';

const API_KEYS = {
    ios: process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY || '',
    android: process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY || '',
};

interface RevenueCatContextType {
    isPro: boolean;
    currentOffering: PurchasesOffering | null;
    purchasePackage: (pack: any) => Promise<void>;
    restorePurchases: () => Promise<void>;
    loading: boolean;
}

const RevenueCatContext = createContext<RevenueCatContextType | undefined>(undefined);

export const RevenueCatProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [isPro, setIsPro] = useState(false);
    const [currentOffering, setCurrentOffering] = useState<PurchasesOffering | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const init = async () => {
            try {
                if (Platform.OS === 'ios') {
                    await Purchases.configure({ apiKey: API_KEYS.ios });
                } else if (Platform.OS === 'android') {
                    await Purchases.configure({ apiKey: API_KEYS.android });
                }

                const customerInfo = await Purchases.getCustomerInfo();
                updateCustomerStatus(customerInfo);

                await loadOfferings();
            } catch (e) {
                console.error('RevenueCat init error:', e);
            } finally {
                setLoading(false);
            }
        };

        init();
    }, []);

    const updateCustomerStatus = (customerInfo: CustomerInfo) => {
        // "pro" is the entitlement identifier in RevenueCat
        const isProActive = customerInfo.entitlements.active['pro'] !== undefined;
        setIsPro(isProActive);
    };

    const loadOfferings = async () => {
        try {
            const offerings = await Purchases.getOfferings();
            if (offerings.current) {
                setCurrentOffering(offerings.current);
            }
        } catch (e) {
            console.error('Error loading offerings:', e);
        }
    };

    const purchasePackage = async (pack: any) => {
        try {
            const { customerInfo } = await Purchases.purchasePackage(pack);
            updateCustomerStatus(customerInfo);
        } catch (e: any) {
            if (!e.userCancelled) {
                Alert.alert('Error', e.message);
            }
        }
    };

    const restorePurchases = async () => {
        try {
            const customerInfo = await Purchases.restorePurchases();
            updateCustomerStatus(customerInfo);

            if (customerInfo.entitlements.active['pro']) {
                Alert.alert('復元成功', 'プレミアムプランを復元しました。');
            } else {
                Alert.alert('復元完了', '有効な購入が見つかりませんでした。');
            }
        } catch (e: any) {
            Alert.alert('Error', e.message);
        }
    };

    return (
        <RevenueCatContext.Provider value={{ isPro, currentOffering, purchasePackage, restorePurchases, loading }}>
            {children}
        </RevenueCatContext.Provider>
    );
};

export const useRevenueCat = () => {
    const context = useContext(RevenueCatContext);
    if (!context) {
        throw new Error('useRevenueCat must be used within a RevenueCatProvider');
    }
    return context;
};
