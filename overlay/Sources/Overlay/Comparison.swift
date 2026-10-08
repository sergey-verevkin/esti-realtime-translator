import AppKit
import SwiftUI

struct ComparisonRow: Identifiable {
    let engine: String
    let style: String
    let text: String
    let error: Bool
    let milliseconds: Double
    var styleLabel: String {
        return style == "sentences" ? "по предложениям" : "целиком"
    }
    var id: String { engine + ":" + style }
}
final class ComparisonModel: ObservableObject {
    @Published var input = "Kui palju kell on? Appi! Kell on juba kolmveerand kaksteist!"
    @Published var sourceLanguage = "et"
    @Published var rows: [ComparisonRow] = []
    @Published var busy = false
    @Published var error = ""
    var process: Process?
    let root: URL
    init(root: URL) { self.root = root }
    func compare() {
        guard !busy, !input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        guard input.count <= 16000 else { error = "Фраза слишком длинная: максимум 16000 символов"; return }
        busy = true; rows = []; error = ""
        let text = input
        let p = Process(); let output = Pipe(); let source = Pipe(); let errors = Pipe()
        p.executableURL = root.appendingPathComponent("translation/.venv/bin/python")
        p.arguments = [root.appendingPathComponent("translation/compare.py").path, "--json", "--source-lang", sourceLanguage]
        p.standardInput = source; p.standardOutput = output; p.standardError = errors
        process = p
        do { try p.run() } catch { self.error = error.localizedDescription; busy = false; process = nil; return }
        DispatchQueue.global().async {
            try? source.fileHandleForWriting.write(contentsOf: Data(text.utf8))
            try? source.fileHandleForWriting.close()
            // Drain stderr independently so verbose failures cannot block the child.
            DispatchQueue.global().async { _ = errors.fileHandleForReading.readDataToEndOfFile() }
            let data = output.fileHandleForReading.readDataToEndOfFile()
            p.waitUntilExit()
            DispatchQueue.main.async {
                self.busy = false; self.process = nil
                guard p.terminationStatus == 0, let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let results = object["results"] as? [[String: Any]] else { self.error = "Не удалось сравнить переводы"; return }
                self.rows = results.map { item in
                    ComparisonRow(engine: item["engine"] as? String ?? "", style: item["style"] as? String ?? "",
                                  text: item["translation"] as? String ?? item["error"] as? String ?? "",
                                  error: item["error"] != nil, milliseconds: item["translation_ms"] as? Double ?? 0)
                }
            }
        }
    }
    func cancel() { if process?.isRunning == true { process?.terminate() } }
}
struct ComparisonView: View {
    @ObservedObject var model: ComparisonModel
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Сравнить перевод фразы").font(.title2)
            Text("Введите оригинал. Сравнение NLLB 600M и 1.3B по предложениям.").foregroundColor(.secondary)
            Picker("Язык оригинала", selection: $model.sourceLanguage) {
                Text("Эстонский").tag("et"); Text("Английский").tag("en")
            }.disabled(model.busy)
            TextEditor(text: $model.input).font(.body).frame(height: 95).disabled(model.busy)
                .overlay(RoundedRectangle(cornerRadius: 5).stroke(Color.secondary.opacity(0.4)))
            HStack {
                Button("Сравнить") { model.compare() }.disabled(model.busy)
                if model.busy { ProgressView().controlSize(.small); Text("Перевожу…").foregroundColor(.secondary) }
            }
            if !model.error.isEmpty { Text(model.error).foregroundColor(.red) }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(model.rows) { row in
                        VStack(alignment: .leading, spacing: 6) {
                            Text("\(row.engine == "nllb-1.3b" ? "NLLB distilled 1.3B" : "NLLB 600M") · \(row.styleLabel)").font(.headline)
                            Text(row.text).foregroundColor(row.error ? .red : .primary).textSelection(.enabled)
                            if !row.error { Text("\(Int(row.milliseconds)) мс").font(.caption).foregroundColor(.secondary) }
                            Divider()
                        }
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
        }.padding(24).frame(minWidth: 580, minHeight: 450)
    }
}
