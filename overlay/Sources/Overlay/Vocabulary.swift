import AppKit
import SwiftUI

struct VocabularyEntry: Codable, Identifiable, Equatable {
    var id = UUID()
    var word: String
    var meaning: String
    var context: String = ""
    var contextTranslation: String = ""
    var note: String = ""
    // Legacy field: retain old saved values when editing existing vocabulary.
    var pinned = false
    var createdAt = Date()
    var sourceLanguage: String? = nil
}
private struct VocabularyDocument: Codable {
    var version = 1
    var entries: [VocabularyEntry]
}
final class VocabularyStore: ObservableObject {
    static var defaultURL: URL { HistoryStore.defaultFolder.deletingLastPathComponent().appendingPathComponent("Vocabulary.json") }
    let url: URL?
    @Published private(set) var entries: [VocabularyEntry] = []
    @Published var error = ""
    private var readable = true
    init(url: URL? = VocabularyStore.defaultURL) {
        self.url = url
        guard let url, FileManager.default.fileExists(atPath: url.path) else { return }
        do {
            let document = try JSONDecoder().decode(VocabularyDocument.self, from: Data(contentsOf: url))
            guard document.version == 1 else { throw CocoaError(.fileReadCorruptFile) }
            entries = document.entries
        } catch { readable = false; self.error = "Не удалось открыть словарь. Исходный файл сохранён: \(url.path)" }
    }
    @discardableResult private func commit(_ next: [VocabularyEntry]) -> Bool {
        guard readable else { return false }
        do {
            if let url {
                try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
                let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
                try encoder.encode(VocabularyDocument(entries: next)).write(to: url, options: .atomic)
            }
            entries = next; error = ""; return true
        } catch { self.error = "Словарь не сохранён: \(error.localizedDescription)"; return false }
    }
    func existing(word: String, context: String, language: String = "et") -> VocabularyEntry? {
        entries.first { $0.word.caseInsensitiveCompare(word) == .orderedSame && $0.context == context && ($0.sourceLanguage ?? "et") == language }
    }
    @discardableResult func save(_ entry: VocabularyEntry) -> Bool {
        var entry = entry
        entry.word = entry.word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !entry.word.isEmpty else { error = "Введите слово или подсказку"; return false }
        var next = entries
        if let index = next.firstIndex(where: { $0.id == entry.id }) { next[index] = entry }
        else if let index = next.firstIndex(where: { $0.word.caseInsensitiveCompare(entry.word) == .orderedSame && $0.context == entry.context && ($0.sourceLanguage ?? "et") == (entry.sourceLanguage ?? "et") }) {
            entry.id = next[index].id; entry.createdAt = next[index].createdAt; next[index] = entry
        } else { next.append(entry) }
        return commit(next)
    }
    func remove(_ entry: VocabularyEntry) { _ = commit(entries.filter { $0.id != entry.id }) }

}

// Links preserve normal sentence wrapping and copyable text; clicking snapshots the context.
struct WordText: View {
    let text: String
    let translation: String
    let open: (String, String, String) -> Void
    static func tokens(_ text: String) -> [NSRange] {
        let regex = try! NSRegularExpression(pattern: "[\\p{L}\\p{M}\\p{N}]+(?:[-’'][\\p{L}\\p{M}\\p{N}]+)*")
        return regex.matches(in: text, range: NSRange(text.startIndex..., in: text)).map(\.range)
    }
    var body: some View {
        let ranges = Self.tokens(text)
        let attributed: AttributedString = {
            var value = AttributedString(text)
            for (i, nsRange) in ranges.enumerated() {
                if let range = Range(nsRange, in: text), let attributedRange = Range(range, in: value) {
                    value[attributedRange].link = URL(string: "vocabulary://word/\(i)")
                }
            }
            return value
        }()
        Text(attributed).environment(\.openURL, OpenURLAction { url in
            guard url.scheme == "vocabulary", let i = Int(url.lastPathComponent), ranges.indices.contains(i),
                  let range = Range(ranges[i], in: text) else { return .discarded }
            open(String(text[range]), text, translation)
            return .handled
        }).help("Нажмите на слово, чтобы сохранить его в словарь")
    }
}

