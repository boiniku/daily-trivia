Pod::Spec.new do |s|
  s.name           = 'WidgetControlModule'
  s.version        = '1.0.2'
  s.summary        = 'A local Expo module for Widget control'
  s.description    = 'Allows reloading widget timelines and saving images from the app'
  s.author         = 'DailyTrivia'
  s.homepage       = 'https://example.com'
  s.platforms      = {
    :ios => '16.0'
  }
  s.source         = { git: '' }
  s.static_framework = true
  s.weak_frameworks = 'WidgetKit'

  s.dependency 'ExpoModulesCore'

  # Swift/Objective-C compatibility
  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }

  s.source_files = "**/*.{h,m,mm,swift,hpp,cpp}"
end
