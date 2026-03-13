import WidgetKit
import SwiftUI

struct TriviaData: Codable {
    let id: Int
    let title: String
    let content: String
    let date: String?
}

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> TriviaEntry {
        TriviaEntry(date: Date(), id: 0, title: "雑学のタイトル", content: "ここに雑学の内容が表示されます。", theme: .morning, displayTheme: "standard")
    }

    func getSnapshot(in context: Context, completion: @escaping (TriviaEntry) -> ()) {
        let entry = TriviaEntry(date: Date(), id: 0, title: "富士山の高さ", content: "富士山の高さは3776メートルです。", theme: .noon, displayTheme: "standard")
        completion(entry)
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TriviaEntry>) -> ()) {
        var entries: [TriviaEntry] = []
        let currentDate = Date()
        let calendar = Calendar.current
        
        // App Group defaults
        let userDefaults = UserDefaults(suiteName: "group.com.dailytrivia.app")
        let triviaJson = userDefaults?.string(forKey: "daily_trivia")
        let displayTheme = userDefaults?.string(forKey: "widget_theme") ?? "standard"
        
        // Load timestamp to bust image cache
        var imageTimestamp: Double = 0
        if displayTheme == "custom" {
            imageTimestamp = userDefaults?.double(forKey: "widget_theme_image_custom_timestamp") ?? Date().timeIntervalSince1970
        } else if displayTheme == "rpg" || displayTheme == "cat" {
            // Time-variant themes: read timestamps from all 3 variants and use the most recent
            let morningTs = userDefaults?.double(forKey: "widget_theme_image_\(displayTheme)_morning_timestamp") ?? 0
            let noonTs = userDefaults?.double(forKey: "widget_theme_image_\(displayTheme)_noon_timestamp") ?? 0
            let nightTs = userDefaults?.double(forKey: "widget_theme_image_\(displayTheme)_night_timestamp") ?? 0
            imageTimestamp = max(morningTs, max(noonTs, nightTs))
            if imageTimestamp == 0 {
                imageTimestamp = Date().timeIntervalSince1970
            }
        } else {
            imageTimestamp = userDefaults?.double(forKey: "widget_theme_image_\(displayTheme)_timestamp") ?? Date().timeIntervalSince1970
        }
        
        var triviaList: [TriviaData] = []
        var staleFallbackList: [TriviaData] = [] // Keep stale data as fallback
        
        // 1. Try to load local data
        if let jsonString = triviaJson, let data = jsonString.data(using: .utf8) {
            do {
                triviaList = try JSONDecoder().decode([TriviaData].self, from: data)
            } catch {
                print("Failed to decode JSON: \(error)")
            }
        }
        
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone.current
        
        // Calculate "Effective Today" (Current Time - 2 hours)
        let effectiveDate = calendar.date(byAdding: .hour, value: -2, to: currentDate)!
        let todayStr = formatter.string(from: effectiveDate)
        
        // 2. Check if data is valid (today's data)
        var isValidData = false
        if !triviaList.isEmpty {
            if let firstItemDate = triviaList[0].date {
                isValidData = (firstItemDate == todayStr)
            } else {
                isValidData = false // FIX: Never treat legacy dataless trivia as current today data
            }
            // Keep old data as fallback (show yesterday's trivia instead of "loading")
            staleFallbackList = triviaList
        }
        
        // 3. Strict User ID Check & Fetch
        let userId = userDefaults?.string(forKey: "user_id")
        let firebaseToken = userDefaults?.string(forKey: "firebase_token")
        
        if isValidData {
            print("Widget: Using valid cached data for today, skipping fetch.")
        } else {
            // If no valid User ID and no stale data, show loading
            if (userId == nil || userId == "" || userId == "widget_guest") && staleFallbackList.isEmpty {
                 print("Widget: No valid User ID and no cached data. Waiting for App...")
                 
                 let loadingEntry = TriviaEntry(
                    date: currentDate,
                    id: 0,
                    title: "読み込み中...",
                    content: "アプリを一度開いてください。",
                    theme: .morning,
                    displayTheme: displayTheme,
                    imageTimestamp: imageTimestamp
                 )
                 
                 let nextUpdate = calendar.date(byAdding: .minute, value: 5, to: currentDate)!
                 let timeline = Timeline(entries: [loadingEntry], policy: .after(nextUpdate))
                 completion(timeline)
                 return
            }
            
            // Valid User ID exists, proceed to fetch
            triviaList = [] // Clear old data
            var urlString = "https://daily-trivia-e7ge.onrender.com/trivia/widget?date=\(todayStr)"
            if let uid = userId, !uid.isEmpty, uid != "widget_guest" {
                urlString += "&user_id=\(uid)"
            }
            
            if let url = URL(string: urlString) {
                print("Fetching widget data from: \(urlString)")
                
                var request = URLRequest(url: url)
                request.httpMethod = "GET"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.timeoutInterval = 10 // Reduced timeout
                
                if let token = firebaseToken, !token.isEmpty {
                    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                } else {
                    print("Widget: No Firebase token available, attempting request without auth.")
                }
                
                let dispatchGroup = DispatchGroup()
                dispatchGroup.enter()
                
                let task = URLSession.shared.dataTask(with: request) { data, response, error in
                    defer { dispatchGroup.leave() }
                    
                    if let data = data {
                        do {
                            // Decode API response validation
                            struct APITriviaItem: Codable {
                                let id: Int
                                let title: String
                                let content: String
                                let date: String?
                            }
                            
                            let apiItems = try JSONDecoder().decode([APITriviaItem].self, from: data)
                            
                            // Map to Widget Data Format
                            let newTriviaList = apiItems.prefix(3).map { item in
                                TriviaData(id: item.id, title: item.title, content: item.content, date: todayStr)
                            }
                            
                            if !newTriviaList.isEmpty {
                                triviaList = newTriviaList
                                
                                // Save to UserDefaults for cache
                                if let encoded = try? JSONEncoder().encode(newTriviaList) {
                                    if let jsonString = String(data: encoded, encoding: .utf8) {
                                        userDefaults?.set(jsonString, forKey: "daily_trivia")
                                        print("Saved fetched data to UserDefaults")
                                    }
                                }
                            }
                        } catch {
                            print("Widget fetch error: \(error)")
                        }
                    }
                }
                task.resume()
                
                // Wait for network
                let result = dispatchGroup.wait(timeout: .now() + 10)
                if result == .timedOut {
                    print("Widget fetch timed out")
                }
            }
        }
        
        // 4. Fallback: use stale cached data if fetch failed
        var usedStaleData = false
        if triviaList.isEmpty {
             if !staleFallbackList.isEmpty {
                 // Show yesterday's data instead of error - much better UX
                 print("Widget: Using stale cached data as fallback")
                 triviaList = staleFallbackList
                 usedStaleData = true
                 // Retry sooner to get fresh data
                 // (will fall through to timeline building below)
             } else {
                 // No cached data at all - show error
                 let errorEntry = TriviaEntry(
                    date: currentDate,
                    id: 0,
                    title: "読み込み失敗",
                    content: "アプリを一度開いて\nデータを更新してください。",
                    theme: .morning,
                    displayTheme: displayTheme,
                    imageTimestamp: imageTimestamp
                 )
                 let nextUpdate = calendar.date(byAdding: .minute, value: 15, to: currentDate)!
                 let timeline = Timeline(entries: [errorEntry], policy: .after(nextUpdate))
                 completion(timeline)
                 return
             }
        }
        
        // Fill up to 3 items if needed (shouldn't happen with valid API)
        while triviaList.count < 3 {
             triviaList.append(triviaList.last ?? TriviaData(id: 0, title: "No Data", content: "No Data", date: todayStr))
        }

        // 5. Build Timeline
        // Use the same effective date logic for consistency
        var baseDate = currentDate
        let currentHour = calendar.component(.hour, from: currentDate)
        if currentHour < 2 {
            // If it's 0:00 or 1:00, we are still showing "yesterday's" trivia until 2:00 AM
            baseDate = calendar.date(byAdding: .day, value: -1, to: currentDate)!
        }
        
        let morningDate = calendar.date(bySettingHour: 2, minute: 0, second: 0, of: baseDate)!
        let noonDate = calendar.date(bySettingHour: 10, minute: 0, second: 0, of: baseDate)!
        let nightDate = calendar.date(bySettingHour: 18, minute: 0, second: 0, of: baseDate)!

        if usedStaleData {
            // SAFE MODE: If using stale data, NEVER schedule for the past.
            // Provide ONE comforting entry for "Right Now".
            var currentTheme: TriviaTheme = .morning
            
            if currentHour >= 18 || currentHour < 2 {
                currentTheme = .night
            } else if currentHour >= 10 {
                currentTheme = .noon
            }
            
            let comfortingEntry = TriviaEntry(
                date: currentDate, // Important: Use NOW so it isn't rejected by WidgetKit
                id: 0,
                title: "今日の雑学を準備中...",
                content: "新しい雑学を探しています。\nもう少々お待ちください…！\n(アプリを開くと早く更新されることがあります)",
                theme: currentTheme,
                displayTheme: displayTheme,
                imageTimestamp: imageTimestamp
            )
            entries.append(comfortingEntry)
        } else {
            // FRESH DATA MODE: Schedule normally, but ONLY if the scheduled time hasn't passed today.
            // Morning
            if currentDate <= morningDate {
                let morningEntry = TriviaEntry(
                    date: morningDate,
                    id: triviaList[0].id,
                    title: triviaList[0].title,
                    content: triviaList[0].content,
                    theme: .morning,
                    displayTheme: displayTheme,
                    imageTimestamp: imageTimestamp
                )
                entries.append(morningEntry)
            } else if entries.isEmpty && currentDate < noonDate {
                // We missed the exact 2:00 AM update, but we are still in the morning window (before 10:00).
                // Ensure there is at least a "Right Now" entry showing the morning content.
                 let morningNowEntry = TriviaEntry(
                    date: currentDate,
                    id: triviaList[0].id,
                    title: triviaList[0].title,
                    content: triviaList[0].content,
                    theme: .morning,
                    displayTheme: displayTheme,
                    imageTimestamp: imageTimestamp
                )
                entries.append(morningNowEntry)
            }
            
            // Noon
            if currentDate <= noonDate {
                let noonEntry = TriviaEntry(
                    date: noonDate,
                    id: triviaList[1].id,
                    title: triviaList[1].title,
                    content: triviaList[1].content,
                    theme: .noon,
                    displayTheme: displayTheme,
                    imageTimestamp: imageTimestamp
                )
                entries.append(noonEntry)
            } else if entries.isEmpty && currentDate < nightDate {
                // Missed 10:00 AM, but still before 18:00
                 let noonNowEntry = TriviaEntry(
                    date: currentDate,
                    id: triviaList[1].id,
                    title: triviaList[1].title,
                    content: triviaList[1].content,
                    theme: .noon,
                    displayTheme: displayTheme,
                    imageTimestamp: imageTimestamp
                )
                entries.append(noonNowEntry)
            }
            
            // Night
            if currentDate <= nightDate {
                let nightEntry = TriviaEntry(
                    date: nightDate,
                    id: triviaList[2].id,
                    title: triviaList[2].title,
                    content: triviaList[2].content,
                    theme: .night,
                    displayTheme: displayTheme,
                    imageTimestamp: imageTimestamp
                )
                entries.append(nightEntry)
            } else if entries.isEmpty {
                 // After 18:00
                 let nightNowEntry = TriviaEntry(
                    date: currentDate,
                    id: triviaList[2].id,
                    title: triviaList[2].title,
                    content: triviaList[2].content,
                    theme: .night,
                    displayTheme: displayTheme,
                    imageTimestamp: imageTimestamp
                )
                entries.append(nightNowEntry)
            }
        }

        // Next update
        let nextUpdate: Date
        if usedStaleData {
            nextUpdate = calendar.date(byAdding: .minute, value: 15, to: currentDate)!
            print("Widget: Scheduled next update in 15 minutes because stale data is used")
        } else {
            nextUpdate = calendar.date(byAdding: .day, value: 1, to: morningDate)!
            print("Widget: Scheduled next update for tomorrow at 2:00 AM")
        }
        
        let timeline = Timeline(entries: entries, policy: .after(nextUpdate))
        completion(timeline)
    }
}

