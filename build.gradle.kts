// Plugins are declared here with `apply false` so CI resolves every pinned version from WP-00 on,
// and modules apply them without repeating versions. See docs/versions.md.
plugins {
  alias(libs.plugins.spring.boot) apply false
  alias(libs.plugins.spotless) apply false
  alias(libs.plugins.errorprone) apply false
}
