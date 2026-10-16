import React from 'react';
import { Alert, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { Colors } from '../constants/Colors';
import { photoAttribution } from '../utils/photoAttribution';

interface SourceReferenceProps {
    source?: string | null;
}

export default function SourceReference({ source }: SourceReferenceProps) {
    const text = typeof source === 'string' ? source.trim() : '';
    if (!text) return null;
    const attribution = photoAttribution(text);

    const openSource = async (url: string) => {
        try {
            await Linking.openURL(url);
        } catch {
            Alert.alert('写真の出典を開けませんでした', '通信状況を確認して、もう一度お試しください。');
        }
    };

    const showDetails = () => {
        const buttons = [];
        if (attribution.sourceUrl) buttons.push({ text: '元の写真', onPress: () => openSource(attribution.sourceUrl!) });
        if (attribution.licenseUrl) buttons.push({ text: 'ライセンス', onPress: () => openSource(attribution.licenseUrl!) });
        buttons.push({ text: '閉じる', style: 'cancel' as const });
        Alert.alert('写真の出典・利用条件', attribution.text, buttons);
    };

    return (
        <View style={styles.section}>
            <Pressable
                onPress={showDetails}
                accessibilityRole="button"
                accessibilityLabel="写真の出典と利用条件を表示"
                accessibilityHint="作者・作品名・ライセンス・加工内容などのクレジット全文を確認できます"
                hitSlop={8}
                style={({ pressed }) => [styles.link, pressed && styles.linkPressed]}
            >
                <Text style={styles.reference} numberOfLines={2}>{attribution.summary} ⓘ</Text>
            </Pressable>
        </View>
    );
}

const styles = StyleSheet.create({
    section: {
        marginTop: 2,
        alignItems: 'flex-end',
    },
    link: {
        paddingVertical: 4,
        maxWidth: '100%',
    },
    linkPressed: {
        opacity: 0.65,
    },
    reference: {
        fontSize: 10,
        lineHeight: 15,
        color: Colors.light.subtext,
        textAlign: 'right',
    },
});
