class HoshiReaderTerminal < Formula
  include Language::Python::Virtualenv

  desc "Terminal reader inspired by Hoshi Reader"
  homepage "https://github.com/AkihaZhang/Hoshi-Reader-Terminal"
  url "https://github.com/AkihaZhang/Hoshi-Reader-Terminal/archive/refs/tags/v0.1.3.tar.gz"
  sha256 "fb6883e2bcc02530427a826f4a96c5fb30aa6b5aa0cf1fc2d4b717daab24c562"
  license "MIT"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "0.1.3", shell_output("#{bin}/hoshi --version")
  end
end
