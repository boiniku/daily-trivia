import { Ionicons } from '@expo/vector-icons';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useFocusEffect, useLocalSearchParams } from 'expo-router';
import { ActivityIndicator, AppState, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import MapView, { Circle, Marker, PROVIDER_GOOGLE } from 'react-native-maps';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { getTriviaSpots } from '../../data/triviaSpots';
import { TriviaLocationManager, TriviaLocationStatus } from '../../managers/TriviaLocationManager';
import { TriviaGeofenceManager } from '../../managers/TriviaGeofenceManager';
import { TriviaUnlockManager, calculateDistanceMeters } from '../../managers/TriviaUnlockManager';
import { Coordinates, TriviaSpot } from '../../models/TriviaSpot';
import { Colors, Theme } from '../../constants/Colors';
import { JAPAN_REGIONS, JapanRegionId, getPrefecturesFromLabel } from '../../constants/JapanRegions';
import {
    BANNER_RESERVED_HEIGHT,
    FLOATING_TAB_BAR_HEIGHT,
    getFloatingTabBarBottom,
    getTabScreenAdBottomMargin,
} from '../../constants/Layout';
import { Config } from '../../constants/Config';
import { useRevenueCat } from '../../contexts/RevenueCatContext';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { AdEventType, BannerAd, BannerAdSize, InterstitialAd, TestIds } from 'react-native-google-mobile-ads';

const JAPAN_REGION = {
    latitude: 36.2048,
    longitude: 138.2529,
    latitudeDelta: 14,
    longitudeDelta: 14,
};

const USER_LOCATION_REGION_DELTA = 0.05;
const PREFECTURE_CLUSTER_LATITUDE_DELTA = 2.2;
const MAP_INTERSTITIAL_COOLDOWN_MS = 20 * 60 * 1000;
const MAP_INTERSTITIAL_LAST_SHOWN_KEY = 'map_last_interstitial_shown';
const MAP_INTERSTITIAL_ID = Config.IS_PRODUCTION
    ? (Platform.OS === 'ios' ? Config.INTERSTITIAL_ID_IOS : Config.INTERSTITIAL_ID_ANDROID)
    : TestIds.INTERSTITIAL;
const MAP_BANNER_ID = Config.IS_PRODUCTION
    ? (Platform.OS === 'ios' ? Config.BANNER_ID_IOS : Config.BANNER_ID_ANDROID)
    : TestIds.BANNER;
const mapInterstitial = InterstitialAd.createForAdRequest(MAP_INTERSTITIAL_ID, {
    requestNonPersonalizedAdsOnly: true,
});

type PrefectureSummary = {
    prefecture: string;
    latitude: number;
    longitude: number;
    spots: TriviaSpot[];
};

const formatDistance = (distance?: number) => {
    if (distance == null) return '距離を取得中';
    if (distance < 1000) return `現在地から約${Math.round(distance)}m`;
    return `現在地から約${(distance / 1000).toFixed(1)}km`;
};

const formatUnlockedDate = (date: Date | null) => {
    if (!date) return '';
    return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
};

const getSpotDistance = (spot: TriviaSpot, userLocation: Coordinates | null) => {
    if (!userLocation) return undefined;
    return calculateDistanceMeters(userLocation, {
        latitude: spot.latitude,
        longitude: spot.longitude,
    });
};

const isSpotInRange = (spot: TriviaSpot, userLocation: Coordinates | null) => {
    const distance = getSpotDistance(spot, userLocation);
    return distance != null && distance <= spot.unlockRadiusMeters;
};

export default function TriviaMapScreen() {
    const { spotId: notificationSpotId } = useLocalSearchParams<{ spotId?: string }>();
    const insets = useSafeAreaInsets();
    const mapRef = useRef<MapView | null>(null);
    const spotsRef = useRef<TriviaSpot[]>([]);
    const hasCenteredOnUserRef = useRef(false);
    const isClusterZoomingRef = useRef(false);
    const handledNotificationSpotRef = useRef<string | null>(null);
    const pendingCollectionSpotRef = useRef<TriviaSpot | null>(null);
    const isHandlingCollectionPressRef = useRef(false);
    const { isPro } = useRevenueCat();
    const [spots, setSpots] = useState<TriviaSpot[]>([]);
    const [selectedSpotId, setSelectedSpotId] = useState<string | null>(null);
    const [userLocation, setUserLocation] = useState<Coordinates | null>(null);
    const [locationStatus, setLocationStatus] = useState<TriviaLocationStatus>('unknown');
    const [isLoading, setIsLoading] = useState(true);
    const [viewMode, setViewMode] = useState<'map' | 'collection'>('map');
    const [selectedRegion, setSelectedRegion] = useState<JapanRegionId | 'all'>('all');
    const [selectedPrefecture, setSelectedPrefecture] = useState<string>('すべて');
    const [nearbyOnly, setNearbyOnly] = useState(false);
    const [unlockPulseId, setUnlockPulseId] = useState<string | null>(null);
    const [isPreviewVisible, setIsPreviewVisible] = useState(false);
    const [isDetailVisible, setIsDetailVisible] = useState(false);
    const [isMapReady, setIsMapReady] = useState(false);
    const [mapLatitudeDelta, setMapLatitudeDelta] = useState(JAPAN_REGION.latitudeDelta);
    const [isInterstitialLoaded, setIsInterstitialLoaded] = useState(mapInterstitial.loaded);

    const selectedSpot = useMemo(
        () => spots.find((spot) => spot.id === selectedSpotId) ?? null,
        [selectedSpotId, spots]
    );

    const unlockedCount = spots.filter((spot) => spot.isUnlocked).length;
    const availablePrefectures = useMemo(() => {
        return new Set(spots.flatMap((spot) => getPrefecturesFromLabel(spot.prefecture)));
    }, [spots]);

    const activeRegion = useMemo(
        () => JAPAN_REGIONS.find((region) => region.id === selectedRegion) ?? null,
        [selectedRegion]
    );

    const regionPrefectures = useMemo(
        () => activeRegion?.prefectures.filter((prefecture) => availablePrefectures.has(prefecture)) ?? [],
        [activeRegion, availablePrefectures]
    );

    const filteredSpots = useMemo(() => {
        return spots.filter((spot) => {
            const spotPrefectures = getPrefecturesFromLabel(spot.prefecture);
            if (selectedPrefecture !== 'すべて') {
                if (!spotPrefectures.includes(selectedPrefecture)) return false;
            } else if (activeRegion && !spotPrefectures.some((prefecture) => activeRegion.prefectures.includes(prefecture))) {
                return false;
            }
            if (nearbyOnly) {
                const distance = getSpotDistance(spot, userLocation);
                return distance != null && distance <= 5000;
            }
            return true;
        });
    }, [activeRegion, nearbyOnly, selectedPrefecture, spots, userLocation]);

    const visibleSpotIds = useMemo(
        () => new Set(filteredSpots.map((spot) => spot.id)),
        [filteredSpots]
    );

    const prefectureSummaries = useMemo<PrefectureSummary[]>(() => {
        const grouped = new Map<string, TriviaSpot[]>();
        spots.forEach((spot) => {
            getPrefecturesFromLabel(spot.prefecture).forEach((prefecture) => {
                const prefectureSpots = grouped.get(prefecture) ?? [];
                prefectureSpots.push(spot);
                grouped.set(prefecture, prefectureSpots);
            });
        });

        return Array.from(grouped.entries()).map(([prefecture, prefectureSpots]) => ({
            prefecture,
            latitude: prefectureSpots.reduce((sum, spot) => sum + spot.latitude, 0) / prefectureSpots.length,
            longitude: prefectureSpots.reduce((sum, spot) => sum + spot.longitude, 0) / prefectureSpots.length,
            spots: prefectureSpots,
        }));
    }, [spots]);

    const showPrefecturePins = mapLatitudeDelta >= PREFECTURE_CLUSTER_LATITUDE_DELTA;

    // Keep native MapKit children mounted while filters change. Rapidly adding
    // and removing Marker/Circle children can crash react-native-maps on iOS.
    const selectedCircleCenter = selectedSpot
        ? { latitude: selectedSpot.latitude, longitude: selectedSpot.longitude }
        : { latitude: JAPAN_REGION.latitude, longitude: JAPAN_REGION.longitude };
    const selectedCircleRadius = selectedSpot ? Math.max(1, selectedSpot.unlockRadiusMeters) : 1;

    const collectionSpots = useMemo(
        () => filteredSpots
            .filter((spot) => spot.isUnlocked)
            .sort((a, b) => (b.unlockedAt?.getTime() ?? 0) - (a.unlockedAt?.getTime() ?? 0)),
        [filteredSpots]
    );
    const isCollectionFiltered = selectedRegion !== 'all' || selectedPrefecture !== 'すべて' || nearbyOnly;

    const setTriviaSpots = (nextSpots: TriviaSpot[]) => {
        spotsRef.current = nextSpots;
        setSpots(nextSpots);
    };

    const refreshUnlockedState = async (sourceSpots = spotsRef.current) => {
        const hydrated = await TriviaUnlockManager.hydrateSpots(sourceSpots);
        setTriviaSpots(hydrated);
        return hydrated;
    };

    const handleUnlockedRecords = async (records: { id: string }[], sourceSpots = spotsRef.current) => {
        if (records.length === 0) return;

        const hydrated = await refreshUnlockedState(sourceSpots);
        const firstUnlocked = hydrated.find((spot) => spot.id === records[0].id);
        if (firstUnlocked) {
            setSelectedSpotId(firstUnlocked.id);
            setIsPreviewVisible(true);
            setUnlockPulseId(firstUnlocked.id);
            setTimeout(() => setUnlockPulseId(null), 1600);
        }

    };

    const checkUnlocks = async (location: Coordinates, sourceSpots = spotsRef.current) => {
        const newlyUnlocked = await TriviaUnlockManager.unlockNearbySpots(sourceSpots, location);
        await handleUnlockedRecords(newlyUnlocked, sourceSpots);
        if (newlyUnlocked.length > 0) {
            await TriviaGeofenceManager.refreshRegistration(sourceSpots, location);
        }
        return newlyUnlocked;
    };

    useEffect(() => {
        let isMounted = true;
        let subscription: { remove: () => void } | null = null;

        const initialize = async () => {
            try {
                const baseSpots = await getTriviaSpots();
                const hydrated = await TriviaUnlockManager.hydrateSpots(baseSpots);
                if (!isMounted) return;

                setTriviaSpots(hydrated);
                setSelectedSpotId(null);

                const status = await TriviaLocationManager.requestForegroundPermission();
                if (!isMounted) return;
                setLocationStatus(status);

                if (status === 'granted') {
                    const current = await TriviaLocationManager.getCurrentLocation();
                    if (!isMounted) return;
                    setUserLocation(current);
                    if (current) {
                        await checkUnlocks(current, hydrated);
                        await TriviaGeofenceManager.refreshRegistration(hydrated, current);
                    }

                    const nextSubscription = await TriviaLocationManager.watchLocation((location) => {
                        setUserLocation(location);
                        checkUnlocks(location).catch((error) => {
                            console.error('Trivia map unlock check failed:', error);
                        });
                    });

                    if (!isMounted) {
                        nextSubscription.remove();
                    } else {
                        subscription = nextSubscription;
                    }
                }
            } catch (error) {
                console.error('Trivia map initialization failed:', error);
            } finally {
                if (isMounted) setIsLoading(false);
            }
        };

        initialize();

        return () => {
            isMounted = false;
            subscription?.remove();
        };
    }, []);

    useEffect(() => {
        if (!isMapReady || !userLocation || hasCenteredOnUserRef.current) return;

        const frame = requestAnimationFrame(() => {
            const map = mapRef.current;
            if (!map) return;
            map.animateToRegion(
                {
                    latitude: userLocation.latitude,
                    longitude: userLocation.longitude,
                    latitudeDelta: USER_LOCATION_REGION_DELTA,
                    longitudeDelta: USER_LOCATION_REGION_DELTA,
                },
                550
            );
            hasCenteredOnUserRef.current = true;
        });

        return () => cancelAnimationFrame(frame);
    }, [isMapReady, userLocation]);

    useEffect(() => {
        if (!selectedSpot) return;
        mapRef.current?.animateToRegion(
            {
                latitude: selectedSpot.latitude,
                longitude: selectedSpot.longitude,
                latitudeDelta: 0.02,
                longitudeDelta: 0.02,
            },
            450
        );
    }, [selectedSpotId]);

    useEffect(() => {
        const requestedSpotId = Array.isArray(notificationSpotId) ? notificationSpotId[0] : notificationSpotId;
        if (!requestedSpotId || handledNotificationSpotRef.current === requestedSpotId) return;
        let cancelled = false;

        refreshUnlockedState().then((hydrated) => {
            if (cancelled) return;
            const spot = hydrated.find((item) => item.id === requestedSpotId && item.isUnlocked);
            if (!spot) return;

            handledNotificationSpotRef.current = requestedSpotId;
            setSelectedSpotId(requestedSpotId);
            setIsPreviewVisible(true);
        }).catch((error) => {
            console.error('Notification unlock refresh failed:', error);
        });

        return () => {
            cancelled = true;
        };
    }, [notificationSpotId, spots.length]);

    useFocusEffect(useCallback(() => {
        refreshUnlockedState().catch((error) => {
            console.error('Trivia map focus refresh failed:', error);
        });
    }, []));

    useEffect(() => {
        let refreshTimer: ReturnType<typeof setTimeout> | null = null;
        const subscription = AppState.addEventListener('change', (state) => {
            if (state === 'active') {
                if (refreshTimer) clearTimeout(refreshTimer);
                refreshTimer = setTimeout(() => {
                    refreshUnlockedState().catch((error) => {
                        console.error('Trivia map resume refresh failed:', error);
                    });
                }, 1000);
            }
        });
        return () => {
            if (refreshTimer) clearTimeout(refreshTimer);
            subscription.remove();
        };
    }, []);

    const moveToCurrentLocation = () => {
        if (!userLocation) return;
        hasCenteredOnUserRef.current = true;
        mapRef.current?.animateToRegion(
            {
                latitude: userLocation.latitude,
                longitude: userLocation.longitude,
                latitudeDelta: USER_LOCATION_REGION_DELTA,
                longitudeDelta: USER_LOCATION_REGION_DELTA,
            },
            450
        );
    };

    const selectPrefectureSummary = (summary: PrefectureSummary) => {
        if (isClusterZoomingRef.current) return;
        isClusterZoomingRef.current = true;

        // Let the native marker press finish before changing the map region.
        // Hiding the pressed marker during its own iOS event can crash MapKit.
        requestAnimationFrame(() => {
            mapRef.current?.animateToRegion(
                {
                    latitude: summary.latitude,
                    longitude: summary.longitude,
                    latitudeDelta: 0.8,
                    longitudeDelta: 0.8,
                },
                450
            );
        });
    };

    const openCollectionSpot = useCallback((spot: TriviaSpot) => {
        setSelectedSpotId(spot.id);
        setViewMode('map');
        setIsPreviewVisible(true);
    }, []);

    useEffect(() => {
        if (isPro) {
            pendingCollectionSpotRef.current = null;
            isHandlingCollectionPressRef.current = false;
            setIsInterstitialLoaded(false);
            return;
        }

        if (mapInterstitial.loaded) setIsInterstitialLoaded(true);

        const unsubscribeLoaded = mapInterstitial.addAdEventListener(AdEventType.LOADED, () => {
            setIsInterstitialLoaded(true);
        });
        const openPendingSpot = () => {
            const pendingSpot = pendingCollectionSpotRef.current;
            pendingCollectionSpotRef.current = null;
            isHandlingCollectionPressRef.current = false;
            if (pendingSpot) openCollectionSpot(pendingSpot);
        };
        const unsubscribeClosed = mapInterstitial.addAdEventListener(AdEventType.CLOSED, () => {
            setIsInterstitialLoaded(false);
            openPendingSpot();
            mapInterstitial.load();
        });
        const unsubscribeError = mapInterstitial.addAdEventListener(AdEventType.ERROR, (error) => {
            setIsInterstitialLoaded(false);
            console.error('[Map Ads] Interstitial failed:', error);
            const hadPendingSpot = pendingCollectionSpotRef.current != null;
            openPendingSpot();
            if (hadPendingSpot) {
                AsyncStorage.removeItem(MAP_INTERSTITIAL_LAST_SHOWN_KEY).catch(() => undefined);
            }
        });

        if (!mapInterstitial.loaded) mapInterstitial.load();

        return () => {
            unsubscribeLoaded();
            unsubscribeClosed();
            unsubscribeError();
        };
    }, [isPro, openCollectionSpot]);

    const selectFromCollection = async (spot: TriviaSpot) => {
        if (isHandlingCollectionPressRef.current) return;
        isHandlingCollectionPressRef.current = true;

        if (isPro || (!isInterstitialLoaded && !mapInterstitial.loaded)) {
            isHandlingCollectionPressRef.current = false;
            openCollectionSpot(spot);
            return;
        }

        try {
            const lastShownValue = await AsyncStorage.getItem(MAP_INTERSTITIAL_LAST_SHOWN_KEY);
            const lastShownAt = Number(lastShownValue);
            const isWithinCooldown = Number.isFinite(lastShownAt)
                && lastShownAt > 0
                && Date.now() - lastShownAt < MAP_INTERSTITIAL_COOLDOWN_MS;

            if (isWithinCooldown) {
                isHandlingCollectionPressRef.current = false;
                openCollectionSpot(spot);
                return;
            }

            pendingCollectionSpotRef.current = spot;
            await AsyncStorage.setItem(MAP_INTERSTITIAL_LAST_SHOWN_KEY, Date.now().toString());
            setIsInterstitialLoaded(false);
            mapInterstitial.show();
        } catch (error) {
            console.error('[Map Ads] Interstitial display failed:', error);
            pendingCollectionSpotRef.current = null;
            isHandlingCollectionPressRef.current = false;
            await AsyncStorage.removeItem(MAP_INTERSTITIAL_LAST_SHOWN_KEY).catch(() => undefined);
            openCollectionSpot(spot);
        }
    };

    const selectSpot = (spot: TriviaSpot) => {
        setSelectedSpotId(spot.id);
        setIsPreviewVisible(true);
    };

    const handlePrefectureChange = (prefecture: string) => {
        setSelectedPrefecture(prefecture);
        setSelectedSpotId(null);
        setIsPreviewVisible(false);
        setIsDetailVisible(false);
    };

    const handleRegionChange = (regionId: JapanRegionId | 'all') => {
        setSelectedRegion(regionId);
        handlePrefectureChange('すべて');
    };

    const toggleNearbyOnly = () => {
        setNearbyOnly((value) => !value);
        setSelectedSpotId(null);
        setIsPreviewVisible(false);
        setIsDetailVisible(false);
    };

    const getPinColor = (spot: TriviaSpot) => {
        if (spot.isUnlocked) return Colors.light.primary;
        if (isSpotInRange(spot, userLocation)) return Colors.light.secondary;
        return '#8E8E93';
    };

    const getReadableState = (spot: TriviaSpot) => {
        const distance = getSpotDistance(spot, userLocation);
        const inRange = isSpotInRange(spot, userLocation);
        const canRead = spot.isUnlocked || inRange;

        return { distance, inRange, canRead };
    };

    const renderSpotPreview = () => {
        if (!selectedSpot) return null;

        const { distance, canRead } = getReadableState(selectedSpot);
        const bodyText = canRead
            ? selectedSpot.description
            : '現地に近づくと本文を読むことができます。';

        return (
            <View style={[
                styles.previewSheet,
                { bottom: isPro ? getFloatingTabBarBottom(insets) + FLOATING_TAB_BAR_HEIGHT + 12 : 12 },
            ]}>
                <Pressable style={styles.closeButton} onPress={() => setIsPreviewVisible(false)} hitSlop={10}>
                    <Ionicons name="close" size={20} color={Colors.light.subtext} />
                </Pressable>
                <Pressable
                    style={styles.previewBody}
                    onPress={() => setIsDetailVisible(true)}
                >
                    <View style={styles.detailHeader}>
                        <View style={styles.detailTitleBlock}>
                            <Text style={styles.detailTitle}>{selectedSpot.title}</Text>
                            <Text style={styles.detailMeta}>
                                {[selectedSpot.prefecture, selectedSpot.address, selectedSpot.category].filter(Boolean).join(' / ')}
                            </Text>
                        </View>
                        <View style={[styles.statusPill, canRead ? styles.unlockedPill : styles.lockedPill]}>
                            <Ionicons name={canRead ? 'checkmark-circle' : 'lock-closed'} size={15} color={canRead ? '#FFFFFF' : Colors.light.subtext} />
                            <Text style={[styles.statusText, canRead ? styles.unlockedStatusText : styles.lockedStatusText]}>
                                {canRead ? '解放済み' : '未解放'}
                            </Text>
                        </View>
                    </View>
                    <Text style={styles.distanceText}>{formatDistance(distance)}</Text>
                    <Text style={canRead ? styles.previewDescription : styles.previewLockedText} numberOfLines={3}>
                        {bodyText}
                    </Text>
                    <View style={styles.previewFooter}>
                        <Text style={styles.previewFooterText}>タップして詳細を見る</Text>
                        <Ionicons name="chevron-forward" size={18} color={Colors.light.primary} />
                    </View>
                </Pressable>
            </View>
        );
    };

    const renderSpotDetailModal = () => {
        if (!selectedSpot) return null;

        const { distance, canRead } = getReadableState(selectedSpot);

        return (
            <Modal
                visible={isDetailVisible}
                animationType="slide"
                presentationStyle="pageSheet"
                onRequestClose={() => setIsDetailVisible(false)}
            >
                <SafeAreaView style={styles.modalContainer}>
                    <View style={styles.modalHeader}>
                        <Pressable style={styles.modalIconButton} onPress={() => setIsDetailVisible(false)}>
                            <Ionicons name="chevron-down" size={24} color={Colors.light.text} />
                        </Pressable>
                        <Text style={styles.modalHeaderTitle}>スポット詳細</Text>
                        <View style={styles.modalIconButton} />
                    </View>

                    <ScrollView contentContainerStyle={styles.modalContent}>
                        <Text style={styles.modalTitle}>{selectedSpot.title}</Text>
                        <Text style={styles.detailMeta}>
                            {[selectedSpot.prefecture, selectedSpot.address, selectedSpot.category].filter(Boolean).join(' / ')}
                        </Text>

                        <View style={styles.modalStatusRow}>
                            <View style={[styles.statusPill, canRead ? styles.unlockedPill : styles.lockedPill]}>
                                <Ionicons name={canRead ? 'checkmark-circle' : 'lock-closed'} size={15} color={canRead ? '#FFFFFF' : Colors.light.subtext} />
                                <Text style={[styles.statusText, canRead ? styles.unlockedStatusText : styles.lockedStatusText]}>
                                    {canRead ? '解放済み' : '未解放'}
                                </Text>
                            </View>
                            <Text style={styles.distanceText}>{formatDistance(distance)}</Text>
                        </View>

                        <View style={[styles.unlockRadiusBox, unlockPulseId === selectedSpot.id && styles.unlockPulseBox]}>
                            <Ionicons name={canRead ? 'sparkles' : 'navigate'} size={18} color={canRead ? Colors.light.primary : Colors.light.secondary} />
                            <Text style={styles.unlockRadiusText}>
                                {`解放範囲: 半径${Math.round(selectedSpot.unlockRadiusMeters)}m`}
                            </Text>
                        </View>

                        {canRead ? (
                            <View>
                                <Text style={styles.sectionLabel}>本文</Text>
                                <Text style={styles.description}>{selectedSpot.description}</Text>
                                {selectedSpot.explanation ? (
                                    <>
                                        <Text style={styles.sectionLabel}>解説</Text>
                                        <Text style={styles.explanation}>{selectedSpot.explanation}</Text>
                                    </>
                                ) : null}
                            </View>
                        ) : (
                            <View style={styles.lockedMessage}>
                                <Text style={styles.lockedTitle}>この雑学はまだ解放されていません。</Text>
                                <Text style={styles.lockedBody}>現地に近づくと読むことができます。</Text>
                            </View>
                        )}

                        {selectedSpot.isUnlocked && selectedSpot.unlockedAt && (
                            <View style={styles.savedBox}>
                                <Ionicons name="albums" size={18} color={Colors.light.primary} />
                                <Text style={styles.savedText}>
                                    {`解放済み雑学に保存されています / ${formatUnlockedDate(selectedSpot.unlockedAt)} 解放`}
                                </Text>
                            </View>
                        )}
                    </ScrollView>
                </SafeAreaView>
            </Modal>
        );
    };

    if (Platform.OS === 'web') {
        return (
            <SafeAreaView style={[styles.container, styles.center]}>
                <Ionicons name="map-outline" size={42} color={Colors.light.primary} />
                <Text style={styles.webTitle}>雑学MAP</Text>
                <Text style={styles.webText}>マップと位置情報による解放はiOS/Androidアプリで利用できます。</Text>
            </SafeAreaView>
        );
    }

    return (
        <SafeAreaView style={styles.container}>
            <View style={styles.header}>
                <View>
                    <Text style={styles.headerTitle}>雑学MAP</Text>
                    <Text style={styles.headerSubTitle}>{unlockedCount}/{spots.length} 解放済み</Text>
                </View>
                <View style={styles.segmentedControl}>
                    <Pressable
                        style={[styles.segmentButton, viewMode === 'map' && styles.segmentButtonActive]}
                        onPress={() => setViewMode('map')}
                    >
                        <Ionicons name="map" size={18} color={viewMode === 'map' ? '#FFFFFF' : Colors.light.primary} />
                    </Pressable>
                    <Pressable
                        style={[styles.segmentButton, viewMode === 'collection' && styles.segmentButtonActive]}
                        onPress={() => setViewMode('collection')}
                    >
                        <Ionicons name="albums" size={18} color={viewMode === 'collection' ? '#FFFFFF' : Colors.light.primary} />
                    </Pressable>
                </View>
            </View>

            {locationStatus === 'denied' && (
                <View style={styles.permissionBanner}>
                    <Ionicons name="location-outline" size={18} color={Colors.light.primary} />
                    <Text style={styles.permissionText}>位置情報を許可すると、近くのご当地雑学を解放できます。</Text>
                </View>
            )}

            <View style={styles.filterPanel}>
                <View style={styles.filterRow}>
                    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterContent}>
                        <TouchableOpacity
                            style={[styles.filterChip, selectedRegion === 'all' && styles.filterChipActive]}
                            onPress={() => handleRegionChange('all')}
                            activeOpacity={0.75}
                        >
                            <Text style={[styles.filterText, selectedRegion === 'all' && styles.filterTextActive]}>
                                全国
                            </Text>
                        </TouchableOpacity>
                        {JAPAN_REGIONS.map((region) => (
                            <TouchableOpacity
                                key={region.id}
                                style={[styles.filterChip, selectedRegion === region.id && styles.filterChipActive]}
                                onPress={() => handleRegionChange(region.id)}
                                activeOpacity={0.75}
                            >
                                <Text style={[styles.filterText, selectedRegion === region.id && styles.filterTextActive]}>
                                    {region.label}
                                </Text>
                            </TouchableOpacity>
                        ))}
                    </ScrollView>
                    <TouchableOpacity
                        style={[styles.nearbyButton, nearbyOnly && styles.nearbyButtonActive]}
                        onPress={toggleNearbyOnly}
                        activeOpacity={0.75}
                    >
                        <Ionicons name="locate" size={16} color={nearbyOnly ? '#FFFFFF' : Colors.light.primary} />
                        <Text style={[styles.nearbyButtonText, nearbyOnly && styles.nearbyButtonTextActive]}>近く</Text>
                    </TouchableOpacity>
                </View>

                {activeRegion ? (
                    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.prefectureFilterContent}>
                        <TouchableOpacity
                            style={[styles.prefectureChip, selectedPrefecture === 'すべて' && styles.prefectureChipActive]}
                            onPress={() => handlePrefectureChange('すべて')}
                            activeOpacity={0.75}
                        >
                            <Text style={[styles.prefectureText, selectedPrefecture === 'すべて' && styles.prefectureTextActive]}>
                                {activeRegion.label}全体
                            </Text>
                        </TouchableOpacity>
                        {regionPrefectures.map((prefecture) => (
                            <TouchableOpacity
                                key={prefecture}
                                style={[styles.prefectureChip, selectedPrefecture === prefecture && styles.prefectureChipActive]}
                                onPress={() => handlePrefectureChange(prefecture)}
                                activeOpacity={0.75}
                            >
                                <Text style={[styles.prefectureText, selectedPrefecture === prefecture && styles.prefectureTextActive]}>
                                    {prefecture}
                                </Text>
                            </TouchableOpacity>
                        ))}
                    </ScrollView>
                ) : null}
            </View>

            {viewMode === 'map' ? (
                <View style={styles.mapWrap}>
                    <MapView
                        ref={mapRef}
                        style={StyleSheet.absoluteFill}
                        initialRegion={JAPAN_REGION}
                        provider={Platform.OS === 'android' ? PROVIDER_GOOGLE : undefined}
                        showsUserLocation={locationStatus === 'granted'}
                        showsMyLocationButton={false}
                        onMapReady={() => setIsMapReady(true)}
                        onRegionChangeComplete={(region) => {
                            setMapLatitudeDelta(region.latitudeDelta);
                            isClusterZoomingRef.current = false;
                        }}
                    >
                        {spots.map((spot) => {
                            const isVisible = !showPrefecturePins && visibleSpotIds.has(spot.id);
                            return (
                                <Marker
                                    key={spot.id}
                                    coordinate={{ latitude: spot.latitude, longitude: spot.longitude }}
                                    anchor={{ x: 0.5, y: 1 }}
                                    zIndex={1}
                                    onPress={() => {
                                        if (isVisible) selectSpot(spot);
                                    }}
                                >
                                    <View
                                        pointerEvents="none"
                                        style={[
                                            styles.spotMarker,
                                            { backgroundColor: getPinColor(spot) },
                                            !isVisible && styles.mapMarkerHidden,
                                        ]}
                                    >
                                        <Ionicons name="bulb" size={15} color="#FFFFFF" />
                                    </View>
                                </Marker>
                            );
                        })}
                        {prefectureSummaries.map((summary) => {
                            const summarySpots = summary.spots.filter((spot) => visibleSpotIds.has(spot.id));
                            const totalCount = summarySpots.length;
                            const unlockedCount = summarySpots.filter((spot) => spot.isUnlocked).length;
                            const isVisible = showPrefecturePins && totalCount > 0;

                            return (
                                <Marker
                                    key={`prefecture-${summary.prefecture}`}
                                    coordinate={{ latitude: summary.latitude, longitude: summary.longitude }}
                                    anchor={{ x: 0.5, y: 0.5 }}
                                    stopPropagation
                                    zIndex={2}
                                    onPress={() => {
                                        if (isVisible) selectPrefectureSummary(summary);
                                    }}
                                >
                                    <View
                                        pointerEvents="none"
                                        style={[styles.prefectureMarker, !isVisible && styles.mapMarkerHidden]}
                                    >
                                        <Text style={styles.prefectureMarkerLabel}>{summary.prefecture}</Text>
                                        <Text style={styles.prefectureMarkerCount}>{`${unlockedCount}/${totalCount}`}</Text>
                                    </View>
                                </Marker>
                            );
                        })}
                        <Circle
                            center={selectedCircleCenter}
                            radius={selectedCircleRadius}
                            strokeColor={selectedSpot ? 'rgba(230, 0, 18, 0.45)' : 'rgba(0, 0, 0, 0)'}
                            fillColor={selectedSpot ? 'rgba(230, 0, 18, 0.08)' : 'rgba(0, 0, 0, 0)'}
                        />
                    </MapView>

                    {isLoading && (
                        <View style={styles.loadingOverlay}>
                            <ActivityIndicator color={Colors.light.primary} />
                            <Text style={styles.loadingText}>MAPを準備中...</Text>
                        </View>
                    )}

                    <Pressable style={styles.currentLocationButton} onPress={moveToCurrentLocation}>
                        <Ionicons name="navigate" size={22} color={Colors.light.primary} />
                    </Pressable>

                    {isPreviewVisible && renderSpotPreview()}
                    {renderSpotDetailModal()}
                </View>
            ) : (
                <ScrollView
                    style={styles.collectionList}
                    contentContainerStyle={[
                        styles.collectionContent,
                        { paddingBottom: isPro ? getFloatingTabBarBottom(insets) + FLOATING_TAB_BAR_HEIGHT + 24 : 24 },
                    ]}
                >
                    <Text style={styles.collectionNote}>MAPで解放した雑学だけを保存します。過去に見た雑学には追加されません。</Text>
                    {collectionSpots.length === 0 ? (
                        <View style={styles.emptyCollection}>
                            <Ionicons
                                name={isCollectionFiltered ? "filter-outline" : "lock-closed-outline"}
                                size={40}
                                color={Colors.light.subtext}
                            />
                            <Text style={styles.emptyTitle}>
                                {isCollectionFiltered ? '条件に合う解放済み雑学はありません' : '解放済み雑学はまだありません'}
                            </Text>
                            <Text style={styles.emptyBody}>
                                {isCollectionFiltered
                                    ? '上の地域・都道府県・近くフィルターを変更してください。'
                                    : '現地に近づくと、ここにコレクションとして保存されます。'}
                            </Text>
                        </View>
                    ) : (
                        collectionSpots.map((spot) => (
                            <Pressable key={spot.id} style={styles.collectionItem} onPress={() => selectFromCollection(spot)}>
                                <View style={styles.collectionIcon}>
                                    <Ionicons name="checkmark" size={20} color="#FFFFFF" />
                                </View>
                                <View style={styles.collectionTextBlock}>
                                    <Text style={styles.collectionTitle}>{spot.title}</Text>
                                    <Text style={styles.collectionMeta}>
                                        {`${spot.prefecture ?? ''} / ${formatUnlockedDate(spot.unlockedAt)} 解放`}
                                    </Text>
                                    <Text style={styles.collectionSnippet} numberOfLines={2}>{spot.description}</Text>
                                </View>
                                <Ionicons name="chevron-forward" size={20} color={Colors.light.subtext} />
                            </Pressable>
                        ))
                    )}
                </ScrollView>
            )}

            {!isPro ? (
                <View style={[
                    styles.adsContainer,
                    {
                        minHeight: BANNER_RESERVED_HEIGHT,
                        marginBottom: getTabScreenAdBottomMargin(insets),
                    },
                ]}>
                    <BannerAd
                        unitId={MAP_BANNER_ID}
                        size={BannerAdSize.ANCHORED_ADAPTIVE_BANNER}
                        requestOptions={{ requestNonPersonalizedAdsOnly: true }}
                    />
                </View>
            ) : null}
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: Colors.light.background,
    },
    center: {
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
    },
    header: {
        paddingHorizontal: 20,
        paddingTop: 12,
        paddingBottom: 12,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    headerTitle: {
        fontSize: 28,
        fontWeight: '900',
        color: Colors.light.primary,
        fontStyle: 'italic',
    },
    headerSubTitle: {
        marginTop: 2,
        fontSize: 13,
        fontWeight: '700',
        color: Colors.light.subtext,
    },
    segmentedControl: {
        flexDirection: 'row',
        backgroundColor: '#FFFFFF',
        borderRadius: 24,
        padding: 4,
        ...Theme.shadow.small,
    },
    segmentButton: {
        width: 42,
        height: 36,
        borderRadius: 18,
        alignItems: 'center',
        justifyContent: 'center',
    },
    segmentButtonActive: {
        backgroundColor: Colors.light.primary,
    },
    permissionBanner: {
        marginHorizontal: 20,
        marginBottom: 10,
        padding: 12,
        borderRadius: 18,
        backgroundColor: '#FFF4F5',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        borderWidth: 1,
        borderColor: '#FFD1D6',
    },
    permissionText: {
        flex: 1,
        fontSize: 13,
        lineHeight: 18,
        fontWeight: '700',
        color: Colors.light.text,
    },
    filterPanel: {
        paddingBottom: 10,
        gap: 8,
    },
    filterRow: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingLeft: 20,
        paddingRight: 16,
        gap: 10,
    },
    filterContent: {
        gap: 8,
        paddingRight: 4,
    },
    filterChip: {
        height: 34,
        paddingHorizontal: 14,
        borderRadius: 17,
        backgroundColor: '#FFFFFF',
        alignItems: 'center',
        justifyContent: 'center',
        borderWidth: 1,
        borderColor: Colors.light.border,
    },
    filterChipActive: {
        backgroundColor: Colors.light.primary,
        borderColor: Colors.light.primary,
    },
    filterText: {
        fontSize: 13,
        fontWeight: '800',
        color: Colors.light.text,
    },
    filterTextActive: {
        color: '#FFFFFF',
    },
    prefectureFilterContent: {
        gap: 8,
        paddingHorizontal: 20,
    },
    prefectureChip: {
        height: 30,
        paddingHorizontal: 12,
        borderRadius: 15,
        backgroundColor: '#F2F4F5',
        alignItems: 'center',
        justifyContent: 'center',
    },
    prefectureChipActive: {
        backgroundColor: Colors.light.secondary,
    },
    prefectureText: {
        fontSize: 12,
        fontWeight: '800',
        color: Colors.light.subtext,
    },
    prefectureTextActive: {
        color: '#FFFFFF',
    },
    nearbyButton: {
        minWidth: 58,
        height: 34,
        borderRadius: 17,
        backgroundColor: '#FFFFFF',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'row',
        gap: 4,
        paddingHorizontal: 10,
        borderWidth: 1,
        borderColor: Colors.light.border,
    },
    nearbyButtonActive: {
        backgroundColor: Colors.light.primary,
        borderColor: Colors.light.primary,
    },
    nearbyButtonText: {
        fontSize: 12,
        fontWeight: '900',
        color: Colors.light.primary,
    },
    nearbyButtonTextActive: {
        color: '#FFFFFF',
    },
    mapWrap: {
        flex: 1,
        overflow: 'hidden',
        backgroundColor: '#E9EEF1',
    },
    adsContainer: {
        width: '100%',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: Colors.light.background,
    },
    loadingOverlay: {
        position: 'absolute',
        top: 16,
        alignSelf: 'center',
        backgroundColor: '#FFFFFF',
        borderRadius: 20,
        paddingHorizontal: 14,
        paddingVertical: 10,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        ...Theme.shadow.small,
    },
    loadingText: {
        fontSize: 13,
        fontWeight: '700',
        color: Colors.light.subtext,
    },
    currentLocationButton: {
        position: 'absolute',
        right: 18,
        top: 18,
        width: 48,
        height: 48,
        borderRadius: 24,
        backgroundColor: '#FFFFFF',
        alignItems: 'center',
        justifyContent: 'center',
        ...Theme.shadow.medium,
    },
    spotMarker: {
        width: 34,
        height: 34,
        borderRadius: 17,
        alignItems: 'center',
        justifyContent: 'center',
        borderWidth: 3,
        borderColor: '#FFFFFF',
        ...Theme.shadow.small,
    },
    mapMarkerHidden: {
        opacity: 0,
    },
    prefectureMarker: {
        minWidth: 58,
        minHeight: 44,
        paddingHorizontal: 9,
        paddingVertical: 5,
        borderRadius: 16,
        backgroundColor: '#FFFFFF',
        alignItems: 'center',
        justifyContent: 'center',
        borderWidth: 2,
        borderColor: Colors.light.primary,
        ...Theme.shadow.small,
    },
    prefectureMarkerLabel: {
        fontSize: 10,
        lineHeight: 13,
        fontWeight: '900',
        color: Colors.light.text,
    },
    prefectureMarkerCount: {
        marginTop: 1,
        fontSize: 14,
        lineHeight: 17,
        fontWeight: '900',
        color: Colors.light.primary,
    },
    previewSheet: {
        position: 'absolute',
        left: 16,
        right: 16,
        backgroundColor: '#FFFFFF',
        borderRadius: 28,
        padding: 14,
        ...Theme.shadow.medium,
        borderWidth: 1,
        borderColor: Colors.light.border,
    },
    previewBody: {
        paddingRight: 24,
    },
    closeButton: {
        position: 'absolute',
        top: 12,
        right: 12,
        zIndex: 5,
        width: 30,
        height: 30,
        borderRadius: 15,
        backgroundColor: Colors.light.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    detailHeader: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 12,
    },
    detailTitleBlock: {
        flex: 1,
    },
    detailTitle: {
        fontSize: 20,
        lineHeight: 26,
        fontWeight: '900',
        color: Colors.light.text,
    },
    detailMeta: {
        marginTop: 4,
        fontSize: 13,
        fontWeight: '700',
        color: Colors.light.subtext,
    },
    statusPill: {
        minHeight: 30,
        borderRadius: 15,
        paddingHorizontal: 10,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
    },
    unlockedPill: {
        backgroundColor: Colors.light.primary,
    },
    lockedPill: {
        backgroundColor: Colors.light.surface,
    },
    statusText: {
        fontSize: 12,
        fontWeight: '900',
    },
    unlockedStatusText: {
        color: '#FFFFFF',
    },
    lockedStatusText: {
        color: Colors.light.subtext,
    },
    distanceText: {
        marginTop: 10,
        fontSize: 14,
        fontWeight: '800',
        color: Colors.light.secondary,
    },
    previewDescription: {
        marginTop: 10,
        fontSize: 14,
        lineHeight: 20,
        fontWeight: '700',
        color: Colors.light.text,
    },
    previewLockedText: {
        marginTop: 10,
        fontSize: 14,
        lineHeight: 20,
        fontWeight: '700',
        color: Colors.light.subtext,
    },
    previewFooter: {
        marginTop: 12,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'flex-end',
        gap: 4,
    },
    previewFooterText: {
        fontSize: 13,
        fontWeight: '900',
        color: Colors.light.primary,
    },
    unlockRadiusBox: {
        marginTop: 12,
        padding: 12,
        borderRadius: 18,
        backgroundColor: Colors.light.surface,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    unlockPulseBox: {
        backgroundColor: '#FFF7CC',
        borderWidth: 1,
        borderColor: Colors.light.accent,
    },
    unlockRadiusText: {
        flex: 1,
        fontSize: 13,
        fontWeight: '800',
        color: Colors.light.text,
    },
    description: {
        marginTop: 8,
        fontSize: 15,
        lineHeight: 23,
        fontWeight: '600',
        color: Colors.light.text,
    },
    sectionLabel: {
        marginTop: 18,
        fontSize: 13,
        fontWeight: '900',
        color: Colors.light.subtext,
    },
    explanation: {
        marginTop: 8,
        fontSize: 15,
        lineHeight: 23,
        fontWeight: '600',
        color: Colors.light.text,
    },
    modalContainer: {
        flex: 1,
        backgroundColor: Colors.light.background,
    },
    modalHeader: {
        height: 56,
        paddingHorizontal: 14,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        backgroundColor: '#FFFFFF',
        borderBottomWidth: 1,
        borderBottomColor: Colors.light.border,
    },
    modalIconButton: {
        width: 42,
        height: 42,
        borderRadius: 21,
        alignItems: 'center',
        justifyContent: 'center',
    },
    modalHeaderTitle: {
        fontSize: 16,
        fontWeight: '900',
        color: Colors.light.text,
    },
    modalContent: {
        padding: 20,
        paddingBottom: 40,
    },
    modalTitle: {
        fontSize: 26,
        lineHeight: 34,
        fontWeight: '900',
        color: Colors.light.text,
    },
    modalStatusRow: {
        marginTop: 14,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
    },
    lockedMessage: {
        marginTop: 14,
        padding: 14,
        borderRadius: 20,
        backgroundColor: '#FAFAFA',
        borderWidth: 1,
        borderColor: Colors.light.border,
    },
    lockedTitle: {
        fontSize: 15,
        fontWeight: '900',
        color: Colors.light.text,
    },
    lockedBody: {
        marginTop: 5,
        fontSize: 14,
        lineHeight: 20,
        fontWeight: '700',
        color: Colors.light.subtext,
    },
    savedBox: {
        marginTop: 16,
        padding: 14,
        borderRadius: 18,
        backgroundColor: '#FFF4F5',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        borderWidth: 1,
        borderColor: '#FFD1D6',
    },
    savedText: {
        flex: 1,
        fontSize: 13,
        lineHeight: 19,
        fontWeight: '800',
        color: Colors.light.text,
    },
    collectionList: {
        flex: 1,
    },
    collectionContent: {
        padding: 20,
        gap: 12,
    },
    collectionNote: {
        fontSize: 13,
        lineHeight: 19,
        fontWeight: '800',
        color: Colors.light.subtext,
        backgroundColor: '#FFFFFF',
        borderRadius: 18,
        padding: 12,
        borderWidth: 1,
        borderColor: Colors.light.border,
    },
    emptyCollection: {
        alignItems: 'center',
        justifyContent: 'center',
        padding: 28,
        borderRadius: 28,
        backgroundColor: '#FFFFFF',
        borderWidth: 1,
        borderColor: Colors.light.border,
    },
    emptyTitle: {
        marginTop: 12,
        fontSize: 18,
        fontWeight: '900',
        color: Colors.light.text,
        textAlign: 'center',
    },
    emptyBody: {
        marginTop: 8,
        fontSize: 14,
        lineHeight: 21,
        fontWeight: '700',
        color: Colors.light.subtext,
        textAlign: 'center',
    },
    collectionItem: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        backgroundColor: '#FFFFFF',
        borderRadius: 24,
        padding: 14,
        borderWidth: 1,
        borderColor: Colors.light.border,
        ...Theme.shadow.small,
    },
    collectionIcon: {
        width: 36,
        height: 36,
        borderRadius: 18,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: Colors.light.primary,
    },
    collectionTextBlock: {
        flex: 1,
        gap: 3,
    },
    collectionTitle: {
        fontSize: 16,
        fontWeight: '900',
        color: Colors.light.text,
    },
    collectionMeta: {
        fontSize: 12,
        fontWeight: '800',
        color: Colors.light.secondary,
    },
    collectionSnippet: {
        fontSize: 13,
        lineHeight: 18,
        fontWeight: '600',
        color: Colors.light.subtext,
    },
    webTitle: {
        marginTop: 12,
        fontSize: 24,
        fontWeight: '900',
        color: Colors.light.primary,
    },
    webText: {
        marginTop: 8,
        fontSize: 15,
        lineHeight: 22,
        fontWeight: '700',
        color: Colors.light.subtext,
        textAlign: 'center',
    },
});
