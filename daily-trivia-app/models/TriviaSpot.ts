export type TriviaSpot = {
    id: string;
    title: string;
    description: string;
    explanation?: string;
    latitude: number;
    longitude: number;
    unlockRadiusMeters: number;
    isUnlocked: boolean;
    unlockedAt: Date | null;
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
