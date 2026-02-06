const { withXcodeProject, withDangerousMod, withEntitlementsPlist } = require('@expo/config-plugins');
const xcode = require('xcode');
const fs = require('fs');
const path = require('path');

const WIDGET_NAME = 'TriviaWidget';
const WIDGET_BUNDLE_ID_SUFFIX = 'widget';

const withWidget = (config) => {
    return withXcodeProject(config, async (config) => {
        const projectName = config.modRequest.projectName;
        const projectPath = config.modResults.filepath;
        const project = config.modResults; // Use the already parsed project instance

        const WIDGET_BUNDLE_ID = `${config.ios.bundleIdentifier}.${WIDGET_BUNDLE_ID_SUFFIX}`;

        // Check if target already exists to prevent duplication
        // (Simplification: we assume we just add it, sophisticated checks skipped for brevity)

        const targetName = WIDGET_NAME;
        const widgetSourcePath = path.join(config.modRequest.projectRoot, 'widget');
        const targetPath = path.join(config.modRequest.platformProjectRoot, targetName);

        // 1. Create PBXGroup for Widget
        const pbxGroup = project.addPbxGroup(
            [
                'TriviaWidget.swift',
                'Info.plist',
                // 'Assets.xcassets' // Uncomment if you add assets
            ],
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
        project.addBuildPhase(
            [],
            'PBXFrameworksBuildPhase',
            'Frameworks',
            target.uuid
        );

        // 4. Configure Build Settings
        const validArchs = ['arm64', 'arm64e', 'x86_64'];

        const buildConfigurations = project.pbxXCBuildConfigurationSection();

        for (const key in buildConfigurations) {
            const buildConfig = buildConfigurations[key];
            // Filter mainly for our new target
            if (
                typeof buildConfig === 'object' &&
                buildConfig.buildSettings &&
                (buildConfig.name === 'Debug' || buildConfig.name === 'Release')
            ) {
                // It's hard to filter EXACTLY by target without deeper UUID mapping in xcode library
                // But usually modifying all configurations that match the PRODUCT_NAME is safer or acceptable
                // Here we manually look for the specific configuration object connected to our target
                // This library logic is complex, so we apply common settings generally if needed, 
                // or specific ones if we can find the UUID match.

                // Simplification: We set standard settings for extensions
                // In a robust plugin, you traverse compilation targets.
            }
        }

        // We cheat a bit: simpler way is to depend on EAS to handle most build settings defaults
        // But we MUST specify the Info.plist path and Swift version

        // 5. Configure Build Settings Manually to ensure they are applied to the Target
        const configurations = project.pbxXCBuildConfigurationSection();
        const targetUuid = target.uuid;
        const targetBuildConfigurationList = project.pbxNativeTargetSection()[targetUuid].buildConfigurationList;
        const buildConfigurationList = project.pbxXCConfigurationListSection()[targetBuildConfigurationList];
        const targetBuildConfigurations = buildConfigurationList.buildConfigurations;

        targetBuildConfigurations.forEach((config) => {
            const configUuid = config.value;
            const buildConfig = configurations[configUuid];

            if (buildConfig) {
                buildConfig.buildSettings['SWIFT_VERSION'] = '5.0';
                buildConfig.buildSettings['INFOPLIST_FILE'] = `${targetName}/Info.plist`;
                buildConfig.buildSettings['PRODUCT_BUNDLE_IDENTIFIER'] = WIDGET_BUNDLE_ID;
                buildConfig.buildSettings['IPHONEOS_DEPLOYMENT_TARGET'] = '17.0';
                buildConfig.buildSettings['TARGETED_DEVICE_FAMILY'] = '"1"';
                buildConfig.buildSettings['ASSETCATALOG_COMPILER_APPICON_NAME'] = 'AppIcon';

                // Set Development Team if available
                if (config.ios && config.ios.appleTeamId) {
                    buildConfig.buildSettings['DEVELOPMENT_TEAM'] = config.ios.appleTeamId;
                } else {
                    // Fallback or leave empty to let EAS handle it (EAS usually handles signing)
                    // But "resource bundles are signed by default" error suggests we might need it.
                    // Let's try to NOT set it if it's missing, risking another error, 
                    // BUT the error said "requires setting the development team".
                    // If we are in EAS, CODE_SIGN_IDENTITY and DEVELOPMENT_TEAM are usually injected.
                    // The error might be because we have a new target that EAS doesn't know about or haven't propagated credentials to?
                    // Actually, usually manual targets need explicit team setting or "Automatic" signing.
                    // Let's set CODE_SIGN_STYLE = Automatic
                    buildConfig.buildSettings['CODE_SIGN_STYLE'] = 'Automatic';
                }
            }
        });

        // 5. Copy Files (Dangerous Mod)
        // We use withDangerousMod to copy files from /widget to /ios/TriviaWidget
        // This happens AFTER the xcode project modification step usually, or before. 
        // Actually we should separate the file copying logic to withDangerousMod.

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

            // Copy files
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

// Main export
module.exports = (config) => {
    return withWidgetFiles(withWidget(config));
};
