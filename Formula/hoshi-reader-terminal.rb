class HoshiReaderTerminal < Formula
  include Language::Python::Virtualenv

  desc "Terminal reader inspired by Hoshi Reader"
  homepage "https://github.com/AkihaZhang/Hoshi-Reader-Terminal"
  url "https://github.com/AkihaZhang/Hoshi-Reader-Terminal/archive/refs/tags/v0.1.2.tar.gz"
  sha256 :no_check
  license "MIT"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "0.1.2", shell_output("#{bin}/hoshi --version")
  end
end