final class WordEditorModel: ObservableObject {
    @Published var entry: VocabularyEntry
    @Published var busy = false
    @Published var error = ""
    var process: Process?
    let root: URL
    let engine: String
    init(entry: VocabularyEntry, root: URL, engine: String) { self.entry = entry; self.root = root; self.engine = engine }
    func translate() {
        guard !busy, !entry.word.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        busy = true; error = ""
        let word = entry.word
        let p = Process(); let output = Pipe(); let errors = Pipe()
        p.executableURL = root.appendingPathComponent("translation/.venv/bin/python")
        p.arguments = [root.appendingPathComponent("translation/translate.py").path, "--text", word, "--format", "jsonl", "--translation-engine", engine, "--source-lang", entry.sourceLanguage ?? "et"]
        p.standardOutput = output; p.standardError = errors
        process = p
        do { try p.run() } catch { busy = false; process = nil; self.error = error.localizedDescription; return }
        DispatchQueue.global().async {
            DispatchQueue.global().async { _ = errors.fileHandleForReading.readDataToEndOfFile() }
            let data = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
            DispatchQueue.main.async {
                guard self.process === p else { return }
                self.busy = false; self.process = nil
                let rows = data.split(separator: 10).compactMap { try? JSONSerialization.jsonObject(with: Data($0)) as? [String: Any] }
                guard p.terminationStatus == 0, let row = rows.last, let meaning = row["translation"] as? String, row["status"] as? String != "error" else {
                    self.error = "Не удалось перевести слово. Можно вписать значение вручную."; return
                }
                if self.entry.word == word { self.entry.meaning = meaning }
            }
        }
    }
    func cancel() { if process?.isRunning == true { process?.terminate() }; process = nil; busy = false }
}
struct WordEditorView: View {
    @ObservedObject var model: WordEditorModel
    @ObservedObject var store: VocabularyStore
    let close: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Слово или подсказка").font(.title2)
            Picker("Язык слова", selection: Binding(get: { model.entry.sourceLanguage ?? "et" }, set: { model.entry.sourceLanguage = $0 })) {
                Text("Эстонский").tag("et"); Text("Английский").tag("en")
            }.disabled(model.busy)
            TextField("Слово или своя заметка", text: $model.entry.word).font(.title3).disabled(model.busy)
            HStack {
                TextField("Русский перевод / значение", text: $model.entry.meaning).disabled(model.busy)
                Button("Перевести слово") { model.translate() }.disabled(model.busy || model.entry.word.isEmpty)
                if model.busy { ProgressView().controlSize(.small) }
            }
            Text("Перевод отдельного слова может отличаться от его значения во фразе. Его можно исправить.").font(.caption).foregroundColor(.secondary)
            if !model.entry.context.isEmpty {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(model.entry.context).fontWeight(.medium)
                        Text(model.entry.contextTranslation.isEmpty ? "Перевод фразы ещё не был готов при выборе слова." : model.entry.contextTranslation).foregroundColor(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
                }.frame(maxHeight: 130)
            }
            TextField("Моя заметка (необязательно)", text: $model.entry.note)
            if !model.error.isEmpty { Text(model.error).foregroundColor(.red) }
            if !store.error.isEmpty { Text(store.error).foregroundColor(.red) }
            HStack {
                Spacer()
                Button("Отмена") { model.cancel(); close() }.keyboardShortcut(.cancelAction)
                Button("Сохранить") { if store.save(model.entry) { model.cancel(); close() } }
                    .keyboardShortcut(.defaultAction).disabled(model.busy || model.entry.word.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }.padding(24).frame(width: 550).background(Color(nsColor: .windowBackgroundColor))
    }
}
struct VocabularyView: View {
    @ObservedObject var store: VocabularyStore
    let edit: (VocabularyEntry) -> Void
    @State private var search = ""
    @State private var deleting: VocabularyEntry?
    var filtered: [VocabularyEntry] {
        store.entries.reversed().filter { search.isEmpty || [$0.word, $0.meaning, $0.context, $0.note].contains { $0.localizedCaseInsensitiveContains(search) } }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Мой словарь").font(.title2)
                Spacer()
                Button("Добавить слово") { edit(VocabularyEntry(word: "", meaning: "")) }
            }
            TextField("Найти слово, перевод или заметку", text: $search)
            if !store.error.isEmpty { Text(store.error).foregroundColor(.red).textSelection(.enabled) }
            if store.entries.isEmpty { Text("Нажмите на слово в субтитрах или истории. Здесь сохранятся слово, перевод и исходная фраза.").foregroundColor(.secondary) }
            else if filtered.isEmpty { Text("Ничего не найдено").foregroundColor(.secondary) }
            List(filtered) { entry in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .top) {
                        Text(entry.word).font(.headline)
                        Text(entry.meaning).foregroundColor(.secondary)
                        Spacer()
                        Button("Изменить") { edit(entry) }
                        Button { deleting = entry } label: { Image(systemName: "trash") }.help("Удалить из словаря")
                    }.buttonStyle(.borderless)
                    if !entry.context.isEmpty { Text(entry.context).font(.callout) }
                    if !entry.contextTranslation.isEmpty { Text(entry.contextTranslation).font(.callout).foregroundColor(.secondary) }
                    if !entry.note.isEmpty { Text(entry.note).font(.callout).foregroundColor(.secondary) }
                }.padding(.vertical, 6).textSelection(.enabled)
            }
        }.padding(22).frame(minWidth: 600, minHeight: 400).background(Color(nsColor: .windowBackgroundColor))
        .alert("Удалить слово из словаря?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } })) {
            Button("Отмена", role: .cancel) { deleting = nil }
            Button("Удалить", role: .destructive) { if let entry = deleting { store.remove(entry) }; deleting = nil }
        }
    }
}
func vocabularySelfTest() throws {
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent("vocabulary-test-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: folder) }
    let url = folder.appendingPathComponent("Vocabulary.json")
    let store = VocabularyStore(url: url)
    let entry = VocabularyEntry(word: "õpin", meaning: "изучаю", context: "Ma õpin eesti keelt.", contextTranslation: "Я изучаю эстонский язык.", pinned: true)
    precondition(store.save(entry))
    var duplicate = entry; duplicate.id = UUID(); duplicate.meaning = "учу"
    precondition(store.save(duplicate) && store.entries.count == 1)
    let reopened = VocabularyStore(url: url)
    precondition(reopened.entries.first?.id == entry.id && reopened.entries.first?.meaning == "учу")
    precondition(reopened.entries.first?.pinned == true && reopened.entries.first?.contextTranslation == entry.contextTranslation)
    reopened.remove(reopened.entries[0]); precondition(VocabularyStore(url: url).entries.isEmpty)
    let corrupt = Data("broken".utf8); try corrupt.write(to: url)
    let broken = VocabularyStore(url: url); precondition(!broken.error.isEmpty && !broken.save(entry))
    let preserved = try Data(contentsOf: url); precondition(preserved == corrupt)
    let text = "„Üks!” kaks-kolm 12 õpin"
    let tokens = WordText.tokens(text).map { String(text[Range($0, in: text)!]) }
    precondition(tokens == ["Üks", "kaks-kolm", "12", "õpin"])
}

final class VocabularyEditorWindow: NSWindow, NSWindowDelegate {
    var onClose: (() -> Void)?
    func windowWillClose(_ notification: Notification) { onClose?(); onClose = nil }
}

func vocabularyPreviews(folder: URL) throws {
    _ = NSApplication.shared
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    let store = VocabularyStore(url: nil)
    store.save(VocabularyEntry(word: "aeglasemalt", meaning: "медленнее", context: "Kas sa saaksid palun aeglasemalt rääkida?", contextTranslation: "Не могли бы вы говорить медленнее?", note: "Полезно на уроке", pinned: true))
    let model = Model()
    model.status = "Слушаю · перевод 640 мс"
    model.captions = [Caption(id: "preview", original: "Kas sa saaksid palun aeglasemalt rääkida?", translation: "Не могли бы вы, пожалуйста, говорить медленнее?", partial: false, updatedAt: Date(), segmentIDs: [], session: "preview")]
    let editor = WordEditorModel(entry: store.entries.last!, root: folder, engine: "nllb")
    func render<V: View>(_ view: V, name: String, size: NSSize) throws {
        let host = NSHostingView(rootView: view)
        let window = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = host; host.frame = NSRect(origin: .zero, size: size)
        window.appearance = NSAppearance(named: .aqua)
        host.layoutSubtreeIfNeeded()
        RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { throw CocoaError(.fileWriteUnknown) }
        host.cacheDisplay(in: host.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else { throw CocoaError(.fileWriteUnknown) }
        try data.write(to: folder.appendingPathComponent(name + ".png"))
    }
    try render(OverlayView(model: model), name: "overlay", size: NSSize(width: 680, height: 440))
    model.size = 18; model.lifetime = 300; model.cardLayout = "columns"
    let samples = [
        ("Tere hommikust!", "Доброе утро!"),
        ("Täna räägime ajast ja kuupäevadest.", "Сегодня поговорим о времени и датах."),
        ("Mis kell sinu tund algab?", "Во сколько начинается твой урок?"),
        ("Minu tund algab kell üheksa.", "Мой урок начинается в девять часов."),
        ("Palun avage õpik ja vaadake järgmist harjutust.", "Пожалуйста, откройте учебник и посмотрите следующее упражнение."),
        ("Kas sa saaksid palun aeglasemalt rääkida?", "Не могли бы вы, пожалуйста, говорить медленнее?"),
        ("Kirjutage vastused vihikusse.", "Запишите ответы в тетрадь."),
        ("Kohtumiseni järgmisel nädalal!", "До встречи на следующей неделе!")]
    model.captions = samples.enumerated().map { index, sample in
        Caption(id: "layout-\(index)", original: sample.0, translation: sample.1, partial: false, updatedAt: model.now, segmentIDs: [], session: "preview", recognitionMs: 1900, translationMs: 250)
    }
    model.draft = "Järgmisel korral õpime uusi sõnu ja kordame tänast teemat."
    model.status = "Слушаю · речь 1,9 с · перевод 250 мс"
    for width in [420, 680, 900] {
        try render(OverlayView(model: model), name: "columns-\(width)", size: NSSize(width: width, height: 720))
    }
    model.cardLayout = "stacked"
    try render(OverlayView(model: model), name: "stacked-680", size: NSSize(width: 680, height: 720))
    try render(VocabularyView(store: store, edit: { _ in }), name: "dictionary", size: NSSize(width: 800, height: 540))
    try render(WordEditorView(model: editor, store: store, close: {}), name: "word", size: NSSize(width: 600, height: 420))
}