enum TriviaTheme {
    case morning, noon, night
}

struct TriviaEntry: TimelineEntry {
    let date: Date
    let id: Int
    let title: String
    let content: String
    let theme: TriviaTheme
    let displayTheme: String // "standard", "light", "dark"
    var imageTimestamp: Double = 0 // Used to bust image cache
}

struct TriviaWidgetEntryView : View {
    var entry: Provider.Entry
    @Environment(\.widgetFamily) private var widgetFamily

    var body: some View {
        if widgetFamily == .accessoryInline || widgetFamily == .accessoryCircular || widgetFamily == .accessoryRectangular {
            accessoryView
                .widgetURL(deepLinkURL)
        } else {
            regularWidgetView
                .widgetURL(deepLinkURL)
        }
    }

    private var deepLinkURL: URL? {
        URL(string: "dailytrivia://details?id=\(entry.id)&title=\(entry.title.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")&content=\(entry.content.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")&from_widget=true")
    }

    @ViewBuilder
    private var accessoryView: some View {
        switch widgetFamily {
        case .accessoryInline:
            Text("毎日雑学: \(entry.title)")
        case .accessoryCircular:
            ZStack {
                AccessoryWidgetBackground()
                Text("雑")
                    .font(.system(size: 16, weight: .bold))
            }
        case .accessoryRectangular:
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.themeTitle)
                    .font(.caption2)
                    .lineLimit(1)
                Text(entry.title)
                    .font(.caption)
                    .fontWeight(.bold)
                    .lineLimit(1)
                Text(entry.content)
                    .font(.caption2)
                    .lineLimit(1)
            }
        default:
            EmptyView()
        }
    }

    private var regularWidgetView: some View {
        let isLight = entry.displayTheme == "light"
        let isDark = entry.displayTheme == "dark"
        let isRpg = entry.displayTheme == "rpg"
        let isCat = entry.displayTheme == "cat"
        let isCustom = entry.displayTheme == "custom"
        let hasOutline = isRpg || isCat
        
        let titleColor: Color = isLight ? Color(white: 0.1) : .white
        let contentColor: Color = isLight ? Color(white: 0.3) : .white
        let badgeBgColor: Color = isLight ? Color(white: 0.95) : (isDark ? Color(white: 0.17) : (isRpg ? .black : Color.black.opacity(0.2)))
        let badgeTextColor: Color = isLight ? Color(white: 0.2) : .white.opacity(0.9)
        let hasShadow = entry.displayTheme == "standard" || isCustom
        let shadowRad: CGFloat = hasShadow ? 2 : 0
        let customFontName = (isRpg) ? "DotGothic16-Regular" : ""
        
        return ZStack {
            BackgroundView(theme: entry.theme, displayTheme: entry.displayTheme, imageTimestamp: entry.imageTimestamp, widgetFamily: widgetFamily)
                .id(entry.imageTimestamp) // Force SwiftUI redraw on timestamp update
            
            VStack(alignment: .leading, spacing: 5) {
                Text(entry.displayTheme == "standard" ? entry.themeTitle : (isRpg ? "▼ まいにちざつがく" : (isCustom ? "✨ 毎日雑学" : "💡 毎日雑学")))
                    .font(customFontName.isEmpty ? .caption : .custom(customFontName, size: 12))
                    .fontWeight(customFontName.isEmpty ? .bold : .regular)
                    .foregroundColor(badgeTextColor)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(badgeBgColor)
                    .overlay(
                        RoundedRectangle(cornerRadius: isRpg ? 0 : 8)
                            .stroke(isRpg ? Color.white : (Color.clear), lineWidth: isRpg ? 2 : 0)
                    )
                    .cornerRadius(isRpg ? 0 : 8)
                
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
                    .lineSpacing(isRpg ? 4 : 0)
                
                Spacer()
            }
            .padding()
        }
    }
}

