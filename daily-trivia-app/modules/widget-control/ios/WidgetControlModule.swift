import ExpoModulesCore
import WidgetKit
import SwiftUI

private enum WidgetImageNormalizer {
  static let widgetAspect: CGFloat = 338.0 / 155.0

  static func normalizeJPEG(from data: Data, compressionQuality: CGFloat = 0.9) -> Data? {
    guard let sourceImage = UIImage(data: data) else { return nil }
    let normalized = centerCropToWidgetAspect(sourceImage)
    return normalized.jpegData(compressionQuality: compressionQuality)
  }

  private static func centerCropToWidgetAspect(_ image: UIImage) -> UIImage {
    let size = image.size
    guard size.width > 0, size.height > 0 else { return image }

    let sourceAspect = size.width / size.height
    var cropRect = CGRect(origin: .zero, size: size)
    if sourceAspect > widgetAspect {
      let cropWidth = size.height * widgetAspect
      cropRect = CGRect(
        x: (size.width - cropWidth) / 2.0,
        y: 0,
        width: cropWidth,
        height: size.height
      )
    } else {
      let cropHeight = size.width / widgetAspect
      cropRect = CGRect(
        x: 0,
        y: (size.height - cropHeight) / 2.0,
        width: size.width,
        height: cropHeight
      )
    }

    guard let cgImage = image.cgImage?.cropping(to: cropRect.integral) else { return image }
    return UIImage(cgImage: cgImage, scale: image.scale, orientation: image.imageOrientation)
  }
}

public class WidgetControlModule: Module {
  public func definition() -> ModuleDefinition {
    Name("WidgetControl")

    Function("reloadAllTimelines") {
      DispatchQueue.main.async {
        if #available(iOS 14.0, *) {
          WidgetCenter.shared.reloadTimelines(ofKind: "TriviaWidget")
          print("WidgetControl: reloadTimelines called")
        }
      }
    }

