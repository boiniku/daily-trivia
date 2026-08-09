import { ActionSheetProvider } from '@expo/react-native-action-sheet';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { Alert, InteractionManager, Linking, View } from 'react-native';
import { RevenueCatProvider } from '../contexts/RevenueCatContext';
import { AuthProvider } from '../contexts/AuthContext';
import { Config, getBackendUrl } from '../constants/Config';

import { registerBackgroundFetchAsync } from '../tasks/backgroundFetch';

const compareVersions = (current: string, minimum: string) => {
  const currentParts = current.split('.').map((part) => Number(part) || 0);
  const minimumParts = minimum.split('.').map((part) => Number(part) || 0);
  const length = Math.max(currentParts.length, minimumParts.length);

  for (let i = 0; i < length; i += 1) {
    const currentValue = currentParts[i] ?? 0;
    const minimumValue = minimumParts[i] ?? 0;
    if (currentValue < minimumValue) return -1;
    if (currentValue > minimumValue) return 1;
  }
  return 0;
};

let hasShownUpdatePrompt = false;

const checkAppVersion = async () => {
  if (hasShownUpdatePrompt) return;

  try {
    const response = await fetch(`${getBackendUrl()}/app/version`, {
      headers: {
        'X-Daily-Trivia-App-Version': Config.APP_VERSION,
        'X-Daily-Trivia-App-Environment': Config.APP_ENV,
        'X-Daily-Trivia-API-Version': Config.API_VERSION,
      },
    });
    if (!response.ok) return;

    const data = await response.json();
    const minimumVersion = String(data.minimum_supported_version || '');
    if (!minimumVersion) return;

    if (compareVersions(Config.APP_VERSION, minimumVersion) < 0) {
      hasShownUpdatePrompt = true;
      const appStoreUrl = String(data.app_store_url || 'https://apps.apple.com/app/id6758872525');
      Alert.alert(
        'アップデートのお願い',
        '新しいバージョンの毎日雑学があります。快適に使うため、アップデートをお願いします。',
        [
          { text: 'あとで', style: 'cancel' },
          { text: 'アップデート', onPress: () => Linking.openURL(appStoreUrl) },
        ]
      );
    }
  } catch (error) {
    console.error('App version check failed:', error);
  }
};

export default function RootLayout() {

  useEffect(() => {
    // Register background fetch
    registerBackgroundFetchAsync().catch(err => console.error("BG Register Error:", err));

    const task = InteractionManager.runAfterInteractions(() => {
      checkAppVersion();

      setTimeout(() => {
        import('react-native-google-mobile-ads')
          .then(({ default: mobileAds }) => mobileAds().initialize())
          .catch(error => {
            console.error('AdMob init error:', error);
          });
      }, 1500);
    });

    return () => task.cancel();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <ActionSheetProvider>
        <RevenueCatProvider>
          <AuthProvider>
            <View style={{ flex: 1 }}>
              <Stack screenOptions={{ headerShown: false }}>
                <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
                <Stack.Screen name="details" options={{ presentation: 'modal', headerShown: false }} />
                <Stack.Screen name="widget-setup" options={{ presentation: 'modal', headerShown: false }} />
              </Stack>
              <StatusBar style="auto" />
            </View>
          </AuthProvider>
        </RevenueCatProvider>
      </ActionSheetProvider>
    </GestureHandlerRootView>
  );
}
