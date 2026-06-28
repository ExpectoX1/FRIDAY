import Foundation
import SwiftUI

struct BitmapAnimationView: View {
    let name: String
    let tint: Color

    @State private var animation: BitmapAnimation?
    @State private var frameIndex = 0

    var body: some View {
        Canvas { context, size in
            guard let animation else { return }
            draw(animation.frames[frameIndex % animation.frames.count], in: size, context: &context)
        }
        .aspectRatio(2, contentMode: .fit)
        .task(id: name) {
            animation = BitmapAnimation.load(named: name)
            frameIndex = 0

            guard let animation else { return }
            while !Task.isCancelled {
                frameIndex = (frameIndex + 1) % animation.frames.count
                try? await Task.sleep(for: .milliseconds(animation.frameDelay))
            }
        }
    }

    private func draw(_ frame: [UInt8], in size: CGSize, context: inout GraphicsContext) {
        let sourceWidth = 128
        let sourceHeight = 64
        let pixelWidth = size.width / CGFloat(sourceWidth)
        let pixelHeight = size.height / CGFloat(sourceHeight)
        let rectSize = CGSize(width: max(pixelWidth, 0.8), height: max(pixelHeight, 0.8))

        for y in 0..<sourceHeight {
            for byteX in 0..<(sourceWidth / 8) {
                let byte = frame[y * (sourceWidth / 8) + byteX]
                guard byte != 0 else { continue }

                for bit in 0..<8 {
                    let mask = UInt8(0x80 >> bit)
                    guard byte & mask != 0 else { continue }

                    let x = byteX * 8 + bit
                    let rect = CGRect(
                        x: CGFloat(x) * pixelWidth,
                        y: CGFloat(y) * pixelHeight,
                        width: rectSize.width,
                        height: rectSize.height
                    )
                    context.fill(Path(rect), with: .color(tint))
                }
            }
        }
    }
}

struct BitmapAnimation {
    let frameDelay: Int
    let frames: [[UInt8]]

    static func exists(named name: String) -> Bool {
        Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Animations") != nil
    }

    static func load(named name: String) -> BitmapAnimation? {
        guard let url = Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Animations"),
              let data = try? Data(contentsOf: url),
              let payload = try? JSONDecoder().decode(BitmapAnimationPayload.self, from: data),
              !payload.frames.isEmpty
        else {
            return nil
        }

        return BitmapAnimation(
            frameDelay: max(payload.frameDelay, 16),
            frames: payload.frames.map { $0.map(UInt8.init(clamping:)) }
        )
    }
}

private struct BitmapAnimationPayload: Decodable {
    let frameDelay: Int
    let frames: [[Int]]
}
