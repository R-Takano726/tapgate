import SwiftUI

struct GlassPanel: ViewModifier {
    func body(content: Content) -> some View {
        content.padding(18)
            .glassEffect(.regular.tint(.white.opacity(0.45)), in: .rect(cornerRadius: 24))
    }
}
struct InboxView: View {
    @StateObject private var model = InboxModel()
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var url = ""
    @State private var code = ""
    @State private var settings = false
    @State private var reviewing = false
    @State private var phoneSent = false
    @ObservedObject private var route = GateRoute.shared
    @Namespace private var glass
    var motion: Animation { reduceMotion ? .linear(duration: 0.01) : .spring(response: 0.4, dampingFraction: 0.85) }
    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(colors: [.white, Color(red: 0.93, green: 0.96, blue: 1)], startPoint: .topLeading, endPoint: .bottomTrailing).ignoresSafeArea()
                if !model.connected { pairing }
                else { inbox }
            }
            .foregroundStyle(Color(red: 0.16, green: 0.21, blue: 0.3))
            .navigationTitle("TapGate")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await model.refresh() } } label: { Image(systemName: "arrow.clockwise") }
                        .accessibilityLabel("再読み込み")
                }
                #if os(iOS)
                ToolbarItem(placement: .topBarLeading) {
                    Button { withAnimation(motion) { settings.toggle() } } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel("設定")
                }
                #endif
            }
        }
        .preferredColorScheme(.light)
        .tint(Color(red: 0.22, green: 0.43, blue: 0.88))
        .task {
            Bridge.shared.start()
            while !Task.isCancelled {
                await model.refresh()
                try? await Task.sleep(for: .seconds(3))
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .gateConnection)) { _ in
            model.connected = Vault.load() != nil
            Task { await model.refresh() }
        }
        .onReceive(route.$error) { model.error = $0 }
        .onReceive(route.$requestID) { id in
            guard let id else { return }
            model.selected = id
            model.result = nil
            #if os(iOS)
            reviewing = true
            #endif
            Task { await model.refresh() }
        }
        #if os(iOS)
        .sheet(isPresented: $reviewing) {
            NavigationStack {
                ScrollView {
                    if let item = model.current { approval(item).padding(24) }
                    else { ProgressView().padding(40) }
                    if let error = model.error { Text(error).foregroundStyle(.red).padding() }
                }.background(Color(red: 0.96, green: 0.98, blue: 1))
                    .navigationTitle("詳細")
                    .toolbar { Button("戻る") { reviewing = false } }
            }.presentationDetents([.large]).preferredColorScheme(.light)
        }
        #endif
        .onReceive(NotificationCenter.default.publisher(for: .gateError)) { note in model.error = note.object as? String }
        .animation(motion, value: model.result?.state)
        .animation(motion, value: model.busy)
        .animation(motion, value: phoneSent)
        .onChange(of: model.selected) { phoneSent = false }
        .animation(motion, value: model.history)
    }
    @ViewBuilder var pairing: some View {
        #if os(watchOS)
        VStack(spacing: 14) {
            Image(systemName: "iphone.and.arrow.right.inward").font(.largeTitle).foregroundStyle(.blue)
            Text("iPhoneで接続してください").font(.headline)
            Button("接続") { Bridge.shared.handshake() }.buttonStyle(.glassProminent)
            if let error = model.error { Text(error).font(.caption2) }
        }.padding()
        #else
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Image(systemName: "checkmark.shield").font(.system(size: 42, weight: .light)).foregroundStyle(.blue)
                Text("端末ペアリング").font(.largeTitle.bold())
                TextField("https://your-host.ts.net", text: $url).textContentType(.URL).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    .padding().background(.white.opacity(0.8), in: .rect(cornerRadius: 16))
                TextField("ペアリングコード", text: $code).keyboardType(.numberPad).textContentType(.oneTimeCode)
                    .padding().background(.white.opacity(0.8), in: .rect(cornerRadius: 16))
                Button { Task { await model.pair(url: url, code: code); await model.refresh() } } label: {
                    HStack { Spacer(); if model.busy { ProgressView() }; Text("接続"); Spacer() }.padding(.vertical, 10)
                }.buttonStyle(.glassProminent).disabled(model.busy || code.count != 8)
                if let error = model.error { Text(error).font(.footnote).foregroundStyle(.red) }
            }.padding(28).modifier(GlassPanel()).padding()
        }
        #endif
    }
    @ViewBuilder var inbox: some View {
        #if os(watchOS)
        ScrollView {
            VStack(spacing: 12) {
                if !model.online { Label("オフライン", systemImage: "wifi.slash").font(.caption2).foregroundStyle(.orange) }
                if model.demo { Text("デモモード").font(.caption2).foregroundStyle(.orange) }
                if let item = model.result ?? model.current {
                    approval(item)
                } else { empty }
                if let error = model.error { Text(error).font(.caption2).foregroundStyle(.red) }
                if model.result == nil && model.items.filter(\.pending).count > 1 {
                    ForEach(model.items.filter { $0.pending && $0.id != model.selected }) { item in
                        Button(item.task) { withAnimation(motion) { model.selected = item.id } }
                            .buttonStyle(.glass).font(.caption)
                    }
                }
            }.padding(.horizontal, 5)
        }
        #else
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                if model.demo { Text("デモモード — 合成データによる表示確認です").font(.caption).foregroundStyle(.orange) }
                HStack {
                    VStack(alignment: .leading, spacing: 7) {
                        Text("承認トレイ").font(.largeTitle.bold())
                        Label(model.online ? "接続中" : "オフライン", systemImage: model.online ? "circle.fill" : "wifi.slash")
                            .font(.caption).foregroundStyle(model.online ? .green : .orange)
                    }
                    Spacer()
                    Text("\(model.items.filter(\.pending).count)").font(.largeTitle.weight(.light)).padding(20).glassEffect()
                }
                if settings {
                    Text("通知にはコマンド全文や秘密情報を含めず、不透明IDのみを送信します。").font(.footnote)
                    Button("承認要求") { NotificationCenter.default.post(name: .gateConnection, object: nil) }.buttonStyle(.glass)
                }
                Picker("承認トレイ", selection: $model.history) {
                    Text("承認待ち").tag(false); Text("履歴").tag(true)
                }.pickerStyle(.segmented)
                if let result = model.result { approval(result).modifier(GlassPanel()) }
                let visible = model.items.filter { model.history ? !$0.pending && $0.state != "notice" : $0.pending || $0.state == "notice" }
                if visible.isEmpty && model.result == nil { empty.frame(maxWidth: .infinity).padding(35) }
                ForEach(visible.filter { $0.id != model.result?.id }) { item in
                    approval(item).modifier(GlassPanel()).transition(.opacity.combined(with: .offset(y: reduceMotion ? 0 : 10)))
                }
                if let error = model.error { Text(error).font(.footnote).foregroundStyle(.red) }
            }.padding(22)
        }
        .refreshable { await model.refresh() }
        #endif
    }
    @ViewBuilder func approval(_ item: Approval) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 5) {
                Image(systemName: item.source == "codex" ? "command" : "sparkle")
                Text(item.source == "codex" ? "Codex" : "Claude Code")
                Spacer(minLength: 4)
                Text(item.host).lineLimit(1)
            }.font(.caption2).foregroundStyle(.secondary)
            Text(item.task).font(.headline).fixedSize(horizontal: false, vertical: true)
            if item.informational && item.state == "notice" {
                Text(item.operation).font(.caption)
                Text("元のターミナルで対応してください").font(.caption).foregroundStyle(.secondary)
            } else if !item.pending {
                VStack(spacing: 12) {
                    Image(systemName: item.state == "approved" ? "checkmark.circle.fill" : "minus.circle")
                        .font(.system(size: 36)).foregroundStyle(item.state == "approved" ? .green : .secondary)
                        .symbolEffect(.bounce, options: .nonRepeating, value: item.state)
                    Text(item.stateLabel).font(.headline)
                    if item.state == "approved" || item.state == "denied" {
                        Text(item.delivered ? "回答受信済み" : "回答の受信待ち").font(.caption2).foregroundStyle(.secondary)
                    }
                    Button("次へ") { withAnimation(motion) { model.next() } }.buttonStyle(.glass)
                }.frame(maxWidth: .infinity).padding(.vertical, 12)
            } else {
                #if os(watchOS)
                Text(item.phoneRequired ? "iPhoneでの確認が必要です" : item.operation)
                    .font(.system(.caption, design: .monospaced)).fixedSize(horizontal: false, vertical: true)
                #else
                Text(item.operation).font(.system(.footnote, design: .monospaced))
                    .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(14)
                    .background(.white.opacity(0.7), in: .rect(cornerRadius: 14))
                if !item.reason.isEmpty {
                    DisclosureGroup("詳細") { Text(item.reason).font(.system(.caption2, design: .monospaced)).textSelection(.enabled) }
                }
                #endif
                if item.informational { Text("元のターミナルで対応してください").font(.caption) }
                else {
                    GlassEffectContainer(spacing: 18) {
                        VStack(spacing: 18) {
                            #if os(watchOS)
                            if item.phoneRequired {
                                Button {
                                    Task {
                                        do { try await Bridge.shared.openPhone(item.id); phoneSent = true }
                                        catch { model.error = error.localizedDescription }
                                    }
                                } label: { Label("iPhoneで全文確認", systemImage: phoneSent ? "checkmark.circle.fill" : "iphone").frame(maxWidth: .infinity).padding(.vertical, 8) }
                                    .buttonStyle(.glass).glassEffectID("phone-\(item.id)", in: glass)
                                    .sensoryFeedback(.success, trigger: phoneSent)
                            } else { approveButton(item) }
                            #else
                            approveButton(item)
                            #endif
                            Button { Task { await model.decide(item, approve: false) } } label: {
                                Text("拒否").frame(maxWidth: .infinity).padding(.vertical, 5)
                            }.buttonStyle(.glass).disabled(model.busy || !model.online || !item.live)
                        }
                    }
                }
            }
        }
        .sensoryFeedback(.success, trigger: item.state == "approved")
    }
    func approveButton(_ item: Approval) -> some View {
        Button { Task { await model.decide(item, approve: true) } } label: {
            HStack { Spacer(); if model.busy { ProgressView() }; Label("許可", systemImage: "checkmark"); Spacer() }.padding(.vertical, 10)
        }.buttonStyle(.glassProminent).disabled(model.busy || !model.online || !item.live)
            .glassEffectID("approve-\(item.id)", in: glass)
    }
    var empty: some View {
        VStack(spacing: 14) {
            Image(systemName: "checkmark.circle").font(.system(size: 40, weight: .ultraLight)).foregroundStyle(.blue.opacity(0.6))
            Text("リクエストはありません").font(.headline)
            Text("処理待ちの承認要求は届いていません。").font(.caption).foregroundStyle(.secondary)
        }
    }
}
