import AppKit
import SwiftUI
import Carbon

struct Caption: Identifiable, Codable {
    let id: String
    var original: String
    var translation: String
    var partial: Bool
    var updatedAt: Date
    var segmentIDs: Set<Int>
    var session: String
    var translationEngine: String? = nil
    var translationStyle: String? = nil
    var beamSize: Int? = nil
    var clockNormalization: Bool? = nil
    var translationInput: String? = nil
    var recognitionMs: Double? = nil
    var translationMs: Double? = nil
    var sinceFirstRecognitionMs: Double? = nil
    var recognitionScope: String? = nil
    var sourceLanguage: String? = nil
    static func duration(_ ms: Double?) -> String {
        guard let ms, ms.isFinite, ms >= 0 else { return "—" }
        return ms < 1000 ? "\(Int(ms.rounded())) мс" : String(format: "%.1f с", ms / 1000)
    }
    var performance: String { "Речь \(Self.duration(recognitionMs)) · Перевод \(Self.duration(translationMs))" }
    var performanceHelp: String {
        (recognitionScope == "stream_chunk" ? "Речь: обработка последней порции звука Zipformer; не время всей фразы." : "Речь: последний проход распознавания для этой фразы; не сумма всех проходов.")
        + " Перевод: обработка текста. Это не полная задержка от звука до карточки."
        + (sinceFirstRecognitionMs.map { " От первого подтверждённого фрагмента до перевода: \(Self.duration($0)) (включает накопление и очередь)." } ?? "")
    }
    func age(at now: Date) -> Double { max(0, now.timeIntervalSince(updatedAt)) }
}
final class Model: ObservableObject {
    var openWord: (String, String, String, String) -> Void = { _, _, _, _ in }
    @Published var sourceLanguage = "et"
    let historyStore: HistoryStore?
    @Published var historyRows: [Caption] = []
    @Published var historyDays: [String] = []
    @Published var historyDay = ""
    @Published var historyError = ""
    init(historyStore: HistoryStore? = nil) {
        self.historyStore = historyStore
        if let historyStore { loadHistory(historyStore.day(for: Date())) }
    }
    func loadHistory(_ day: String) {
        historyDay = day
        guard let historyStore else { historyRows = captions.filter { !$0.partial }; return }
        do {
            historyRows = try historyStore.load(day)
            try historyStore.exportText(day, rows: historyRows)
            historyDays = Array(Set(historyStore.days + [historyStore.day(for: Date())])).sorted(by: >)
            historyError = historyStore.warning
        } catch { historyError = "Не удалось прочитать историю: \(error.localizedDescription)" }
    }
    var lastRecognitionMs: Double?
    var lastTranslationMs: Double?
    var performanceStatus: String { "Слушаю · речь \(Caption.duration(lastRecognitionMs)) · перевод \(Caption.duration(lastTranslationMs))" }
    @Published var hiddenIDs: Set<String> = []
    @Published var draft = ""
    @Published var captions: [Caption] = []
    @Published var pending: [(session: String, id: Int, text: String)] = []
    @Published var now = Date()
    @Published var lifetime = UserDefaults.standard.double(forKey: "lifetime") == 0 ? 30.0 : UserDefaults.standard.double(forKey: "lifetime")
    @Published var status = "Нажмите «Начать» в меню"
    @Published var size = UserDefaults.standard.double(forKey: "textSize") == 0 ? 22.0 : UserDefaults.standard.double(forKey: "textSize")
    @Published var opacity = UserDefaults.standard.double(forKey: "opacity") == 0 ? 0.85 : UserDefaults.standard.double(forKey: "opacity")
    @Published var originalFirst = true
    @Published var cardLayout = UserDefaults.standard.string(forKey: "cardLayout") ?? "columns"
    // Hide noise hallucinations made solely of thanks, without changing history data.
    static func isStandaloneThanks(_ text: String) -> Bool {
        let words = text.precomposedStringWithCanonicalMapping.lowercased()
            .components(separatedBy: CharacterSet.whitespacesAndNewlines.union(.punctuationCharacters))
            .filter { !$0.isEmpty }
        return !words.isEmpty && words.allSatisfy { $0 == "aita" || $0 == "aitäh" }
    }
    var active: Caption? { captions.last(where: { $0.partial }) }
    var liveOriginal: String {
        let current = active
        let remaining = pending.filter { item in !(current?.session == item.session && current?.segmentIDs.contains(item.id) == true) }
        let text = ([current?.original ?? ""] + remaining.map { $0.text } + [draft]).filter { !$0.isEmpty }.joined(separator: " ")
        return Self.isStandaloneThanks(text) ? "" : text
    }
    var visible: [Caption] { captions.reversed().filter { !$0.partial && !hiddenIDs.contains($0.id) && !Self.isStandaloneThanks($0.original) && $0.age(at: now) < lifetime } }
    func textScale(_ item: Caption) -> Double {
        item.age(at: now) < 10 ? 1 : 0.75
    }
    func hide(_ item: Caption) { hiddenIDs.insert(item.id) }
    func accept(_ data: Data, at received: Date = Date()) {
        guard let e = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        now = received
        if e["type"] as? String == "transcript" {
            if let ms = e["inference_ms"] as? Double { lastRecognitionMs = ms }
            if e["status"] as? String == "partial" { draft = e["text"] as? String ?? "" }
            else {
                draft = ""
                if let session = e["session_id"] as? String, let id = e["segment_id"] as? Int,
                   let text = e["text"] as? String, !text.isEmpty,
                   !pending.contains(where: { $0.session == session && $0.id == id }) {
                    pending.append((session, id, text))
                }
            }
            status = performanceStatus
            return
        }
        guard e["type"] as? String == "translation", let session = e["session_id"] as? String, let group = e["group_id"] as? Int else { return }
        if e["status"] as? String == "error" { status = "Ошибка перевода: \(e["error"] as? String ?? "неизвестная")"; return }
        let item = Caption(id: "\(session):\(group)", original: e["original"] as? String ?? "", translation: e["translation"] as? String ?? "", partial: e["status"] as? String == "partial", updatedAt: received, segmentIDs: Set(e["segment_ids"] as? [Int] ?? []), session: session, translationEngine: e["translation_engine"] as? String, translationStyle: e["translation_style"] as? String, beamSize: e["beam_size"] as? Int, clockNormalization: e["clock_normalization"] as? Bool, translationInput: e["translation_input"] as? String, recognitionMs: e["asr_last_inference_ms"] as? Double, translationMs: e["translation_ms"] as? Double, sinceFirstRecognitionMs: e["since_first_asr_final_ms"] as? Double, recognitionScope: e["asr_inference_scope"] as? String, sourceLanguage: e["source_lang"] as? String)
        if let i = captions.firstIndex(where: { $0.id == item.id }) { captions[i] = item } else { captions.append(item) }
        if !item.partial {
            if let remaining = e["remaining_transcripts"] as? [[String: Any]] {
                pending.removeAll { $0.session == session }
                for piece in remaining {
                    if let id = piece["segment_id"] as? Int, let text = piece["text"] as? String, !text.isEmpty {
                        pending.append((session, id, text))
                    }
                }
            } else {
                pending.removeAll { $0.session == session && item.segmentIDs.contains($0.id) }
            }
            if let historyStore {
                do {
                    try historyStore.append(item)
                    if historyDay == historyStore.day(for: item.updatedAt) { loadHistory(historyDay) }
                    else { historyDays = Array(Set(historyStore.days + [historyDay])).sorted(by: >) }
                } catch { historyError = "История не сохранена: \(error.localizedDescription)" }
            } else { historyRows = captions.filter { !$0.partial } }
        }
        lastTranslationMs = item.translationMs
        if let ms = item.recognitionMs { lastRecognitionMs = ms }
        status = performanceStatus
    }
}
final class DragHandleView: NSView {
    override var mouseDownCanMoveWindow: Bool { false }
    override func mouseDown(with event: NSEvent) { window?.performDrag(with: event) }
    override func resetCursorRects() { addCursorRect(bounds, cursor: .openHand) }
}
struct DragHandle: NSViewRepresentable {
    func makeNSView(context: Context) -> DragHandleView { DragHandleView() }
    func updateNSView(_ nsView: DragHandleView, context: Context) {}
}
final class HeightHandleView: NSView {
    private var startingFrame = NSRect.zero
    private var startingPoint = NSPoint.zero
    override var mouseDownCanMoveWindow: Bool { false }
    override func resetCursorRects() { addCursorRect(bounds, cursor: .resizeUpDown) }
    override func mouseDown(with event: NSEvent) {
        guard let window else { return }
        startingFrame = window.frame
        startingPoint = NSEvent.mouseLocation
    }
    override func mouseDragged(with event: NSEvent) {
        guard let window else { return }
        let screenBottom = window.screen?.visibleFrame.minY ?? -CGFloat.greatestFiniteMagnitude
        let proposed = startingFrame.height + startingPoint.y - NSEvent.mouseLocation.y
        let available = max(window.minSize.height, startingFrame.maxY - screenBottom)
        let height = min(available, max(window.minSize.height, proposed))
        window.setFrame(NSRect(x: startingFrame.minX, y: startingFrame.maxY - height,
                               width: startingFrame.width, height: height), display: true)
    }
    override func mouseUp(with event: NSEvent) { window?.saveFrame(usingName: "RealtimeOverlay") }
}
struct HeightHandle: NSViewRepresentable {
    func makeNSView(context: Context) -> HeightHandleView { HeightHandleView() }
    func updateNSView(_ nsView: HeightHandleView, context: Context) {}
}
struct OverlayView: View {
    @ObservedObject var model: Model
    var body: some View {
        GeometryReader { geometry in
        let columns = model.cardLayout == "columns" && geometry.size.width >= 600
        VStack(alignment: .leading, spacing: 10) {
            ZStack {
                DragHandle().frame(height: 32).help("Перетащите окно за эту полоску на нужный экран")
                HStack {
                Image(systemName: "line.3.horizontal").foregroundColor(.white.opacity(0.65))
                Text("Eesti / Русский").font(.system(size: 12, weight: .medium)).foregroundColor(Color(red: 0.66, green: 0.83, blue: 0.93))
                Spacer()
                Text(model.status).font(.system(size: 11)).foregroundColor(.white.opacity(0.65)).lineLimit(2)
                }.allowsHitTesting(false)
            }
            if !model.historyError.isEmpty { Text(model.historyError).font(.system(size: 11)).foregroundColor(.orange) }
            ScrollView {
            VStack(alignment: .leading, spacing: columns ? 8 : 16) {
            if columns {
                HStack(spacing: 20) {
                    Text(model.originalFirst ? "Оригинал" : "Русский").frame(maxWidth: .infinity, alignment: .leading)
                    Text(model.originalFirst ? "Русский" : "Оригинал").frame(maxWidth: .infinity, alignment: .leading)
                }.font(.system(size: 10, weight: .medium)).foregroundColor(.white.opacity(0.5))
            }
            if model.captions.isEmpty && model.liveOriginal.isEmpty {
                Text("Речь и русский перевод появятся здесь.").font(.system(size: model.size)).foregroundColor(.white.opacity(0.75))
                Text("Перемещайте окно за верхнюю полоску ≡. Настройки — в меню «ET» сверху.").font(.system(size: 13)).foregroundColor(.white.opacity(0.6))
            }
            if !model.liveOriginal.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    CaptionTextPair(original: model.liveOriginal, translation: model.active?.translation ?? "", originalFirst: model.originalFirst, columns: columns, size: model.size, openWord: { word, context, _ in model.openWord(word, context, "", model.sourceLanguage) })
                    Text("Сейчас · распознавание продолжается").font(.system(size: 10)).foregroundColor(.white.opacity(0.55))
                }.fixedSize(horizontal: false, vertical: true)
            }
            ForEach(model.visible) { item in
                VStack(alignment: .leading, spacing: 6) {
                    CaptionTextPair(original: item.original, translation: item.translation, originalFirst: model.originalFirst, columns: columns, size: model.size * model.textScale(item), openWord: { word, context, translation in model.openWord(word, context, translation, item.sourceLanguage ?? "et") })
                    HStack(alignment: .center, spacing: 8) {
                        Text("\(Int(item.age(at: model.now))) сек. назад").monospacedDigit()
                        Spacer(minLength: 4)
                        Text(item.performance).multilineTextAlignment(.trailing).help(item.performanceHelp)
                        Button { model.hide(item) } label: {
                            Image(systemName: "xmark").frame(width: 22, height: 22).contentShape(Rectangle())
                        }.buttonStyle(.plain).help("Скрыть карточку с экрана; оставить в истории")
                            .accessibilityLabel("Скрыть карточку")
                    }.font(.system(size: 10)).foregroundColor(.white.opacity(0.65))
                }.fixedSize(horizontal: false, vertical: true)
                .opacity(model.textScale(item) == 1 ? 1 : 0.8)
                Divider().overlay(.white.opacity(0.15))
            }
            }.frame(maxWidth: .infinity, alignment: .leading)
            }
            ZStack {
                HeightHandle().frame(height: 18).help("Потяните вверх или вниз, чтобы изменить высоту")
                Capsule().fill(Color.white.opacity(0.45)).frame(width: 52, height: 4).allowsHitTesting(false)
            }
        }
        .padding(.horizontal, 20).padding(.top, 12).padding(.bottom, 6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.black.opacity(model.opacity))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .overlay(alignment: .leading) { WidthGrip(left: true) }
        .overlay(alignment: .trailing) { WidthGrip(left: false) }
        .padding(4)
        }
    }
}
struct HistoryView: View {
    @ObservedObject var model: Model
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("История занятий").font(.title2)
            if model.historyStore != nil {
                Picker("День", selection: Binding(get: { model.historyDay }, set: { model.loadHistory($0) })) {
                    ForEach(model.historyDays, id: \.self) { day in Text(day).tag(day) }
                }.frame(maxWidth: 300)
                Text("Сохранено по дням · время Таллина").foregroundColor(.secondary)
            } else { Text("Демонстрация · история не записывается").foregroundColor(.secondary) }
            if !model.historyError.isEmpty { Text(model.historyError).foregroundColor(.red).textSelection(.enabled) }
            if model.historyRows.isEmpty { Text("За этот день пока нет завершённых фраз.").foregroundColor(.secondary) }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(model.historyRows) { item in
                        VStack(alignment: .leading, spacing: 5) {
                            HStack {
                                Text(item.updatedAt, style: .time)
                                if let engine = item.translationEngine { Text("\(engine) · \(item.translationStyle == "block" ? "целиком" : "по предложениям")\(item.clockNormalization == true ? " · часы цифрами" : "")") }
                            }.font(.caption).foregroundColor(.secondary)
                            WordText(text: item.original, translation: item.translation, open: { word, context, translation in model.openWord(word, context, translation, item.sourceLanguage ?? "et") }).font(.body.weight(.medium))
                            Text(item.translation).foregroundColor(.secondary)
                            if item.translationMs != nil { Text(item.performance).font(.caption).foregroundColor(.secondary).help(item.performanceHelp) }
                            Divider()
                        }.textSelection(.enabled)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
        }.padding(24).frame(minWidth: 500, minHeight: 300)
    }
}
final class Panel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}
final class Delegate: NSObject, NSApplicationDelegate {
    let model: Model
    let vocabulary: VocabularyStore
    var vocabularyWindow: NSWindow?
    var wordWindows: [NSWindow] = []
    var wordEditors: [WordEditorModel] = []
    var panel: Panel!
    var statusItem: NSStatusItem!
    var process: Process?
    var outPipe: Pipe?
    var errPipe: Pipe?
    var buffer = Data()
    var errorBuffer = Data()
    var stopping = false
    var generation = 0
    var showItem: NSMenuItem!
    var startItem: NSMenuItem!
    let root: URL
    let demo: Bool
    var signalSources: [DispatchSourceSignal] = []
    var hotKeys: [EventHotKeyRef?] = []
    var eventHandler: EventHandlerRef?
    var translationEngine = UserDefaults.standard.string(forKey: "nllbModelChoice") ?? "nllb"
    var translationItems: [NSMenuItem] = []
    let translationStyle = "sentences"
    var contextMode = UserDefaults.standard.string(forKey: "contextMode") ?? "balanced"
    var contextItems: [NSMenuItem] = []
    var comparisonWindow: NSWindow?
    var comparisonModel: ComparisonModel?
    var asrEngine = UserDefaults.standard.string(forKey: "asrEngine") ?? "zipformer-large"
    var asrItems: [NSMenuItem] = []
    var vadMode = UserDefaults.standard.string(forKey: "vadMode") ?? "silero"
    var vadItems: [NSMenuItem] = []
    var restartAfterStop = false
    var historyWindow: NSWindow?
    var ageTimer: Timer?
    var lifetimeItems: [NSMenuItem] = []
    var layoutItems: [NSMenuItem] = []
    var demoTimer: Timer?
    init(root: URL, demo: Bool) { self.root = root; self.demo = demo; self.model = Model(historyStore: demo ? nil : HistoryStore()); self.vocabulary = VocabularyStore(url: demo ? nil : VocabularyStore.defaultURL); super.init() }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        panel?.orderFrontRegardless()
        showItem?.title = "Скрыть оверлей"
        return true
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1200, height: 800)
        panel = Panel(contentRect: NSRect(x: screen.midX - 340, y: screen.minY + 70, width: 680, height: 420), styleMask: [.borderless, .nonactivatingPanel, .resizable], backing: .buffered, defer: false)
        panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = true
        panel.level = .floating; panel.isFloatingPanel = true; panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = false
        panel.minSize = NSSize(width: 420, height: 180)
        model.openWord = { [weak self] word, context, translation, language in
            guard let self else { return }
            self.editWord(self.vocabulary.existing(word: word, context: context, language: language) ?? VocabularyEntry(word: word, meaning: "", context: context, contextTranslation: translation, sourceLanguage: language))
        }
        model.sourceLanguage = asrEngine == "zipformer-en" ? "en" : "et"
        panel.contentView = NSHostingView(rootView: OverlayView(model: model))
        panel.setFrameAutosaveName("RealtimeOverlay")
        panel.setFrameUsingName("RealtimeOverlay")
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "ET"
        let menu = NSMenu()
        startItem = add(menu, "Начать / продолжить", #selector(toggleCapture))
        showItem = add(menu, "Скрыть оверлей", #selector(toggleVisible))
        let screens = NSMenuItem(title: "Переместить на экран", action: nil, keyEquivalent: "")
        let screenMenu = NSMenu()
        for (index, display) in NSScreen.screens.enumerated() {
            let item = add(screenMenu, "\(index + 1). \(display.localizedName)", #selector(moveToScreen(_:)))
            item.tag = index
        }
        screens.submenu = screenMenu; menu.addItem(screens)
        menu.addItem(.separator())
        _ = add(menu, "Текст крупнее", #selector(bigger)); _ = add(menu, "Текст мельче", #selector(smaller))
        _ = add(menu, "Подложка плотнее", #selector(moreOpaque)); _ = add(menu, "Подложка прозрачнее", #selector(lessOpaque))
        _ = add(menu, "Поменять приоритет языков", #selector(swapLanguages))
        let layoutMenu = NSMenu()
        for (title, value) in [("Колонки", "columns"), ("Друг под другом", "stacked")] {
            let item = add(layoutMenu, title, #selector(selectLayout(_:)))
            item.representedObject = value; item.state = model.cardLayout == value ? .on : .off
            layoutItems.append(item)
        }
        let layoutItem = NSMenuItem(title: "Вид карточек", action: nil, keyEquivalent: "")
        layoutItem.submenu = layoutMenu; menu.addItem(layoutItem)
        let recognitionMenu = NSMenu()
        for (title, engine) in [("Parakeet V3 · автоматически", "onnx"), ("Whisper TalTech · эстонский", "whisper"), ("Zipformer TalTech · потоковый", "zipformer"), ("Zipformer Large TalTech · эстонский → русский", "zipformer-large"), ("Zipformer · английский → русский", "zipformer-en")] {
            let item = add(recognitionMenu, title, #selector(selectRecognizer(_:)))
            item.representedObject = engine; item.state = asrEngine == engine ? .on : .off
            asrItems.append(item)
        }
        let recognition = NSMenuItem(title: "Распознавание речи", action: nil, keyEquivalent: "")
        recognition.submenu = recognitionMenu; menu.addItem(recognition)
        let vadMenu = NSMenu()
        for (title, mode) in [("Определять речь · Silero", "silero"), ("По громкости · прежний режим", "energy")] {
            let item = add(vadMenu, title, #selector(selectVAD(_:)))
            item.representedObject = mode; item.state = vadMode == mode ? .on : .off
            vadItems.append(item)
        }
        let vad = NSMenuItem(title: "Определение речи", action: nil, keyEquivalent: "")
        vad.submenu = vadMenu; menu.addItem(vad)
        let translationMenu = NSMenu()
        for (title, engine) in [("NLLB 600M", "nllb"), ("NLLB distilled 1.3B", "nllb-1.3b")] {
            let item = add(translationMenu, title, #selector(selectTranslator(_:)))
            item.representedObject = engine; item.state = translationEngine == engine ? .on : .off
            translationItems.append(item)
        }
        let translation = NSMenuItem(title: "Модель перевода", action: nil, keyEquivalent: "")
        translation.submenu = translationMenu; menu.addItem(translation)
        for (title, choices, action) in [
            ("Накопление контекста", [("Обычное", "balanced"), ("Больше контекста", "context")], #selector(selectContext(_:)))
        ] {
            let submenu = NSMenu()
            for (label, key) in choices {
                let item = add(submenu, label, action); item.representedObject = key
                item.state = key == contextMode ? .on : .off; contextItems.append(item)
            }
            let item = NSMenuItem(title: title, action: nil, keyEquivalent: ""); item.submenu = submenu; menu.addItem(item)
        }
        _ = add(menu, "Сравнить фразу…", #selector(showComparison))
        _ = add(menu, "Мой словарь…", #selector(showVocabulary))
        _ = add(menu, "История…", #selector(showHistory))
        _ = add(menu, "Открыть папку истории", #selector(openHistoryFolder))
        let lifetimeMenu = NSMenu()
        for seconds in [15, 30, 60, 120, 180, 300] {
            let label = seconds < 60 ? "\(seconds) секунд" : [60: "1 минута", 120: "2 минуты", 180: "3 минуты", 300: "5 минут"][seconds]!
            let item = add(lifetimeMenu, label, #selector(setLifetime(_:)))
            item.tag = seconds; item.state = Int(model.lifetime) == seconds ? .on : .off
            lifetimeItems.append(item)
        }
        let lifetimeItem = NSMenuItem(title: "Время показа фразы", action: nil, keyEquivalent: "")
        lifetimeItem.submenu = lifetimeMenu; menu.addItem(lifetimeItem)
        _ = add(menu, "Скрыть текущие строки", #selector(clear))
        menu.addItem(.separator()); _ = add(menu, "Завершить", #selector(quit))
        statusItem.menu = menu
        panel.orderFrontRegardless()
        ageTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.model.now = Date() }
        installHotKeys()
        for number in [SIGINT, SIGTERM] {
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: number, queue: .main)
            source.setEventHandler { [weak self] in self?.quit() }
            source.resume(); signalSources.append(source)
        }
        if demo { runDemo() } else { start() }
    }
    func installHotKeys() {
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let pointer = Unmanaged.passUnretained(self).toOpaque()
        let result = InstallEventHandler(GetApplicationEventTarget(), { _, event, context in
            guard let event, let context else { return OSStatus(eventNotHandledErr) }
            var id = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil, MemoryLayout<EventHotKeyID>.size, nil, &id)
            let owner = Unmanaged<Delegate>.fromOpaque(context).takeUnretainedValue()
            if id.id == 1 { owner.toggleVisible() } else if id.id == 2 { owner.toggleCapture() }
            return noErr
        }, 1, &type, pointer, &eventHandler)
        guard result == noErr else { return }
        for (key, id) in [(UInt32(kVK_ANSI_O), UInt32(1)), (UInt32(kVK_ANSI_P), UInt32(2))] {
            var ref: EventHotKeyRef?
            if RegisterEventHotKey(key, UInt32(controlKey | optionKey), EventHotKeyID(signature: 0x45545255, id: id), GetApplicationEventTarget(), 0, &ref) == noErr { hotKeys.append(ref) }
        }
        showItem.title = "Скрыть оверлей (⌃⌥O)"
        startItem.toolTip = "Пауза / продолжение: Control + Option + P"
    }
    func add(_ menu: NSMenu, _ title: String, _ action: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: ""); item.target = self; menu.addItem(item); return item
    }
    @objc func toggleVisible() { if panel.isVisible { panel.orderOut(nil); showItem.title = "Показать оверлей" } else { panel.orderFrontRegardless(); showItem.title = "Скрыть оверлей" } }
    @objc func moveToScreen(_ sender: NSMenuItem) {
        guard NSScreen.screens.indices.contains(sender.tag) else { return }
        let visible = NSScreen.screens[sender.tag].visibleFrame
        var frame = panel.frame
        frame.size.width = min(frame.width, visible.width)
        frame.size.height = min(frame.height, visible.height)
        frame.origin = NSPoint(x: visible.midX - frame.width / 2, y: visible.minY + min(70, max(0, visible.height - frame.height)))
        panel.setFrame(frame, display: true)
        panel.orderFrontRegardless()
        showItem.title = "Скрыть оверлей"
    }
    @objc func selectLayout(_ sender: NSMenuItem) {
        guard let value = sender.representedObject as? String else { return }
        model.cardLayout = value; UserDefaults.standard.set(value, forKey: "cardLayout")
        for item in layoutItems { item.state = item.representedObject as? String == value ? .on : .off }
    }
    @objc func bigger() { model.size = min(36, model.size + 2); save() }
    @objc func smaller() { model.size = max(14, model.size - 2); save() }
    @objc func moreOpaque() { model.opacity = min(1, model.opacity + 0.05); save() }
    @objc func lessOpaque() { model.opacity = max(0.35, model.opacity - 0.05); save() }
    func save() { UserDefaults.standard.set(model.size, forKey: "textSize"); UserDefaults.standard.set(model.opacity, forKey: "opacity") }
    @objc func swapLanguages() { model.originalFirst.toggle() }
    @objc func clear() {
        model.hiddenIDs.formUnion(model.captions.map { $0.id })
        model.draft = ""; model.pending.removeAll()
        model.captions.removeAll(where: { $0.partial })
    }
    @objc func setLifetime(_ sender: NSMenuItem) {
        model.lifetime = Double(sender.tag)
        UserDefaults.standard.set(model.lifetime, forKey: "lifetime")
        for item in lifetimeItems { item.state = item.tag == sender.tag ? .on : .off }
    }
    @objc func openHistoryFolder() {
        let folder = model.historyStore?.folder ?? HistoryStore.defaultFolder
        do { try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true); NSWorkspace.shared.open(folder) }
        catch { model.historyError = "Не удалось открыть папку: \(error.localizedDescription)" }
    }
    @objc func showVocabulary() {
        if vocabularyWindow == nil {
            let window = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 780, height: 550), styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
            window.title = "Мой словарь"; window.isReleasedWhenClosed = false
            window.contentView = NSHostingView(rootView: VocabularyView(store: vocabulary, edit: { [weak self] in self?.editWord($0) }))
            window.center(); vocabularyWindow = window
        }
        NSApp.activate(ignoringOtherApps: true); vocabularyWindow?.makeKeyAndOrderFront(nil)
    }
    func editWord(_ entry: VocabularyEntry) {
        // Keep each clicked phrase as a snapshot while live captions continue changing.
        let editor = WordEditorModel(entry: entry, root: root, engine: translationEngine)
        let window = VocabularyEditorWindow(contentRect: NSRect(x: 100, y: 100, width: 600, height: 420), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Сохранить слово"; window.isReleasedWhenClosed = false
        window.level = .floating
        window.contentView = NSHostingView(rootView: WordEditorView(model: editor, store: vocabulary, close: { [weak window] in window?.close() }))
        window.delegate = window
        window.onClose = { [weak self, weak editor, weak window] in
            editor?.cancel()
            self?.wordEditors.removeAll { $0 === editor }
            self?.wordWindows.removeAll { $0 === window }
        }
        wordEditors.append(editor); wordWindows.append(window)
        window.center(); NSApp.activate(ignoringOtherApps: true); window.makeKeyAndOrderFront(nil)
    }
    @objc func showHistory() {
        if let store = model.historyStore { model.loadHistory(model.historyDay.isEmpty ? store.day(for: Date()) : model.historyDay) }
        if historyWindow == nil {
            let window = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 760, height: 600), styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
            window.title = "История перевода"
            window.contentView = NSHostingView(rootView: HistoryView(model: model))
            window.isReleasedWhenClosed = false; window.center()
            historyWindow = window
        }
        NSApp.activate(ignoringOtherApps: true)
        historyWindow?.makeKeyAndOrderFront(nil)
    }
    @objc func selectRecognizer(_ sender: NSMenuItem) {
        guard let engine = sender.representedObject as? String, engine != asrEngine else { return }
        if engine == "whisper" && !FileManager.default.fileExists(atPath: root.appendingPathComponent("capture-transcription/models/whisper-taltech/ggml-model.bin").path) {
            model.status = "Whisper ещё не установлен: запустите setup-whisper.sh"
            return
        }
        if ["zipformer", "zipformer-large", "zipformer-en"].contains(engine) {
            let directory = engine == "zipformer-en" ? "zipformer-en" : engine == "zipformer-large" ? "zipformer-large-taltech" : "zipformer-taltech"
            if !["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"].allSatisfy({ FileManager.default.fileExists(atPath: root.appendingPathComponent("capture-transcription/models/" + directory + "/" + $0).path) }) {
                model.status = "Zipformer ещё не установлен: запустите setup-" + engine + ".sh"
                return
            }
        }
        asrEngine = engine
        model.sourceLanguage = engine == "zipformer-en" ? "en" : "et"
        UserDefaults.standard.set(engine, forKey: "asrEngine")
        for item in asrItems { item.state = item.representedObject as? String == engine ? .on : .off }
        if process != nil { restartAfterStop = true; stop() } else if !demo { start() }
    }
    func restartForSetting() { if process != nil { restartAfterStop = true; stop() } else if !demo { start() } }
    @objc func selectVAD(_ sender: NSMenuItem) {
        guard let mode = sender.representedObject as? String, mode != vadMode else { return }
        if mode == "silero" && !FileManager.default.fileExists(atPath: root.appendingPathComponent("capture-transcription/models/silero-vad/silero_vad.onnx").path) {
            model.status = "Детектор речи ещё не установлен: запустите download_vad.py"
            return
        }
        vadMode = mode; UserDefaults.standard.set(mode, forKey: "vadMode")
        for item in vadItems { item.state = item.representedObject as? String == mode ? .on : .off }
        restartForSetting()
    }
    @objc func selectTranslator(_ sender: NSMenuItem) {
        guard let engine = sender.representedObject as? String, engine != translationEngine else { return }
        let directory = engine == "nllb-1.3b" ? "nllb-1.3b-int8" : "nllb-600m-int8"
        guard FileManager.default.fileExists(atPath: root.appendingPathComponent("translation/models/\(directory)/model.bin").path) else {
            model.status = "Выбранная модель перевода ещё не установлена"
            return
        }
        translationEngine = engine
        UserDefaults.standard.set(engine, forKey: "nllbModelChoice")
        for item in translationItems { item.state = item.representedObject as? String == engine ? .on : .off }
        restartForSetting()
    }
    @objc func selectContext(_ sender: NSMenuItem) {
        guard let key = sender.representedObject as? String, key != contextMode else { return }
        contextMode = key; UserDefaults.standard.set(key, forKey: "contextMode")
        for item in contextItems { item.state = item.representedObject as? String == key ? .on : .off }
        restartForSetting()
    }
    @objc func showComparison() {
        if comparisonWindow == nil {
            let comparison = ComparisonModel(root: root)
            comparisonModel = comparison
            let window = NSWindow(contentRect: NSRect(x: 100, y: 100, width: 760, height: 650), styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
            window.title = "Сравнение перевода"; window.isReleasedWhenClosed = false
            window.contentView = NSHostingView(rootView: ComparisonView(model: comparison)); window.center(); comparisonWindow = window
        }
        NSApp.activate(ignoringOtherApps: true); comparisonWindow?.makeKeyAndOrderFront(nil)
    }
    @objc func toggleCapture() { if demo { return }; if process == nil { start() } else { stop() } }
    func start() {
        guard process == nil else { return }
        model.draft = ""; model.pending.removeAll(); model.captions.removeAll(where: { $0.partial })
        generation += 1; let token = generation
        buffer.removeAll(); errorBuffer.removeAll(); stopping = false
        model.status = "Подготовка распознавания и перевода…"
        let p = Process(); let output = Pipe(); let errors = Pipe()
        p.executableURL = root.appendingPathComponent("translation/listen.sh")
        p.arguments = ["--format", "jsonl", "--forward-transcripts", "--asr-engine", asrEngine, "--asr-interval", asrEngine == "whisper" ? "3" : "1"]
        p.arguments = (p.arguments ?? []) + ["--source-lang", asrEngine == "zipformer-en" ? "en" : "et", "--vad", vadMode, "--translation-engine", translationEngine, "--translation-style", translationStyle,
                        "--max-wait", contextMode == "context" ? "6" : "2.5", "--max-words", contextMode == "context" ? "48" : "24"]
        p.standardOutput = output; p.standardError = errors
        outPipe = output; errPipe = errors; process = p
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { guard let self, self.generation == token else { return }; self.read(data) }
        }
        errors.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { guard let self, self.generation == token else { return }; self.readErrors(data) }
        }
        p.terminationHandler = { [weak self] child in
            DispatchQueue.main.async {
                guard let self, self.generation == token else { return }
                self.process = nil; self.startItem.title = "Начать / продолжить"
                if self.restartAfterStop { self.restartAfterStop = false; self.start(); return }
                if self.stopping { self.model.status = "На паузе" } else if child.terminationStatus != 0 { self.model.status = "Остановлено с ошибкой. Проверьте журнал запуска." } else { self.model.status = "Захват завершён" }
            }
        }
        do { try p.run(); startItem.title = "Пауза" } catch { process = nil; model.status = "Не удалось запустить: \(error.localizedDescription)" }
    }
    func read(_ data: Data) {
        buffer.append(data)
        while let end = buffer.firstIndex(of: 10) { let line = Data(buffer[..<end]); buffer.removeSubrange(...end); model.accept(line) }
        if buffer.count > 65536 { model.status = "Ошибка формата потока"; stop() }
    }
    func readErrors(_ data: Data) {
        FileHandle.standardError.write(data)
        errorBuffer.append(data)
        while let end = errorBuffer.firstIndex(of: 10) {
            let line = String(decoding: errorBuffer[..<end], as: UTF8.self); errorBuffer.removeSubrange(...end)
            if line.contains("ERROR") { model.status = String(line.suffix(220)) }
            else if line.contains("Ready:") { model.status = "Слушаю · ожидаю речь" }
        }
        if errorBuffer.count > 65536 { errorBuffer.removeAll() }
    }
    func stop() { stopping = true; model.status = "Останавливаю захват…"; process?.terminate() }
    @objc func quit() {
        restartAfterStop = false
        comparisonModel?.cancel()
        wordEditors.forEach { $0.cancel() }
        demoTimer?.invalidate(); ageTimer?.invalidate()
        stop()
        // The Python supervisor drains and terminates its capture child on SIGTERM.
        if let p = process, p.isRunning {
            DispatchQueue.global().async { p.waitUntilExit(); DispatchQueue.main.async { NSApp.terminate(nil) } }
        } else { NSApp.terminate(nil) }
    }
    func runDemo() {
        startItem.title = "Демонстрация · без захвата"
        let samples = [
            ("Tere hommikust! Alustame koosolekut.", "Доброе утро! Начинаем встречу."),
            ("Kas sa saaksid palun aeglasemalt rääkida?", "Не могли бы вы, пожалуйста, говорить медленнее?"),
            ("Järgmine koosolek toimub homme kell kümme.", "Следующая встреча состоится завтра в десять часов.")]
        var step = 0
        func tick() {
            let index = (step / 2) % samples.count; let group = step / 2 + 1
            let sample = samples[index]; let partial = step % 2 == 0
            let event: [String: Any] = ["type": "translation", "session_id": "demo", "group_id": group, "status": partial ? "partial" : "final", "original": partial ? String(sample.0.prefix(24)) : sample.0, "translation": partial ? "Перевод появляется по мере речи…" : sample.1, "translation_ms": 420]
            model.accept(try! JSONSerialization.data(withJSONObject: event)); model.status = "Демонстрация · звук не захватывается"; step += 1
        }
        tick(); demoTimer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { _ in tick() }
    }
}
let arguments = CommandLine.arguments
if let index = arguments.firstIndex(of: "--preview-vocabulary"), index + 1 < arguments.count {
    try vocabularyPreviews(folder: URL(fileURLWithPath: arguments[index + 1]))
    exit(0)
}
if let index = arguments.firstIndex(of: "--check-jsonl"), index + 1 < arguments.count {
    let model = Model()
    let content = try String(contentsOfFile: arguments[index + 1], encoding: .utf8)
    for line in content.split(separator: "\n") { model.accept(Data(line.utf8)) }
    guard !model.captions.isEmpty, model.captions.last?.partial == false else { fatalError("No final caption received") }
    print("JSONL accepted: \(model.captions.count) caption groups")
    exit(0)
}
if arguments.contains("--self-test") {
    let model = Model()
    func feed(_ group: Int, _ status: String, _ text: String, _ session: String = "test") {
        model.accept(try! JSONSerialization.data(withJSONObject: ["type": "translation", "session_id": session, "group_id": group, "status": status, "original": text, "translation": "Перевод", "translation_ms": 300]))
    }
    feed(1, "partial", "Tere"); feed(1, "final", "Tere hommikust!")
    precondition(model.captions.count == 1 && !model.captions[0].partial)
    precondition(model.captions[0].original == "Tere hommikust!")
    for i in 2...5 { feed(i, "final", "Lause") }
    precondition(model.captions.count == 5 && model.visible.first?.id == "test:5")
    feed(5, "final", "Uus", "new-session")
    precondition(model.captions.last?.id == "new-session:5")
    model.accept(Data("broken".utf8)); precondition(model.captions.count == 6)
    model.accept(try! JSONSerialization.data(withJSONObject: ["type": "transcript", "status": "partial", "text": "Pooleli"]))
    precondition(model.draft == "Pooleli")
    let latest = model.captions.last!
    model.lifetime = 30
    model.now = latest.updatedAt.addingTimeInterval(9)
    precondition(model.textScale(latest) == 1)
    model.now = latest.updatedAt.addingTimeInterval(10)
    precondition(model.textScale(latest) == 0.75)
    model.now = latest.updatedAt.addingTimeInterval(25)
    precondition(model.textScale(latest) == 0.75)
    model.hide(latest)
    precondition(!model.visible.contains { $0.id == latest.id } && model.historyRows.contains { $0.id == latest.id })
    model.hiddenIDs.removeAll()
    model.now = latest.updatedAt.addingTimeInterval(model.lifetime / 2)
    precondition(model.textScale(latest) < 1 && !model.visible.isEmpty)
    model.now = latest.updatedAt.addingTimeInterval(model.lifetime + 1)
    precondition(model.visible.isEmpty && model.captions.count == 6)
    let live = Model()
    func transcript(_ id: Int, _ status: String, _ text: String) {
        live.accept(try! JSONSerialization.data(withJSONObject: ["type": "transcript", "session_id": "s", "segment_id": id, "status": status, "text": text]))
    }
    transcript(1, "final", "Tere"); transcript(2, "partial", "hommikust")
    precondition(live.liveOriginal == "Tere hommikust")
    live.accept(try! JSONSerialization.data(withJSONObject: ["type": "translation", "session_id": "s", "group_id": 1, "segment_ids": [1], "status": "partial", "original": "Tere", "translation": "Привет"]))
    precondition(live.liveOriginal == "Tere hommikust")
    live.accept(try! JSONSerialization.data(withJSONObject: ["type": "translation", "session_id": "s", "group_id": 1, "segment_ids": [1], "status": "final", "original": "Tere", "translation": "Привет"]))
    precondition(live.liveOriginal == "hommikust" && live.visible.count == 1)
    let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("overlay-history-test-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: temporary) }
    let store = HistoryStore(folder: temporary)
    var saved = live.captions[0]
    saved.recognitionMs = 2100; saved.translationMs = 250; saved.sinceFirstRecognitionMs = 4000
    saved.translationEngine = "opus"; saved.translationStyle = "sentences"; saved.clockNormalization = true; saved.translationInput = "Tere"
    saved.updatedAt = ISO8601DateFormatter().date(from: "2026-10-06T21:30:00Z")!
    precondition(store.day(for: saved.updatedAt) == "2026-10-07")
    try! store.append(saved); try! store.append(saved)
    precondition(try! store.load("2026-10-07").count == 1)
    let reopened = Model(historyStore: HistoryStore(folder: temporary))
    reopened.loadHistory("2026-10-07")
    precondition(reopened.historyRows.first?.original == saved.original && reopened.captions.isEmpty && reopened.historyRows.first?.translationEngine == "opus" && reopened.historyRows.first?.clockNormalization == true)
    precondition(reopened.historyRows.first?.recognitionMs == 2100 && reopened.historyRows.first?.translationMs == 250)
    let readable = try! String(contentsOf: temporary.appendingPathComponent("2026-10-07.txt"), encoding: .utf8)
    precondition(readable.contains(saved.original) && readable.contains(saved.translation))
    saved.partial = true // Partial events never reach disk.
    try! store.append(saved); precondition(try! store.load("2026-10-07").count == 1)
    let journal = temporary.appendingPathComponent("2026-10-07.jsonl")
    let broken = try! FileHandle(forWritingTo: journal)
    try! broken.seekToEnd(); try! broken.write(contentsOf: Data("{\"interrupted\":".utf8)); try! broken.close()
    let recovered = try! store.load("2026-10-07")
    precondition(recovered.count == 1 && !store.warning.isEmpty)
    saved.partial = false; try! store.append(saved)
    precondition(try! store.load("2026-10-07").count == 1)
    let blocked = temporary.appendingPathComponent("not-a-directory")
    try! Data("blocked".utf8).write(to: blocked)
    let failing = Model(historyStore: HistoryStore(folder: blocked))
    failing.accept(try! JSONSerialization.data(withJSONObject: ["type": "translation", "session_id": "s", "group_id": 99, "status": "final", "original": "Tere", "translation": "Привет"]))
    precondition(!failing.historyError.isEmpty && failing.captions.count == 1)
    for text in ["Aita", " AITÄH! ", "„Aitäh.”", "Aita?", "Aita\u{0308}h!", "Aitäh. Aitäh. Aitäh. Aitäh. ", "AITÄH! aita? Aitäh", "Aitäh.Aitäh", "Aitäh\nAita"] {
        precondition(Model.isStandaloneThanks(text))
    }
    for text in ["Aitäh sulle!", "Palun aita mind.", "Aitäh! Tere.", "Aita 2", "", "Tere", "Aitäh. Aitäh sulle!", "... !", "Aitäh + Aitäh", "Aitähaitäh"] {
        precondition(!Model.isStandaloneThanks(text))
    }
    let noise = Model()
    noise.draft = "Aitäh!"; precondition(noise.liveOriginal.isEmpty)
    noise.draft = "Aitäh sulle!"; precondition(noise.liveOriginal == "Aitäh sulle!")
    noise.draft = ""
    func noiseFeed(_ text: String, _ status: String) {
        noise.accept(try! JSONSerialization.data(withJSONObject: ["type": "translation", "session_id": "noise", "group_id": 1, "status": status, "original": text, "translation": "Спасибо"]))
    }
    noiseFeed("Aitäh!", "partial"); precondition(noise.liveOriginal.isEmpty)
    noiseFeed("Aitäh sulle!", "final"); precondition(noise.visible.count == 1)
    noiseFeed("Aitäh. Aitäh. Aitäh. Aitäh. ", "partial"); precondition(noise.liveOriginal.isEmpty)
    noiseFeed("Aitäh. Aitäh. Aitäh. Aitäh. ", "final"); precondition(noise.visible.isEmpty && noise.historyRows.count == 1)
    let sentenceCards = Model()
    sentenceCards.accept(try! JSONSerialization.data(withJSONObject: ["type": "transcript", "session_id": "sentences", "segment_id": 1, "status": "final", "text": "Tere! Homme"]))
    sentenceCards.accept(try! JSONSerialization.data(withJSONObject: ["type": "translation", "session_id": "sentences", "group_id": 1, "segment_ids": [1], "status": "partial", "original": "Tere! Homme", "translation": "Привет! Завтра"]))
    sentenceCards.accept(try! JSONSerialization.data(withJSONObject: ["type": "translation", "session_id": "sentences", "group_id": 1, "segment_ids": [1], "status": "final", "original": "Tere!", "translation": "Привет!", "remaining_transcripts": [["segment_id": 1, "text": "Homme"]]]))
    precondition(sentenceCards.visible.count == 1 && sentenceCards.liveOriginal == "Homme" && sentenceCards.active == nil)
    sentenceCards.accept(try! JSONSerialization.data(withJSONObject: ["type": "translation", "session_id": "sentences", "group_id": 2, "segment_ids": [1], "status": "final", "original": "Homme", "translation": "Завтра", "remaining_transcripts": []]))
    precondition(sentenceCards.liveOriginal.isEmpty && sentenceCards.visible.count == 2 && sentenceCards.historyRows.count == 2)
    let resizeStart = NSRect(x: 200, y: 100, width: 680, height: 500)
    let resizeScreen = NSRect(x: 0, y: 0, width: 1920, height: 1080)
    let growLeft = WidthHandleView.resized(resizeStart, delta: -100, left: true, minimum: 420, screen: resizeScreen)
    precondition(growLeft.width == 780 && growLeft.maxX == resizeStart.maxX && growLeft.height == resizeStart.height)
    let shrinkRight = WidthHandleView.resized(resizeStart, delta: -1000, left: false, minimum: 420, screen: resizeScreen)
    precondition(shrinkRight.width == 420 && shrinkRight.minX == resizeStart.minX)
    let maxRight = WidthHandleView.resized(resizeStart, delta: 10000, left: false, minimum: 420, screen: resizeScreen)
    precondition(maxRight.maxX == resizeScreen.maxX)
    try! vocabularySelfTest()
    let languageStore = VocabularyStore(url: nil)
    let englishEntry = VocabularyEntry(word: "test", meaning: "проверка", sourceLanguage: "en")
    let estonianEntry = VocabularyEntry(word: "test", meaning: "тест", sourceLanguage: "et")
    assert(languageStore.save(englishEntry)); assert(languageStore.save(estonianEntry))
    assert(languageStore.entries.count == 2)
    assert(languageStore.existing(word: "test", context: "", language: "en")?.id == englishEntry.id)
    let roundtripEntry = try JSONDecoder().decode(VocabularyEntry.self, from: JSONEncoder().encode(englishEntry))
    assert(roundtripEntry.sourceLanguage == "en")
    let englishCaption = Caption(id: "en", original: "Hello!", translation: "Привет!", partial: false, updatedAt: Date(), segmentIDs: [], session: "test", sourceLanguage: "en")
    let roundtripCaption = try JSONDecoder().decode(Caption.self, from: JSONEncoder().encode(englishCaption))
    assert(roundtripCaption.sourceLanguage == "en")
    print("Overlay, history and vocabulary checks passed")
    exit(0)
}
// Preserve preferences when moving from the command-line executable to the app bundle.
if let identifier = Bundle.main.bundleIdentifier, identifier == "local.realtime-translation.overlay" {
    let defaults = UserDefaults.standard
    if !defaults.bool(forKey: "legacyPreferencesImported") {
        let previous = defaults.persistentDomain(forName: "realtime-overlay") ?? [:]
        for (key, value) in previous { defaults.set(value, forKey: key) }
        defaults.set(true, forKey: "legacyPreferencesImported")
    }
    let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Realtime Translation")
    try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
    let log = logs.appendingPathComponent("application.log")
    if let size = (try? FileManager.default.attributesOfItem(atPath: log.path)[.size]) as? NSNumber, size.intValue > 5_000_000 {
        let previous = logs.appendingPathComponent("application.previous.log")
        try? FileManager.default.removeItem(at: previous)
        try? FileManager.default.moveItem(at: log, to: previous)
    }
    freopen(log.path, "a", stderr)
}
let rootPath = arguments.dropFirst().first(where: { !$0.hasPrefix("--") }) ?? Bundle.main.object(forInfoDictionaryKey: "RealtimeWorkspaceRoot") as? String ?? FileManager.default.currentDirectoryPath
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
if !FileManager.default.isExecutableFile(atPath: URL(fileURLWithPath: rootPath).appendingPathComponent("translation/listen.sh").path) {
    let alert = NSAlert()
    alert.messageText = "Не найдены файлы Realtime Translation"
    alert.informativeText = "Ожидаемая папка: \(rootPath)\nЕсли проект перемещён, пересоберите приложение через overlay/build-app.sh в новой папке."
    alert.runModal(); exit(1)
}
let delegate = Delegate(root: URL(fileURLWithPath: rootPath), demo: arguments.contains("--demo"))
app.delegate = delegate
app.run()
