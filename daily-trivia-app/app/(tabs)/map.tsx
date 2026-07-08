import { Ionicons } from '@expo/vector-icons';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import MapView, { Circle, Marker, PROVIDER_GOOGLE } from 'react-native-maps';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { getTriviaSpots } from '../../data/triviaSpots';
import { TriviaLocationManager, TriviaLocationStatus } from '../../managers/TriviaLocationManager';
import { TriviaNotificationManager } from '../../managers/TriviaNotificationManager';
import { TriviaUnlockManager, calculateDistanceMeters } from '../../managers/TriviaUnlockManager';
import { Coordinates, TriviaSpot } from '../../models/TriviaSpot';
import { Colors, Theme } from '../../constants/Colors';
import { getFloatingTabBarBottom, FLOATING_TAB_BAR_HEIGHT } from '../../constants/Layout';

const JAPAN_REGION = {
    latitude: 36.2048,
    longitude: 138.2529,
    latitudeDelta: 14,
    longitudeDelta: 14,
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
    const insets = useSafeAreaInsets();
    const mapRef = useRef<MapView | null>(null);
    const spotsRef = useRef<TriviaSpot[]>([]);
    const [spots, setSpots] = useState<TriviaSpot[]>([]);
    const [selectedSpotId, setSelectedSpotId] = useState<string | null>(null);
    const [userLocation, setUserLocation] = useState<Coordinates | null>(null);
    const [locationStatus, setLocationStatus] = useState<TriviaLocationStatus>('unknown');
    const [isLoading, setIsLoading] = useState(true);
    const [viewMode, setViewMode] = useState<'map' | 'collection'>('map');
    const [selectedPrefecture, setSelectedPrefecture] = useState<string>('すべて');
    const [nearbyOnly, setNearbyOnly] = useState(false);
    const [unlockPulseId, setUnlockPulseId] = useState<string | null>(null);
    const [isPreviewVisible, setIsPreviewVisible] = useState(false);
    const [isDetailVisible, setIsDetailVisible] = useState(false);

    const selectedSpot = useMemo(
        () => spots.find((spot) => spot.id === selectedSpotId) ?? null,
        [selectedSpotId, spots]
    );

    const unlockedCount = spots.filter((spot) => spot.isUnlocked).length;
    const prefectures = useMemo(() => {
        const values = spots.map((spot) => spot.prefecture).filter(Boolean) as string[];
        return ['すべて', ...Array.from(new Set(values))];
    }, [spots]);

    const visibleSpots = useMemo(() => {
        return spots.filter((spot) => {
            if (selectedPrefecture !== 'すべて' && spot.prefecture !== selectedPrefecture) return false;
            if (nearbyOnly) {
                const distance = getSpotDistance(spot, userLocation);
                return distance != null && distance <= 5000;
            }
            return true;
        });
    }, [nearbyOnly, selectedPrefecture, spots, userLocation]);

    const collectionSpots = useMemo(
        () => spots.filter((spot) => spot.isUnlocked).sort((a, b) => (b.unlockedAt?.getTime() ?? 0) - (a.unlockedAt?.getTime() ?? 0)),
        [spots]
    );

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

        records.forEach((record) => {
            const spot = hydrated.find((item) => item.id === record.id);
            if (spot) {
                TriviaNotificationManager.notifyUnlockedSpot(spot).catch((error) => {
                    console.error('Trivia map notification failed:', error);
                });
            }
        });
    };

    const checkUnlocks = async (location: Coordinates, sourceSpots = spotsRef.current) => {
        const newlyUnlocked = await TriviaUnlockManager.unlockNearbySpots(sourceSpots, location);
        await handleUnlockedRecords(newlyUnlocked, sourceSpots);
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
                setSelectedSpotId(hydrated[0]?.id ?? null);

                TriviaNotificationManager.requestPermission().catch((error) => {
                    console.error('Trivia map notification permission failed:', error);
                });

                const status = await TriviaLocationManager.requestForegroundPermission();
                if (!isMounted) return;
                setLocationStatus(status);

                if (status === 'granted') {
                    const current = await TriviaLocationManager.getCurrentLocation();
                    if (!isMounted) return;
                    setUserLocation(current);
                    if (current) {
                        await checkUnlocks(current, hydrated);
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

    const moveToCurrentLocation = () => {
        if (!userLocation) return;
        mapRef.current?.animateToRegion(
            {
                latitude: userLocation.latitude,
                longitude: userLocation.longitude,
                latitudeDelta: 0.025,
                longitudeDelta: 0.025,
            },
            450
        );
    };

    const selectFromCollection = (spot: TriviaSpot) => {
        setSelectedSpotId(spot.id);
        setViewMode('map');
        setIsPreviewVisible(true);
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
            <View style={[styles.previewSheet, { bottom: getFloatingTabBarBottom(insets) + FLOATING_TAB_BAR_HEIGHT + 12 }]}>
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

            <View style={styles.filterRow}>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterContent}>
                    {prefectures.map((prefecture) => (
                        <Pressable
                            key={prefecture}
                            style={[styles.filterChip, selectedPrefecture === prefecture && styles.filterChipActive]}
                            onPress={() => handlePrefectureChange(prefecture)}
                        >
                            <Text style={[styles.filterText, selectedPrefecture === prefecture && styles.filterTextActive]}>
                                {prefecture}
                            </Text>
                        </Pressable>
                    ))}
                </ScrollView>
                <Pressable
                    style={[styles.nearbyButton, nearbyOnly && styles.nearbyButtonActive]}
                    onPress={toggleNearbyOnly}
                >
                    <Ionicons name="locate" size={16} color={nearbyOnly ? '#FFFFFF' : Colors.light.primary} />
                    <Text style={[styles.nearbyButtonText, nearbyOnly && styles.nearbyButtonTextActive]}>近く</Text>
                </Pressable>
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
                    >
                        {visibleSpots.map((spot) => (
                            <Marker
                                key={spot.id}
                                coordinate={{ latitude: spot.latitude, longitude: spot.longitude }}
                                pinColor={getPinColor(spot)}
                                onPress={() => selectSpot(spot)}
                            />
                        ))}
                        {selectedSpot && (
                            <Circle
                                center={{ latitude: selectedSpot.latitude, longitude: selectedSpot.longitude }}
                                radius={selectedSpot.unlockRadiusMeters}
                                strokeColor="rgba(230, 0, 18, 0.45)"
                                fillColor="rgba(230, 0, 18, 0.08)"
                            />
                        )}
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
                        { paddingBottom: getFloatingTabBarBottom(insets) + FLOATING_TAB_BAR_HEIGHT + 24 },
                    ]}
                >
                    <Text style={styles.collectionNote}>MAPで解放した雑学だけを保存します。過去に見た雑学には追加されません。</Text>
                    {collectionSpots.length === 0 ? (
                        <View style={styles.emptyCollection}>
                            <Ionicons name="lock-closed-outline" size={40} color={Colors.light.subtext} />
                            <Text style={styles.emptyTitle}>解放済み雑学はまだありません</Text>
                            <Text style={styles.emptyBody}>現地に近づくと、ここにコレクションとして保存されます。</Text>
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
    filterRow: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingLeft: 20,
        paddingRight: 16,
        paddingBottom: 10,
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
