export type TriviaSpot = {
    id: string;
    title: string;
    description: string;
    explanation?: string;
    source?: string;
    image_url?: string | null;
    image_urls?: string[];
    image_sources?: Record<string, string>;
    latitude: number;
    longitude: number;
    unlockRadiusMeters: number;
    isUnlocked: boolean;
    unlockedAt: Date | null;
    unlockCount: number;
    isArchived?: boolean;
    prefecture?: string;
    address?: string;
    category?: string;
    hint?: string;
};

export type UnlockedTriviaRecord = {
    id: string;
    unlockedAt: string;
};

export type Coordinates = {
    latitude: number;
    longitude: number;
};
