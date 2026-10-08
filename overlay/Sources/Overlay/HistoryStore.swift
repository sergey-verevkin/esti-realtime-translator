import Foundation

/// JSONL is the authoritative journal; the readable text file is regenerated from it.
final class HistoryStore {
    static var defaultFolder: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/Realtime Translation/History", isDirectory: true)
    }
    let folder: URL
    private(set) var warning = ""
    private let dayFormatter: DateFormatter
    private let timeFormatter: DateFormatter
    init(folder: URL = HistoryStore.defaultFolder) {
        self.folder = folder
        dayFormatter = DateFormatter(); dayFormatter.locale = Locale(identifier: "en_US_POSIX")
        dayFormatter.timeZone = TimeZone(identifier: "Europe/Tallinn")
        dayFormatter.dateFormat = "yyyy-MM-dd"
        timeFormatter = DateFormatter(); timeFormatter.locale = Locale(identifier: "en_US_POSIX")
        timeFormatter.timeZone = dayFormatter.timeZone; timeFormatter.dateFormat = "HH:mm:ss"
    }
    func day(for date: Date) -> String { dayFormatter.string(from: date) }
    var days: [String] {
        let names = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
        return names.filter { $0.pathExtension == "jsonl" }.map { $0.deletingPathExtension().lastPathComponent }.sorted(by: >)
    }
    private func url(_ day: String, _ ext: String) throws -> URL {
        guard day.count == 10, dayFormatter.date(from: day) != nil,
              day.allSatisfy({ $0.isNumber || $0 == "-" }) else { throw CocoaError(.fileReadInvalidFileName) }
        return folder.appendingPathComponent(day).appendingPathExtension(ext)
    }
    func load(_ day: String) throws -> [Caption] {
        let path = try url(day, "jsonl")
        guard FileManager.default.fileExists(atPath: path.path) else { return [] }
        let data = try Data(contentsOf: path)
        var seen: Set<String> = []; var rows: [Caption] = []
        let lines = data.split(separator: 10).filter { !$0.isEmpty }
        for (index, line) in lines.enumerated() {
            let decoder = JSONDecoder(); decoder.dateDecodingStrategy = .iso8601
            let row: Caption
            do { row = try decoder.decode(Caption.self, from: Data(line)) }
            catch {
                if index == lines.count - 1 && data.last != 10 {
                    let backup = folder.appendingPathComponent(day + ".interrupted-" + UUID().uuidString)
                    try data.write(to: backup, options: .atomic)
                    try Data(data.prefix(data.count - line.count)).write(to: path, options: .atomic)
                    warning = "Восстановлена история после прерванной записи. Исходный файл сохранён рядом."
                    break
                }
                throw error
            }
            if !row.partial && seen.insert(row.id).inserted { rows.append(row) }
        }
        return rows.sorted { $0.updatedAt < $1.updatedAt }
    }
    func append(_ row: Caption) throws {
        guard !row.partial else { return }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let key = day(for: row.updatedAt)
        var rows = try load(key)
        if !rows.contains(where: { $0.id == row.id }) {
            let path = try url(key, "jsonl")
            if !FileManager.default.fileExists(atPath: path.path) {
                guard FileManager.default.createFile(atPath: path.path, contents: nil) else { throw CocoaError(.fileWriteUnknown) }
            }
            let handle = try FileHandle(forWritingTo: path)
            defer { try? handle.close() }
            try handle.seekToEnd()
            let existing = try Data(contentsOf: path)
            if !existing.isEmpty && existing.last != 10 { try handle.write(contentsOf: Data([10])) }
            let encoder = JSONEncoder(); encoder.dateEncodingStrategy = .iso8601; encoder.outputFormatting = .sortedKeys
            var data = try encoder.encode(row); data.append(10)
            try handle.write(contentsOf: data); try handle.synchronize()
            rows.append(row)
        }
        try exportText(key, rows: rows)
    }
    func exportText(_ key: String, rows: [Caption]) throws {
        guard !rows.isEmpty else { return }
        let text = rows.map { row in
            "[\(timeFormatter.string(from: row.updatedAt))] Сессия \(row.session)\nПеревод: \(row.translationEngine ?? "nllb") / \(row.translationStyle ?? "legacy")\(row.clockNormalization == true ? " / часы цифрами" : "")\n\((row.sourceLanguage ?? "et").uppercased()): \(row.original)\nRU: \(row.translation)\n"
        }.joined(separator: "\n")
        try text.write(to: try url(key, "txt"), atomically: true, encoding: .utf8)
    }
}
