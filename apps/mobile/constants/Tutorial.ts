export const TUTORIAL_COMPLETION_KEY = 'hasSeenTutorial';
export const TUTORIAL_REVISION_KEY = 'hasSeenTutorialRevision';

// Increment only when every user should see the tutorial again.
// Keeping this separate from the app version prevents routine updates from
// repeatedly showing onboarding.
export const CURRENT_TUTORIAL_REVISION = '2';
