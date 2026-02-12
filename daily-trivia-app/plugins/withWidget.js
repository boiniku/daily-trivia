const { withXcodeProject, withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');
const pbxFile = require('xcode/lib/pbxFile');
const WIDGET_NAME = 'TriviaWidget';
const WIDGET_BUNDLE_ID_SUFFIX = 'widget';
const TEAM_ID = '86V3PV77T6'; // Hardcoded Team ID for EAS Build

const withWidget = (config) => {
    return withXcodeProject(config, async (config) => {
        const project = config.modResults;
        const WIDGET_BUNDLE_ID = `${config.ios.bundleIdentifier}.${WIDGET_BUNDLE_ID_SUFFIX}`;
        const targetName = WIDGET_NAME;

        // 0. Ensure PBXVariantGroup section exists (Fix for node-xcode crash)
        if (!project.hash.project.objects['PBXVariantGroup']) {
            project.hash.project.objects['PBXVariantGroup'] = {};
        }

        // 1. Create PBXGroup for Widget (Empty first)
        const pbxGroup = project.addPbxGroup(
            [],
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

        // 3. Add Source File (Robust)
        // This adds to Group, File Ref, and Sources Build Phase in one go
        project.addSourceFile(
            'TriviaWidget.swift',
            { target: target.uuid },
            pbxGroup.uuid // Pass the UUID, not the name!
        );

        // 4. Add Info.plist to Group (File ref only)
        // addFile isn't standard in all node-xcode versions, using addPluginFile or manually adding to group if needed.
        // Actually addPbxGroup helper added files comfortably. 
        // Let's use addResourceFile for Info.plist but remove it from build phase if added
        // Or simply stick to addPbxGroup for Info.plist specifically?

        // Let's use a simpler approach: use addPbxGroup for Info.plist only.
        // But we already created the group empty.
        // We can push to the group children manually or use addFile if available.
        // project.addFile('Info.plist', targetName); // This might not be exposed reliably.

        // Alternative: Re-use addPbxGroup logic for Info.plist? No, duplicates group.

        // Let's just add Info.plist as a resource file (it won't hurt, and ensures it's in the project).
        // project.addResourceFile('Info.plist', { target: target.uuid }, targetName);
        // Wait, Info.plist shouldn't be in Copy Bundle Resources usually?
        // It's compiled into the binary via INFOPLIST_FILE setting.

        // Let's manually add Info.plist file ref and group entry.
        // This is getting complex.

        // Backtrack: addSourceFile works for Swift.
        // What if we keep addPbxGroup for Info.plist?
        // project.addPbxGroup(['Info.plist'], targetName, targetName); -> Duplicate group error!

        // Solution:
        // Use addSourceFile for Swift.
        // For Info.plist, let's just assume it's fine if we omit it from the project tree (it's in the FS), 
        // but it's better to verify.
        // Actually, just add it as a file.
        const infoPlistFile = new pbxFile('Info.plist');
        infoPlistFile.fileRef = project.generateUuid();
        infoPlistFile.uuid = project.generateUuid();
        project.addToPbxFileReferenceSection(infoPlistFile);
        project.addToPbxGroup(infoPlistFile, targetName);

        // 5. Add Resources Build Phase (Empty for now if no assets)
        project.addBuildPhase(
            [],
            'PBXResourcesBuildPhase',
            'Resources',
            target.uuid
        );

        // 3.5. Link PBXGroup to Main Group (CRITICAL fix for "file not found")
        // 3.5. Link PBXGroup to Main Group (CRITICAL fix for "file not found")
        const mainGroupUuid = project.getFirstProject().firstProject.mainGroup;
        // Access PBXGroup directly via hash to avoid "is not a function" error
        const mainGroup = project.hash.project.objects['PBXGroup'][mainGroupUuid];
        // Check if already added to avoid duplicates
        const alreadyAdded = mainGroup.children.some(child => child.comment === targetName);
        if (!alreadyAdded) {
            mainGroup.children.push({
                value: pbxGroup.uuid,
                comment: targetName
            });
            console.log(`[withWidget] Added ${targetName} group to main project group`);
        }

        // 4. Configure Build Settings (Robust approach)
        // Use the UUID returned by addTarget to look up the configuration list directly
        const nativeTargets = project.pbxNativeTargetSection();
        const widgetTarget = nativeTargets[target.uuid];

        if (widgetTarget) {
            const configListUuid = widgetTarget.buildConfigurationList;
            // Access XCConfigurationList directly via hash
            const configList = project.hash.project.objects['XCConfigurationList'][configListUuid];
            const buildConfigs = configList.buildConfigurations;

            buildConfigs.forEach((configRef) => {
                const configUuid = configRef.value;
                // Access XCBuildConfiguration directly via hash
                const buildConfig = project.hash.project.objects['XCBuildConfiguration'][configUuid];

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
                    const PROFILE_UUID = '16b88775-5f67-4e25-87c9-b282302f37f1';
                    buildConfig.buildSettings['PROVISIONING_PROFILE_SPECIFIER'] = `"${PROFILE_UUID}"`;
                    buildConfig.buildSettings['PROVISIONING_PROFILE'] = `"${PROFILE_UUID}"`;

                    if (buildConfig.name === 'Release') {
                        buildConfig.buildSettings['CODE_SIGN_IDENTITY'] = '"iPhone Distribution"';
                    } else {
                        buildConfig.buildSettings['CODE_SIGN_IDENTITY'] = '"iPhone Developer"';
                    }
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
