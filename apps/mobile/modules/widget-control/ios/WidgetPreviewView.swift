import ExpoModulesCore
import SwiftUI

class WidgetPreviewView: ExpoView {
  private let hostingController: UIHostingController<TriviaWidgetEntryViewCopy>
  
  // Start with some default entry so the view isn't empty initially.
  private var currentEntry: TriviaEntryCopy = TriviaEntryCopy(
    date: Date(),
    id: 1,
    title: "富士山の高さ",
    content: "富士山の高さは3776メートルです。",
    theme: .noon,
    displayTheme: "standard",
    imageTimestamp: Date().timeIntervalSince1970
  )

  required init(appContext: AppContext? = nil) {
    self.hostingController = UIHostingController(rootView: TriviaWidgetEntryViewCopy(entry: currentEntry))
    super.init(appContext: appContext)
    
    // Embed the hosting controller's view.
    self.hostingController.view.translatesAutoresizingMaskIntoConstraints = false
    self.hostingController.view.backgroundColor = .clear
    self.addSubview(self.hostingController.view)
    
    NSLayoutConstraint.activate([
      self.hostingController.view.topAnchor.constraint(equalTo: self.topAnchor),
      self.hostingController.view.bottomAnchor.constraint(equalTo: self.bottomAnchor),
      self.hostingController.view.leadingAnchor.constraint(equalTo: self.leadingAnchor),
      self.hostingController.view.trailingAnchor.constraint(equalTo: self.trailingAnchor),
    ])
  }
  
  // These will be called by Expo when the JS props update.
  func setDisplayTheme(_ theme: String) {
    self.currentEntry = TriviaEntryCopy(
      date: self.currentEntry.date,
      id: self.currentEntry.id,
      title: self.currentEntry.title,
      content: "富士山の高さは3776メートルです。",
      theme: self.currentEntry.theme,
      displayTheme: theme,
      imageTimestamp: Date().timeIntervalSince1970
    )
    updateView()
  }

  func setTimeTheme(_ time: String) {
    let tTheme: TriviaThemeCopy
    if time == "morning" { tTheme = .morning }
    else if time == "night" { tTheme = .night }
    else { tTheme = .noon }
    
    self.currentEntry = TriviaEntryCopy(
      date: self.currentEntry.date,
      id: self.currentEntry.id,
      title: self.currentEntry.title,
      content: self.currentEntry.content,
      theme: tTheme,
      displayTheme: self.currentEntry.displayTheme,
      imageTimestamp: Date().timeIntervalSince1970
    )
    updateView()
  }

  private func updateView() {
    self.hostingController.rootView = TriviaWidgetEntryViewCopy(entry: currentEntry)
  }
}