    AsyncFunction("getWidgetImageBase64") { (displayTheme: String, timeThemeString: String, promise: Promise) in
      Task { @MainActor in
        if #available(iOS 16.0, *) {
          let tTheme: TriviaThemeCopy
          if timeThemeString == "morning" { tTheme = .morning }
          else if timeThemeString == "night" { tTheme = .night }
          else { tTheme = .noon }
          
          let entry = TriviaEntryCopy(
              date: Date(),
              id: 1,
              title: "富士山の高さ",
              content: "富士山の高さは3776メートルです。",
              theme: tTheme,
              displayTheme: displayTheme,
              imageTimestamp: Date().timeIntervalSince1970
          )
          
          let view = TriviaWidgetEntryViewCopy(entry: entry).frame(width: 320, height: 150)
          
          let renderer = ImageRenderer(content: view)
          renderer.scale = UIScreen.main.scale
          
          if let uiImage = renderer.uiImage, let data = uiImage.jpegData(compressionQuality: 0.8) {
            promise.resolve(data.base64EncodedString())
          } else {
            promise.reject("RENDER_FAILED", "Failed to render widget image")
          }
        } else {
          promise.reject("UNSUPPORTED_IOS", "Requires iOS 16.0+")
        }
      }
    }

    AsyncFunction("saveWidgetThemeImage") { (themeName: String, base64String: String, promise: Promise) in
      guard let imageData = Data(base64Encoded: base64String, options: .ignoreUnknownCharacters) else {
        promise.reject("INVALID_DATA", "Invalid base64 image data")
        return
      }
      
      guard let containerURL = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.com.dailytrivia.app") else {
        promise.reject("NO_APP_GROUP", "App Group container not found")
        return
      }
      
      let filename = "widget_bg_\(themeName).jpeg"
      let imageURL = containerURL.appendingPathComponent(filename)
      let outputData = WidgetImageNormalizer.normalizeJPEG(from: imageData) ?? imageData
      
      do {
        try outputData.write(to: imageURL, options: .atomic)
        print("WidgetControl: Widget theme image saved: \(filename) (size: \(outputData.count) bytes)")
        
        let defaults = UserDefaults(suiteName: "group.com.dailytrivia.app")
        defaults?.set(Date().timeIntervalSince1970, forKey: "widget_theme_image_\(themeName)_timestamp")
        
        promise.resolve(true)
      } catch {
        print("WidgetControl: Failed to save theme image: \(error)")
        promise.reject("SAVE_FAILED", "Failed to save widget theme image: \(error.localizedDescription)")
      }
    }

    AsyncFunction("downloadAndSaveWidgetThemeImage") { (urlString: String, themeName: String, promise: Promise) in
      guard let url = URL(string: urlString) else {
        promise.reject("INVALID_URL", "Invalid URL string")
        return
      }
      
      guard let containerURL = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.com.dailytrivia.app") else {
        promise.reject("NO_APP_GROUP", "App Group container not found")
        return
      }
      
      var request = URLRequest(url: url)
      request.timeoutInterval = 30
      request.cachePolicy = .reloadIgnoringLocalCacheData
      request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")

      let task = URLSession.shared.dataTask(with: request) { data, response, error in
        if let error = error {
          promise.reject("DOWNLOAD_ERROR", "Network error: \(error.localizedDescription)")
          return
        }
        
        guard let httpResponse = response as? HTTPURLResponse, (200...299).contains(httpResponse.statusCode), let data = data else {
           let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
           promise.reject("DOWNLOAD_FAILED", "Server returned error status: \(statusCode)")
           return
        }
        
        let filename = "widget_bg_\(themeName).jpeg"
        let imageURL = containerURL.appendingPathComponent(filename)
        let outputData = WidgetImageNormalizer.normalizeJPEG(from: data) ?? data
        
        do {
          try outputData.write(to: imageURL, options: .atomic)
          print("WidgetControl: Downloaded and saved theme image: \(filename) (size: \(outputData.count) bytes)")
          
          let defaults = UserDefaults(suiteName: "group.com.dailytrivia.app")
          defaults?.set(Date().timeIntervalSince1970, forKey: "widget_theme_image_\(themeName)_timestamp")
          
          promise.resolve(true)
        } catch let writeError {
          print("WidgetControl: Failed to download/save theme image: \(writeError)")
          promise.reject("SAVE_FAILED", "Failed to write image data to container: \(writeError.localizedDescription)")
        }
      }
      task.resume()
    }

    AsyncFunction("showWidgetPreviewScreen") { (promise: Promise) in
      DispatchQueue.main.async {
        print("WidgetControl: showWidgetPreviewScreen called")
        
        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let window = windowScene.windows.first(where: { $0.isKeyWindow }) ?? windowScene.windows.first,
              let rootVC = window.rootViewController else {
          print("WidgetControl: ERROR - No root VC")
          promise.reject("NO_ROOT_VC", "Could not find root view controller")
          return
        }
        
        var topVC = rootVC
        while let presented = topVC.presentedViewController {
          topVC = presented
        }
        
        let previewVC = WidgetPreviewScreenController()
        previewVC.modalPresentationStyle = .fullScreen
        
        topVC.present(previewVC, animated: true) {
          print("WidgetControl: Modal presented")
          promise.resolve(true)
        }
      }
    }

    AsyncFunction("getSavedWidgetFiles") { (promise: Promise) in
      guard let containerURL = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.com.dailytrivia.app") else {
        promise.reject("NO_APP_GROUP", "App Group container not found")
        return
      }
      
      do {
        let fileURLs = try FileManager.default.contentsOfDirectory(at: containerURL, includingPropertiesForKeys: [.fileSizeKey], options: [])
        let files = fileURLs.map { url -> [String: Any] in
            let resourceValues = try? url.resourceValues(forKeys: [.fileSizeKey])
            return [
                "name": url.lastPathComponent,
                "size": resourceValues?.fileSize ?? 0
            ]
        }
        promise.resolve(files)
      } catch {
        promise.reject("READ_FAILED", "Failed to list files: \(error.localizedDescription)")
      }
    }

    AsyncFunction("saveAllWidgetImages") { (promise: Promise) in
      DispatchQueue.main.async {
        let savedCount = WidgetImageSaver.saveAll()
        promise.resolve(savedCount)
      }
    }

    View(WidgetPreviewView.self) {
      Prop("displayTheme") { (view: WidgetPreviewView, theme: String) in
        view.setDisplayTheme(theme)
      }
      Prop("timeTheme") { (view: WidgetPreviewView, time: String) in
        view.setTimeTheme(time)
      }
    }
  }
}

// MARK: - Widget Image Saver (shared logic)
class WidgetImageSaver {
  struct ThemeConfig {
    let displayTheme: String
    let timeTheme: String
    let filename: String
  }
  
