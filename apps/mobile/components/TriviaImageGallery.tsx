import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, Image, LayoutChangeEvent, NativeScrollEvent, NativeSyntheticEvent, Pressable, StyleSheet, Text, View } from 'react-native';
import { Colors } from '../constants/Colors';
import { Config } from '../constants/Config';
import { normalizeTriviaImageUrls, readTriviaImageSources, resolveTriviaImageUrl } from '../utils/triviaImages';
import SourceReference from './SourceReference';

type Props = {
    imageUrls?: unknown;
    imageUrl?: unknown;
    imageSources?: unknown;
    title: string;
    itemKey?: string | number;
};

export default function TriviaImageGallery({ imageUrls, imageUrl, imageSources, title, itemKey }: Props) {
    const urls = useMemo(() => normalizeTriviaImageUrls(imageUrls, imageUrl)
        .map(url => resolveTriviaImageUrl(url, Config.TRIVIA_IMAGE_R2_BASE_URL))
        .filter(Boolean), [imageUrls, imageUrl]);
    const sources = useMemo(() => Object.fromEntries(Object.entries(readTriviaImageSources(imageSources) ?? {})
        .map(([image, source]) => [resolveTriviaImageUrl(image, Config.TRIVIA_IMAGE_R2_BASE_URL), source])
        .filter(([image]) => !!image)), [imageSources]);
    const [width, setWidth] = useState(0);
    const [activeIndex, setActiveIndex] = useState(0);
    const listRef = useRef<FlatList<string>>(null);
    const identity = JSON.stringify([itemKey, urls, width]);
    const identityRef = useRef(identity);
    identityRef.current = identity;

    useEffect(() => {
        setActiveIndex(0);
        listRef.current?.scrollToOffset({ offset: 0, animated: false });
    }, [identity]);

    const updatePage = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
        if (identityRef.current !== identity || width <= 0) return;
        const offset = event.nativeEvent.contentOffset.x;
        if (!Number.isFinite(offset)) return;
        setActiveIndex(Math.max(0, Math.min(urls.length - 1, Math.round(offset / width))));
    };
    const onLayout = (event: LayoutChangeEvent) => {
        const nextWidth = event.nativeEvent.layout.width;
        if (Number.isFinite(nextWidth) && nextWidth > 0) setWidth(nextWidth);
    };

    if (urls.length === 0) return null;
    const currentIndex = Math.min(activeIndex, urls.length - 1);

    return (
        <View style={styles.container}>
            <View style={styles.frame} onLayout={onLayout}>
                {width > 0 ? (
                    <FlatList
                        key={identity}
                        ref={listRef}
                        data={urls}
                        horizontal
                        pagingEnabled
                        nestedScrollEnabled
                        directionalLockEnabled
                        showsHorizontalScrollIndicator={false}
                        scrollEnabled={urls.length > 1}
                        onScroll={updatePage}
                        onMomentumScrollEnd={updatePage}
                        scrollEventThrottle={16}
                        initialNumToRender={1}
                        maxToRenderPerBatch={2}
                        windowSize={3}
                        keyExtractor={(url, index) => `${index}:${url}`}
                        getItemLayout={(_, index) => ({ length: width, offset: width * index, index })}
                        renderItem={({ item, index }) => (
                            <Image
                                source={{ uri: item }}
                                style={[styles.image, { width }]}
                                resizeMode="cover"
                                accessibilityLabel={`${title}の写真 ${index + 1}枚目、全${urls.length}枚`}
                            />
                        )}
                    />
                ) : (
                    <Image source={{ uri: urls[0] }} style={styles.image} resizeMode="cover" accessibilityLabel={`${title}の写真`} />
                )}
            </View>
            {urls.length > 1 && (
                <View style={styles.pagination}>
                    <View style={styles.dots}>
                        {urls.map((url, index) => (
                            <Pressable
                                key={`${index}:${url}`}
                                style={styles.dotButton}
                                accessibilityRole="button"
                                accessibilityLabel={`写真${index + 1}枚目を表示、全${urls.length}枚`}
                                accessibilityState={{ selected: currentIndex === index }}
                                disabled={width <= 0}
                                onPress={() => {
                                    if (identityRef.current !== identity || width <= 0) return;
                                    listRef.current?.scrollToOffset({ offset: index * width, animated: true });
                                    setActiveIndex(index);
                                }}
                            >
                                <View style={[styles.dot, currentIndex === index && styles.activeDot]} />
                            </Pressable>
                        ))}
                    </View>
                    <Text style={styles.position} accessibilityLiveRegion="polite" accessibilityLabel={`全${urls.length}枚中${currentIndex + 1}枚目の写真`}>
                        {currentIndex + 1} / {urls.length}
                    </Text>
                </View>
            )}
            <Text style={styles.disclaimer}>画像はイメージです</Text>
            <SourceReference source={sources[urls[currentIndex]]} />
        </View>
    );
}

const styles = StyleSheet.create({
    container: { marginTop: 16, marginBottom: 20 },
    frame: { width: '100%', aspectRatio: 16 / 9, borderRadius: 20, overflow: 'hidden', backgroundColor: '#ECEFF1' },
    image: { height: '100%', flex: 1 },
    pagination: { alignItems: 'center', marginTop: 6 },
    dots: { flexDirection: 'row', justifyContent: 'center', flexWrap: 'wrap' },
    dotButton: { width: 30, height: 36, alignItems: 'center', justifyContent: 'center' },
    dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#CED4DA' },
    activeDot: { backgroundColor: Colors.light.primary, width: 9, height: 9, borderRadius: 5 },
    position: { fontSize: 11, color: Colors.light.subtext },
    disclaimer: { marginTop: 6, fontSize: 11, color: Colors.light.subtext, textAlign: 'right' },
});
