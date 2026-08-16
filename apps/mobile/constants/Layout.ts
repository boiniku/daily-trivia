import { EdgeInsets } from 'react-native-safe-area-context';

export const FLOATING_TAB_BAR_HEIGHT = 70;
export const FLOATING_TAB_BAR_BOTTOM_GAP = 12;
export const BANNER_RESERVED_HEIGHT = 64;

export const getFloatingTabBarBottom = (insets: EdgeInsets) => {
    return Math.max(insets.bottom, 16) + FLOATING_TAB_BAR_BOTTOM_GAP;
};

export const getTabScreenAdBottomMargin = (insets: EdgeInsets) => {
    return getFloatingTabBarBottom(insets) + FLOATING_TAB_BAR_HEIGHT + 12;
};