  static let allThemes: [ThemeConfig] = [
    ThemeConfig(displayTheme: "standard", timeTheme: "morning", filename: "standard_morning"),
    ThemeConfig(displayTheme: "standard", timeTheme: "noon", filename: "standard_noon"),
    ThemeConfig(displayTheme: "standard", timeTheme: "night", filename: "standard_night"),
    ThemeConfig(displayTheme: "light", timeTheme: "noon", filename: "light"),
    ThemeConfig(displayTheme: "dark", timeTheme: "noon", filename: "dark"),
    ThemeConfig(displayTheme: "rpg", timeTheme: "noon", filename: "rpg"),
    ThemeConfig(displayTheme: "gameboy", timeTheme: "noon", filename: "gameboy"),
  ]
  
  static func makeTriviaTheme(_ timeTheme: String) -> TriviaThemeCopy {
    if timeTheme == "morning" { return .morning }
    if timeTheme == "night" { return .night }
    return .noon
  }
  
  static func makeWidgetView(displayTheme: String, timeTheme: String, size: CGSize) -> UIView {
    let tTheme = makeTriviaTheme(timeTheme)
    let entry = TriviaEntryCopy(
      date: Date(),
      id: 1,
      title: "富士山の高さ",
      content: "富士山の高さは3776メートルです。",
      theme: tTheme,
      displayTheme: displayTheme,
      imageTimestamp: Date().timeIntervalSince1970
    )
    let swiftUIView = TriviaWidgetEntryViewCopy(entry: entry)
      .frame(width: size.width, height: size.height)
      .clipShape(RoundedRectangle(cornerRadius: 22))
    
    let hc = UIHostingController(rootView: swiftUIView)
    hc.view.frame = CGRect(origin: .zero, size: size)
    hc.view.backgroundColor = .clear
    return hc.view
  }
  
  static func saveAll() -> Int {
    let widgetSize = CGSize(width: 338, height: 155)
    var savedCount = 0
    
    // Create a temporary off-screen window for rendering
    let tempWindow = UIWindow(frame: CGRect(origin: .zero, size: widgetSize))
    tempWindow.isHidden = false
    
    for config in allThemes {
      let widgetView = makeWidgetView(displayTheme: config.displayTheme, timeTheme: config.timeTheme, size: widgetSize)
      tempWindow.addSubview(widgetView)
      widgetView.setNeedsLayout()
      widgetView.layoutIfNeeded()
      
      let renderer = UIGraphicsImageRenderer(size: widgetSize)
      let image = renderer.image { _ in
        widgetView.drawHierarchy(in: CGRect(origin: .zero, size: widgetSize), afterScreenUpdates: true)
      }
      
      widgetView.removeFromSuperview()
      UIImageWriteToSavedPhotosAlbum(image, nil, nil, nil)
      savedCount += 1
      print("WidgetControl: Saved \(config.filename) to camera roll")
    }
    
    tempWindow.isHidden = true
    return savedCount
  }
}

// MARK: - Native Preview Screen (pure UIKit + UIHostingController)
class WidgetPreviewScreenController: UIViewController {
  private let scrollView = UIScrollView()
  private let stackView = UIStackView()
  
  override func viewDidLoad() {
    super.viewDidLoad()
    view.backgroundColor = UIColor.systemBackground
    
    setupNavigationBar()
    setupScrollView()
    addWidgetPreviews()
  }
  