extension TriviaEntry {
    var themeTitle: String {
        switch theme {
        case .morning: return "☀️ おはよう雑学"
        case .noon: return "⛅️ こんにちは雑学"
        case .night: return "🌙 こんばんは雑学"
        }
    }
}

struct BackgroundView: View {
    let theme: TriviaTheme
    let displayTheme: String
    let imageTimestamp: Double
    let widgetFamily: WidgetFamily
    
    /// App Group から widget_bg_{displayTheme}.jpeg を読み込み
    private func loadThemeImage() -> UIImage? {
        guard displayTheme != "standard" else { return nil }
        guard let containerURL = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.com.dailytrivia.app") else { return nil }
        
        // RPGや猫は時間帯別の画像を試す (rpg_morning, rpg_noon, rpg_night)
        if displayTheme == "rpg" || displayTheme == "cat" {
            let timeVariant: String
            switch theme {
            case .morning: timeVariant = "morning"
            case .noon: timeVariant = "noon"
            case .night: timeVariant = "night"
            }
            let variantFilename = "widget_bg_\(displayTheme)_\(timeVariant).jpeg"
            let variantURL = containerURL.appendingPathComponent(variantFilename)
            
            // Bypass UIImage cache by loading as Data first
            if let imageData = try? Data(contentsOf: variantURL), let img = UIImage(data: imageData) {
                return img
            }
        }
        
        // 通常のファイル名
        let filename = "widget_bg_\(displayTheme).jpeg"
        let imageURL = containerURL.appendingPathComponent(filename)
        
        // Bypass UIImage cache by loading as Data first
        if let imageData = try? Data(contentsOf: imageURL), let img = UIImage(data: imageData) {
            return img
        }
        
        return nil
    }
    
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                if displayTheme == "standard" {
                    standardBackground(geometry: geometry)
                } else if let themeImage = loadThemeImage() {
                    let trailingCropForSmall = widgetFamily == .systemSmall && (displayTheme == "rpg" || displayTheme == "cat")
                    Image(uiImage: themeImage)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(
                            width: geometry.size.width,
                            height: geometry.size.height,
                            alignment: trailingCropForSmall ? .trailing : .center
                        )
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
    func standardBackground(geometry: GeometryProxy) -> some View {
        LinearGradient(gradient: Gradient(colors: gradientColors), startPoint: .top, endPoint: .bottom)
        if theme == .morning {
            Circle().fill(Color.orange.opacity(0.6)).frame(width: 100, height: 100)
                .position(x: geometry.size.width * 0.8, y: geometry.size.height * 0.3).blur(radius: 20)
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
    }
    
    @ViewBuilder
    func fallbackBackground(geometry: GeometryProxy) -> some View {
        if displayTheme == "light" {
            Color.white
        } else if displayTheme == "dark" {
            Color(white: 0.11)
        } else if displayTheme == "gameboy" {
            Color(red: 155/255, green: 188/255, blue: 15/255)
        } else if displayTheme == "rpg" {
            Color.black
        } else if displayTheme == "cat" {
            // Neutral grey/brown instead of skin color
            Color(red: 0.2, green: 0.15, blue: 0.1)
        } else {
            LinearGradient(gradient: Gradient(colors: gradientColors), startPoint: .top, endPoint: .bottom)
        }
    }
    
    var gradientColors: [Color] {
        switch theme {
        case .morning:
            return [Color(red: 1.0, green: 0.8, blue: 0.6), Color(red: 1.0, green: 0.6, blue: 0.6)]
        case .noon:
            return [Color(red: 0.4, green: 0.8, blue: 1.0), Color(red: 0.6, green: 0.9, blue: 1.0)]
        case .night:
            return [Color(red: 0.1, green: 0.1, blue: 0.4), Color(red: 0.2, green: 0.2, blue: 0.6)]
        }
    }
}

@main
struct TriviaWidget: Widget {
    let kind: String = "TriviaWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            TriviaWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("毎日雑学")
        .description("朝・昼・夜で変わる雑学をお届けします。")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryInline, .accessoryCircular, .accessoryRectangular])
        .contentMarginsDisabled()
    }
}

