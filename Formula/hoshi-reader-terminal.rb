class HoshiReaderTerminal < Formula
  desc "Terminal reader inspired by Hoshi Reader"
  homepage "https://github.com/AkihaZhang/Hoshi-Reader-Terminal"
  url "https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/download/v0.1.2/Hoshi-Reader-Terminal-0.1.2-macos-standalone.tar.gz"
  sha256 :no_check
  license "MIT"

  def install
    package = Dir["Hoshi-Reader-Terminal-*-macos-standalone"].first
    bin.install "#{package}/hoshi"
    prefix.install "#{package}/examples"
    doc.install "#{package}/README.md"
    doc.install "#{package}/README.zh-CN.md"
  end

  test do
    assert_match "0.1.2", shell_output("#{bin}/hoshi --version")
  end
end
