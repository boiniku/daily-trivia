const { withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const withPodfileFix = (config) => {
    return withDangerousMod(config, [
        'ios',
        async (config) => {
            const podfilePath = path.join(config.modRequest.platformProjectRoot, 'Podfile');
            if (fs.existsSync(podfilePath)) {
                let podfileContent = fs.readFileSync(podfilePath, 'utf8');

                // Blanket fix: Disable signing for ALL Pods
                const fixCode = `
    puts "[withPodfileFix] Starting blanket post_install hook..."
    installer.pods_project.targets.each do |target|
      puts "[withPodfileFix] Disabling signing for target: #{target.name}"
      target.build_configurations.each do |config|
          config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
          config.build_settings['CODE_SIGNING_REQUIRED'] = 'NO'
          config.build_settings['CODE_SIGNING_IDENTITY'] = ""
          config.build_settings['EXPANDED_CODE_SIGN_IDENTITY'] = ""
      end
    end
    puts "[withPodfileFix] Finished blanket post_install hook."
`;

                if (!podfileContent.includes("puts \"[withPodfileFix] Starting blanket post_install hook...\"")) {

                    if (podfileContent.includes('post_install do |installer|')) {
                        console.log('[withPodfileFix] Injecting blanket fix into existing post_install block.');
                        podfileContent = podfileContent.replace(
                            'post_install do |installer|',
                            `post_install do |installer|${fixCode}`
                        );
                    } else {
                        console.log('[withPodfileFix] Appending new post_install block with blanket fix.');
                        podfileContent += `
post_install do |installer|
${fixCode}
end
`;
                    }

                    fs.writeFileSync(podfilePath, podfileContent);
                    console.log('[withPodfileFix] Applied blanket signing fix to Podfile.');
                } else {
                    console.log('[withPodfileFix] Blanket fix already present in Podfile.');
                }
            } else {
                console.warn('[withPodfileFix] Podfile not found at ' + podfilePath);
            }
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
