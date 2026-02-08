const { withXcodeProject, withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const WIDGET_NAME = 'TriviaWidget';
const WIDGET_BUNDLE_ID_SUFFIX = 'widget';
const TEAM_ID = '86V3PV77T6'; // Hardcoded Team ID for EAS Build

const withWidget = (config) => {
    return withXcodeProject(config, async (config) => {
        const project = config.modResults;
        const WIDGET_BUNDLE_ID = `${config.ios.bundleIdentifier}.${WIDGET_BUNDLE_ID_SUFFIX}`;
        const targetName = WIDGET_NAME;

        // 1. Create PBXGroup for Widget
        const pbxGroup = project.addPbxGroup(
            ['TriviaWidget.swift', 'Info.plist'],
            targetName,
            targetName
        );

        // 2. Add Target
        const target = project.addTarget(
            targetName,
            'app_extension',
            targetName,
            WIDGET_BUNDLE_ID
        );

        // 3. Add Build Phases
        project.addBuildPhase(
            ['TriviaWidget.swift'],
            'PBXSourcesBuildPhase',
            'Sources',
            target.uuid
        );
        project.addBuildPhase(
            [],
            'PBXResourcesBuildPhase',
            'Resources',
            target.uuid
        );

        // 4. Configure Build Settings (Robust approach)
        // Use the UUID returned by addTarget to look up the configuration list directly
        const nativeTargets = project.pbxNativeTargetSection();
        const widgetTarget = nativeTargets[target.uuid];

        if (widgetTarget) {
            const configListUuid = widgetTarget.buildConfigurationList;
            const configList = project.pbxXCConfigurationListSection()[configListUuid];
            const buildConfigs = configList.buildConfigurations;

            buildConfigs.forEach((configRef) => {
                const configUuid = configRef.value;
                const buildConfig = project.pbxXCBuildConfigurationSection()[configUuid];

                if (buildConfig) {
                    if (!buildConfig.buildSettings) buildConfig.buildSettings = {};

                    // Common settings
                    buildConfig.buildSettings['SWIFT_VERSION'] = '5.0';
                    buildConfig.buildSettings['INFOPLIST_FILE'] = `${targetName}/Info.plist`;
                    buildConfig.buildSettings['PRODUCT_BUNDLE_IDENTIFIER'] = WIDGET_BUNDLE_ID;
                    buildConfig.buildSettings['IPHONEOS_DEPLOYMENT_TARGET'] = '17.0';
                    buildConfig.buildSettings['TARGETED_DEVICE_FAMILY'] = '"1"'; // iPhone
                    buildConfig.buildSettings['ASSETCATALOG_COMPILER_APPICON_NAME'] = 'AppIcon';
                    buildConfig.buildSettings['CLANG_ENABLE_MODULES'] = 'YES';
                    buildConfig.buildSettings['SWIFT_OPTIMIZATION_LEVEL'] = '-Onone';

                    // Signing Settings - CRITICAL FOR EAS BUILD
                    buildConfig.buildSettings['DEVELOPMENT_TEAM'] = TEAM_ID;
                    buildConfig.buildSettings['CODE_SIGN_STYLE'] = 'Automatic';
                    buildConfig.buildSettings['CODE_SIGN_IDENTITY'] = '"iPhone Developer"'; // Generally safe default

                    console.log(`[withWidget] Configured ${buildConfig.name} settings for ${targetName}`);
                }
            });
        } else {
            console.error('[withWidget] Failed to find widget target to configure build settings!');
        }

        return config;
    });
};

const withWidgetFiles = (config) => {
    return withDangerousMod(config, [
        'ios',
        async (config) => {
            const sourceDir = path.join(config.modRequest.projectRoot, 'widget');
            const targetDir = path.join(config.modRequest.platformProjectRoot, WIDGET_NAME);

            if (!fs.existsSync(targetDir)) {
                fs.mkdirSync(targetDir);
            }

            ['TriviaWidget.swift', 'Info.plist'].forEach((file) => {
                const sourceFile = path.join(sourceDir, file);
                const targetFile = path.join(targetDir, file);
                if (fs.existsSync(sourceFile)) {
                    fs.copyFileSync(sourceFile, targetFile);
                } else {
                    console.warn(`Warning: ${file} not found in widget directory.`);
                }
            });

            return config;
        },
    ]);
};

module.exports = (config) => {
    return withWidgetFiles(withWidget(config));
};