  private func setupNavigationBar() {
    let navBar = UINavigationBar(frame: .zero)
    navBar.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(navBar)
    
    let navItem = UINavigationItem(title: "ウィジェットプレビュー")
    navItem.leftBarButtonItem = UIBarButtonItem(title: "閉じる", style: .plain, target: self, action: #selector(closeTapped))
    navItem.rightBarButtonItem = UIBarButtonItem(title: "全て保存", style: .done, target: self, action: #selector(saveAllTapped))
    navBar.items = [navItem]
    
    NSLayoutConstraint.activate([
      navBar.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
      navBar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      navBar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
    ])
    
    // Setup scroll view below nav bar
    scrollView.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(scrollView)
    NSLayoutConstraint.activate([
      scrollView.topAnchor.constraint(equalTo: navBar.bottomAnchor),
      scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      scrollView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
    ])
  }
  
  private func setupScrollView() {
    stackView.axis = .vertical
    stackView.spacing = 24
    stackView.alignment = .center
    stackView.translatesAutoresizingMaskIntoConstraints = false
    scrollView.addSubview(stackView)
    
    NSLayoutConstraint.activate([
      stackView.topAnchor.constraint(equalTo: scrollView.topAnchor, constant: 20),
      stackView.bottomAnchor.constraint(equalTo: scrollView.bottomAnchor, constant: -40),
      stackView.leadingAnchor.constraint(equalTo: scrollView.leadingAnchor, constant: 20),
      stackView.trailingAnchor.constraint(equalTo: scrollView.trailingAnchor, constant: -20),
      stackView.widthAnchor.constraint(equalTo: scrollView.widthAnchor, constant: -40),
    ])
    
    let desc = UILabel()
    desc.text = "SwiftUIで直接レンダリングされたウィジェットです。\n「全て保存」でカメラロールに保存できます。"
    desc.font = .systemFont(ofSize: 13)
    desc.textColor = .gray
    desc.textAlignment = .center
    desc.numberOfLines = 0
    stackView.addArrangedSubview(desc)
  }
  
  private func addWidgetPreviews() {
    let widgetSize = CGSize(width: 338, height: 155)
    
    for config in WidgetImageSaver.allThemes {
      let container = UIView()
      
      // Label
      let label = UILabel()
      label.text = themeLabel(for: config)
      label.font = .boldSystemFont(ofSize: 14)
      label.translatesAutoresizingMaskIntoConstraints = false
      container.addSubview(label)
      
      // Widget view
      let widgetView = WidgetImageSaver.makeWidgetView(
        displayTheme: config.displayTheme,
        timeTheme: config.timeTheme,
        size: widgetSize
      )
      widgetView.translatesAutoresizingMaskIntoConstraints = false
      widgetView.layer.cornerRadius = 22
      widgetView.clipsToBounds = true
      widgetView.layer.shadowColor = UIColor.black.cgColor
      widgetView.layer.shadowOffset = CGSize(width: 0, height: 4)
      widgetView.layer.shadowOpacity = 0.15
      widgetView.layer.shadowRadius = 8
      container.addSubview(widgetView)
      
      container.translatesAutoresizingMaskIntoConstraints = false
      NSLayoutConstraint.activate([
        label.topAnchor.constraint(equalTo: container.topAnchor),
        label.leadingAnchor.constraint(equalTo: container.leadingAnchor),
        
        widgetView.topAnchor.constraint(equalTo: label.bottomAnchor, constant: 8),
        widgetView.centerXAnchor.constraint(equalTo: container.centerXAnchor),
        widgetView.widthAnchor.constraint(equalToConstant: widgetSize.width),
        widgetView.heightAnchor.constraint(equalToConstant: widgetSize.height),
        widgetView.bottomAnchor.constraint(equalTo: container.bottomAnchor),
      ])
      
      stackView.addArrangedSubview(container)
    }
  }
  
  private func themeLabel(for config: WidgetImageSaver.ThemeConfig) -> String {
    switch config.filename {
    case "standard_morning": return "スタンダード - 朝"
    case "standard_noon": return "スタンダード - 昼"
    case "standard_night": return "スタンダード - 夜"
    case "light": return "ホワイト"
    case "dark": return "ダーク"
    case "rpg": return "ドラクエ風（RPG）"
    case "gameboy": return "ゲームボーイ風"
    default: return config.filename
    }
  }
  
  @objc private func closeTapped() {
    dismiss(animated: true)
  }
  
  @objc private func saveAllTapped() {
    let count = WidgetImageSaver.saveAll()
    let alert = UIAlertController(
      title: "保存完了",
      message: "\(count)枚のウィジェット画像をカメラロールに保存しました。",
      preferredStyle: .alert
    )
    alert.addAction(UIAlertAction(title: "OK", style: .default))
    present(alert, animated: true)
  }
}


// ---------------------------------------------------------
// INJECTED WIDGET CODE TO AVOID TARGET DEPENDENCY ISSUES
// We append "Copy" to avoid naming collisions if they happen to share the namespace in Expo's build step.
// ---------------------------------------------------------

enum TriviaThemeCopy {
    case morning, noon, night
}

struct TriviaEntryCopy {
    var date: Date
    let id: Int
    let title: String
    let content: String
    let theme: TriviaThemeCopy
    let displayTheme: String
    var imageTimestamp: Double = 0
}

struct TriviaWidgetEntryViewCopy: View {
    var entry: TriviaEntryCopy

    var body: some View {
        let isLight = entry.displayTheme == "light"
        let isDark = entry.displayTheme == "dark"
        let isRpg = entry.displayTheme == "rpg"
        let isCat = entry.displayTheme == "cat"
        let isGameboy = entry.displayTheme == "gameboy"
        let hasOutline = isRpg || isCat
        
        let titleColor: Color = isLight ? Color(white: 0.1) : (isGameboy ? Color(red: 15/255, green: 56/255, blue: 15/255) : .white)
        let contentColor: Color = isLight ? Color(white: 0.3) : (isGameboy ? Color(red: 15/255, green: 56/255, blue: 15/255) : .white)
        let badgeBgColor: Color = isLight ? Color(white: 0.95) : (isDark ? Color(white: 0.17) : (isRpg ? .black : (isGameboy ? Color(red: 139/255, green: 172/255, blue: 15/255) : Color.black.opacity(0.2))))
        let badgeTextColor: Color = isLight ? Color(white: 0.2) : (isGameboy ? Color(red: 15/255, green: 56/255, blue: 15/255) : .white.opacity(0.9))
        let hasShadow = entry.displayTheme == "standard"
        let shadowRad: CGFloat = hasShadow ? 2 : 0
        let customFontName = (isRpg || isGameboy) ? "DotGothic16-Regular" : ""
        
        ZStack {
            BackgroundViewCopy(theme: entry.theme, displayTheme: entry.displayTheme, imageTimestamp: entry.imageTimestamp)
                .id(entry.imageTimestamp)
            
            VStack(alignment: .leading, spacing: 5) {
                Text(entry.displayTheme == "standard" ? themeTitle(for: entry.theme) : (isRpg ? "▼ まいにちざつがく" : (isGameboy ? "DAILY TRIVIA" : "💡 毎日雑学")))
                    .font(customFontName.isEmpty ? .caption : .custom(customFontName, size: 12))
                    .fontWeight(customFontName.isEmpty ? .bold : .regular)
                    .foregroundColor(badgeTextColor)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(badgeBgColor)
                    .overlay(
                        RoundedRectangle(cornerRadius: (isRpg || isGameboy) ? 0 : 8)
                            .stroke(isRpg ? Color.white : (isGameboy ? Color(red: 15/255, green: 56/255, blue: 15/255) : Color.clear), lineWidth: (isRpg || isGameboy) ? 2 : 0)
                    )
                    .cornerRadius((isRpg || isGameboy) ? 0 : 8)
                
                Spacer()
                
                Text(entry.title)
                    .font(customFontName.isEmpty ? .system(size: 20, weight: .black, design: .rounded) : .custom(customFontName, size: 20))
                    .foregroundColor(titleColor)
                    .shadow(color: hasOutline ? .black : .clear, radius: 0, x: 1, y: 1)
                    .shadow(color: hasOutline ? .black : .clear, radius: 0, x: -1, y: 1)
                    .shadow(color: hasOutline ? .black : .clear, radius: 0, x: 1, y: -1)
                    .shadow(color: hasOutline ? .black : .clear, radius: 0, x: -1, y: -1)
                    .shadow(radius: shadowRad)
                    .minimumScaleFactor(0.8)
                
                Text(entry.content)
                    .font(customFontName.isEmpty ? .system(size: 13, weight: .bold, design: .rounded) : .custom(customFontName, size: 13))
                    .foregroundColor(contentColor)
                    .lineLimit(4)
                    .shadow(color: hasOutline ? .black : .clear, radius: 0, x: 1, y: 1)
                    .shadow(color: hasOutline ? .black : .clear, radius: 0, x: -1, y: 1)
                    .shadow(color: hasOutline ? .black : .clear, radius: 0, x: 1, y: -1)
                    .shadow(color: hasOutline ? .black : .clear, radius: 0, x: -1, y: -1)
                    .shadow(radius: hasShadow ? 1 : 0)
                    .lineSpacing(isRpg || isGameboy ? 4 : 0)
                
                Spacer()
            }
            .padding()
        }
        .overlay(
            RoundedRectangle(cornerRadius: isRpg ? 0 : (isGameboy ? 4 : 22))
                .stroke(isRpg ? Color.white : (isGameboy ? Color(red: 15/255, green: 56/255, blue: 15/255) : Color.clear), lineWidth: isRpg ? 4 : (isGameboy ? 2 : 0))
        )
    }
    
    func themeTitle(for theme: TriviaThemeCopy) -> String {
        switch theme {
        case .morning: return "☀️ おはよう雑学"
        case .noon: return "⛅️ こんにちは雑学"
        case .night: return "🌙 こんばんは雑学"
        }
    }
}

struct BackgroundViewCopy: View {
    let theme: TriviaThemeCopy
    let displayTheme: String
    let imageTimestamp: Double
    
    private func loadThemeImage() -> UIImage? {
        guard displayTheme != "standard" else { return nil }
        guard let containerURL = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.com.dailytrivia.app") else { return nil }
        
        if displayTheme == "rpg" || displayTheme == "cat" {
            let timeVariant: String
            switch theme {
            case .morning: timeVariant = "morning"
            case .noon: timeVariant = "noon"
            case .night: timeVariant = "night"
            }
            let variantFilename = "widget_bg_\(displayTheme)_\(timeVariant).jpeg"
            let variantURL = containerURL.appendingPathComponent(variantFilename)
            if let imageData = try? Data(contentsOf: variantURL), let img = UIImage(data: imageData) {
                return img
            }
        }
        
        let filename = "widget_bg_\(displayTheme).jpeg"
        let imageURL = containerURL.appendingPathComponent(filename)
        if let imageData = try? Data(contentsOf: imageURL), let img = UIImage(data: imageData) {
            return img
        }
        return nil
    }
    
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                if displayTheme == "standard" {
                    LinearGradient(gradient: Gradient(colors: gradientColors), startPoint: .top, endPoint: .bottom)
                    if theme == .morning {
                        Circle().fill(Color.orange.opacity(0.6)).frame(width: 100, height: 100).position(x: geometry.size.width * 0.8, y: geometry.size.height * 0.3).blur(radius: 20)
                    } else if theme == .noon {
                        Circle().fill(Color.white.opacity(0.6)).frame(width: 60, height: 60).position(x: 30, y: 30)
                        Circle().fill(Color.white.opacity(0.7)).frame(width: 80, height: 80).position(x: geometry.size.width - 40, y: 50)
                        VStack { Spacer(); Rectangle().fill(Color.green.opacity(0.6)).frame(height: 30).cornerRadius(15).offset(y: 15) }
                    } else if theme == .night {
                        Circle().fill(Color.yellow).frame(width: 4, height: 4).position(x: 20, y: 20)
                        Circle().fill(Color.yellow).frame(width: 3, height: 3).position(x: 100, y: 40)
                        Circle().fill(Color.yellow).frame(width: 5, height: 5).position(x: geometry.size.width - 30, y: 30)
                        Circle().fill(Color.yellow.opacity(0.8)).frame(width: 40, height: 40).position(x: 40, y: 40)
                    }
                } else if let themeImage = loadThemeImage() {
                    Image(uiImage: themeImage)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(width: geometry.size.width, height: geometry.size.height)
                        .clipped()
                    if displayTheme == "custom" {
                        Color.black.opacity(0.25)
                    }
                } else {
                    fallbackBackground(geometry: geometry)
                }
            }
        }
    }
    
    @ViewBuilder
    func fallbackBackground(geometry: GeometryProxy) -> some View {
        if displayTheme == "light" {
            Color.white
        } else if displayTheme == "dark" {
            Color(white: 0.11)
        } else if displayTheme == "gameboy" {
            Color(red: 155/255, green: 188/255, blue: 15/255)
        } else if displayTheme == "cat" {
            // Neutral grey/brown instead of skin color
            Color(red: 0.2, green: 0.15, blue: 0.1)
        } else {
            LinearGradient(gradient: Gradient(colors: gradientColors), startPoint: .top, endPoint: .bottom)
        }
    }
    
    var gradientColors: [Color] {
        switch theme {
            case .morning: return [Color(red: 1.0, green: 0.8, blue: 0.6), Color(red: 1.0, green: 0.6, blue: 0.6)]
            case .noon: return [Color(red: 0.4, green: 0.8, blue: 1.0), Color(red: 0.6, green: 0.9, blue: 1.0)]
            case .night: return [Color(red: 0.1, green: 0.1, blue: 0.4), Color(red: 0.2, green: 0.2, blue: 0.6)]
        }
    }
}
