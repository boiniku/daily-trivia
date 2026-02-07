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

                // STRATEGY: Hybrid (Run Last)
                // 1. Bundles: Sign with Team ID (Satisfy Xcode 16 strictness).
                // 2. Others: Disable Signing (Prevent static lib errors).
                // 3. PLACEMENT: Must run AFTER react_native_post_install.

                const fixCode = `
    # [withPodfileFix] Hybrid Fix - Running LAST
    puts "[withPodfileFix] Applying HYBRID settings (Bundles=Sign, Others=NoSign)..."
    
    installer.pods_project.targets.each do |target|
      product_type = target.respond_to?(:product_type) ? target.product_type : "unknown"
      
      target.build_configurations.each do |config|
        if product_type == "com.apple.product-type.bundle"
            # BUNDLES: Enabled Signing + Team ID
            # This fixes "resource bundles are signed by default" error in Xcode 16
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'YES'
            config.build_settings['CODE_SIGNING_REQUIRED'] = 'YES'
            config.build_settings['CODE_SIGN_STYLE'] = 'Automatic'
            config.build_settings['DEVELOPMENT_TEAM'] = '86V3PV77T6' 
            # config.build_settings['CODE_SIGN_IDENTITY'] = 'Apple Development' # Optional, let Xcode decide
        else
            # EVERYTHING ELSE: Disable Signing
            # This prevents "empty code signing identity" errors for static libs
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
            config.build_settings['CODE_SIGNING_REQUIRED'] = 'NO'
            config.build_settings.delete('DEVELOPMENT_TEAM')
        end
      end
    end
    puts "[withPodfileFix] Finished applying settings."
`;

                // 1. Remove previous fix variants if present (to avoid double injection)
                // We previously injected at 'post_install do |installer|'.
                // The cleanest way is to assume we are overwriting previous logic if we use the same file name.
                // But since we are reading the file, we should strip old hooks if possible, 
                // OR just accept that if we inject at the end, we override previous ones.
                // However, to be clean, let's remove the "start of block" injection key if we used it.

                // If the file contains our old "Starting GLOBAL signing DISABLE hook", we might want to warn or clean it.
                // But regex cleaning is risky.
                // Proceed with appending to end. The last setting wins in Xcode.

                // 2. Inject at the END of the post_install block.
                // Robust heuristic: Replace the LAST occurence of "end" in the file.
                // Valid Podfiles end with the "end" of the post_install block (or the main loop).
                // We will match the last "end" followed by optional whitespace/comments.

                if (!podfileContent.includes("[withPodfileFix] Hybrid Fix - Running LAST")) {
                    // Attempt to match the last 'end'
                    const lastEndRegex = /\nend\s*$/;

                    if (lastEndRegex.test(podfileContent)) {
                        console.log('[withPodfileFix] Injecting fix at the END of Podfile.');
                        podfileContent = podfileContent.replace(
                            lastEndRegex,
                            `\n${fixCode}\nend`
                        );
                        fs.writeFileSync(podfilePath, podfileContent);
                    } else {
                        // Fallback: If we can't find a clean "end" at the end of file, 
                        // try to find standard End of post_install block if indented?
                        // Or just append it if we assume the file structure is open? No, that's invalid syntax.
                        console.warn('[withPodfileFix] Could not find trailing "end" to inject code. Trying simple append (risky).');
                        // This path is dangerous so we log a warning.
                        // But for Expo managed projects, Podfile is generated and usually standard.
                    }
                } else {
                    console.log('[withPodfileFix] Fix already present.');
                }

            } else {
                console.warn('[withPodfileFix] Podfile not found at ' + podfilePath);
            }
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
