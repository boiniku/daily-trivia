import React, { createContext, useContext, useEffect, useState } from 'react';
import { Platform, Alert } from 'react-native';
import Purchases, { CustomerInfo, PurchasesOfferings, PurchasesPackage } from 'react-native-purchases';

const API_KEYS = {
    ios: process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY || '',
    android: process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY || '',
};

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

    useEffect(() => {
        let customerInfoUpdated: ((info: CustomerInfo) => void) | null = null;
        let listenerRegistered = false;

        const init = async () => {
            try {
                // Enable debug logs before setup
                await Purchases.setLogLevel(Purchases.LOG_LEVEL.DEBUG);

                let apiKey = '';
                if (Platform.OS === 'ios') {
                    apiKey = API_KEYS.ios;
                } else if (Platform.OS === 'android') {
                    apiKey = API_KEYS.android;
                }

                if (!apiKey) {
                    console.warn('RevenueCat API key not found for platform:', Platform.OS);
                    setLoading(false);
                    return;
                }

                await Purchases.configure({ apiKey });

                // Register listener AFTER configure() to avoid native crash
                customerInfoUpdated = (info: CustomerInfo) => {
                    updateCustomerStatus(info);
                };
                Purchases.addCustomerInfoUpdateListener(customerInfoUpdated);
                listenerRegistered = true;

                const customerInfo = await Purchases.getCustomerInfo();
                updateCustomerStatus(customerInfo);

                await loadOfferings();
            } catch (e) {
                console.error('RevenueCat init error:', e);
            } finally {
                setLoading(false);
            }
        };

        // Delay initialization to prevent startup crash
        setTimeout(() => {
            init();
        }, 1000);

        return () => {
            if (listenerRegistered && customerInfoUpdated) {
                Purchases.removeCustomerInfoUpdateListener(customerInfoUpdated);
            }
        };
    }, []);

    const updateCustomerStatus = (customerInfo: CustomerInfo) => {
        // "pro" is the entitlement identifier in RevenueCat
        const isProActive = customerInfo.entitlements.active['pro'] !== undefined;
        setIsPro(isProActive);
    };

    const loadOfferings = async () => {
        try {
            setLoading(true);
            const offerings = await Purchases.getOfferings();
            console.log('Offerings loaded:', offerings);
            if (offerings.current) {
                if (offerings.current.availablePackages.length === 0) {
                    console.warn('RevenueCat: Offering has no packages');
                }
                setCurrentOffering(offerings);
            } else {
                console.log('No current offering configured in RevenueCat console');
                console.warn('RevenueCat: No current offering configured');
            }
        } catch (e: any) {
            console.error('Error loading offerings:', e);
        } finally {
            setLoading(false);
        }
    };

    // Expose loadOfferings for manual retry
    const retryLoadOfferings = () => loadOfferings();

    const purchasePackage = async (pack: PurchasesPackage) => {
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
            Alert.alert('Success', 'Purchases restored successfully!');
        } catch (e: any) {
            Alert.alert('Error', e.message);
        }
    };

    const logIn = async (userId: string) => {
        try {
            const { customerInfo } = await Purchases.logIn(userId);
            updateCustomerStatus(customerInfo);
            console.log("RevenueCat logged in as:", userId);
        } catch (e: any) {
            console.error("RevenueCat login error:", e);
        }
    };

    const logOut = async () => {
        try {
            const customerInfo = await Purchases.logOut();
            updateCustomerStatus(customerInfo);
            console.log("RevenueCat logged out");
        } catch (e: any) {
            console.error("RevenueCat logout error:", e);
        }
    };

    return (
        <RevenueCatContext.Provider value={{ isPro, currentOffering, purchasePackage, restorePurchases, loading, retryLoadOfferings, logIn, logOut }}>
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
