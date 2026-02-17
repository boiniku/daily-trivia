require 'json'

package = JSON.parse(File.read(File.join(__dir__, 'package.json')))

Pod::Spec.new do |s|
  s.name           = 'widget-control'
  s.version        = package['version']
  s.summary        = 'A local Expo module for Widget control'
  s.description    = 'Allows reloading widget timelines from the app'
  s.license        = 'MIT'
  s.author         = 'DailyTrivia'
  s.homepage       = 'https://example.com'
  s.platform       = :ios, '16.0'
  s.swift_version  = '5.4'
  s.source         = { git: '' }
  s.weak_frameworks = 'WidgetKit'

  s.dependency 'ExpoModulesCore'

  # Swift/Objective-C compatibility
  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }

  s.source_files = "ios/**/*.{h,m,swift}"
end
