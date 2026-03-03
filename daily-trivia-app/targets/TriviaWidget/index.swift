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
        TriviaEntry(date: Date(), id: 0, title: "雑学のタイトル", content: "ここに雑学の内容が表示されます。", theme: .morning)
    }

    func getSnapshot(in context: Context, completion: @escaping (TriviaEntry) -> ()) {
        let entry = TriviaEntry(date: Date(), id: 0, title: "富士山の高さ", content: "富士山の高さは3776メートルです。", theme: .noon)
        completion(entry)
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TriviaEntry>) -> ()) {
        var entries: [TriviaEntry] = []
        let currentDate = Date()
        let calendar = Calendar.current
        
        // App Group defaults
        let userDefaults = UserDefaults(suiteName: "group.com.dailytrivia.app")
        let triviaJson = userDefaults?.string(forKey: "daily_trivia")
        
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
        
        if !isValidData {
            // If no valid User ID and no stale data, show loading
            if (userId == nil || userId == "" || userId == "widget_guest") && staleFallbackList.isEmpty {
                 print("Widget: No valid User ID and no cached data. Waiting for App...")
                 
                 let loadingEntry = TriviaEntry(
                    date: currentDate,
                    id: 0,
                    title: "読み込み中...",
                    content: "アプリを一度開いてください。",
                    theme: .morning
                 )
                 
                 let nextUpdate = calendar.date(byAdding: .minute, value: 5, to: currentDate)!
                 let timeline = Timeline(entries: [loadingEntry], policy: .after(nextUpdate))
                 completion(timeline)
                 return
            }
            
            // Valid User ID exists, proceed to fetch
            triviaList = [] // Clear old data
            var urlString = "https://daily-trivia-e7ge.onrender.com/trivia/widget?date=\(todayStr)"
            if let uid = userId, !uid.isEmpty {
                urlString += "&user_id=\(uid)"
            }
            
            if let url = URL(string: urlString) {
                print("Fetching widget data from: \(urlString)")
                
                var request = URLRequest(url: url)
                request.httpMethod = "GET"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.timeoutInterval = 15 // Increased from default for Render cold start
                
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
                                // Optional date for validation if backend sends it
                                let date: String?
                            }
                            
                            let apiItems = try JSONDecoder().decode([APITriviaItem].self, from: data)
                            
                            // Validate Date if available (Optional but recommended)
                            // For now, we trust the API returned today's data for this user
                            // But strict checking effectively happens because we request 'today'
                            
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
                
                // Wait for up to 15 seconds for network (Render cold start can be slow)
                let result = dispatchGroup.wait(timeout: .now() + 15)
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
                    theme: .morning
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
                theme: currentTheme
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
                    theme: .morning
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
                    theme: .morning
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
                    theme: .noon
                )
                entries.append(noonEntry)
            } else if entries.isEmpty && currentDate < nightDate {
                // Missed 10:00 AM, but still before 18:00
                 let noonNowEntry = TriviaEntry(
                    date: currentDate,
                    id: triviaList[1].id,
                    title: triviaList[1].title,
                    content: triviaList[1].content,
                    theme: .noon
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
                    theme: .night
                )
                entries.append(nightEntry)
            } else if entries.isEmpty {
                 // After 18:00
                 let nightNowEntry = TriviaEntry(
                    date: currentDate,
                    id: triviaList[2].id,
                    title: triviaList[2].title,
                    content: triviaList[2].content,
                    theme: .night
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
}

struct TriviaWidgetEntryView : View {
    var entry: Provider.Entry

    var body: some View {
        ZStack {
            // 背景 (Storybook Style)
            BackgroundView(theme: entry.theme)
            
            // コンテンツ
            VStack(alignment: .leading, spacing: 5) {
                Text(entry.themeTitle)
                    .font(.caption)
                    .fontWeight(.bold)
                    .foregroundColor(.white.opacity(0.9))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.black.opacity(0.2))
                    .cornerRadius(8)
                
                Spacer()
                
                Text(entry.title)
                    .font(.system(size: 20, weight: .black, design: .rounded))
                    .foregroundColor(.white)
                    .shadow(radius: 2)
                    .minimumScaleFactor(0.8)
                
                Text(entry.content)
                    .font(.system(size: 13, weight: .bold, design: .rounded))
                    .foregroundColor(.white)
                    .lineLimit(4)
                    .shadow(radius: 1)
                
                Spacer()
            }
            .padding()
        }
        .widgetURL(URL(string: "dailytrivia://details?id=\(entry.id)&title=\(entry.title.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")&content=\(entry.content.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")"))
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
    
    var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Base Gradient
                LinearGradient(gradient: Gradient(colors: gradientColors), startPoint: .top, endPoint: .bottom)
                
                // Storybook Elements
                if theme == .morning {
                    // Soft Sunrise
                    Circle()
                    .fill(Color.orange.opacity(0.6))
                    .frame(width: 100, height: 100)
                    .position(x: geometry.size.width * 0.8, y: geometry.size.height * 0.3)
                    .blur(radius: 20)
                } else if theme == .noon {
                    // Fluffy Clouds (Simple Circles)
                    Circle()
                        .fill(Color.white.opacity(0.6))
                        .frame(width: 60, height: 60)
                        .position(x: 30, y: 30)
                    Circle()
                        .fill(Color.white.opacity(0.7))
                        .frame(width: 80, height: 80)
                        .position(x: geometry.size.width - 40, y: 50)
                    // Green Field at bottom
                    VStack {
                        Spacer()
                        Rectangle()
                            .fill(Color.green.opacity(0.6))
                            .frame(height: 30)
                            .cornerRadius(15)
                            .offset(y: 15)
                    }
                } else if theme == .night {
                    // Stars
                    Circle().fill(Color.yellow).frame(width: 4, height: 4).position(x: 20, y: 20)
                    Circle().fill(Color.yellow).frame(width: 3, height: 3).position(x: 100, y: 40)
                    Circle().fill(Color.yellow).frame(width: 5, height: 5).position(x: geometry.size.width - 30, y: 30)
                    // Moon
                    Circle()
                        .fill(Color.yellow.opacity(0.8))
                        .frame(width: 40, height: 40)
                        .position(x: 40, y: 40)
                }
            }
        }
    }
    
    var gradientColors: [Color] {
        switch theme {
        case .morning:
            return [Color(red: 1.0, green: 0.8, blue: 0.6), Color(red: 1.0, green: 0.6, blue: 0.6)] // Pastel Orange/Pink
        case .noon:
            return [Color(red: 0.4, green: 0.8, blue: 1.0), Color(red: 0.6, green: 0.9, blue: 1.0)] // Sky Blue
        case .night:
            return [Color(red: 0.1, green: 0.1, blue: 0.4), Color(red: 0.2, green: 0.2, blue: 0.6)] // Dark Blue
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
        .supportedFamilies([.systemSmall, .systemMedium])
        .contentMarginsDisabled()
    }
}
