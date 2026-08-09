export const Colors = {
    light: {
        text: '#1A1A1A', // Darker, sharper black
        background: '#F8F9FA', // Off-white explicitly to contrast with white cards
        tint: '#E60012', // Nintendo Red
        tabIconDefault: '#cccccc',
        tabIconSelected: '#E60012',
        cardBackground: '#FFFFFF',
        primary: '#E60012', // Nintendo Red
        accent: '#FFD700', // Coin Yellow / Star color
        secondary: '#00B2CA', // Playful Blue
        border: '#EEEEEE',
        subtext: '#888888',
        surface: '#F5F5F5', // Light gray surface for depth
    },
    dark: {
        text: '#fff',
        background: '#1A1A1A',
        tint: '#E60012',
        tabIconDefault: '#ccc',
        tabIconSelected: '#E60012',
        cardBackground: '#2C2C2C',
        primary: '#FF4D4D',
        accent: '#FFD700',
        secondary: '#00E5FF',
        border: '#444444',
        subtext: '#AAAAAA',
        surface: '#222222',
    },
};

export const Theme = {
    colors: Colors.light,
    spacing: {
        s: 8,
        m: 16,
        l: 24,
        xl: 32,
    },
    borderRadius: {
        s: 12,
        m: 24, // Rounder!
        l: 36, // Very round!
        xl: 48,
    },
    shadow: {
        medium: {
            shadowColor: "#000",
            shadowOffset: {
                width: 0,
                height: 6,
            },
            shadowOpacity: 0.1,
            shadowRadius: 8,
            elevation: 6,
        },
        small: {
            shadowColor: "#000",
            shadowOffset: {
                width: 0,
                height: 3,
            },
            shadowOpacity: 0.08,
            shadowRadius: 3,
            elevation: 3,
        },
        pop: { // Stronger shadow for "pop" effect
            shadowColor: "#E60012",
            shadowOffset: {
                width: 0,
                height: 8,
            },
            shadowOpacity: 0.25,
            shadowRadius: 10,
            elevation: 8,
        }
    }
};
