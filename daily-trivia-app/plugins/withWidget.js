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

        // 5. Configure Build Settings Manually (Robust Search Strategy)
        // Also set Project-level SWIFT_VERSION to be safe
        project.addBuildProperty('SWIFT_VERSION', '5.0');

        try {
            const nativeTargets = project.pbxNativeTargetSection();
            let widgetTargetUuid = null;

            // Search for the target by name to ensure we get the right one
            for (const uuid in nativeTargets) {
                const t = nativeTargets[uuid];
                if (t.isa === 'PBXNativeTarget' && (t.name === targetName || t.productName === targetName)) {
                    widgetTargetUuid = uuid;
                    console.log(`[withWidget] Found widget target: ${t.name} (UUID: ${uuid})`);
                    break;
                }
            }

            if (widgetTargetUuid) {
                const targetBuildConfigurationList = nativeTargets[widgetTargetUuid].buildConfigurationList;
                const configurationListSection = project.pbxXCConfigurationListSection();
                const buildConfigurationList = configurationListSection[targetBuildConfigurationList];
                const targetBuildConfigurations = buildConfigurationList.buildConfigurations;
                const configurations = project.pbxXCBuildConfigurationSection();

                targetBuildConfigurations.forEach((config) => {
                    const configUuid = config.value;
                    const buildConfig = configurations[configUuid];

                    if (buildConfig) {
                        if (!buildConfig.buildSettings) buildConfig.buildSettings = {};

                        buildConfig.buildSettings['SWIFT_VERSION'] = '5.0';
                        buildConfig.buildSettings['INFOPLIST_FILE'] = `${targetName}/Info.plist`;
                        buildConfig.buildSettings['PRODUCT_BUNDLE_IDENTIFIER'] = WIDGET_BUNDLE_ID;
                        buildConfig.buildSettings['IPHONEOS_DEPLOYMENT_TARGET'] = '17.0';
                        buildConfig.buildSettings['TARGETED_DEVICE_FAMILY'] = '"1"'; // iPhone
                        buildConfig.buildSettings['ASSETCATALOG_COMPILER_APPICON_NAME'] = 'AppIcon';

                        // Signing - Set Team ID explicitly for EAS Build
                        buildConfig.buildSettings['DEVELOPMENT_TEAM'] = '86V3PV77T6';
                        buildConfig.buildSettings['CODE_SIGN_STYLE'] = 'Automatic';

                        console.log(`[withWidget] Applied settings to config: ${buildConfig.name} (UUID: ${configUuid})`);
                    }
                });
            } else {
                console.error('[withWidget] CRITICAL: Could not find widget target by name after creation.');
                // Fallback: This is very unlikely if addTarget succeeded.
            }
        } catch (e) {
            console.error('[withWidget] Exception in manual build configuration:', e);
        }

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