// ==========================================
// Xcode Canvas Previews
// 以下のコードブロックの隣にある「プレビュー再生ボタン」を押すか、XcodeのCanvasを開くと、
// 全てのウィジェットデザインを一覧表示でき、ここから直接スクショを撮ることが可能です！
// ==========================================
struct TriviaWidget_Previews: PreviewProvider {
    // プレビュー用のダミーデータ
    static let dummyDate = Date()
    static let baseEntry = TriviaEntry(
        date: dummyDate,
        id: 1,
        title: "富士山の高さ",
        content: "富士山の高さは3776メートルです。",
        theme: .noon,
        displayTheme: "standard"
    )
    
    // Rpg用のダミーデータ（ひらがな）
    static let rpgEntry = TriviaEntry(
        date: dummyDate,
        id: 1,
        title: "富士山の高さ",
        content: "ふじさんの たかさは\n3776メートル である！",
        theme: .noon,
        displayTheme: "rpg"
    )

    static var previews: some View {
        Group {
            // --- Standard ---
            TriviaWidgetEntryView(entry: TriviaEntry(date: dummyDate, id: 1, title: "富士山の高さ", content: "富士山の高さは3776メートルです。", theme: .morning, displayTheme: "standard"))
                .previewContext(WidgetPreviewContext(family: .systemMedium))
                .previewDisplayName("Standard - Morning")

            TriviaWidgetEntryView(entry: TriviaEntry(date: dummyDate, id: 1, title: "富士山の高さ", content: "富士山の高さは3776メートルです。", theme: .noon, displayTheme: "standard"))
                .previewContext(WidgetPreviewContext(family: .systemMedium))
                .previewDisplayName("Standard - Noon")

            TriviaWidgetEntryView(entry: TriviaEntry(date: dummyDate, id: 1, title: "富士山の高さ", content: "富士山の高さは3776メートルです。", theme: .night, displayTheme: "standard"))
                .previewContext(WidgetPreviewContext(family: .systemMedium))
                .previewDisplayName("Standard - Night")

            // --- Light & Dark ---
            TriviaWidgetEntryView(entry: TriviaEntry(date: dummyDate, id: 1, title: "富士山の高さ", content: "富士山の高さは3776メートルです。", theme: .noon, displayTheme: "light"))
                .previewContext(WidgetPreviewContext(family: .systemMedium))
                .previewDisplayName("Light Theme")

            TriviaWidgetEntryView(entry: TriviaEntry(date: dummyDate, id: 1, title: "富士山の高さ", content: "富士山の高さは3776メートルです。", theme: .noon, displayTheme: "dark"))
                .previewContext(WidgetPreviewContext(family: .systemMedium))
                .previewDisplayName("Dark Theme")

            // --- Game Contexts ---
            TriviaWidgetEntryView(entry: rpgEntry)
                .previewContext(WidgetPreviewContext(family: .systemMedium))
                .previewDisplayName("RPG Theme (changes by time)")

            TriviaWidgetEntryView(entry: baseEntry.modified(displayTheme: "cat"))
                .previewContext(WidgetPreviewContext(family: .systemMedium))
                .previewDisplayName("Cat Theme")

            // --- Lock Screen ---
            TriviaWidgetEntryView(entry: baseEntry)
                .previewContext(WidgetPreviewContext(family: .accessoryInline))
                .previewDisplayName("Lock Screen - Inline")

            TriviaWidgetEntryView(entry: baseEntry)
                .previewContext(WidgetPreviewContext(family: .accessoryCircular))
                .previewDisplayName("Lock Screen - Circular")

            TriviaWidgetEntryView(entry: baseEntry)
                .previewContext(WidgetPreviewContext(family: .accessoryRectangular))
                .previewDisplayName("Lock Screen - Rectangular")
        }
    }
}

extension TriviaEntry {
    func modified(displayTheme: String) -> TriviaEntry {
        return TriviaEntry(date: self.date, id: self.id, title: self.title, content: self.content, theme: self.theme, displayTheme: displayTheme)
    }
}
