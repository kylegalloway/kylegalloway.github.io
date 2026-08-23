source "https://rubygems.org"

# NOTE: intentionally not using the "github-pages" meta-gem here. It pins an
# ancient Jekyll/Liquid that depends on Ruby's String#tainted? (removed in
# Ruby 3.2+), so it can't run under any current Ruby. GitHub Pages' live
# build uses its own pinned toolchain server-side regardless of this
# Gemfile, so local dev instead uses plain jekyll plus the specific plugins
# below -- all of which are on GitHub Pages' supported-plugins list, so the
# live build stays compatible.
gem "jekyll", "~> 4.3"
gem "jekyll-paginate"
gem "jekyll-seo-tag"
gem "jekyll-sitemap"
gem "jekyll-feed"
gem "webrick", "~> 1.8"
gem "csv"
gem "logger"
gem "base64"
gem "bigdecimal"
