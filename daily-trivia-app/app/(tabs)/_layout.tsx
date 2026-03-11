import { Tabs } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { View, Platform } from 'react-native';
import { Colors, Theme } from '../../constants/Colors';

export default function TabLayout() {
    return (
        <Tabs
            screenOptions={{
                headerShown: false,
                tabBarActiveTintColor: Colors.light.primary,
                tabBarInactiveTintColor: '#BBBBBB',
                tabBarStyle: {
                    position: 'absolute',
                    bottom: 50, // Moved up to avoid home button overlap
                    left: 40,
                    right: 40,
                    elevation: 0,
                    backgroundColor: '#FFFFFF',
                    borderRadius: 40, // Pill shape
                    height: 70,
                    ...Theme.shadow.pop, // Strong shadow
                    borderTopWidth: 0,
                    paddingBottom: Platform.OS === 'ios' ? 25 : 0, // Center icons vertically
                    paddingTop: 0,
                    alignItems: 'center',
                    justifyContent: 'center',
                },
                tabBarShowLabel: false,
                tabBarItemStyle: {
                    height: 70,
                    paddingTop: 10,
                }
            }}
        >
            <Tabs.Screen
                name="index"
                options={{
                    title: 'Today',
                    tabBarIcon: ({ color, focused }) => (
                        <View style={{ alignItems: 'center', justifyContent: 'center', height: 46 }}>
                            <Ionicons name={focused ? "sparkles" : "sparkles-outline"} size={32} color={color} />
                            {focused && <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: color, position: 'absolute', bottom: 0 }} />}
                        </View>
                    ),
                }}
            />
            <Tabs.Screen
                name="collections"
                options={{
                    title: 'Collections',
                    tabBarIcon: ({ color, focused }) => (
                        <View style={{ alignItems: 'center', justifyContent: 'center', height: 46 }}>
                            <Ionicons name={focused ? "library" : "library-outline"} size={32} color={color} />
                            {focused && <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: color, position: 'absolute', bottom: 0 }} />}
                        </View>
                    ),
                }}
            />
            <Tabs.Screen
                name="settings"
                options={{
                    title: 'Settings',
                    tabBarIcon: ({ color, focused }) => (
                        <View style={{ alignItems: 'center', justifyContent: 'center', height: 46 }}>
                            <Ionicons name={focused ? "settings" : "settings-outline"} size={32} color={color} />
                            {focused && <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: color, position: 'absolute', bottom: 0 }} />}
                        </View>
                    ),
                }}
            />
            <Tabs.Screen
                name="widget"
                options={{
                    title: 'Widget',
                    tabBarIcon: ({ color, focused }) => (
                        <View style={{ alignItems: 'center', justifyContent: 'center', height: 46 }}>
                            <Ionicons name={focused ? "cube" : "cube-outline"} size={32} color={color} />
                            {focused && <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: color, position: 'absolute', bottom: 0 }} />}
                        </View>
                    ),
                }}
            />
        </Tabs>
    );
}
